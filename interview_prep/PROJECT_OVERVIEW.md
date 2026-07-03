# Sparki 项目介绍 — 通用版

> 本文档是面试准备的参考基准，所有公司/岗位的简历和逐字稿都从本文档出发。

---

## 一、项目基本信息

**项目名称**：Sparki — AI Prompt 库平台（Sparki SEO Prompt Library）

**项目类型**：AI 数据采集 + LLM 应用 + 前端展示的全栈项目

**一句话介绍**：
> 从 X.com（Twitter）爬取高质量 AI 视频生成 Prompt（如 Veo 3、Sora），经过质量筛选、封面图生成、评分排序后，发布到 GitHub Pages 网站，供 AI 创作者检索使用。

**技术栈**：
- Python 3.11（主力语言）
- LangGraph（V3 ReAct Agent 框架）
- SQLite（本地数据库，存储 prompts + 记忆）
- Gemini API（LLM + Embedding）
- Google Cloud Storage（图片存储）
- Apify（X.com 爬虫）
- GitHub Pages（静态网站托管）
- Playwright + Twikit（爬虫框架）

---

## 二、核心功能模块

### 2.1 数据采集（V1 Pipeline）

```
搜索词配置 → Apify 爬虫 → 内容过滤 → LLM Prompt 提取 → 质量评分 → 入库
```

- **搜索词管理**：`configs/queries.yaml` 配置种子搜索词，支持负向关键词过滤
- **爬虫**：Apify Actor（`nfp1fpt5gUlBwPcor`）爬取 X.com 推文，过滤低互动量内容
- **Prompt 提取**：用 LLM 从推文中提取"可生成视频的 Prompt"，要求：
  - 至少 15 词（过滤 Nano Banana 等无意义内容）
  - 包含必须关键词：`ai video`、`generated`、`prompt`、`veo`、`sora` 等
- **质量评分**：4 维评分（Specificity、Visual Detail、Novelty、Generatability），加权求和

### 2.2 封面图生成（V1 + V3 Agent）

- 使用 Gemini 2.5 Flash Image 模型生成封面图
- **串行安全模式**：2 秒间隔（避免 429），RateLimitSafeGenerator 封装
- 图片上传 GCS：`gs://sparki-op-test/prompts/{category}/{yyyy-mm}/{id}.png`

### 2.3 网页发布

- 模板：`outputs/templates/veo3-prompt-library.html`
- 构建：`scripts/build_html.py` 从 SQLite 读取 `image_status='done'` 的 prompts
- 同步图片：`scripts/sync_images_from_gcs.py` GCS → 本地 `outputs/generated_images/`
- 发布：Git push 到 `sparki-ai/veo-prompt-station`（GitHub Pages）

### 2.4 V3 ReAct Agent（当前开发中）

**定位**：用自然语言驱动整个流程（"跑一遍全程"、"发布网站"），替代手动操作各脚本。

**架构**：LangGraph StateGraph + Skill Registry

```
用户输入 → think_node（意图分类）→ plan_node（选工具）→ act_node（执行）→ observe_node（判断是否继续）→ 最终回复
```

**6 个 Node**：start / think / plan / act / observe / final_reply / error

**核心技能（12 个）**：
- Phase Skills：`crawl_tweets`、`extract_prompts`、`score_prompts`、`generate_images`、`sync_images`、`build_html`、`publish`
- Utility Skills：`pool_status`、`search_prompts`、`retry_failed`、`show_history`、`save_preference`、`get_preference`

**两种运行模式**：
- Agent 模式：单步/多步，LLM 自主选工具
- Pipeline 模式：用户说"全程/一键"，自动串完整 phase 链

---

## 三、技术亮点（面试常考）

### 亮点 1：ReAct Agent 架构设计

**问题**：为什么用 ReAct 而不是直接 Function Calling？

**回答**：
> Function Calling 是"用户说做什么，LLM 直接调工具"，适合单步操作。但我们的场景是"发布网站"这种多步任务，Agent 需要自己规划步骤（比如：先爬数据→再生成图→再发布）。ReAct 的显式 Thought 让 LLM 先推理再行动，可以自主规划多步任务链，而且每一步的 Observation 都会写入记忆，供下一步使用。

**追问**：ReAct 和 Toolformer 的区别？
> Toolformer 是离线先生成工具调用数据集再 fine-tune，ReAct 是在推理时在线推理。ReAct 更适合我们的场景因为我们需要一个能自主规划的中枢，而不是单独的工具调用模型。

### 亮点 2：Phase 完全解耦

**问题**：Phase Skills 拆分的好处？

**回答**：
> 拆分后每个 Skill 原子化，V3 Agent 可以单独调用任意 phase，也可以串成 Pipeline。用户说"跑全程"就自动串 7 个 phase，说"只生成图"就只调 generate_images。而且每个 phase 可以独立测试和替换，不影响其他环节。

### 亮点 3：Rate-Limit 安全机制

**问题**：怎么避免 API 429？

**回答**：
> 图片生成用了 `RateLimitSafeGenerator`，串行执行 + 2 秒间隔。如果遇到 429，指数退避重试（最多 3 次）。爬虫用的是 Apify 的 rate limit 控制，不直接碰 X.com API。

### 亮点 4：SQLite WAL 模式的多进程安全

**问题**：多个进程同时读写 SQLite 怎么保证不冲突？

**回答**：
> 开了 WAL 模式（`check_same_thread=False`），读进程可以并发，但写操作有锁。曾经遇到过一个进程持有写锁导致另一个进程卡住的问题，靠 `Stop-Process` 杀掉旧进程解决。

### 亮点 5：Embedding 语义搜索

**问题**：Prompt 搜索怎么做的？

**回答**：
> 每条 Prompt 入库时调用 Gemini Embedding API 生成 768 维向量，存到 SQLite BLOB。用户搜索时，把 query 也 embedding，与库里的向量做余弦相似度排序，返回 top-k。

---

## 四、数据结构

### SQLite 主要表

| 表名 | 用途 |
|---|---|
| `prompts` | 核心数据：tweet_id、prompt_text、quality_scores、image_gcs_url、image_status |
| `scrape_runs` | 爬取批次记录 |
| `authors` | 作者信息（粉丝数、发推数） |
| `conversation_history` | V3 Agent 对话历史 |
| `user_preferences` | 用户偏好 KV |
| `prompt_embeddings` | Prompt embedding 向量 |
| `task_history` | V3 历史任务 |
| `keyword_yields` | 关键词漏斗数据 |
| `approved_keywords` | 已确认的搜索关键词 |

### prompts 表关键字段

```sql
id, tweet_id, category, title, prompt_text,
quality_scores (JSON), image_gcs_url, image_status ('pending'|'generating'|'done'|'failed'),
author_id, likes_count, retweet_count, reply_count
```

---

## 五、项目演化路径

| 版本 | 时间 | 核心变化 |
|---|---|---|
| V1.0 | 早期 | Pipeline MVP：爬→提→评→图→HTML，单脚本串行跑 |
| V2.0 | 中期 | Async Pool：图生成异步化，Worker 模式 |
| V3.0 | 近期 | ReAct Agent：对话式 Agent，LangGraph，Skill Registry |
| V3.2 | 当前 | 两模式架构：Agent 模式 + Pipeline 模式，Phase 解耦 |

---

## 六、个人角色

** Evan Pan**（GitHub: evanpanlabs-design）

- 独立完成整个项目（需求分析→架构设计→编码实现→部署维护）
- 主要工作：V1 爬虫框架搭建、V3 ReAct Agent 架构设计、Skill 系统实现、GitHub Pages 部署

---

## 七、能回答的技术细节

### Q: LangGraph 的 ConditionEdge 怎么实现的？

A: `add_conditional_edges(source, routing_function, mapping)`，routing_function 接收 state 返回字符串（目标节点名）。

### Q: 为什么不用 LangChain 而是自己包装？

A: LangChain 太重，我们只需要 StateGraph + checkpointer，自己封装更轻量。

### Q: Apify 爬虫怎么防封？

A: Apify 有自己的 proxy pool 和 browser fingerprint，我们通过 `configs/crawler.yaml` 配置 `max_scrolls=20` 和 `stale_threshold=3` 控制爬取深度。

### Q: 图片上传 GCS 怎么做的？

A: 用 `google-cloud-storage` 库，`blob.upload_from_file(file_handle)`，路径格式 `gs://sparki-op-test/prompts/{category}/{yyyy-mm}/{id}.png`。

### Q: 质量评分怎么做的？

A: 4 个维度各用 LLM 评分（0-1），加权求和：specificity(0.25) + visual_detail(0.30) + novelty(0.20) + generatability(0.25)。

### Q: 遇到最难的问题是什么？

A: X.com 的 SSL proxy 问题导致 LLM 调用失败。解决：配置 `OPENAI_API_BASE` 环境变量绕过代理直连。或者 Windows 路径问题（`WindowsPath` 不能传给 `blob.download_to_file()`），解决：用 `open(path, 'wb')` 而非直接传 Path 对象。

---

## 八、可以主动展示的工程习惯

- 所有配置进 YAML，不硬编码（`configs/queries.yaml`、`configs/llm.yaml` 等）
- 数据库 schema 带 migration（`ALTER TABLE ADD COLUMN` 兼容旧 DB）
- 错误不抛异常，统一转字符串返回（`tool_result` 格式）
- 脚本支持 `--limit`、`--category`、`--dry-run` 等 CLI 参数
- 代码模块化：`scripts/` 放可执行脚本，`src/` 放核心代码
- Git commit 规范：`@ v1.0 —`、`@ v2.0 —`、`@ v3.0 —` 前缀标记版本节点