# 工具数据接口文档

> 本文档定义所有 Skill Tool 的输入参数、输出数据、依赖表、上下游接口。
> 适用版本：V3.2（pending: GCS 中转废除 → 本地直存改造）

---

## 接口约定

- 所有 tool 函数签名：`def tool_NAME(args: dict) -> str`
- `args` 的所有参数均为可选（有默认值）
- 返回值：人类可读的状态字符串（不是 JSON）
- 数据库写操作均在 tool 函数内部完成，通过 `src.memory.schema._conn()` 获取连接
- 工具调用流水已记录在 `conversation_history` 表（role=tool）

---

## 工具清单

---

### 1. `crawl_tweets` — Apify 爬虫

**文件**：`src/agent/skills/core_tools.py` → `tool_crawl_tweets()`

**分类**：`data_collection`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `queries` | `list[str]` | 从 `configs/queries.yaml` 读取 | 搜索关键词列表 |
| `max_items` | `int` | 500 | 每个 Actor run 的最大条目数 |
| `max_cost` | `float` | 10.0 | 每关键词最大花费（美元） |

**输出**：状态字符串
```
爬取完成: {N} tweets, {K} queries
写入 DB 完成，待 extract_prompts 阶段处理
```

**读取数据源**
- `configs/crawler.yaml` — `actor_id`, `api_token`, `timeout_ms`, `max_retries`
- 环境变量 `APIFY_API_TOKEN`

**写入表**：`tweets`（INSERT OR IGNORE，按 `tweet_id` 去重）

| 字段 | 来源 |
|---|---|
| `tweet_id` | Apify 返回 |
| `url` | Apify 返回 |
| `text` | Apify 返回 |
| `short_text` | Apify 返回 |
| `author_name` | Apify 返回 |
| `author_screen` | Apify 返回 |
| `author_followers` | Apify 返回 |
| `likes_count` | Apify 返回 |
| `retweet_count` | Apify 返回 |
| `reply_count` | Apify 返回 |
| `view_count` | Apify 返回 |
| `scraped_at` | Apify 返回 |
| `created_at` | `datetime.now(timezone.utc)` |

**前置条件**：无
**后续工具**：`extract_prompts`

---

### 2. `extract_prompts` — LLM Prompt 提取

**文件**：`src/agent/skills/core_tools.py` → `tool_extract_prompts()`

**分类**：`data_collection`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `batch` | `int` | 50 | 最大处理条数 |

**输出**：状态字符串
```
提取完成: {M}/{N} prompts extracted（跳过 {S} 条非 Prompt 推文）
```

**读取表**：V3.2: `tweets`（WHERE `has_prompt = 0`）→ V3.3 目标: `prompts`（WHERE `has_prompt = 0`）

**写入表**

1. V3.2: `tweets`（UPDATE prompt_text/category/title/notes）+ `prompts`（INSERT）
2. V3.3 目标: `prompts`（同一张表 UPDATE 所有字段）

| tweets 更新字段 | 来源 |
|---|---|
| `prompt_text` | LLM 提取结果 |
| `category` | LLM 提取结果 |
| `title` | LLM 提取结果 |
| `notes` | LLM 提取结果 |

| prompts 写入字段 | 来源 |
|---|---|
| `tweet_id` | tweets 表 |
| `url` | tweets 表 |
| `category` | LLM 提取结果 |
| `title` | LLM 提取结果 |
| `prompt_text` | LLM 提取结果 |
| `notes` | LLM 提取结果 |
| `author_name` | tweets 表 |
| `author_screen` | tweets 表 |
| `author_followers` | tweets 表 |
| `likes_count` | tweets 表 |
| `retweet_count` | tweets 表 |
| `reply_count` | tweets 表 |
| `view_count` | tweets 表 |
| `extracted_at` | `datetime.now(timezone.utc)` |
| `image_status` | `'pending'`（固定）→ V3.3 改用 `has_cover_image = 0` |

**前置条件**：`crawl_tweets` 已完成
**后续工具**：`score_prompts`
**依赖 LLM**：`GeminiClient`（`src/llm/gemini_client.py`）
**依赖文件**：`prompts/extraction/01_extraction_system.md`（三阶段提取 prompt）

---

### 3. `score_prompts` — 质量打分

**文件**：`src/agent/skills/core_tools.py` → `tool_score_prompts()`

**分类**：`data_collection`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `batch` | `int` | 50 | 最大处理条数 |
| `min_score` | `float` | 0.4 | 合格分数线（overall score） |

**输出**：状态字符串
```
评分完成: {Q}/{T} qualified（min={min_score}，batch={batch}）
```

**读取表**：`prompts`（WHERE `quality_scores IS NULL AND prompt_text IS NOT NULL`，按 `likes_count DESC`）

**写入表**：`prompts`（UPDATE `quality_scores`）

| 字段 | 来源 |
|---|---|
| `quality_scores` | CSV 字符串：`spec,vis,nov,gen,overall` |

**前置条件**：`extract_prompts` 已完成
**后续工具**：`generate_images`
**依赖 LLM**：`GeminiClient`
**依赖文件**：`prompts/scoring/01_scoring_system.md`（四维打分 prompt）
**依赖配置**：`configs/quality.yaml`（权重和阈值）

---

### 4. `generate_images` — 封面图生成

**文件**：`src/agent/skills/core_tools.py` → `tool_generate_images()`

**分类**：`ai_generation`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `batch` | `int` | 8 | 最大生成条数（0=全部 pending） |
| `sort_by` | `str` | `"score"` | 排序方式：`score`（质量分 DESC）/ `newest`（id DESC） |
| `filter` | `dict` | `None` | 过滤条件，如 `{"min_score": 0.6}` |
| `max_workers` | `int` | 3 | 并行 worker 数 |

**输出**：状态字符串
```
图片生成完成: {S}/{T} 成功, {F}/{T} 失败
模型: gemini-2.5-flash-image
当前池: {P} pending, {D} done, {F} failed
```

**读取表**：V3.2: `prompts`（WHERE `image_status = 'pending'`）→ V3.3 目标: `prompts`（WHERE `has_cover_image = 0 AND has_prompt = 1`）

**写入表**：生成完成后统一 UPDATE `prompts`

| 字段 | 来源 |
|---|---|
| `image_gcs_url` | GCS URL（待废除）→ 改为 `image_local_path` |
| `image_status` | `'done'`（成功）或 `'failed'`（失败） |

**本地文件写入**：`outputs/generated_images/{id}.png`（GCS 中转废除后）

**前置条件**：`score_prompts` 已完成（或直接对 pending 状态生效）
**后续工具**：`build_html`（sync_images 阶段已废除）
**依赖模块**：`src/image_gen/generator.py`（`RateLimitSafeGenerator`）
**依赖配置**：`configs/gemini.yaml`（模型列表、风格关键字）

**注**：10 条一批，429 时在批内末尾重试。每张生成后立即写 DB（待改）。

---

### 5. `sync_images` — 图片同步

**文件**：`src/agent/skills/core_tools.py` → `tool_sync_images()`

**分类**：`ai_generation`

> ⚠️ **状态**：GCS 中转已废除，此工具保留用于兼容，后续可能废弃。

**输入参数**：无

**输出**：状态字符串
```
Images: {C} copied, {S} skipped, {E} errors
```

**工作流**：
1. 调用 `scripts/sync_images_from_gcs.py` → `download_all()` — GCS → `outputs/images/{cat}/{yyyy-mm}/`
2. 调用 `scripts/build_html.py` → `_sync_images_to_flat_dir()` — 复制到 `outputs/generated_images/`

**前置条件**：`generate_images` 已完成（GCS 上传完毕）
**后续工具**：`build_html`

---

### 6. `build_html` — HTML 构建

**文件**：`src/agent/skills/core_tools.py` → `tool_build_html()`

**分类**：`web_maintenance`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `category` | `str` | `None` | 按分类过滤 |
| `min_score` | `float` | `None` | 按质量分过滤 |
| `sync_images` | `bool` | `True` | 是否先执行图片同步 |
| `limit` | `int` | `None` | 最大构建条数 |

**输出**：状态字符串
```
Built HTML: {N} prompts
```

**读取表**：`prompts`（WHERE `image_status = 'done'`）

**写入文件**：
- `outputs/index.html`（主页）
- `outputs/prompts/{tweet_id}.html`（详情页，1+N 模式）
- `outputs/generated_images/`（图片已在上一步同步）

**前置条件**：`generate_images` 已完成
**后续工具**：`publish`
**依赖文件**：
- `outputs/templates/veo3-prompt-library.html`（主页模板）
- `scripts/build_html.py`

---

### 7. `publish` — GitHub 推送

**文件**：`src/agent/skills/core_tools.py` → `tool_publish()`

**分类**：`web_maintenance`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `repo` | `str` | `PROJECT_ROOT/.git` | Git 仓库路径 |
| `message` | `str` | `"Update prompt library"` | 提交信息 |
| `category` | `str` | `None` | 仅推送该分类 |
| `min_score` | `float` | `None` | 按质量分过滤 |

**输出**：状态字符串
```
Published: {N} prompts → GitHub Pages
Official repo push: {status}
```

**工作流**：
1. 调用 `scripts/build_html.py --sync-images`（含 HTML 构建）
2. `git add outputs/`
3. `git commit -m "{message}"`
4. `git push origin gh-pages`（个人仓库）
5. `git push origin main`（官方仓库）

**前置条件**：`build_html` 已完成
**后续工具**：无（终端步骤）

---

### 8. `pool_status` — 池状态查询

**文件**：`src/agent/skills/core_tools.py` → `tool_pool_status()`

**分类**：`system`

**输入参数**：无

**输出**：状态字符串
```
Prompt Pool 状态:
  pending    : {N}
  generating : {N}
  done       : {N}
  failed     : {N}
  published  : {N}
  ──────────────────
  总计        : {N}
```

**读取表**：`prompts`（GROUP BY `image_status`）

---

### 9. `search_prompts` — 语义检索

**文件**：`src/agent/skills/core_tools.py` → `tool_search_prompts()`

**分类**：`system`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | `""` | 搜索关键词 |
| `top_k` | `int` | 5 | 返回条数 |
| `min_score` | `float` | `None` | 最低相似度阈值 |

**输出**：状态字符串（截断后显示）
```
找到 {N} 条相关Prompt（按相关性排序）:
  1. [0.68] {prompt_text 前200字符 truncated}...
  2. [0.61] {prompt_text}...
  ...
```

**读取表**：`prompt_embeddings`（JOIN `prompts`）
**依赖模块**：`src/agent/memory/embedding.py`（`search_prompts()`）
**依赖配置**：`configs/agent.yaml`（embedding 模型）

---

### 10. `retry_failed` — 重试失败图片

**文件**：`src/agent/skills/core_tools.py` → `tool_retry_failed()`

**分类**：`ai_generation`

**输入参数**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `batch` | `int` | 8 | 最大重试条数 |

**输出**：状态字符串
```
已重置 {N} 条 failed → pending
图片生成完成: {S}/{T} 成功, {F}/{T} 失败
当前池: {P} pending, {D} done, {F} failed
```

**工作流**：
1. SELECT `image_status = 'failed'` 的记录
2. UPDATE status → `'pending'`
3. 调用 `generator.generate()` 逐条重试
4. UPDATE 结果（成功 → `image_gcs_url` + `'done'`；失败 → 保持 `'failed'`）

---

### 11~13. Memory 系列（`show_history` / `save_preference` / `get_preference`）

**文件**：`src/agent/skills/core_tools.py`

| 工具 | 读取表 | 写入表 |
|---|---|---|
| `show_history` | `conversation_history`（LIMIT 20，ORDER BY `created_at DESC`） | — |
| `save_preference` | — | `user_preferences`（UPSERT on `key`） |
| `get_preference` | `user_preferences`（WHERE `key = ?`） | — |

---

### 14~18. Keyword 系列

| 工具 | 文件 | 读取表 | 写入表 |
|---|---|---|---|
| `analyze_keyword_yield` | `keyword_tools.py` | `keyword_yields` | — |
| `generate_keyword_suggestions` | `keyword_tools.py` | `approved_keywords` | `keyword_suggestions` |
| `confirm_keywords` | `keyword_tools.py` | `keyword_suggestions` | `approved_keywords`（INSERT） + `keyword_suggestions`（UPDATE status） |
| `show_approved_keywords` | `keyword_tools.py` | `approved_keywords` | — |
| `crawl_with_keywords` | `keyword_integration.py` | `approved_keywords` | 同 `crawl_tweets` |

---

## 数据库写入汇总（V3.3 目标：3表 → 2表）

> ⚠️ 以下为当前实现（V3.2）。目标版本将 tweets + prompts 合并为一张 `prompts` 表，images 改为 `image_attempts`。

### 当前写入表（V3.2）

| 工具 | 写入表 | 关键字段 |
|---|---|---|
| `crawl_tweets` | `tweets` | tweet_id（去重）, url, text, author, likes/view/retweet/reply, has_raw=1 |
| `extract_prompts` | `tweets` | prompt_text, category, title, notes（UPDATE） |
| `extract_prompts` | `prompts` | tweet_id, category, title, prompt_text, notes, author, likes, image_status='pending' |
| `score_prompts` | `prompts` | quality_scores（CSV） |
| `generate_images` | `prompts` | image_local_path, image_status |
| `retry_failed` | `prompts` | image_status（'pending' → 'done'/'failed'） |
| `show_history` | — | 只读 |
| `save_preference` | `user_preferences` | key-value |
| `get_preference` | — | 只读 |
| `analyze_keyword_yield` | — | 只读 |
| `generate_keyword_suggestions` | `keyword_suggestions` | suggested_keyword, reason, status='pending' |
| `confirm_keywords` | `approved_keywords` | keyword, source, approved_at |
| `confirm_keywords` | `keyword_suggestions` | status → 'approved'/'rejected' |
| `crawl_with_keywords` | `tweets` | 同 `crawl_tweets` |

### 目标写入表（V3.3 合并后）

| 工具 | 写入表 | 关键字段 |
|---|---|---|
| `crawl_tweets` | `prompts` | tweet_id, url, text, author, likes/view/retweet/reply, **has_raw_tweet=1** |
| `extract_prompts` | `prompts` | prompt_text, category, title, notes, quality_scores, **has_prompt=1** |
| `generate_images` | `prompts` | image_local_path, **has_cover_image=1** |
| `generate_images` | `image_attempts` | prompt_id, attempt_index, model_used, status, error_message |
| `score_prompts` | `prompts`（同一张） | quality_scores（UPDATE） |
| `retry_failed` | `image_attempts`（追加日志） | attempt_index++, status, error_message |

### V3.3 三 Flag 状态机

| Flag | 说明 | 触发工具 |
|---|---|---|
| `has_raw_tweet` | Tweet 原始数据已入库 | `crawl_tweets` |
| `has_prompt` | Prompt 文本 + 分类已提取 | `extract_prompts` |
| `has_cover_image` | 封面图已生成（本地路径已记录） | `generate_images` |

---

## Pipeline 阶段链（V3.3 目标版）

```
crawl_tweets
    ↓ prompts 表 INSERT，has_raw_tweet=1
extract_prompts
    ↓ prompts 表 UPDATE prompt_text/category/title/notes，has_prompt=1
score_prompts
    ↓ prompts 表 UPDATE quality_scores（同一行）
generate_images   ← 10条一批，429 批内末尾 retry，逐图写 DB + image_attempts 日志
    ↓ prompts 表 UPDATE image_local_path，has_cover_image=1
build_html        ← sync_images 已废除，直接引用 generated_images/
    ↓ outputs/index.html + outputs/prompts/*.html
publish
    ↓ git push → 个人仓 gh-pages + 官方仓 main
```

### V3.3 Flag 状态查询

| 当前状态 | 查询条件 |
|---|---|
| 待爬取 | `has_raw_tweet = 0` |
| 待提取 | `has_raw_tweet = 1 AND has_prompt = 0` |
| 待生图 | `has_raw_tweet = 1 AND has_prompt = 1 AND has_cover_image = 0` |
| 待发布 | `has_cover_image = 1` |

---

*文档版本：V3.2 · 2026-05-27 · 含 V3.3 目标架构标注*