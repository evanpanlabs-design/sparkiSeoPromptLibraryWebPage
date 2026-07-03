# Sparki V2 并行开发命令手册

> **Version**: 2.0 | **Predecessor**: [04_ParallelDevCommands.md](04_ParallelDevCommands.md) v1.0

---

## 开发任务分配

| 实例 | 模块 | 依赖 | 关键输出 |
|---|---|---|---|
| Code-1 | DB Migration + Pool Queries | 无 | `image_status` 列, pool CRUD |
| Code-2 | `src/agent/tools.py` (7 个工具) | Code-1 | 所有工具函数实现 |
| Code-3 | `src/agent/chat_agent.py` + `chat.py` | Code-1, Code-2 | Agent 核心循环 + CLI |
| Code-4 | `src/agent/memory.py` + `src/types/chat.py` | 无 | 对话记忆 + 新类型定义 |
| Code-5 | `src/image_gen/client.py` (RateLimitSafe mode) | 无 | 串行安全生图 |
| Code-6 | V1 Pipeline 瘦身 (移除 IMAGING) | Code-1 | graph.py, nodes.py 修改 |
| Code-7 | 导入脚本 + 集成测试 | Code-1~6 | 端到端验证 |

---

## 启动顺序

```
Step 1: Code-1 (DB) + Code-4 (types) → 并行启动，互不依赖
Step 2: Code-5 (image worker) → 独立模块，无依赖
Step 3: Code-2 (tools) → 依赖 Code-1 的 pool queries
Step 4: Code-3 (agent) → 依赖 Code-2 的工具注册表
Step 5: Code-6 (pipeline trim) → 依赖 Code-1 的 migration
Step 6: Code-7 (integration) → 全部完成后
```

---

## Code-1 — Database Migration + Pool Queries

```
在现有 src/memory/schema.py 中添加 V2 迁移和 Pool 查询函数。

参考文档：
- docs/03_InterfaceContract_V2.md §3.1 prompts.image_status 状态机
- docs/03_InterfaceContract_V2.md §3.2 conversation_history 表
- docs/03_InterfaceContract_V2.md §3.3 user_preferences 表
- docs/02_DevGuide_V2.md §4 Database Changes

目标文件：src/memory/schema.py (在现有基础上修改)

实现要求：
1. 添加 _migrate_prompts_image_status() 函数
2. 添加 init_conversation_tables() 函数
3. 在 init_db() 中调用这两个新迁移
4. 添加 pool query 函数到 src/memory/prompts.py:
   - get_pool_summary() → dict[str, int]  返回各状态计数
   - pop_pending_for_generation(limit, sort_by) → list[dict]
   - mark_done_as_published() → int  返回更新行数
   - reset_failed_to_pending() → int
5. 添加导入脚本 src/memory/import_v1_data.py:
   - 读取 outputs/last_crawl.json 中缓存的 tweet 数据
   - 将已有 39 张成功图对应的 prompt 标记为 done（通过 GCS 中 tweet_id 匹配）
   - 其余 scored_prompts 标记为 pending
6. image_status 的 CHECK 约束：CHECK (image_status IN ('pending','generating','done','failed','published'))

完成后运行：
python -c "from src.memory.schema import init_db; init_db(); print('Migration OK')"
sqlite3 data/veo_prompts.db "SELECT image_status, COUNT(*) FROM prompts GROUP BY image_status;"
确认完成后再告知我。
```

---

## Code-2 — Tool Functions

```
实现 7 个工具函数，每个函数签名严格按 InterfaceContract_V2 §2。

参考文档：
- docs/03_InterfaceContract_V2.md §2.2-§2.7 每个工具的精确合约
- docs/02_DevGuide_V2.md §3.2 Tools 模块设计

目标文件：src/agent/tools.py (新建)

实现要求：
1. 每个工具函数签名：def tool_<name>(args: dict) -> str
2. 所有工具返回中文结果字符串
3. 工具内部 try/except 所有异常，返回 "错误: {exception}" 字符串
4. tool_pool_status: 调用 Code-1 的 get_pool_summary()
5. tool_crawl: 复用 V1 的 crawler_node + worker_node + quality_scorer_node
   - 结果写入 prompts 表时 image_status='pending'
6. tool_generate_images: 调用 Code-5 的 RateLimitSafeGenerator
   - 先从池中 pop N 条 pending
   - 逐个生成（串行）
   - 成功→done, 失败→failed
7. tool_publish: 复用 V1 的 output_composer_node + build_html.py
   - 然后 git clone/push GitHub Pages
8. 每个工具函数独立可测（不需要 Agent 运行）

工具注册表（供 Code-3 使用）：
TOOL_REGISTRY = {
    "pool_status": tool_pool_status,
    "crawl": tool_crawl,
    "generate_images": tool_generate_images,
    "retry_failed": tool_retry_failed,
    "publish": tool_publish,
    "show_history": tool_show_history,
}

完成后单独测试每个工具：
python -c "from src.agent.tools import tool_pool_status; print(tool_pool_status({}))"
确认完成后再告知我。
```

---

## Code-3 — Agent Core + CLI

```
实现 SparkiAgent 类和 CLI 聊天入口。

参考文档：
- docs/02_DevGuide_V2.md §3.1 Chat Agent 设计
- docs/02_DevGuide_V2.md §5 Agent System Prompt
- docs/02_DevGuide_V2.md §6 Agent Loop 伪代码
- docs/02_DevGuide_V2.md §7 Chat CLI Entry Point

目标文件：
- src/agent/chat_agent.py (新建) — SparkiAgent 类
- src/agent/chat.py (新建) — CLI 入口

实现要求：
1. SparkiAgent.__init__ 接收：llm_client, db_conn, tools dict, system_prompt
2. SparkiAgent.chat(message) 实现完整的 Agent Loop（最多 5 轮迭代）
3. _build_context() 注入：当前时间 + pool_summary + 最近 10 条对话历史
4. _parse_response() 解析 LLM 输出中的 {"tool": "..."} JSON
5. SYSTEM_PROMPT 从 chat_agent.py 顶部常量加载
6. CLI 支持两种模式：
   - python -m src.agent.chat → 交互式 REPL
   - python -m src.agent.chat --msg "池子状态" → 单次命令
7. CLI 启动时打印欢迎信息和可用工具列表

LLM 调用使用现有的 GeminiClient (src/llm/gemini_client.py)

完成后运行：
python -m src.agent.chat --msg "池子状态"
确认完成后再告知我。
```

---

## Code-4 — Conversation Memory + Chat Types

```
实现对话记忆层和新类型定义。

参考文档：
- docs/03_InterfaceContract_V2.md §3.2 conversation_history 表
- docs/03_InterfaceContract_V2.md §3.3 user_preferences 表
- docs/03_InterfaceContract_V2.md §5.3 新类型定义

目标文件：
- src/agent/memory.py (新建) — 对话记忆 CRUD
- src/types/chat.py (新建) — ToolName, ToolCall, ConversationTurn, PoolSummary

实现要求：
1. src/types/chat.py:
   - ToolName enum (6 个值)
   - ToolCall dataclass (tool: str, args: dict)
   - ConversationTurn dataclass (role, content, tool_name, tool_args, created_at)
   - PoolSummary dataclass (pending, generating, done, failed, published, total())

2. src/agent/memory.py:
   - save_turn(conn, role, content, tool_name, tool_args) → None
   - load_recent_history(conn, limit=20) → list[ConversationTurn]
   - load_pool_summary(conn) → PoolSummary
   - get_preference(conn, key) → str | None
   - set_preference(conn, key, value) → None

3. 所有函数使用 sqlite3.Row 或 dataclass 返回类型
4. load_recent_history 按 created_at DESC 排序

完成后运行：
python -c "
from src.memory.schema import init_db, _conn
from src.agent.memory import load_pool_summary
init_db()
s = load_pool_summary(_conn())
print(f'Pool: {s.pending} pending, {s.done} done, {s.failed} failed')
"
确认完成后再告知我。
```

---

## Code-5 — Rate-Limit-Safe Image Generator

```
在现有 GeminiImageClient 基础上，添加串行安全生成模式。

参考文档：
- docs/02_DevGuide_V2.md §8 Image Worker — Rate-Limit-Safe Mode

目标文件：src/image_gen/client.py (在现有基础上修改)

实现要求：
1. 添加 RateLimitSafeGenerator 类：
   - __init__(model, min_interval_s=15.0)
   - generate_batch(items) → list[dict]  串行，每条间隔 ≥ min_interval_s
   - _generate_one(item) → dict  单条生成
2. 保持现有的 GeminiImageClient 不变（向后兼容）
3. 如果 429 仍然发生，sleep 60s 然后重试同一张（不跳到下一张）
4. 进度打印: "[N/total] OK/FAIL tweet_id (Xs)"

完成后测试：
python -c "
from src.image_gen.client import RateLimitSafeGenerator
gen = RateLimitSafeGenerator(model='gemini-2.5-flash-image', min_interval_s=15)
# Test with 2 items
items = [{'tweet_id': 'test_1', 'prompt_text': 'A sunset over mountains', 'category': 'cinematic', 'title': 'Test 1'}]
results = gen.generate_batch(items)
print(results)
"
确认完成后再告知我。
```

---

## Code-6 — V1 Pipeline 瘦身

```
从 V1 LangGraph pipeline 中移除 IMAGING 阶段，让 pipeline 在 SCORING 后直接入库。

参考文档：
- docs/02_DevGuide_V2.md §1.2 Two-Loop Architecture

目标文件：
- src/agent/graph.py — 移除 IMAGING 边
- src/agent/nodes.py — 修改 scorer_node 输出

实现要求：
1. graph.py: SCORING → COMPOSING（跳过 IMAGING）
2. nodes.py 的 quality_scorer_node:
   - 每个 ScoredPrompt 写入 DB 时设置 image_status='pending'
   - 不再设置 needs_image 控制位
3. nodes.py 的 output_composer_node:
   - 改为只输出 JSON（HTML 由 tool_publish 负责）
4. src/main.py 保持不变（--from-cache 仍然可用）
5. 所有现有 V1 测试必须通过

完成后运行：
python -m src.main run --from-cache --dry-run  # 验证 pipeline 能跑通
确认完成后再告知我。
```

---

## Code-7 — 集成测试 & 导入脚本

```
端到端验证：从 V1 缓存数据导入池子 → Agent 工具链 → 图片生成 → 发布。

目标文件：
- tests/integration/test_v2_agent.py (新建)
- src/memory/import_v1_data.py (新建，配合 Code-1)

实现要求：
1. import_v1_data.py:
   - 从 outputs/last_crawl.json 读取所有 tweet 数据
   - 查 prompts 表，匹配 tweet_id
   - 匹配 GCS 中已有的图片（通过 tweet_id 查 png 文件名）
   - 有图→done, 无图→pending
   - 打印导入统计

2. test_v2_agent.py:
   - test_pool_summary(): 验证 PoolSummary 计数正确
   - test_tool_pool_status(): 验证工具返回字符串包含所有状态
   - test_tool_generate_images_minimal(): 用 1 条 prompt 测试生成流程
   - test_agent_chat_simple(): 发送"池子状态"→验证回复包含数字
   - test_v1_pipeline_still_works(): 验证瘦身后的 pipeline 能跑

3. Manual integration test checklist（提供给人工验证）:
   [ ] python -m src.memory.import_v1_data → 导入成功
   [ ] python -m src.agent.chat --msg "池子状态" → 显示正确计数
   [ ] python -m src.agent.chat --msg "生成2张" → 生成成功
   [ ] python -m src.agent.chat --msg "发布" → HTML 正确
   [ ] python -m src.main run --from-cache → V1 pipeline 正常

完成后报告集成测试结果。
```
