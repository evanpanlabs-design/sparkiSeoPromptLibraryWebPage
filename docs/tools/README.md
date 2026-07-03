# Tool Documentation Index

每个工具文档记录：
- 调用方法（Python 代码）
- 输入/输出
- 状态（✅已验证 / 🔄进行中 / ⏳待测）
- Agent skill name（如果有）

---

## Pipeline Tools

| # | Tool | Status | Agent Skill | Doc |
|---|------|--------|------------|-----|
| 1 | ApifyCrawler.crawl() | ✅ Verified | - | [01_crawl_apify.md](01_crawl_apify.md) |
| 2 | import_data() | 🔄 Pending | - | [02_import_v2_data.md](02_import_v2_data.md) |
| 3 | tool_generate_images | 🔄 Pending | `generate_images` | [03_generate_images.md](03_generate_images.md) |
| 4 | sync_images_from_gcs.py | 🔄 Pending | - | [04_sync_images.md](04_sync_images.md) |
| 5 | tool_publish | 🔄 Pending | `publish` | [05_publish.md](05_publish.md) |

---

## Agent Skills (V3 SkillRegistry)

Agent 能调用的工具通过 `SkillRegistry` 注册，见 `src/agent/skills/core_tools.py`。

可用 skill：`pool_status`, `search_prompts`, `generate_images`, `retry_failed`, `publish`, `crawl`, `extract`

---

## 调用模式

**直接 Python 调用：**
```python
import sys; sys.path.insert(0, '.')
# 调用
```

**通过 Agent 调用：**
```
你: 生成10张图
Sparki: 执行 generate_images: ...
```