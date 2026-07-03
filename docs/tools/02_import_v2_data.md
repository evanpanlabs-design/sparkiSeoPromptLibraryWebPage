# 02 — import_v2_data.py

**状态：** 🔄 进行中（数据采集未完成）

**调用方式：** 直接 Python 执行

```bash
python scripts/import_v2_data.py
python scripts/import_v2_data.py --dry-run   # 预览不过写入
```

---

## 调用方法

```python
import sys
sys.path.insert(0, '.')

from scripts.import_v2_data import import_data

stats = import_data(dry_run=False)
print(stats)
```

输出：
```
=== Import Statistics ===
  Total tweets in file:     2850
  Passed engagement gate:   340
  Qualified (LLM filter):   85
  Written to DB:            85
  Embedding succeeded:      85
  Embedding failed:         0
=============================
```

---

## Pipeline 流程

```
last_crawl.json (1422条)
    ↓
Engagement gate: favorite>=50, views>=1000, followers>=1000
    ↓
PromptExtractor (并行 10线程) → LLM判断是否是prompt
    ↓
QualityScorer (并行 10线程) → LLM打4维度质量分
    ↓
quality.overall >= 0.40 → prompts表 + gemini-embedding-2向量
```

---

## 输出统计

| 字段 | 说明 |
|------|------|
| `total` | last_crawl.json 中原始推文数 |
| `gate_passed` | 通过 engagement gate 的数量 |
| `qualified` | LLM 判断为有效 prompt 且质量>=0.40 的数量 |
| `inserted` | 写入 prompts 表的数量 |
| `embedded_ok` | 成功生成嵌入向量的数量 |
| `embedded_fail` | 嵌入生成失败的数量 |

---

## 当前状态

- 等待 Apify 爬虫完成 → `last_crawl.json` 有数据后才能运行
- 当前 `last_crawl.json` 不存在或为空

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 创建文档 | 🔄 待验证 |