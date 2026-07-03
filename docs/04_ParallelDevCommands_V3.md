# Sparki V3.2 并行开发命令手册 — 两模式架构 + Phase 拆分

> **Version**: 3.2 | **Parent**: [02_DevGuide_V3.md](02_DevGuide_V3.md) §13
> **架构**: ReAct Agent + 两模式（Agent 模式 / Pipeline 模式）
> **方案**: 废弃 V1 main.py phase 调用，每个 phase 拆分为独立 Skill

---

## 架构变更摘要

**V3.1（旧）**：
- `tool_crawl` 内部调用 `python -m src.main run`（V1 graph）
- 9 个 core skills（其中 `crawl` 是黑盒封装）

**V3.2（新）**：
- `tool_crawl` 废弃，拆分为 `crawl_tweets`, `extract_prompts`, `score_prompts`
- 新增 `sync_images`, `build_html` 独立为 Skill
- 12 个 core skills（不含 keyword strategy）
- V1 `main.py` 仅保留 `init-db` 和 `status` 命令

**两种运行模式**：
- **Agent 模式**：`think_node` 识别 `STATUS_QUERY / TASK_EXECUTION / SEARCH`，LLM 自主选单步工具
- **Pipeline 模式**：`think_node` 识别 `MULTI_STEP + "全程/一键/跑一遍"`，ReAct 循环自动串 `crawl_tweets → extract_prompts → score_prompts → generate_images → sync_images → build_html → publish`

---

## 开发任务分配

| 实例 | 任务 | 依赖 | 关键输出 |
|---|---|---|---|
| **Code-1** | Phase Skills 拆分（crawl_tweets, extract_prompts, score_prompts, sync_images, build_html） | 无 | `core_tools.py`（新 12 skills） |
| **Code-2** | Pipeline 模式识别 + observe_node 增强 | Code-1 | `think_node.py`, `observe_node.py` |
| **Code-3** | V1 main.py 废弃 + 兼容层清理 | Code-1 完成后 | `main.py`, `graph.py` |
| **Code-4** | Embedding search 实现 | 无 | `embedding.py`, `tool_search_prompts` |
| **Code-5** | Keyword strategy tools | Code-1（SkillRegistry） | `keyword_tools.py` |
| **Code-6** | 测试 + 集成验证 | Code-1,2,3,4,5 | `tests/` |

---

## 启动顺序

```
Step 1: Code-1, Code-4, Code-5 → 全部并行启动（互不依赖）
Step 2: Code-1 完成后 → Code-2（Pipeline 模式依赖新 Skills）
Step 3: Code-1 完成后 → Code-3（V1 废弃依赖新 Skills）
Step 4: Code-1,2,3,4,5 全部完成 → Code-6（集成测试）
```

**重要：Code-1 是所有其他任务的前置条件，必须优先完成。** Code-4 和 Code-5 可与 Code-1 完全并行（不依赖 phase skills 的具体实现，只依赖 SkillRegistry 接口）。

---

## Code-1 — Phase Skills 拆分

```
我将开发 Sparki V3.2 的 Phase Skills 拆分：废弃 tool_crawl（V1 main.py 调用），
拆分为独立的原子 phase skills，并新增独立的 sync_images 和 build_html。

参考文档：
- docs/02_DevGuide_V3.md §13.4 Phase Skills（方案 B）
- docs/02_DevGuide_V3.md §13.5 Phase 依赖关系
- docs/02_DevGuide_V3.md §13.6 V1 main.py 废弃说明
- docs/tools/06_build_html.md（build_html.py 用法）
- src/agent/skills/core_tools.py（当前 tool_crawl 实现）

目标文件：
- src/agent/skills/core_tools.py（重写，新增 5 个 skills，废弃 1 个）

需要实现的 12 个 core skills：

1. crawl_tweets (NEW, 替代 tool_crawl)
   - 直接调 Apify API，不通过 src.main run
   - 输入：queries (list), from_cache (bool), max_cost (float)
   - 输出：爬取统计字符串，如 "爬取完成: 47 tweets, 12 prompts extracted"
   - 参考 src.crawler/ 中的 ApifyClient 调用方式

2. extract_prompts (NEW)
   - 从 DB 中 image_status='pending' 且无 prompt_text 的 tweets 提取 prompt
   - 输入：batch (int, 默认 50)
   - 输出：提取统计，如 "提取完成: 31/47 prompts extracted"
   - 使用 LLM extraction（参考 src/worker/extractor.py 的 _extract_single）

3. score_prompts (NEW)
   - 对 extract_prompts 后的 prompts 做质量评分
   - 输入：batch (int, 默认 50), min_score (float, 默认 0.4)
   - 输出：评分统计，如 "评分完成: 28/31 qualified (min=0.4)"
   - 使用 src/worker/scorer.py 的评分逻辑

4. sync_images (NEW)
   - GCS → 本地 generated_images/
   - 输入：无参数（从 DB 读取 done prompts 的 GCS URL）
   - 输出：同步统计，如 "Images: 15 copied, 2 skipped, 0 errors"
   - 逻辑同 scripts/sync_images_from_gcs.py，但包装为 Skill

5. build_html (NEW, 对应 scripts/build_html.py)
   - DB → HTML
   - 输入：category (str, optional), min_score (float, optional), sync_images (bool)
   - 输出：构建统计，如 "Built HTML: 42 prompts"
   - 调用 scripts/build_html.py 或直接调用其 build_html() 函数

6. generate_images (EXISTING, 保持不变)
   - 已有实现，检查是否需要调整参数签名

7. pool_status (EXISTING, 保持不变)
   - 已有实现

8. search_prompts (EXISTING, 签名不变，实现等 Code-4)
   - 目前是空壳，Code-4 实现后自动生效

9. retry_failed (EXISTING, 保持不变)
   - 已有实现

10. publish (EXISTING, 检查是否需要调整)
    - 已有实现，检查与 build_html 的关系

11. show_history (EXISTING, 保持不变)
    - 已有实现

12. save_preference (EXISTING, 保持不变)
    - 已有实现

13. get_preference (EXISTING, 保持不变)
    - 已有实现

注册函数：
register_core_tools(registry: SkillRegistry)
  → 注册上述 12 个 skills（不含 search_prompts 的完整实现）

关键要求：
- crawl_tweets 必须直接调 Apify，不能调用 src.main run
- extract_prompts 和 score_prompts 需要能独立运行，不依赖完整的 V1 pipeline
- 每个 skill 的 examples 字段要有 2 个中文用例
- 所有错误捕获返回中文错误字符串，不抛异常

完成后运行：
python -c "
from src.agent.skills.registry import SkillRegistry
from src.agent.skills.core_tools import register_core_tools
reg = SkillRegistry()
register_core_tools(reg)
tools = reg.list_all()
print(f'Total: {len(tools)} tools')
print('New phase skills:', [t for t in tools if t in ['crawl_tweets','extract_prompts','score_prompts','sync_images','build_html']])
"
验证输出应为：Total: 12 tools，包含所有 5 个新 phase skills。
确认完成后再告知我。
```

---

## Code-2 — Pipeline 模式识别 + observe_node 增强

```
我将开发 Sparki V3.2 的 Pipeline 模式识别：让 think_node 能识别 Pipeline 触发词，
observe_node 能根据 phase 结果决定下一步。

参考文档：
- docs/02_DevGuide_V3.md §13.1 模式决策
- docs/02_DevGuide_V3.md §13.3 Pipeline 模式示例
- docs/02_DevGuide_V3.md §13.7 Pipeline 自主决策逻辑
- src/agent/nodes/think_node.py（现有 _keyword_intent 函数）
- src/agent/nodes/observe_node.py

目标文件：
- src/agent/nodes/think_node.py（修改 _keyword_intent，新增 Pipeline 触发检测）
- src/agent/nodes/observe_node.py（修改 observe 决策逻辑）

实现要求：

1. think_node.py：扩展 _keyword_intent()，新增 Pipeline 模式识别

   添加 Pipeline 触发关键词检测：
   pipeline_keywords = ["全程", "完整流程", "一键", "跑一遍", "更新全部", "全流程"]

   当检测到这些关键词时：
   - 设置 intent_type = "MULTI_STEP"
   - （保持 thought 描述为 "用户想要执行完整流程..."）

2. observe_node.py：增强 Pipeline 模式下的 continue 决策

   在 LLM 调用之外，增加规则-based 的快速路径：
   - 当 tool_result 包含 phase 完成标记时，直接判断下一步
   - phase 完成标记与下一步映射：
     "crawl_tweets 完成" → "extract_prompts"
     "extract_prompts 完成" → "score_prompts"
     "score_prompts 完成" → "generate_images"
     "generate_images 完成" → "sync_images"
     "sync_images 完成" → "build_html"
     "build_html 完成" → "publish"
     "publish 完成" → None (Pipeline 结束)

   实现方式：
   - 如果 LLM 返回的 continue 不确定（"maybe"），用规则辅助判断
   - 保持 LLM 判断为主，规则为辅（避免硬编码）

3. plan_node.py 可能需要的小调整：
   - 当 intent_type == "MULTI_STEP" 时，第一步强制从 crawl_tweets 开始
   - 在 plan_prompt 中注入 "当前是 Pipeline 模式，第一步是 crawl_tweets"

完成后运行：
python -c "
from src.agent.nodes.think_node import _keyword_intent
test_phrases = ['跑一遍全程', '一键更新', '看看池子', '搜索 cinematic']
for p in test_phrases:
    result = _keyword_intent(p)
    print(f'{p!r} -> {result}')
"
预期：
'跑一遍全程' -> 'MULTI_STEP'
'一键更新' -> 'MULTI_STEP'
'看看池子' -> 'STATUS_QUERY'
'搜索 cinematic' -> 'SEARCH'
确认完成后再告知我。
```

---

## Code-3 — V1 main.py 废弃 + 兼容层清理

```
我将开发 Sparki V3.2 的 V1 main.py 废弃工作：删除 V1 phase 调用，
仅保留 init-db 和 status 命令，清理 graph.py 中的兼容层。

参考文档：
- docs/02_DevGuide_V3.md §13.6 V1 main.py 废弃
- src/main.py（当前完整实现）
- src/agent/graph.py（compile_graph 兼容层）

目标文件：
- src/main.py（修改）
- src/agent/graph.py（修改 compile_graph，标记 deprecated）

实现要求：

1. main.py 修改：
   - 删除 run_pipeline() 函数（或保留但标记为 DEPRECATED）
   - 删除 run_parser 的 --phase, --scrape-id, --dry-run, --interactive, --headed, --from-cache 参数
   - 保留 `main init-db` 和 `main status` 命令
   - 在文件顶部加警告注释：
     # DEPRECATED: phase-based pipeline removed in V3.2
     # Use V3 Agent for data collection: python -m src.agent.chat

2. graph.py 修改：
   - compile_graph() 函数顶部加 @deprecated 装饰器或注释
   - 说明："Use build_react_graph(registry) directly for V3"
   - 保留 compile_graph() 以避免 src.main 导入报错

3. 确保以下命令仍可用：
   python -m src.main init-db
   python -m src.main status
   python -m src.main status --scrape-id 1

4. 确认以下命令报错（预期）：
   python -m src.main run  # 应提示 deprecated
   python -m src.main run --all  # 应提示 deprecated

完成后运行：
python -m src.main status
# 应显示最近的 scrape runs

python -m src.main run --all 2>&1 | head -5
# 应输出 deprecation warning
确认完成后再告知我。
```

---

## Code-4 — Embedding Search 实现

```
我将开发 Sparki V3.2 的 Embedding Search：实现 tool_search_prompts 的完整逻辑。

参考文档：
- docs/02_DevGuide_V3.md §7.3 Embedding Search
- src/agent/memory/embedding.py（当前空壳或占位实现）
- src/agent/skills/core_tools.py 中的 tool_search_prompts

目标文件：
- src/agent/memory/embedding.py（实现完整逻辑）
- src/agent/skills/core_tools.py（tool_search_prompts 实现体，依赖 embedding.py）

实现要求：

1. embedding.py 实现：

   def embed_text(text: str) -> list[float]:
     """调用 Gemini embeddings API 返回向量。"""
     - 使用 configs/llm.yaml 中的 gemini 项目配置
     - 模型：gemini-embedding-exp-03-07
     - 返回 list[float]

   def cosine_similarity(a: list[float], b: list[float]) -> float:
     """计算余弦相似度。"""

   def search_prompts(conn, query: str, top_k: int = 5) -> list[dict]:
     """语义搜索 prompts。
     1. embed_text(query) 得到查询向量
     2. 从 prompt_embeddings 表读取所有 embedding
     3. 计算 cosine_similarity，排序
     4. 返回 top_k 条结果，包含 score 字段
     """
     - 返回格式：[{"id": 1, "prompt_text": "...", "score": 0.89}, ...]

   def embed_pending_prompts(conn) -> dict:
     """为所有 embedding_status='pending' 的 prompt 生成 embedding。"""

2. tool_search_prompts 实现：
   - 调用 embedding.search_prompts(conn, query, top_k)
   - 格式化输出为可读字符串

3. 循环依赖避免：
   - embedding.py 不导入 src.agent.skills.core_tools
   - core_tools.py 的 tool_search_prompts 导入 embedding.py

完成后运行：
python -c "
from src.agent.memory.embedding import search_prompts
from src.memory.schema import _conn
conn = _conn()
results = search_prompts(conn, 'cinematic animation', top_k=3)
print(f'Found {len(results)} results')
for r in results:
    print(f'  [{r.get(\"score\", 0):.2f}] {r.get(\"prompt_text\", \"\")[:50]}...')
"
如果有 embedding 数据应返回结果；如果为空应提示 "Embedding 搜索暂不可用（等待 Code-4 实现）"。
确认完成后再告知我。
```

---

## Code-5 — Keyword Strategy Tools

```
我将开发 Sparki V3.2 的 Keyword Strategy Tools：5 个关键词策略相关工具。

参考文档：
- docs/02_DevGuide_V3.md §8B Keyword Strategy System
- docs/03_InterfaceContract_V3.md §7 Tool Contracts 7.10-7.14
- src/agent/skills/keyword_tools.py（如已存在则扩充）

目标文件：
- src/agent/skills/keyword_tools.py（新建或修改）

实现要求：

1. 实现 5 个 Skill（严格按 DevGuide §8B 的函数签名）：

   analyze_keyword_yield(top_n=10, scrape_run_id=None)
     → 返回漏斗分析：各关键词的 raw/filtered/extracted/qualified 数量和比率

   generate_keyword_suggestions(top_n=5, based_on_high_yield=True)
     → 基于历史 yield 数据生成关键词建议

   confirm_keywords(keywords: list[str], action: str, note: str = None)
     → action='confirm' 写入 approved_keywords；action='reject' 标记为 rejected

   show_approved_keywords()
     → 查看当前已确认的关键词列表

   crawl_with_keywords(keywords: list[str] | None, from_cache: bool = True, record_yield: bool = True)
     → 使用指定关键词执行爬虫（调用 crawl_tweets）

2. register_keyword_tools(registry: SkillRegistry) 函数：
   - 实例化 5 个 Skill 并注册
   - 每个 Skill 的 examples 字段要有 2 个中文用例

3. DevGuide §8B 的 get_active_keywords, record_keyword_yield, confirm_keywords
   逻辑直接在 keyword_tools.py 中实现

完成后运行：
python -c "
from src.agent.skills.registry import SkillRegistry
from src.agent.skills.keyword_tools import register_keyword_tools
reg = SkillRegistry()
register_keyword_tools(reg)
tools = [t for t in reg.list_all() if 'keyword' in t or 'crawl_with' in t]
print(f'Keyword tools: {len(tools)}')
print(tools)
"
预期输出：5 个 keyword 相关 tools。
确认完成后再告知我。
```

---

## Code-6 — 测试 + 集成验证

```
我将开发 Sparki V3.2 的测试 + 集成验证：验证两模式架构和 Pipeline 串链。

参考文档：
- docs/02_DevGuide_V3.md §13.1-§13.3（两模式架构）
- docs/02_DevGuide_V3.md §13.7（Pipeline 决策逻辑）
- src/agent/nodes/think_node.py
- src/agent/nodes/observe_node.py

目标文件：
- tests/agent/test_think_node.py（修改，增设 Pipeline 模式测试）
- tests/agent/test_observe_node.py（新建，observe 决策测试）
- tests/integration/test_v3_agent.py（修改，增设 Pipeline 模式测试）

实现要求：

1. test_think_node.py 新增：
   - test_pipeline_trigger_keywords(): 验证 "跑一遍全程" 等触发 MULTI_STEP
   - test_non_pipeline_keywords(): 验证 "池子状态" 等不触发 MULTI_STEP

2. test_observe_node.py（新建）：
   - test_phase_complete_continue(): 验证 "crawl 完成" 后 observe 决定继续 extract
   - test_all_phases_done_stop(): 验证 "publish 完成" 后 observe 决定停止
   - test_pending_triggers_generate(): 验证 "pending: 47" 后 observe 决定继续

3. test_v3_agent.py 新增：
   - test_pipeline_mode_full_flow(): 发送 "跑一遍全程" → 验证多步 ReAct
   - test_agent_mode_single_tool(): 发送 "池子状态" → 验证单步
   - test_agent_mode_multi_tool(): 发送 "生成 3 张图然后发布" → 验证多步但非 Pipeline

4. 手动集成验证清单：
   [ ] python -m src.agent.chat --msg "池子状态怎么样？" → 返回 pending/done 数字
   [ ] python -m src.agent.chat --msg "跑一遍全程" → 自动串 crawl→extract→score→generate→sync→build→publish
   [ ] python -m src.agent.chat --msg "搜索 cinematic" → 返回 embedding 结果
   [ ] python -m src.main init-db → 正常
   [ ] python -m src.main status → 正常
   [ ] python -m src.main run --all → 应提示 deprecated

完成后报告集成测试结果。
```

---

## 验证命令汇总

每个 Code 实例完成后运行对应的验证命令。

| 实例 | 验证命令 | 预期结果 |
|---|---|---|
| Code-1 | `python -c "from src.agent.skills.core_tools import register_core_tools; from src.agent.skills.registry import SkillRegistry; r=SkillRegistry(); register_core_tools(r); print(f'{len(r.list_all())} tools'); print([t for t in r.list_all() if t in ['crawl_tweets','extract_prompts','score_prompts','sync_images','build_html']])"` | 12 tools，包含 5 个新 phase skills |
| Code-2 | `python -c "from src.agent.nodes.think_node import _keyword_intent; print(_keyword_intent('跑一遍全程')); print(_keyword_intent('看看池子'))"` | MULTI_STEP, STATUS_QUERY |
| Code-3 | `python -m src.main status` | 显示 scrape runs |
| Code-3 | `python -m src.main run --all 2>&1 | head -3` | 含 deprecation 提示 |
| Code-4 | `python -c "from src.agent.memory.embedding import search_prompts; from src.memory.schema import _conn; print(search_prompts(_conn(), 'cinematic', top_k=3))"` | 结果列表或空列表（无数据时） |
| Code-5 | `python -c "from src.agent.skills.keyword_tools import register_keyword_tools; from src.agent.skills.registry import SkillRegistry; r=SkillRegistry(); register_keyword_tools(r); print(len([t for t in r.list_all() if 'keyword' in t or 'crawl_with' in t]))"` | 5 |
| Code-6 | `python -m pytest tests/agent/test_think_node.py -v` | ALL PASSED |
| Code-6 | `python -m src.agent.chat --msg "池子状态怎么样？"` | 包含 pending/done 回复 |

---

## 分支策略

每个 Code 实例应在独立分支开发：

```bash
git checkout -b code-1-phase-skills        # Phase skills 拆分
git checkout -b code-2-pipeline-mode       # Pipeline 模式识别
git checkout -b code-3-v1-deprecation      # V1 废弃
git checkout -b code-4-embedding           # Embedding 实现
git checkout -b code-5-keyword-tools       # Keyword tools
git checkout -b code-6-integration          # 测试 + 集成
```

合并顺序：Code-1 → Code-2 + Code-3（可并行）→ Code-4 + Code-5（可并行）→ Code-6

---

## 文件冲突协调

| 文件 | 可能的冲突方 | 协调规则 |
|---|---|---|
| `src/agent/skills/core_tools.py` | Code-1, Code-5 | Code-1 先完成，Code-5 在其基础上 add |
| `src/agent/nodes/think_node.py` | Code-2 | 仅 Code-2 改 |
| `src/agent/nodes/observe_node.py` | Code-2 | 仅 Code-2 改 |
| `src/main.py` | Code-3 | 仅 Code-3 改 |
| `src/agent/graph.py` | Code-3 | 仅 Code-3 改 |
| `src/agent/memory/embedding.py` | Code-4 | 仅 Code-4 改 |
| `tests/` | Code-6 | 仅 Code-6 改 |
| `src/memory/schema.py` | Code-1, Code-4 | 仅添加新列/新表，不删除现有列 |