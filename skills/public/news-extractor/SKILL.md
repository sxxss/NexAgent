---
id: news-extractor
name: 新闻文章提取器 Pro
description: 从网页智能抓取新闻文章，提取标题、作者、时间、正文等关键信息。支持批量处理、AI摘要、新闻分类等多种功能。
version: 0.1.0
---

# 新闻文章提取器 Pro

> 从网页智能抓取新闻文章，提取关键信息

## 这个 Skill 做什么

接收新闻网页 URL，提取完整结构化信息：
- **基础字段**：标题、作者、发布时间、正文、来源、封面图
- **AI 增强**：摘要（≤200字）、关键词（3-5个）、语言检测、新闻分类
- **附加信息**：阅读时长估算、发布日期标准化

---

## 使用方法

### 基本调用
```
请帮我提取这篇新闻：https://example.com/article123
```

### 指定输出格式
```
用 JSON 格式提取这篇新闻：https://example.com/article123
```

### 批量提取
```
帮我抓取以下新闻：
- https://news1.com/a1
- https://news2.com/a2
- https://news3.com/a3
```

---

## 执行流程

### Step 1：接收用户输入
- 解析 URL（单个或多个）
- 识别输出格式偏好（Markdown/JSON/CSV）

### Step 2：网页抓取
- 使用 fetch 工具获取网页内容
- 应用重试机制（最多3次）

### Step 3：结构化提取
> ⚠️ 详细提取策略见 `references/extraction-strategy.md`

按优先级尝试多种提取策略：
1. JSON-LD 结构化数据
2. Open Graph / Twitter Card 元数据
3. 传统 HTML 标签（h1、article、meta）
4. 智能正文推断

### Step 4：AI 增强处理
> ⚠️ 详细处理逻辑见 `references/ai-processing.md`

- 生成文章摘要
- 提取关键词
- 检测语言
- 分类新闻类型

### Step 5：格式化输出
> ⚠️ 输出格式模板见 `references/output-templates.md`

根据用户偏好返回：
- Markdown（默认）
- JSON
- CSV（仅批量时）

---

## 输出示例

### Markdown 格式
```markdown
# 文章标题

- **作者**：张三
- **发布时间**：2024-01-15 10:30:00
- **来源**：科技日报
- **阅读时长**：5 分钟
- **关键词**：人工智能、科技、创新
- **分类**：科技

## 摘要
这是文章的摘要内容...

## 正文
这是文章的正文内容...
```

### JSON 格式
```json
{
  "title": "文章标题",
  "author": "张三",
  "published_time": "2024-01-15T10:30:00",
  "source": "科技日报",
  "reading_time": 5,
  "keywords": ["人工智能", "科技", "创新"],
  "category": "科技",
  "summary": "这是文章的摘要内容...",
  "content": "这是文章的正文内容..."
}
```

---

## 边界情况处理

| 情况 | 处理方式 |
|------|----------|
| URL 无法访问 | 返回错误提示，说明原因（404/超时/拒绝访问） |
| 非新闻网页 | 尝试提取，标注"未知分类" |
| 内容被加密 | 返回部分信息，标注"正文可能不完整" |
| 批量全部失败 | 返回汇总错误报告 |
| 部分失败 | 成功的内容正常返回，失败的标注原因 |

---

## 何时读取 references/

| 文件 | 何时读取 |
|------|----------|
| `references/extraction-strategy.md` | 实现提取逻辑时必读 |
| `references/ai-processing.md` | 实现 AI 增强功能时必读 |
| `references/output-templates.md` | 生成输出格式时必读 |
| `references/category-keywords.md` | 需要分类词库时参考 |

---

## 附加功能（可选）

如需以下高级功能，请参考对应文档：
- **批量处理**：`references/batch-processing.md`
- **缓存机制**：`references/caching.md`
- **错误处理**：`references/error-handling.md`
- **性能优化**：`references/performance.md`

---

## 常见问题

**Q：支持哪些网站？**
> A：支持所有公开的新闻类网页，包括门户新闻、博客、媒体官网等。

**Q：提取失败怎么办？**
> A：自动重试3次，仍失败会返回详细错误信息，您可以手动检查 URL 或更换来源。

**Q：批量有数量限制吗？**
> A：建议单次不超过 10 个 URL，数量多可分批处理。
