# 内容提取策略

> 详细说明如何从网页中提取各类字段

## 提取优先级

```
┌─────────────────────────────────────────────┐
│  1. JSON-LD 结构化数据 (最高优先级)          │
│     → 通常包含最完整的元数据                  │
├─────────────────────────────────────────────┤
│  2. Open Graph / Twitter Card               │
│     → og:title, og:description, og:image   │
├─────────────────────────────────────────────┤
│  3. HTML Meta 标签                          │
│     → meta[name="author"], meta[property]  │
├─────────────────────────────────────────────┤
│  4. 传统 HTML 语义标签                       │
│     → article, header, time, author        │
├─────────────────────────────────────────────┤
│  5. 智能推断 (最低优先级)                    │
│     → 基于内容分析推断                       │
└─────────────────────────────────────────────┘
```

## 各字段提取策略

### 标题 (title)

| 优先级 | 选择器 | 说明 |
|--------|--------|------|
| 1 | `json-ld > headline` | JSON-LD 中的 headline 字段 |
| 2 | `og:title` | Open Graph 标题 |
| 3 | `h1` |页面主标题 |
| 4 | `title` | 浏览器标题 |

### 作者 (author)

| 优先级 | 选择器 | 说明 |
|--------|--------|------|
| 1 | `json-ld > author > name` | JSON-LD 作者 |
| 2 | `meta[name="author"]` | Meta 作者标签 |
| 3 | `meta[property="article:author"]` | Facebook 作者 |
| 4 | `author` / `.author` | 常见 class 名 |
| 5 | 智能推断 | 从正文开头推断 |

### 发布时间 (published_time)

| 优先级 | 选择器 | 说明 |
|--------|--------|------|
| 1 | `json-ld > datePublished` | ISO 格式时间 |
| 2 | `meta[property="article:published_time"]` | Open Graph 时间 |
| 3 | `time[datetime]` | HTML5 time 标签 |
| 4 | `meta[name="date"]` | 通用日期标签 |
| 5 | 智能解析 | 从 URL 或正文推断 |

### 正文 (content)

| 优先级 | 方法 | 说明 |
|--------|------|------|
| 1 | `json-ld > articleBody` | 结构化正文 |
| 2 | `article` | HTML5 文章标签 |
| 3 | `main` + 文本密度 | 主内容区 + 密度分析 |
| 4 | `div[class*="content"]` | 常见内容容器 |
| 5 | 文本节点合并 | 合并所有段落文本 |

### 正文提取算法

```python
def extract_content(html):
    # 1. 移除脚本、样式、导航等无关内容
    unwanted_tags = ['script', 'style', 'nav', 'footer', 'header', 'aside']
    for tag in unwanted_tags:
        html = remove_tag(html, tag)
    
    # 2. 查找可能的内容容器
    candidates = html.find_all(['article', 'main', 'div'])
    
    # 3. 计算每个候选的文本密度
    scored = []
    for c in candidates:
        text_len = len(c.get_text())
        link_ratio = count_links(c) / max(text_len, 1)
        # 文本多、链接少 = 高分
        score = text_len * (1 - link_ratio)
        scored.append((score, c))
    
    # 4. 返回得分最高的容器内容
    best = max(scored, key=lambda x: x[0])
    return clean_text(best[1])
```

### 来源 (source)

| 优先级 | 选择器 | 说明 |
|--------|--------|------|
| 1 | `json-ld > publisher > name` | 发布机构名称 |
| 2 | `meta[property="og:site_name"]` | 网站名称 |
| 3 | 域名提取 | 从 URL 提取域名 |

### 封面图 (cover_image)

| 优先级 | 选择器 | 说明 |
|--------|--------|------|
| 1 | `json-ld > image` | 结构化图片 |
| 2 | `og:image` | Open Graph 图片 |
| 3 | `meta[name="twitter:image"]` | Twitter 图片 |
| 4 | 文章内首图 | 正文第一张图片 |

---

## 清洗规则

提取后的内容需要清洗：

| 规则 | 示例 |
|------|------|
| 移除多余空白 | `"  多个   空格  "` → `"多个空格"` |
| 移除特殊字符 | 去除乱码、非打印字符 |
| 截断过长内容 | 正文保留前 50000 字符 |
| 标准化换行 | 统一使用 `\n` |

---

## 错误处理

| 情况 | 处理 |
|------|------|
| 所有策略都失败 | 返回空字符串，标记"未找到" |
| 部分字段缺失 | 使用默认值（见下表） |

| 字段 | 默认值 |
|------|--------|
| title | "无标题" |
| author | "未知作者" |
| published_time | 当前时间 |
| source | 域名 |
| category | "未分类" |
