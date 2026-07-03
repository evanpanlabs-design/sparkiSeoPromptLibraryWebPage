# Veo Prompt Library — 内容更新操作手册

> **版本**: v2.0 | **日期**: 2026-07-03
> **受众**: (1) 人类业务运营人员 (2) Claude Code 等 Coding Agent
> **用途**: 使用现有工具完成"增加提示词子页面"的完整操作指南

---

## 0. 文档约定

本文档中所有操作命令都标注了执行方式：

| 标记 | 含义 |
|---|---|
| `[Human]` | 人类在终端执行的命令 |
| `[Agent]` | Coding Agent 调用的 Skill/Tool 名称 |
| `[Both]` | 两种方式都可以 |

---

## 1. 系统概览

### 1.1 当前有什么

项目有 **13 个独立工具**，每个工具完成一个具体任务。Agent 编排层尚未搭建完成，工具需要**逐个手动调用**。

### 1.2 工具全景图

```
数据采集                AI 生成                 Web 发布
───────────          ────────────           ───────────
crawl_tweets         generate_images        build_html
    ↓                     ↑                     ↓
extract_prompts      sync_images (弃用)     publish
    ↓                                          
score_prompts        retry_failed              
                        
辅助工具: pool_status, search_prompts, show_history, save_preference, get_preference
```

### 1.3 核心数据流

```
X.com → crawl → tweets 表 → extract → prompts 表 → score → quality_scores
                                                          ↓
用户访问 ← gh-pages ← publish ← index.html ← build ← GCS images ← generate
```

### 1.4 工具总表

| # | 工具名 | 做什么 | 输入 | 输出 | 状态 |
|---|---|------|------|------|------|
| 1 | `crawl_tweets` | 从 X.com 采集推文 | 搜索关键词 | `tweets` 表 | ✅ |
| 2 | `extract_prompts` | 从推文中提取 Veo prompt | `tweets` 表 | `prompts` 表 | ✅ |
| 3 | `score_prompts` | 给 prompt 打分 | `prompts` 表 | `quality_scores` | ✅ |
| 4 | `generate_images` | 用 AI 生成封面图 | `prompts` 表 | GCS + `image_gcs_url` | ✅ |
| 5 | `sync_images` | 从 GCS 同步图片到本地 | GCS bucket | `outputs/images/` | ⚠️ 即将弃用 |
| 6 | `build_html` | 构建静态 HTML 页面 | `prompts` 表 + 模板 | `index.html` + 详情页 | ⚠️ import 有 bug |
| 7 | `publish` | 发布到 GitHub Pages | HTML 文件 | `gh-pages` 分支 | ⚠️ git add 不全 |
| 8 | `retry_failed` | 重试失败的图片生成 | 失败的 prompt | 重试生成 | ✅ |
| 9 | `pool_status` | 查看 prompt 池状态 | 无 | 统计表格 | ✅ |
| 10 | `search_prompts` | 语义搜索 prompt | 查询文本 | 搜索结果 | ⚠️ 返回 stub |
| 11 | `show_history` | 查看任务历史 | 无 | 历史记录 | ✅ |
| 12 | `save_preference` | 保存用户偏好 | key-value | DB 写入 | ✅ |
| 13 | `get_preference` | 读取用户偏好 | key | value | ✅ |

---

## 2. 环境准备

### 2.1 [Human] 前置条件检查

```bash
# 进入项目目录
cd 16_NewCrawler

# 确认 Python 环境
python --version      # 需要 3.10+

# 确认数据库存在
ls data/veo_prompts.db

# 确认 Apify token（用于 crawl_tweets）
grep APIFY_API_TOKEN .env
# 应输出: APIFY_API_TOKEN=your_apify_token_here

# 确认 GCS 认证（用于 generate_images）
gcloud auth application-default login 2>/dev/null || echo "需要先认证 GCS"
```

### 2.2 [Agent] 前置条件检查

Agent 应首先调用以下工具确认环境就绪：

```
Step 1: pool_status   → 确认 DB 可读，了解当前 prompt 池状态
Step 2: 检查 .env 中的 APIFY_API_TOKEN 是否已配置
Step 3: 检查 configs/queries.yaml 中的搜索关键词
```

---

## 3. 标准全流程：从零增加新 Prompt 子页面

以下是从采集到发布上线的完整 7 步流程。

### Step 1: 采集推文 — `crawl_tweets`

**做什么**: 用 Apify 从 X.com 搜索 Veo 相关推文，写入 `tweets` 表。

**[Human] 命令行执行:**
```bash
python -m src.agent.chat -m "crawl_tweets"
```
或者进入交互模式后输入 `crawl_tweets`。

**[Agent] 工具调用:**
```
Tool: crawl_tweets
Params:
  queries: ["veo 3 prompt", "veo video generation", ...]  # 可选，默认从 configs/queries.yaml 读取
  max_items: 500       # 每个 query 最多获取推文数
  max_cost: 0.10       # 每个 query 最大花费 USD
  sort: "Latest + Top"
```

**验证成功:**
```
[Human]  python -m src.main status    # 查看 scrape 状态
[Agent]  调用 pool_status             # 查看 tweets 数量变化
[Both]   sqlite3 data/veo_prompts.db "SELECT COUNT(*) FROM tweets;"
```

**卡住了？**
- Apify token 无效 → 检查 `.env` 中的 `APIFY_API_TOKEN`
- 网络不通 → Apify 需要外网访问，确认代理设置
- 0 条 tweet → 检查 `configs/queries.yaml` 中的关键词是否合理

---

### Step 2: 提取 Prompt — `extract_prompts`

**做什么**: 从 `tweets` 表中筛选包含 "veo" 关键词的推文，用 LLM 三遍提取 prompt 文本，写入 `prompts` 表。

**前置条件**: Step 1 完成，`tweets` 表有数据。

**[Human] 命令行执行:**
```bash
python -m src.agent.chat -m "extract_prompts batch 100"
```

**[Agent] 工具调用:**
```
Tool: extract_prompts
Params:
  batch: 100      # 最多处理推文数，按 likes 降序取前 N 条
```

**验证成功:**
```bash
sqlite3 data/veo_prompts.db "SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;"
```
- 有 `pending` 状态的 prompt 出现即为正常
- 可以抽查: `SELECT prompt_text FROM prompts LIMIT 3;` 确认提取质量

**卡住了？**
- 0 条提取 → 检查 tweets 表中 `prompt_text IS NULL` 的行数；可能是推文不包含 "veo" 关键词被过滤
- LLM 报错 → 检查 Vertex AI 认证: `gcloud auth print-access-token`

---

### Step 3: 评分 — `score_prompts`

**做什么**: 用 LLM 对每个 prompt 从 4 个维度打分（specificity, visual_detail, novelty, generatable），写入 `quality_scores` 字段。

**前置条件**: Step 2 完成，有 `quality_scores IS NULL` 的 prompt。

**[Human] 命令行执行:**
```bash
python -m src.agent.chat -m "score_prompts batch 50 min_score 0.4"
```

**[Agent] 工具调用:**
```
Tool: score_prompts
Params:
  batch: 50        # 最多评分数量
  min_score: 0.4   # 最低分阈值（低于此分的 prompt 不会被 publish）
```

**验证成功:**
```bash
sqlite3 data/veo_prompts.db "SELECT quality_scores FROM prompts WHERE quality_scores IS NOT NULL LIMIT 3;"
```
- 应输出类似 `0.75,0.80,0.60,0.70,0.71` 的 CSV 格式

**卡住了？**
- LLM 返回格式错误 → 检查 `configs/llm.yaml` 中模型配置
- 全部低于阈值 → 调低 `min_score`，或检查 prompt 质量

---

### Step 4: 生成封面图 — `generate_images`

**做什么**: 对 `image_status='pending'` 的 prompt 调用 Gemini Image 模型生成 16:9 封面图，上传到 GCS。

**前置条件**: Step 3 可选完成（未评分的 prompt 也可生成图片），需要有 GCS 写入权限和 Gemini 配额。

**[Human] 命令行执行:**
```bash
python -m src.agent.chat -m "generate_images batch 8"
```

**[Agent] 工具调用:**
```
Tool: generate_images
Params:
  batch: 8             # 本次生成数量 (0=全部)
  sort_by: "score"     # "score" 按评分降序, "newest" 按最新
  max_workers: 3       # 并发数 (不要超过 3，有 rate limit)
  filter: {"min_score": 0.5}   # 可选，只给高分 prompt 生成
```

**验证成功:**
```
[Human]  python -m src.main status
[Agent]  调用 pool_status
```
- `done` 计数增加
- 检查 GCS: `gsutil ls gs://sparki-op-test/prompts/`

**卡住了？**
- Rate limit → 降低 `max_workers` 到 1，稍后重试
- GCS 权限 → 确认 `gcloud auth application-default login` 的账号有 `sparki-op-test` bucket 写入权限
- 图片质量差 → 可以接受，后续通过 retry_failed 重试

---

### Step 5: 同步图片 — `sync_images` (可选，即将弃用)

**做什么**: 从 GCS 下载图片到本地 `outputs/images/` 和 `outputs/generated_images/`。

**注意**: V3.2 中 `build_html` 已包含此步骤。单独调用仅用于诊断。

**[Human] 命令行执行:**
```bash
python scripts/sync_images_from_gcs.py
```

---

### Step 6: 构建 HTML — `build_html`

**做什么**: 从 `prompts` 表读取所有 `image_status='done'` 的 prompt，生成 `outputs/index.html`（首页）和 `outputs/prompts/{slug}.html`（详情页）。

**前置条件**: Step 4 完成，有 `image_status='done'` 的 prompt。

**[Human] 命令行执行:**
```bash
# 方式 A: 直接用脚本（推荐，绕过 Agent 的 import bug）
python scripts/build_html.py

# 方式 B: 筛选特定分类
python scripts/build_html.py --category cinematic

# 方式 C: 限制数量和最低分
python scripts/build_html.py --limit 20 --min-score 0.6
```

**[Agent] 执行方式:**
```
# Agent 应直接运行脚本而非调用 tool_build_html（该工具 import 有 bug）
Bash: cd {PROJECT_ROOT} && python scripts/build_html.py --category {cat} --min-score {score}
```

**验证成功:**
```bash
# 确认首页生成
ls -la outputs/index.html

# 确认详情页生成
ls outputs/prompts/ | wc -l

# 抽查详情页链接
grep 'href="/prompts/' outputs/prompts/*.html | head -5
# 所有链接应以 /prompts/ 开头（绝对路径），不应出现 ../prompts/ 或 ../../prompts/

# 抽查首页链接
grep "window.location.href='/prompts/" outputs/index.html | head -3
# 所有链接应以 /prompts/ 开头
```

**卡住了？**
- Sentinel markers not found → `outputs/templates/index.html` 中必须有 `const prompts = [` 和 `] // PROMPTS_ARRAY_SENTINEL;` 标记
- 0 个 detail 页面 → 检查 `prompts` 表中 `image_status='done'` 的记录数
- 链接是相对路径 → 检查 `scripts/build_html.py` 中的模板，所有 `href=` 必须以 `/` 开头

---

### Step 7: 发布 — `publish`

**做什么**: 将 `outputs/` 目录下的文件推送到 GitHub Pages (`gh-pages` 分支)。

**前置条件**: Step 6 完成。

**[Human] 命令行执行:**
```bash
# 方式 A: 完整发布（构建 + git push）
python scripts/build_site.py --no-html --no-sitemap
# --no-html    = 跳过构建（已在 Step 6 完成）
# --no-sitemap = 跳过 sitemap（已在 Step 6.5 完成）

# 方式 B: 仅 git 操作（最直接）
cd outputs
git add index.html 404.html prompts/ sitemap.xml generated_images/
git commit -m "deploy: update prompt library $(date +%Y-%m-%d)"
git subtree push --prefix outputs origin gh-pages
```

**[Agent] 执行方式:**
```
Bash: cd {PROJECT_ROOT}/outputs && git add -A && git commit -m "deploy: update prompts" && git push origin `git subtree split --prefix outputs master`:gh-pages --force
```

**验证成功:**
- 等待 2-3 分钟（GitHub Pages 构建延迟）
- 访问 `https://veo.sparki.io/` 确认首页更新
- 访问 `https://veo.sparki.io/sitemap.xml` 确认 URL 格式正确（有 `.html` 后缀）
- 抽查详情页: `https://veo.sparki.io/prompts/{任意slug}.html`

**卡住了？**
- 推送被拒绝 → 检查是否有未拉取的远程更新: `git fetch origin gh-pages`
- 线上没变化 → GitHub Pages 有 1-3 分钟缓存；检查 `https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage/deployments`
- 图片 404 → 检查 `outputs/generated_images/` 是否被 git add 并推送

---

## 4. 增量更新：已有数据，只增加新 Prompt

如果数据库已有新的 prompt（跳过 Step 1-3），只需更新图片和页面：

```
Step 4: generate_images   → 只为 pending prompt 生成图片
Step 6: build_html        → 重建所有页面（包含新旧 prompt）
Step 7: publish           → 发布
```

简化命令:
```bash
# [Human] 一条龙
python -m src.agent.chat -m "generate_images batch 0"  # batch=0 表示全部
python scripts/build_html.py
# 然后手动 git push
```

---

## 5. 增量更新：已有数据不变，只重建页面

如果只是模板/样式改了，数据库没变：

```bash
# [Human]
python scripts/build_html.py    # 重新构建
# 验证后 publish
```

---

## 6. 新增分类子页面

当前系统**不支持**自动生成独立分类页面。如果需要给某个分类（如 `cinematic`、`commercial`）创建独立 SEO 落地页，流程如下：

### 6.1 当前已有的分类能力

首页已内置 `category` 筛选：
- URL: `https://veo.sparki.io/?category=cinematic`
- 通过 JS 过滤，无需额外页面
- 这**不是**独立的 SEO 页面（搜索引擎不会索引 URL 参数）

### 6.2 创建真正的独立分类页面

需要开发介入，涉及以下文件变更：

| 步骤 | 文件 | 改动 |
|---|---|---|
| 1 | `outputs/templates/` | 创建新模板 `{category}-prompts.html` |
| 2 | `scripts/build_html.py` | 在 `build()` 中增加 `--category-page` 参数，按分类独立构建 |
| 3 | `scripts/generate_sitemap.py` | 将新页面 URL 加入 sitemap |
| 4 | `outputs/index.html` | 导航栏增加新页面链接 |
| 5 | `scripts/build_html.py:265-272` | 详情页导航栏也增加链接 |

**预估工作量**: 2-4 小时开发 + 测试。

---

## 7. 验证清单

每次内容更新后，按以下 checklist 逐项验证：

### 7.1 数据库级验证

```bash
# 查看各状态 prompt 数量
sqlite3 data/veo_prompts.db "SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;"

# 查看最近更新的 prompt
sqlite3 data/veo_prompts.db "SELECT id, title, image_status FROM prompts ORDER BY id DESC LIMIT 5;"

# 确认有 done 状态的 prompt（否则 build_html 输出为空）
```

### 7.2 页面级验证

- [ ] `https://veo.sparki.io/` 首页正常加载
- [ ] 首页卡片数量与预期一致
- [ ] 点击卡片能跳转到详情页
- [ ] 详情页图片正常显示
- [ ] 详情页 Prompt 文本完整
- [ ] Copy Prompt 按钮可复制
- [ ] Share 按钮链接正确
- [ ] 底部 "Same Category" 推荐卡片链接正确
- [ ] 返回首页按钮正常
- [ ] `https://veo.sparki.io/404.html` 存在且显示友好

### 7.3 SEO 验证

- [ ] `https://veo.sparki.io/sitemap.xml` 可访问
- [ ] sitemap 中所有 URL 格式为 `https://veo.sparki.io/prompts/{slug}.html`（**有 `.html` 后缀**）
- [ ] sitemap 中无重复 URL

### 7.4 已知风险 URL 专项验证

```
https://veo.sparki.io/prompts/the-mirrors-reflection-2048318771547549709.html
https://veo.sparki.io/prompts/dior-lipstick-forging-cinematic-ad-2040753443040809168.html
```
这两个 URL 在 2026-07-03 修复前会导致重定向循环。**每次发布后必须验证这两条能正常访问。**

---

## 8. 已知问题 & 陷阱

本节列出 Agent 文档与实际代码之间的差异。**遇到问题时优先查这里。**

### 8.1 tool_build_html 的 import bug

**位置**: `src/agent/skills/core_tools.py:409`

```python
# 当前代码（错误）:
from scripts.build_html import build_html, _sync_images_to_flat_dir
# 正确应该是:
from scripts.build_html import build, sync_images_to_flat_dir
```

**影响**: Agent 模式下调用 `build_html` 工具会报 `ImportError`。
**绕过**: 直接运行 `python scripts/build_html.py`（不走 Agent）。

### 8.2 tool_publish 的 git add 不全

**位置**: `src/agent/skills/core_tools.py:723-728`

当前只 add 了 `outputs/index.html`，**没有 add**:
- `outputs/prompts/*.html`（所有详情页）
- `outputs/generated_images/*.png`（所有封面图）
- `outputs/sitemap.xml`
- `outputs/404.html`

**绕过**: 手动 `git add outputs/` 或使用 `git subtree push`。

### 8.3 quality_scores 的排序 bug

`CAST(quality_scores AS REAL)` 读取的是 CSV 中**第一个值**（specificity），而非 overall 评分（第五个值）。所有按分排序的结果实际上是按 specificity 排序。

### 8.4 search_prompts 返回 stub

`tool_search_prompts` 会捕获 `ImportError` 并返回"等 Code-4 实现"的占位消息。即使 embedding 模块已就绪，这个 catch 也会触发。

---

## 9. Agent 执行模板

以下是 Coding Agent 在执行"全流程更新"时应遵循的标准操作序列：

```
Task: 全流程更新 Prompt Library

Phase 1 — 数据采集
  1. pool_status              → 记录初始状态
  2. crawl_tweets             → 采集推文 (params: from queries.yaml)
  3. pool_status              → 确认 tweets 数量增长

Phase 2 — 数据处理
  4. extract_prompts          → 提取 prompt (params: batch=100)
  5. pool_status              → 确认 pending 数量
  6. score_prompts            → 评分 (params: batch=50, min_score=0.4)
  7. pool_status              → 确认评分完成

Phase 3 — 图片生成
  8. generate_images          → 生成封面图 (params: batch=8, max_workers=3)
  9. pool_status              → 确认 done 数量增长
  10. retry_failed (可选)     → 重试失败的 (params: batch=8)

Phase 4 — 构建发布
  11. Bash: python scripts/build_html.py
      → 验证: ls outputs/prompts/ | wc -l
      → 验证: grep 'href="/prompts/' outputs/prompts/*.html
  12. Bash: python scripts/generate_sitemap.py
      → 验证: grep '.html' outputs/sitemap.xml | head -3
  13. Bash: git add -A outputs/ && git commit -m "deploy: update prompts" && git subtree push --prefix outputs origin gh-pages

Phase 5 — 验证
  14. 抽查线上详情页 URL
  15. 验证 sitemap.xml 可访问
  16. 验证已知风险 URL
```

**关键规则**:
1. 每个 Phase 完成后**必须**调用 `pool_status` 确认数据变化
2. Step 11-13 必须使用 `Bash` 直接运行脚本，**不要**使用 Agent 的 `tool_build_html` / `tool_publish`（这两个有已知 bug）
3. 如果任何步骤失败，**不要继续下一步**，先排查问题
4. Phase 5 验证必须完成才算发布成功

---

## 10. 快速参考卡片

```bash
# ─── 常用命令 ───────────────────────────────────────
# 查看状态
python -m src.main status
sqlite3 data/veo_prompts.db "SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;"

# 采集
python -m src.agent.chat -m "crawl_tweets"

# 提取
python -m src.agent.chat -m "extract_prompts batch 100"

# 评分
python -m src.agent.chat -m "score_prompts batch 50 min_score 0.4"

# 生成图片
python -m src.agent.chat -m "generate_images batch 8"

# 构建 HTML（直接用脚本）
python scripts/build_html.py
python scripts/build_html.py --category cinematic --limit 20

# Sitemap
python scripts/generate_sitemap.py

# 发布（手动 git）
git add outputs/
git commit -m "deploy: update prompts $(date +%Y-%m-%d)"
git subtree push --prefix outputs origin gh-pages

# ─── 调试命令 ───────────────────────────────────────
# 查看 DB 结构
sqlite3 data/veo_prompts.db ".schema prompts"

# 抽查 prompt 质量
sqlite3 data/veo_prompts.db "SELECT title, quality_scores FROM prompts WHERE quality_scores IS NOT NULL LIMIT 5;"

# 验证生成页面的链接
grep -c '/prompts/' outputs/index.html
grep 'href="/prompts/' outputs/prompts/*.html | wc -l

# 验证 sitemap
grep '.html' outputs/sitemap.xml | wc -l
```
