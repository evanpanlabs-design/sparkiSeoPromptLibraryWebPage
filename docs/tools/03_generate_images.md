# 03 — tool_generate_images (Agent Skill)

**状态：** ✅ Verified（之前测试成功）

**Agent skill name：** `generate_images`

**调用位置：** `src/agent/skills/core_tools.py` → `tool_generate_images(args)`

---

## Agent 对话中调用

```
你: 生成10张图
Sparki: 执行 generate_images: 图片生成完成: 10/10 成功, 0/10 失败
模型: gemini-2.5-flash-image
当前状态: 50 pending, 31 done, 0 failed
```

---

## 直接 Python 调用

```python
import sys
sys.path.insert(0, '.')

from src.agent.skills.core_tools import tool_generate_images

result = tool_generate_images({
    "batch": 10,           # 生成数量，默认8
    "sort_by": "score",    # 排序：score / newest / relevance
    "filter": {"min_score": 0.6}  # 可选：最低质量分
})

print(result)
```

输出示例：
```
图片生成完成: 2/2 成功, 0/2 失败
模型: gemini-2.5-flash-image
当前状态: 59 pending, 12 done, 0 failed
```

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `batch` | integer | 8 | 生成图片数量 |
| `sort_by` | string | "score" | 排序方式：score / newest / relevance |
| `filter` | object | None | 过滤条件，如 `{"min_score": 0.6}` |

---

## 返回值

成功：打印 `图片生成完成: X/Y 成功, Z/Y 失败` + 当前池子状态

失败：打印错误信息字符串

---

## 内部逻辑

```python
# 1. 从 prompts 表查询 pending 的记录
sql = """SELECT id, prompt_text, category
         FROM prompts
         WHERE image_gcs_url IS NULL AND image_status = 'pending'
         ORDER BY CAST(quality_scores AS REAL) DESC
         LIMIT {batch}"""

# 2. 逐条调用 RateLimitSafeGenerator.generate()
#    → GeminiImageClient.generate()
#    → 直接上传 bytes 到 GCS: gs://sparki-op-test/prompts/{id}.png

# 3. 更新 DB
UPDATE prompts SET image_gcs_url = ?, image_status = 'done' WHERE id = ?
```

---

## 速率限制

- 串行执行，15s 间隔（`RateLimitSafeGenerator`）
- 避免 Vertex AI 429 RESOURCE_EXHAUSTED

---

## 依赖

- `RateLimitSafeGenerator` (`src/image_gen/generator.py`)
- `GeminiImageClient` (`src/image_gen/client.py`)
- GCS bucket `sparki-op-test` 可写

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 测试 batch=1 | ✅ 成功生成并上传 GCS |