"""
News Extractor Skill - 新闻文章智能提取工具

提供从网页中提取新闻文章结构化信息的能力，支持：
- 单篇/批量URL处理
- 多格式输出（Markdown/JSON/CSV）
- AI摘要生成和关键词提取
- 会话级缓存去重
"""

from typing import List, Dict, Any, Optional, Literal, Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
import re
import json
import hashlib
from datetime import datetime
from collections import OrderedDict


# ============== 数据模型 ==============

class ArticleInfo(BaseModel):
    """单篇文章提取结果"""
    url: str = Field(description="文章URL")
    title: Optional[str] = Field(default=None, description="标题")
    author: Optional[str] = Field(default=None, description="作者")
    publish_time: Optional[str] = Field(default=None, description="发布时间")
    source: Optional[str] = Field(default=None, description="来源网站")
    language: Optional[str] = Field(default="zh-CN", description="语言")
    category: Optional[str] = Field(default=None, description="新闻类型")
    reading_time_minutes: Optional[int] = Field(default=None, description="预估阅读时长(分钟)")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    summary: Optional[str] = Field(default=None, description="摘要")
    full_text: Optional[str] = Field(default=None, description="完整正文")
    cover_image: Optional[str] = Field(default=None, description="封面图URL")
    word_count: Optional[int] = Field(default=None, description="字数统计")
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="提取时间")
    error: Optional[str] = Field(default=None, description="错误信息")


class ExtractionResult(BaseModel):
    """批量提取结果"""
    success: bool = Field(description="是否全部成功")
    articles: List[ArticleInfo] = Field(default_factory=list, description="成功提取的文章列表")
    failed: List[Dict[str, str]] = Field(default_factory=list, description="失败的URL及原因")
    cached: int = Field(default=0, description="从缓存返回的数量")


class NewsExtractInput(BaseModel):
    """news_extract 工具的输入参数"""
    urls: List[str] = Field(description="要提取的新闻URL列表")
    output_format: Literal["markdown", "json", "csv"] = Field(
        default="markdown", 
        description="输出格式：markdown（默认）、json、csv"
    )
    summary_length: int = Field(default=300, ge=50, le=2000, description="摘要最大字数")
    include_full_text: bool = Field(default=False, description="是否包含完整正文")
    force_refresh: bool = Field(default=False, description="是否强制刷新缓存")
    timeout: int = Field(default=30, ge=5, le=120, description="单个URL超时秒数")
    max_retries: int = Field(default=2, ge=0, le=5, description="失败重试次数")


# ============== 缓存管理 ==============

class SessionCache:
    """会话级缓存管理器"""
    def __init__(self, max_size: int = 100):
        self._cache: OrderedDict[str, ArticleInfo] = OrderedDict()
        self._max_size = max_size
    
    def _get_url_hash(self, url: str) -> str:
        """计算URL的哈希值作为缓存键"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    def get(self, url: str) -> Optional[ArticleInfo]:
        """从缓存获取文章"""
        key = self._get_url_hash(url)
        return self._cache.get(key)
    
    def set(self, url: str, article: ArticleInfo) -> None:
        """将文章存入缓存"""
        key = self._get_url_hash(url)
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = article
    
    def exists(self, url: str) -> bool:
        """检查URL是否已在缓存中"""
        key = self._get_url_hash(url)
        return key in self._cache


# 全局会话缓存实例
_session_cache = SessionCache()


# ============== 核心提取逻辑 ==============

def extract_title(html_content: str, url: str) -> Optional[str]:
    """从HTML中提取标题"""
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:title["\']',
        r'<h1[^>]*>([^<]+)</h1>',
        r'<title[^>]*>([^<]+)</title>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
        if match:
            title = match.group(1).strip()
            title = re.sub(r'\s+', ' ', title)
            title = re.sub(r'\s*[-_|]\s*[^-_|]+$', '', title)
            return title if title else None
    return None


def extract_author(html_content: str) -> Optional[str]:
    """从HTML中提取作者"""
    patterns = [
        r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']author["\']',
        r'<meta[^>]+property=["\']article:author["\'][^>]+content=["\']([^"\']+)["\']',
        r'<[^>]+class=["\'][^"\']*author[^"\']*["\'][^>]*>([^<]+)<',
        r'作者[：:]\s*([^\s<]+)',
        r'文[／/]\s*([^\s<]+)',
        r'记者[：:]\s*([^\s<]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            author = match.group(1).strip()
            if author and len(author) < 50:
                return author
    return None


def extract_publish_time(html_content: str) -> Optional[str]:
    """从HTML中提取发布时间"""
    time_patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'<meta[^>]+name=["\']publishdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r'<time[^>]*>([^<]+)</time>',
        r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?[日\s]+\d{1,2}:\d{2}(:\d{2})?',
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',
        r'\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}',
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            time_str = match.group(1).strip()
            if '年' in time_str:
                time_str = time_str.replace('年', '-').replace('月', '-').replace('日', '')
            time_str = re.sub(r'\s+', ' ', time_str).strip()
            return time_str
    return None


def extract_content(html_content: str) -> str:
    """从HTML中提取正文内容"""
    clean_html = re.sub(r'<(script|style|nav|header|footer|aside|iframe)[^>]*>.*?</\1>', '', 
                        html_content, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', clean_html)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'(版权所有|Copyright|©|举报|反馈|评论|分享|收藏|点赞).*$', '', text, flags=re.IGNORECASE)
    return text


def extract_keywords(html_content: str, text: str) -> List[str]:
    """提取关键词"""
    keywords = []
    meta_patterns = [
        r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']news_keywords["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in meta_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            kws = match.group(1).split(',')
            keywords.extend([k.strip() for k in kws if k.strip()])
    
    tag_pattern = r'<meta[^>]+property=["\']article:tag["\'][^>]+content=["\']([^"\']+)["\']'
    for match in re.finditer(tag_pattern, html_content, re.IGNORECASE):
        tag = match.group(1).strip()
        if tag and tag not in keywords:
            keywords.append(tag)
    
    seen = set()
    unique_keywords = []
    for kw in keywords:
        if kw.lower() not in seen and len(kw) < 20:
            seen.add(kw.lower())
            unique_keywords.append(kw)
    
    return unique_keywords[:8]


def extract_cover_image(html_content: str) -> Optional[str]:
    """提取封面图片URL"""
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def detect_language(text: str) -> str:
    """检测文本语言"""
    if not text:
        return "unknown"
    
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    japanese_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
    korean_chars = len(re.findall(r'[\uac00-\ud7af]', text))
    
    total = chinese_chars + english_chars + japanese_chars + korean_chars
    if total == 0:
        return "unknown"
    
    ratios = {
        'zh-CN': chinese_chars / total,
        'en': english_chars / total,
        'ja': japanese_chars / total,
        'ko': korean_chars / total
    }
    
    return max(ratios, key=ratios.get) if max(ratios.values()) > 0.3 else "unknown"


def estimate_reading_time(text: str) -> int:
    """估算阅读时长（分钟）"""
    if not text:
        return 0
    word_count = len(text)
    reading_time = max(1, word_count // 350)
    return reading_time


def generate_summary(text: str, max_length: int = 300) -> str:
    """生成摘要"""
    if not text:
        return ""
    
    text = re.sub(r'\s+', ' ', text).strip()
    
    if len(text) <= max_length:
        return text
    
    truncated = text[:max_length + 50]
    for end_char in ['。', '！', '？', '.', '!', '?', '；', ';']:
        last_pos = truncated.rfind(end_char)
        if max_length - 50 < last_pos <= max_length + 50:
            return text[:last_pos + 1]
    
    return text[:max_length] + '...'


def categorize_news(title: str, text: str, keywords: List[str]) -> str:
    """分类新闻类型"""
    combined = (title + ' ' + ' '.join(keywords)).lower()
    
    categories = {
        '科技': ['科技', '技术', '互联网', '人工智能', 'AI', '数码', '手机', '电脑', '软件'],
        '财经': ['财经', '股市', '金融', '经济', '投资', '股票', '基金', '银行'],
        '体育': ['体育', '足球', '篮球', '比赛', '运动员', '奥运会', '世界杯'],
        '娱乐': ['娱乐', '明星', '电影', '音乐', '综艺', '演员', '歌手'],
        '政治': ['政治', '政府', '政策', '外交', '领导人', '会议'],
        '社会': ['社会', '民生', '教育', '医疗', '交通', '天气'],
        '国际': ['国际', '美国', '欧洲', '日本', '韩国', '国际新闻'],
    }
    
    for category, keywords_list in categories.items():
        for kw in keywords_list:
            if kw in combined:
                return category
    
    return '综合'


# ============== 工具类 ==============

class NewsExtractTool(BaseTool):
    """新闻文章提取工具"""
    name: str = "news_extract"
    description: str = """从新闻网页中提取结构化信息。

输入参数：
- urls: 新闻URL列表（必填）
- output_format: 输出格式 markdown/json/csv（默认markdown）
- summary_length: 摘要最大字数（默认300）
- include_full_text: 是否包含完整正文（默认False）
- force_refresh: 是否强制刷新缓存（默认False）
- timeout: 单个URL超时秒数（默认30）
- max_retries: 失败重试次数（默认2）

返回：
- 成功提取的文章列表
- 失败的URL及原因
- 缓存命中数量
"""
    args_schema: Type[BaseModel] = NewsExtractInput
    
    def _run(
        self,
        urls: List[str],
        output_format: str = "markdown",
        summary_length: int = 300,
        include_full_text: bool = False,
        force_refresh: bool = False,
        timeout: int = 30,
        max_retries: int = 2
    ) -> str:
        """执行新闻提取"""
        global _session_cache
        
        articles: List[ArticleInfo] = []
        failed: List[Dict[str, str]] = []
        cached_count = 0
        
        for url in urls:
            if not self._is_valid_url(url):
                failed.append({"url": url, "reason": "URL格式无效"})
                continue
            
            if not force_refresh:
                cached = _session_cache.get(url)
                if cached:
                    articles.append(cached)
                    cached_count += 1
                    continue
            
            article = self._fetch_and_extract(
                url, 
                summary_length, 
                include_full_text, 
                timeout, 
                max_retries
            )
            
            if article.error:
                failed.append({"url": url, "reason": article.error})
            else:
                articles.append(article)
                _session_cache.set(url, article)
        
        result = ExtractionResult(
            success=len(failed) == 0,
            articles=articles,
            failed=failed,
            cached=cached_count
        )
        
        return self._format_output(result, output_format)
    
    def _is_valid_url(self, url: str) -> bool:
        """验证URL格式"""
        pattern = r'^https?://[^\s<>"{}|\\^`\[\]]+$'
        return bool(re.match(pattern, url, re.IGNORECASE))
    
    def _fetch_and_extract(
        self, 
        url: str, 
        summary_length: int,
        include_full_text: bool,
        timeout: int,
        max_retries: int
    ) -> ArticleInfo:
        """抓取并解析网页"""
        import time
        import urllib.request
        import urllib.error
        
        html_content = None
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    }
                )
                
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    html_content = response.read().decode('utf-8', errors='ignore')
                break
                
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    last_error = "访问被拒绝(403)，目标网站可能有反爬机制"
                elif e.code == 404:
                    last_error = "页面不存在(404)"
                elif e.code == 429:
                    last_error = "请求过于频繁(429)，请稍后重试"
                else:
                    last_error = f"HTTP错误: {e.code}"
                break
                
            except urllib.error.URLError as e:
                last_error = f"网络错误: {str(e.reason)}"
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    
            except Exception as e:
                last_error = f"未知错误: {str(e)}"
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        
        if html_content is None:
            return ArticleInfo(url=url, error=last_error or "无法获取网页内容")
        
        title = extract_title(html_content, url)
        author = extract_author(html_content)
        publish_time = extract_publish_time(html_content)
        text = extract_content(html_content)
        keywords = extract_keywords(html_content, text)
        cover_image = extract_cover_image(html_content)
        language = detect_language(text)
        reading_time = estimate_reading_time(text)
        summary = generate_summary(text, summary_length)
        category = categorize_news(title or "", text, keywords)
        
        return ArticleInfo(
            url=url,
            title=title,
            author=author,
            publish_time=publish_time,
            source=self._extract_source(url),
            language=language,
            category=category,
            reading_time_minutes=reading_time,
            keywords=keywords,
            summary=summary,
            full_text=text if include_full_text else None,
            cover_image=cover_image,
            word_count=len(text) if text else None
        )
    
    def _extract_source(self, url: str) -> str:
        """从URL提取来源网站名"""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return "未知来源"
    
    def _format_output(self, result: ExtractionResult, output_format: str) -> str:
        """格式化输出"""
        if output_format == "json":
            return result.model_dump_json(indent=2, ensure_ascii=False)
        
        elif output_format == "csv":
            lines = ["URL,标题,作者,发布时间,来源,摘要,关键词"]
            for article in result.articles:
                title = (article.title or "").replace(",", "，")
                author = (article.author or "").replace(",", "，") or "未知"
                pub_time = article.publish_time or "未知"
                source = article.source or "未知"
                summary = (article.summary or "").replace(",", "，").replace("\n", " ")[:100]
                keywords = ";".join(article.keywords)
                lines.append(f'"{article.url}","{title}","{author}","{pub_time}","{source}","{summary}","{keywords}"')
            
            if result.failed:
                for f in result.failed:
                    lines.append(f'"{f["url"]}","提取失败","{f["reason"]}","","","",""')
            
            return "\n".join(lines)
        
        else:
            return self._format_markdown(result)
    
    def _format_markdown(self, result: ExtractionResult) -> str:
        """格式化为Markdown"""
        lines = ["## 📰 新闻提取报告\n"]
        
        total = len(result.articles) + len(result.failed)
        success = len(result.articles)
        lines.append(f"> 📊 提取统计：成功 {success}/{total} 篇，缓存命中 {result.cached} 篇\n")
        
        for i, article in enumerate(result.articles, 1):
            lines.append(f"### [{i}/{total}] {article.title or '（无标题）'}\n")
            lines.append("| 字段 | 内容 |")
            lines.append("|------|------|")
            lines.append(f"| 来源 | [{article.source}]({article.url}) |")
            lines.append(f"| 标题 | {article.title or '未检测到'} |")
            lines.append(f"| 作者 | {article.author or '未检测到'} |")
            lines.append(f"| 发布时间 | {article.publish_time or '未检测到'} |")
            lines.append(f"| 来源网站 | {article.source or '未知'} |")
            lines.append(f"| 阅读时长 | 约 {article.reading_time_minutes or '?'} 分钟 |")
            lines.append(f"| 语言 | {article.language} |")
            lines.append(f"| 类型 | {article.category or '综合'} |")
            lines.append(f"| 字数 | {article.word_count or '?'} 字 |")
            
            if article.cover_image:
                lines.append(f"| 封面图 | [点击查看]({article.cover_image}) |")
            
            lines.append(f"\n**摘要**\n> {article.summary or '无摘要'}\n")
            
            if article.keywords:
                keywords_str = " ".join([f"`{kw}`" for kw in article.keywords])
                lines.append(f"**关键词**\n{keywords_str}\n")
            
            if article.full_text:
                lines.append(f"<details>\n<summary>📄 点击查看完整正文</summary>\n\n{article.full_text}\n\n</details>\n")
            
            lines.append("---\n")
        
        if result.failed:
            lines.append("### ⚠️ 提取失败的链接\n")
            lines.append("| URL | 失败原因 |")
            lines.append("|-----|----------|")
            for f in result.failed:
                lines.append(f"| {f['url']} | {f['reason']} |")
            lines.append("")
        
        lines.append(f"*提取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        return "\n".join(lines)


# ============== Skill 入口 ==============

try:
    from nexagent.skills import BaseSkill
except ImportError:
    try:
        from agent.skills import BaseSkill
    except ImportError:
        # 创建一个基础的 BaseSkill 类
        class BaseSkill:
            @classmethod
            def get_tools(cls) -> List[BaseTool]:
                return []
            
            @classmethod
            def get_description(cls) -> str:
                return ""


class NewsExtractorSkill(BaseSkill):
    """新闻文章提取器 Skill"""
    
    @classmethod
    def get_tools(cls) -> List[BaseTool]:
        """返回工具列表"""
        return [NewsExtractTool()]
    
    @classmethod
    def get_description(cls) -> str:
        """返回技能描述"""
        return "智能从新闻网页中提取结构化信息，支持批量处理、AI摘要、多格式输出"


__all__ = ['NewsExtractorSkill', 'NewsExtractTool', 'NewsExtractInput', 'ArticleInfo', 'ExtractionResult']
