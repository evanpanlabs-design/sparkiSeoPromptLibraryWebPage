# Sparki 并行开发命令手册

> 本文档记录各 Claude Code 实例的完整启动命令。
> 参考：docs/03_InterfaceContract.md（接口契约）、docs/02_DevGuide.md（开发者指南）

---

## 开发任务分配

| 实例 | 模块 | 依赖 | 关键输出 |
|---|---|---|---|
| Code-1 | `src/agent/state.py` + `src/types/` | 无 | 所有共享数据类定义 |
| Code-2 | `src/crawler/` | Code-1 | Playwright 爬虫 |
| Code-3 | `src/worker/` | Code-1 | LLM 提取 + 评分 |
| Code-4 | `src/image_gen/` | Code-1 | Gemini 图像生成 |
| Code-5 | `src/agent/graph.py` + `src/agent/nodes.py` | 全部 | LangGraph 连接 |
| Code-6 | `src/memory/` | 无 | SQLite 持久层 |
| Code-7 | `src/api/` | Code-1 | FastAPI 服务 |

---

## 启动顺序

```
Step 1: Code-1（类型定义）→ 完成后
Step 2: 同时启动 Code-2, 3, 4, 6
Step 3: Step 2 全部完成后 → Code-5（LangGraph）
Step 4: Code-5 完成后 → Code-7（API）
```

---

## Code-1 — 类型定义（最先启动）

```
我将开发 Sparki Agent 的类型定义层，这是所有其他节点开发的前置依赖。

目标文件：src/agent/state.py + src/types/*.py

参考文档：
- docs/03_InterfaceContract.md §2 AgentState 完整定义
- docs/03_InterfaceContract.md §3 枚举类型
- docs/03_InterfaceContract.md §4 数据对象 Schemas（12个类）
- docs/03_InterfaceContract.md §6 异常类定义
- docs/03_InterfaceContract.md §8 类型别名

实现要求：
1. 实现 src/agent/state.py 中的 AgentState dataclass，完全对应 §2 的每一个字段
2. 在 src/types/ 目录下创建：
   - src/types/__init__.py
   - src/types/tweet.py (Tweet, AuthorRef)
   - src/types/prompt.py (ExtractedPrompt, ScoredPrompt, QualityScores)
   - src/types/image.py (ImageResult, ImageGenStatus)
   - src/types/query.py (QueryCandidate, QueryMetrics)
   - src/types/author.py (AuthorMetrics)
   - src/types/category.py (CategorySuggestion)
   - src/types/pipeline.py (PipelineStats, PipelineError, PipelinePhase, RouterDecision)
   - src/types/config.py (PipelineConfig 及所有子配置类)
3. src/exceptions.py 实现 §6 所有异常类
4. 使用 from src.agent.state import * 统一导出所有类型
5. 所有 dataclass 必须有 field(default_factory=...) 或默认值，不能有无默认值的必填字段
6. 严格按文档中的类型编写，不自行添加字段

完成后运行：pytest tests/unit/node_contract/test_initialize_contract.py -v 验证基本结构

确认完成后再告知我。
```

---

## Code-2 — 爬虫模块

```
我将开发 Sparki 的爬虫模块（src/crawler/），负责从 X.com 抓取推文数据。

参考文档：
- docs/03_InterfaceContract.md §4.2 Tweet 数据结构
- docs/03_InterfaceContract.md §5.4 crawler_node 契约（输入输出）
- docs/02_DevGuide.md §3.2 Crawler 模块设计
- 参考代码：E:\2027_GET_A_JOB\Get_An_AI_Job\视界Sparki\11_X_Scrape\scripts\x_scraper_pw.py（关键模式复用）

目标文件：
- src/crawler/__init__.py
- src/crawler/browser.py（BrowserManager 类，cookie 加载、session 验证、context 管理）
- src/crawler/extraction.py（TweetExtractor，从 DOM 提取 tweet 数据）
- src/crawler/scroll.py（async scroll_and_extract 函数）
- src/crawler/enrichment.py（访问作者主页获取 followers_count，访问推文详情获取 views）
- src/agent/nodes.py 中的 crawler_node 函数

实现要求：
1. 必须使用 async/await（asyncio + playwright.async_api），不是同步版本
2. BrowserManager.load_cookies 从 cookies.json 加载，verify_session 检查登录状态
3. extraction.py 的 extract_search_tweets 必须解析 [data-testid='tweet'] 元素，字段对应 Tweet dataclass
4. scroll_and_extract 支持 max_scrolls 和 stale_threshold 参数
5. enrichment 为每个 tweet 访问作者主页和推文详情
6. crawler_node 函数签名：def crawler_node(state: AgentState) -> AgentState
   输入：state.query_candidates, state.config.crawler, state.config.engagement
   输出：state.tweets_by_query（dict[str, list[Tweet]]），state.all_tweet_ids（set），state.phase = EXTRACTING
   所有推文必须经过 engagement 过滤（min_likes, min_followers, min_views）
7. 写入 src/agent/nodes.py，不要创建新文件

运行 pytest tests/unit/node_contract/test_crawler_contract.py -v 验证契约

确认完成后再告知我。
```

---

## Code-3 — Worker 模块

```
我将开发 Sparki 的 Worker 模块（src/worker/），负责从推文提取 Prompt 并进行质量评分。

参考文档：
- docs/03_InterfaceContract.md §4.3 ExtractedPrompt、§4.4 QualityScores、§4.5 ScoredPrompt
- docs/03_InterfaceContract.md §5.5 worker_node、§5.7 quality_scorer_node 契约
- docs/02_DevGuide.md §3.3 Worker 模块设计
- 参考代码：E:\2027_GET_A_JOB\Get_An_AI_Job\视界Sparki\11_X_Scrape\scripts\extract_prompts.py（LLM 调用模式）

目标文件：
- src/worker/__init__.py
- src/worker/extractor.py（PromptExtractor 类，LLM 调用 + 验证/修复逻辑）
- src/worker/dedup.py（PromptDeduplicator，基于文本相似度）
- src/worker/scorer.py（QualityScorer，质量评分）
- src/agent/nodes.py 中的 worker_node 和 quality_scorer_node 函数

实现要求：
1. LLM 调用使用 src/llm/client.py 的 LLMClient（先假设该 client 存在，参考 extract_prompts.py 的调用模式）
2. extractor.py 必须处理：
   - 首次 LLM 分类（is_prompt? category?）
   - recheck：对于含 "prompt:"、"见评论" 等指示符的推文做二次审查
   - 验证与修复：检测 JSON key name 提取错误、placeholder 文本，执行 reextract_structured_prompt
3. extractor.py 的 extract_batch 使用 ThreadPoolExecutor + as_completed，并发数从 config.llm.extraction_concurrency 读取
4. scorer.py 的 QualityScorer.score 对每个 prompt 评分 4 个维度（specificity, visual_detail, novelty, generatable），计算 overall = 加权平均
5. needs_image 由 quality.thresholds.min_overall 决定（< 0.40 → False）
6. worker_node：def worker_node(state) → state.extracted_prompts, pending_category_suggestions, phase=SCORING
   如果 pending_category_suggestions 非空：waiting_for_human=True, router_decision=WAIT_HUMAN
7. quality_scorer_node：输入 extracted_prompts，输出 scored_prompts（同对象引用，quality_scores in-place）
8. 写入 src/agent/nodes.py

运行 pytest tests/unit/node_contract/test_worker_contract.py -v
运行 pytest tests/unit/node_contract/test_quality_scorer_contract.py -v
确认契约

确认完成后再告知我。
```

---

## Code-4 — 图像生成模块

```
我将开发 Sparki 的图像生成模块（src/image_gen/），负责为 Prompt 生成封面图。

参考文档：
- docs/03_InterfaceContract.md §4.6 ImageResult、§4.12 PipelineConfig(GeminiConfig)
- docs/03_InterfaceContract.md §5.8 image_gen_node 契约
- docs/02_DevGuide.md §3.6 Image Gen 模块设计
- 参考代码：E:\2027_GET_A_JOB\Get_An_AI_Job\视界Sparki\11_X_Scrape\scripts\generate_images.py（多模型 fallback 模式）

目标文件：
- src/image_gen/__init__.py
- src/image_gen/client.py（GeminiImageClient，多模型 fallback，generate + generate_batch）
- src/image_gen/style.py（Category 风格关键词系统 build_image_prompt）
- src/image_gen/gcs.py（GCS 上传工具 upload_to_gcs）
- src/agent/nodes.py 中的 image_gen_node 函数

实现要求：
1. GeminiImageClient 使用 google.genai，VERTEX AI 模式
2. MODELS = ["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image"]
3. generate() 实现多模型 fallback：每模型最多 3 次重试，429/RESOURCE_EXHAUSTED 时等待 (attempt+1)*retry_delay_base 秒
4. generate_batch() 使用 ThreadPoolExecutor，max_workers = config.gemini.generation_concurrency
5. build_image_prompt(style.py) 从 configs/gemini.yaml 的 style_keywords 读取，随机选 3 个关键词拼接
6. upload_to_gcs 使用 google.cloud.storage.client，bucket = config.gemini.gcs_bucket
7. image_gen_node：def image_gen_node(state) → state.image_results, stats.images_generated/failed, phase=COMPOSING
8. needs_image=False 的 prompt 不产生 ImageResult（跳过）
9. 写入 src/agent/nodes.py

运行 pytest tests/unit/node_contract/test_image_gen_contract.py -v 确认契约

确认完成后再告知我。
```

---

## Code-5 — LangGraph 连接

```
我将开发 Sparki 的 LangGraph 连接层，把所有节点串联成完整 pipeline。

参考文档：
- docs/03_InterfaceContract.md §7 节点依赖与并行图
- docs/03_InterfaceContract.md §5 所有节点的输入输出契约
- docs/02_DevGuide.md §2.1 系统架构图
- LangGraph 官方文档（StateGraph, add_node, add_edge, ConditionalEdge）

目标文件：
- src/agent/graph.py（build_graph 函数，返回编译后的 StateGraph）
- src/agent/config.py（NodeConfig，节点级别配置：max_retries, retry_delay）
- src/agent/nodes.py（确保所有节点函数签名统一：def node_name(state: AgentState) -> AgentState）

实现要求：
1. build_graph() 必须包含全部 9 个节点：
   initialize_node, query_planner_node, crawler_node, worker_node,
   router_node, quality_scorer_node, image_gen_node,
   output_composer_node, feedback_node
2. 节点顺序边（按 §7 依赖图）：
   INITIALIZING → QUERY_PLANNING → CRAWLING → EXTRACTING → SCORING → IMAGING → COMPOSING → DONE
3. router_node 是唯一写 state.phase 的节点（使用 ConditionalEdge）
4. WAITING_HUMAN decision → 挂起 graph，等待外部重新调用
5. ERROR decision → FAILED phase
6. 每个节点配置 NodeConfig(max_retries=3, retry_delay=5)
7. 使用 @retry 装饰器（tenacity 或自定义）处理可重试异常
8. graph.py 的 compile() 返回编译后的 graph，main.py 调用 graph.compile().invoke(initial_state)

同时检查并补全 src/agent/nodes.py 中所有节点函数：
- initialize_node：插入 scrape_runs 行，加载历史 metrics，phase → QUERY_PLANNING
- query_planner_node：从 configs/queries.yaml 读 seed queries，从 query_metrics 选 top-N 做 LLM expansion，phase → CRAWLING
- router_node：消费 router_decision，写入下一 phase
- output_composer_node：生成 HTML gallery + JSON export，phase 不变（COMPOSING）
- feedback_node：写 metrics 到 DB，phase → DONE

确认完成后再告知我。
```

---

## Code-6 — Memory 持久层

```
我将开发 Sparki 的 Memory 持久层（src/memory/），负责所有 SQLite 数据操作。

参考文档：
- docs/03_InterfaceContract.md §4.7 QueryMetrics、§4.8 AuthorMetrics
- docs/02_DevGuide.md §3.4 Memory 模块（schema.py + repositories）
- 参考代码：E:\2027_GET_A_JOB\Get_An_AI_Job\视界Sparki\11_X_Scrape\scripts\db.py（现有完整 schema 和 CRUD）

目标文件：
- src/memory/__init__.py
- src/memory/schema.py（init_db()，DDL，migration 函数）
- src/memory/queries.py（QueryRepository.create/update/get_top_performing）
- src/memory/authors.py（AuthorRepository.upsert/get_high_value）
- src/memory/prompts.py（PromptRepository.insert/update_quality/update_image_url/get_without_images）
- src/memory/scrape_runs.py（ScrapeRunRepository）

实现要求：
1. schema.py 的 SCHEMA 完全对应 docs/03_InterfaceContract.md §3.4 的 DDL
2. 每次 init_db() 时调用所有 _migrate_* 函数（向后兼容已有 DB）
3. QueryRepository.update_yield 更新 tweets_raw, tweets_filtered, prompts_extracted, qualified，计算 qualified_rate 和 prompt_yield_rate
4. AuthorRepository.upsert 使用 INSERT OR REPLACE，record_prompt 更新 total_prompts 和 qualified_prompts
5. PromptRepository.get_without_images(scrape_run_id, limit) 支持增量处理
6. 使用全局 _connection 单例，check_same_thread=False
7. 所有 Repository 方法返回 Pydantic/dataclass 对象，不直接返回 dict

确认完成后再告知我。
```

---

## Code-7 — API 服务

```
我将开发 Sparki 的 FastAPI REST 服务（src/api/）。

参考文档：
- docs/02_DevGuide.md §5 API Reference（所有端点定义）
- docs/03_InterfaceContract.md §4.10 PipelineStats 作为 /agent/status 响应

目标文件：
- src/api/__init__.py
- src/api/main.py（FastAPI app，生命周期管理）
- src/api/agent_routes.py（/agent/run, /agent/status, /agent/stop）
- src/api/prompt_routes.py（/prompts, /prompts/{id}, /images/regenerate/{id}）
- src/api/category_routes.py（/categories, /categories/{id}）
- src/api/queries_routes.py（/queries, /authors）

实现要求：
1. 使用 BackgroundTasks 实现 /agent/run 的异步执行（不阻塞 HTTP 请求）
2. /agent/status 返回 PipelineStats 结构（phase, progress, errors, estimated_completion_minutes）
3. /prompts 支持 query 参数：category, min_score, since, limit, offset
4. /categories/{id} PATCH 支持 action=approve/reject/rename
5. 所有端点验证输入，返回标准错误结构 {detail: string}
6. 使用 src.memory 的 Repository 读取数据，不直接操作 DB
7. 运行时端口 8000，文档在 /docs

确认完成后再告知我。
```

---

## 验证命令

全部完成后，在项目目录运行：

```bash
# 验证类型契约
pytest tests/unit/node_contract/ -v

# 验证完整 pipeline（需要 API keys）
python -m src.main run --all --dry-run

# 启动 API
python -m src.api.main
```