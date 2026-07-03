# Skill Tool Descriptions

**File:** `src/agent/skills/core_tools.py` (line ~829) + `src/agent/skills/keyword_tools.py` + `src/agent/skills/keyword_integration.py`  
**Purpose:** These descriptions are registered as `Skill` objects in the `SkillRegistry`. They are NOT direct LLM prompts themselves, but define the tool schema the LLM sees in `plan_node`'s `{tool_list}` field. When the LLM decides which tool to call, it reads these descriptions to understand what each tool does.

---

## Core Skills (core_tools.py)

### 1. crawl_tweets
```
从 X.com 爬取推文，直接调用 Apify API，将结果写入 DB
```
**Parameters:**
- `queries` (array) — 搜索关键词列表，默认使用 configs/queries.yaml
- `from_cache` (boolean) — 跳过爬取（仅返回提示）
- `max_cost` (float) — 每查询最大消费 USD，默认 0.10
- `max_items` (integer) — 每次爬取最大条数（Apify maxItems），默认 500
- `sort` (string) — 排序方式：Latest + Top / Latest / Top，默认 Latest + Top
- `include_search_terms` (boolean) — 是否在结果中包含搜索关键词，默认 False

**Examples:** `爬取最新推文`, `用新关键词跑一轮 crawl`

---

### 2. extract_prompts
```
从 DB 中无 prompt_text 的推文提取 Prompt（LLM 分析）
```
**Parameters:**
- `batch` (integer) — 最大处理条数，默认 50

**Examples:** `提取前50条prompt`, `跑一遍 extract 阶段`

---

### 3. score_prompts
```
对提取的 Prompts 做质量评分，过滤低于阈值的
```
**Parameters:**
- `batch` (integer) — 最大评分条数，默认 50
- `min_score` (float) — 最低质量分门槛，默认 0.4

**Examples:** `评分质量分0.5以上`, `跑一遍评分过滤`

---

### 4. sync_images
```
将 GCS 中的封面图同步到本地 generated_images/ 目录
```
**Parameters:** (none)

**Examples:** `同步所有封面图`, `把 GCS 图片同步到本地`

---

### 5. build_html
```
将 DB 中的 done prompts 生成为可浏览的 HTML 页面
```
**Parameters:**
- `category` (string) — 按分类筛选（可选）
- `min_score` (float) — 最低质量分门槛（可选）
- `sync_images` (boolean) — 是否同步图片到扁平目录，默认 True
- `limit` (integer) — 最大条数限制（可选）

**Examples:** `生成 HTML 页面`, `构建最新一批 prompt 的网页`

---

### 6. pool_status
```
查询 Prompt 池的当前状态——各状态的数量统计
```
**Parameters:** (none)

**Examples:** `池子状态怎么样？`, `还有多少图没生成？`

---

### 7. search_prompts
```
通过语义 Embedding 搜索 Prompt 库，找到与关键词最相关的 Prompt
```
**Parameters:**
- `query` (string, required) — 语义搜索的关键词
- `top_k` (integer) — 返回数量，默认 5
- `min_score` (float) — 最低相关性分数筛选

**Examples:** `找 Veo 3 相关的 prompt`, `搜索动画风格高质量提示词`

---

### 8. generate_images
```
为池中 pending 的 Prompt 生成封面图（串行安全模式，15s 间隔）
```
**Parameters:**
- `batch` (integer) — 生成数量，默认 8（0=全部）
- `sort_by` (string) — 排序方式：score（质量分）/ newest（最新）
- `filter` (object) — 过滤条件，如 {"min_score": 0.6}

**Examples:** `生成 10 张图`, `按分数生成前 5 张`

---

### 9. retry_failed
```
重试之前图片生成失败的 Prompt
```
**Parameters:**
- `batch` (integer) — 最大重试数量，默认 8

**Examples:** `重试失败的图`, `把失败的再跑一遍`

---

### 10. publish
```
将池中 done 状态的 Prompt 发布到 GitHub Pages 网站
```
**Parameters:**
- `category` (string) — 按分类筛选（可选）
- `min_score` (float) — 最低质量分门槛（可选）
- `message` (string) — git 提交信息

**Examples:** `发布网页`, `更新网站`

---

### 11. show_history
```
查看最近的任务执行历史和对话记录
```
**Parameters:**
- `limit` (integer) — 显示数量，默认 5
- `include_conversation` (boolean) — 是否包含对话历史

**Examples:** `之前做了什么`, `看看历史`

---

### 12. save_preference
```
保存用户偏好设置
```
**Parameters:**
- `key` (string, required) — 偏好键名
- `value` (string, required) — 偏好值

**Examples:** `记住我偏好 10 张一批`, `设置默认模型为 gemini-2.5`

---

### 13. get_preference
```
读取用户偏好设置
```
**Parameters:**
- `key` (string, required) — 偏好键名

**Examples:** `我之前偏好是什么`, `默认批次大小是多少`

---

## Keyword Strategy Tools (keyword_tools.py)

### 14. analyze_keyword_yield
```
分析历史漏斗表现，返回各关键词的 raw/filtered/extracted/qualified 数量和比率
```
**Parameters:**
- `scrape_run_id` (integer) — 指定某次爬取（可选，默认全部）

---

### 15. generate_keyword_suggestions
```
基于历史漏斗表现生成新的关键词建议（需要用户确认后才能用于爬虫）
```
**Parameters:** (none, reads from keyword_yields analysis)

---

### 16. confirm_keywords
```
用户确认/否决 AI 建议的关键词（确认后写入 approved_keywords 表，用于下次爬虫）
```
**Parameters:**
- `keywords` (array, required) — 关键词列表
- `action` (string, required) — "approve" | "reject"

---

### 17. show_approved_keywords
```
查看当前已确认用于爬取的关键词列表
```
**Parameters:** (none)

---

### 18. crawl_with_keywords
```
使用指定关键词执行爬虫（优先级：用户指定 > 已确认推荐 > seed）
```
**Parameters:**
- `keywords` (array) — 用户指定关键词（可选）
- `max_cost` (float) — 最大消费 USD