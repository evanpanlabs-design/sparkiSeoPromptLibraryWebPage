# Pipeline Reference — 从 11_X_Scrape 继承的构建发布管线

> **版本**: 1.0 | **来源**: `11_X_Scrape` 生产系统 | **用途**: 16_NewCrawler 开发时的基准参考

---

## 1. 总体数据流

```
configs/x-scraper.yaml          ← 查询词 + 过滤阈值
        │
        ▼
[Phase 1] Playwright 浏览器抓取 → tweets 表     (x_multi_search.py → x_scraper_pw.py)
        │
        ▼
[Phase 2] MiniMax LLM 提取     → prompts 表    (extract_prompts.py)
        │
        ▼
[Phase 3] Gemini Vertex AI 生图 → .png + GCS   (generate_images.py)
        │
        ▼
[Build ] build_html.py          → HTML 文件     (DB → JS 数组嵌入)
        │
        ▼
[Publish] git push gh-pages     → GitHub Pages  上线
```

**核心设计原则**: 每阶段 `INSERT OR IGNORE` / `WHERE NOT EXISTS`，天然支持断点续跑和增量更新。

---

## 2. 数据库 (SQLite)

### 2.1 数据库文件

```
11_X_Scrape/data/veo_prompts.db
```

### 2.2 核心表

| 表 | 用途 | 关键字段 |
|---|---|---|
| `scrapes` | 抓取批次记录 | id, scrape_time, queries(JSON), query_stats(JSON) |
| `tweets` | 原始推文（去重） | id, tweet_id(UNIQUE), scrape_id(FK), text, author_name, author_screen, followers_count, favorite_count, retweet_count, reply_count, view_count, source_query |
| `prompts` | 提取的 Prompt | id, tweet_id(UNIQUE), scrape_id(FK), category, title, prompt_text, notes, author_name, author_screen, followers_count, likes_count, retweet_count, reply_count, view_count, image_gcs_url, image_generated_at, category_path |
| `categories` | 分类定义 | id, name(UNIQUE), description, is_active |
| `category_suggestions` | LLM 建议的新分类 | id, suggested_name, reason, status(pending/approved/rejected) |

### 2.3 关键查询接口（供 16_NewCrawler 实现时参考）

```python
# ── tweets 写入（去重） ──
def insert_tweets(scrape_id: int, tweets: list[dict], source_query: str = None):
    """INSERT OR IGNORE INTO tweets (...) VALUES (...)"""

# ── 增量获取未处理的 tweets ──
def get_tweets_without_prompts(limit: int = None) -> list[dict]:
    """SELECT t.* FROM tweets t LEFT JOIN prompts p ON t.tweet_id = p.tweet_id WHERE p.id IS NULL"""

# ── prompts 写入（去重） ──
def insert_prompts(scrape_id: int, prompts: list[dict]):
    """INSERT OR IGNORE INTO prompts (...) VALUES (...)"""

# ── 增量获取未生图的 prompts ──
def get_prompts_without_images(scrape_id: int = None, limit: int = None) -> list[dict]:
    """SELECT * FROM prompts WHERE image_gcs_url IS NULL"""

# ── 更新图片 URL ──
def update_prompt_image(prompt_id: int, gcs_url: str, category_path: str = None):
    """UPDATE prompts SET image_gcs_url=?, image_generated_at=?, category_path=COALESCE(?, category_path) WHERE id=?"""
```

---

## 3. HTML 构建 (build_html.py)

### 3.1 工作原理

[build_html.py](../scripts/build_html.py) 从 DB 读取全量 prompts，将其序列化为 JavaScript 数组，**直接替换** HTML 模板中的数据占位区。

### 3.2 模板机制

```
outputs/templates/veo3-prompt-library.html   ← 源模板（含空 prompts 数组 + sentinel 标记）
        │
        │  build_html.py 替换
        ▼
outputs/veo3-prompt-library.html             ← 构建产物（含真实数据，可直接打开）
```

**模板中的 sentinel 标记:**

```javascript
const prompts = [
    // ... 一行示例数据(构建时被替换) ...
] // PROMPTS_ARRAY_SENTINEL;
```

构建脚本找到 `const prompts = [` 到 `// PROMPTS_ARRAY_SENTINEL` 之间的内容，整段替换为 DB 最新数据。

### 3.3 数据转换映射

```python
# DB 扁平行 → 嵌套 JS 结构
prompts.append({
    "id": row["id"],
    "tweet_id": row["tweet_id"],
    "url": row["url"],
    "category": row["category"],
    "title": row["title"],
    "prompt_text": row["prompt_text"],
    "notes": row["notes"] or "",
    "author": {
        "name": row["author_name"],
        "screen_name": row["author_screen"],
        "followers": row["followers_count"],
    },
    "engagement": {
        "likes": row["likes_count"],
        "retweets": row["retweet_count"],
        "replies": row["reply_count"],
    },
})
```

### 3.4 质量控制（构建前校验）

```python
# 过滤占位符 prompt_text
PLACEHOLDER_TEXTS = {"...", "[the full prompt text]", ""}

# Schema 验证
REQUIRED_FIELDS = ["id", "tweet_id", "url", "category", "title", "prompt_text", "notes", "author", "engagement"]

# 图片验证
img_path = local_img_dir / f"{prompt['id']}.png"
if not img_path.exists():
    errors.append(f"missing image: {img_path}")
```

### 3.5 CLI 用法

```bash
# 本地构建
python scripts/build_html.py

# 指定 scrape
python scripts/build_html.py --scrape-id 2

# 自定义输出路径
python scripts/build_html.py --output /tmp/test.html

# 构建 + 推送 GitHub Pages
python scripts/build_html.py --publish

# 预览发布内容
python scripts/build_html.py --publish --dry-run
```

---

## 4. GitHub Pages 推送

### 4.1 目标仓库

```
https://github.com/sparki-ai/veo-prompt-station
分支: gh-pages
```

> **注意**: 11_X_Scrape 中 `build_html.py` 的 `GITHUB_REPO` 常量当前指向旧仓库 `evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git`，需要在 16_NewCrawler 中改为上述新地址。

### 4.2 推送流程

```
1. 检查 GH_TOKEN 环境变量/.env
2. clone/pull 目标仓库的 gh-pages 分支到 ~/.cache/sparki-web-pages/
3. 复制 index.html (构建产物) → gh-pages 仓库根目录
4. 复制 generated_images/*.png → gh-pages 仓库 generated_images/
5. git add -A && git commit && git push origin gh-pages
```

### 4.3 图片路径约定

| 位置 | 路径 |
|---|---|
| HTML 中引用 | `<img src="generated_images/{prompt_id}.png">` |
| 本地存储 | `outputs/generated_images/{prompt_id}.png` |
| GCS 存储 | `gs://sparki-op-test/prompts/{category}/{YYYY-MM}/{scrape_id}/{prompt_id}.png` |
| GitHub Pages | `generated_images/{prompt_id}.png` (相对于 index.html) |

### 4.4 图片容错机制

```html
<img src="generated_images/${prompt.id}.png"
     onerror="this.src='https://picsum.photos/seed/${prompt.tweet_id}/550/307'">
```

当本地图片不存在时，自动 fallback 到 Lorem Picsum 随机图。

---

## 5. 各阶段配置汇总

### 5.1 X 抓取 (Phase 1)

| 配置项 | 文件 | 默认值 |
|---|---|---|
| 搜索查询 | `configs/x-scraper.yaml` → `queries` | 5 组 Veo 关键词 |
| 负面关键词 | `configs/x-scraper.yaml` → `negative_keywords` | 9 个竞品名 |
| 最低点赞 | `configs/x-scraper.yaml` → `engagement.min_likes` | 50 |
| 最低粉丝 | `configs/x-scraper.yaml` → `engagement.min_followers` | 1000 |
| 最大滚动 | `--scroll` CLI 参数 | 20 |
| 代理 | `--proxy` CLI 参数 | `http://127.0.0.1:7897` |
| Cookie 有效期 | `run_pipeline.py` 硬编码 | 7 天 |

### 5.2 LLM 提取 (Phase 2)

| 配置项 | 来源 | 默认值 |
|---|---|---|
| API Base | env `OPENAI_API_BASE` | `https://api.minimaxi.com/v1` |
| API Key | env `OPENAI_API_KEY` | — |
| 模型 | `--model` CLI 参数 | `MiniMax-M2.7` |
| 并发 | `--concurrency` CLI 参数 | 15 |
| 超时 | 硬编码 | 60s/调用 |

### 5.3 图片生成 (Phase 3)

| 配置项 | 来源 | 默认值 |
|---|---|---|
| GCP 项目 | 硬编码 | `sparki-op` |
| GCS Bucket | 硬编码 | `sparki-op-test` |
| 模型优先级 | `IMAGE_MODELS` 列表 | `gemini-3-pro-image-preview` → `gemini-3.1-flash-image-preview` → `gemini-2.5-flash-image` |
| 并发 | 硬编码 | 3 |
| 重试次数 | 硬编码 | 3 次/模型 |
| 重试延迟 | 硬编码 | 5s 指数退避 |

---

## 6. 16_NewCrawler 对接要点

### 6.1 需要新增的模块

| 模块 | 对应 11_X_Scrape | 说明 |
|---|---|---|
| `src/agent/nodes.py` → `output_composer_node` | `build_html.py` | DB → HTML 构建 |
| `src/agent/nodes.py` → `publisher_node` (新) | `build_html.py --publish` | GitHub Pages 推送 |
| `src/memory/prompts.py` | `db.py` prompts 部分 | Prompt CRUD |
| `src/image_gen/gcs.py` | `generate_images.py` GCS 部分 | 图片上传 |

### 6.2 HTML 模板位置

```
16_NewCrawler/outputs/templates/veo3-prompt-library.html   ← 已从 11_X_Scrape 复制
```

构建节点从此文件读取模板，替换 sentinel 标记区域后输出到 `outputs/veo3-prompt-library.html`。

### 6.3 需要修改的 GitHub 目标

在 `build_html.py` 或对应的新模块中，将:
```python
GITHUB_REPO = "https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git"
```
改为:
```python
GITHUB_REPO = "https://github.com/sparki-ai/veo-prompt-station.git"
```

同时确保:
- `.env` 中有 `GH_TOKEN=ghp_...`（具有该仓库的 push 权限）
- 目标仓库已创建且 `gh-pages` 分支已存在
- GitHub Pages 已在仓库 Settings 中启用（Source: `gh-pages` branch）

### 6.4 流水线 CLI 参考

```bash
# 11_X_Scrape 的完整运行命令
python scripts/run_pipeline.py --all              # 全量
python scripts/run_pipeline.py --phase 1          # 仅抓取
python scripts/run_pipeline.py --phase 2          # 仅提取
python scripts/run_pipeline.py --phase 3          # 仅生图

# 构建 + 发布
python scripts/build_html.py --publish
```

---

## 7. 环境变量

```bash
# .env 文件（git-ignored）
OPENAI_API_KEY=sk-...                    # MiniMax API Key
OPENAI_API_BASE=https://api.minimaxi.com/v1
GOOGLE_CLOUD_PROJECT=sparki-op
GH_TOKEN=ghp_...                        # GitHub Personal Access Token（需要 repo scope）
```

---

## 8. 关键文件路径对照

```
11_X_Scrape/                              16_NewCrawler/
──────────────────────────────────        ──────────────────────────────────
scripts/db.py                             src/memory/prompts.py + schema.py
scripts/x_scraper_pw.py                   src/crawler/extraction.py + scroll.py + browser.py
scripts/x_multi_search.py                 (合并入 crawler_node + query_planner_node)
scripts/extract_prompts.py                src/worker/extractor.py
scripts/generate_images.py                src/image_gen/client.py + gcs.py
scripts/build_html.py                     src/agent/nodes.py → output_composer_node
scripts/run_pipeline.py                   src/agent/graph.py
configs/x-scraper.yaml                    configs/queries.yaml + engagement.yaml + crawler.yaml
outputs/templates/veo3-prompt-library.html  outputs/templates/veo3-prompt-library.html
outputs/generated_images/                 outputs/generated_images/
data/veo_prompts.db                       data/veo_prompts.db
```
