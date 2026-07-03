# Category 框架自动分析方案

> 需求来源：mt | 评估日期：2026-05-25

---

## 1. 现状分析

### 1.1 当前 Category 分类逻辑

```
数据流：
  推文文本
    ↓
  _content_filter (快速过滤：含 "veo" + 15 词以上)
    ↓
  PromptExtractor._call_llm()
    ↓
  LLM system prompt 中给定固定列表：
  ["cinematic", "video-generation", "other", "character-design", "product-photography"]
    ↓
  LLM 返回 {category: "cinematic", ...}
    ↓
  写入 prompts.category
```

**文件位置**：`src/worker/extractor.py` 第 168-170 行

```python
self.categories = categories
cat_names = ", ".join(categories) if categories else "video-generation, cinematic, other"
self._system_prompt = (
    f"... category: \"{cat_names}\" | \"other\" | null, ..."
)
```

**问题**：
- 列表是人工拍脑袋定的（5 个分类）
- 不随数据演变（新产品风格出现时无法感知）
- "other" 过多说明分类不覆盖真实数据

### 1.2 当前 Category 分布（假设）

基于 import_v2_data.py 的初始 categories：

```
cinematic             : ~40%
video-generation       : ~25%
other                 : ~20%
character-design      : ~10%
product-photography   : ~5%
```

### 1.3 问题的本质

LLM 是在给定选项中选，不是真正理解数据后给出标签。数据的多样性被强制压缩到 5 个桶里。

---

## 2. 自动分析方案

### 2.1 目标

入库一批 Prompt 后，自动分析是否需要调整 Category 框架，输出人工可读的诊断报告。

### 2.2 方案：聚类 + 关键词提取

```
入库 Prompt（N 条）
    ↓
获取 N 条 prompt_text 的 embedding
    ↓
K-means 聚类（K = 6~12，可配置）
    ↓
每个簇提取关键词（词频 / LLM 描述）
    ↓
对比现有 5 个 category
    ↓
输出诊断报告
```

### 2.3 诊断报告内容

```markdown
## Category 框架诊断报告
生成时间：2026-05-25
样本数：131 条

### 簇分布

| 簇ID | 数量 | 主要关键词 | 对应现有Category | 建议 |
|------|------|-----------|----------------|------|
| 0    | 42   | cinematic, lighting, shot | cinematic | 无需改动 |
| 1    | 28   | video, animation, motion  | video-generation | 无需改动 |
| 2    | 31   | character, portrait, style | character-design | 范围重叠 |
| 3    | 15   | product, commercial, studio| product-photography | 可考虑合并 |
| 4    | 10   | 3d, render, environment     | other | 建议新增 "3d-render" |
| 5    | 5    | (无明显共性)                 | other | 建议合并到 other |

### 具体建议

1. 【新增】建议新增 category: "3d-render"
   - 理由：簇 4 有 10 条明显是 3D 渲染相关，现有分类无法覆盖
   - 操作：extractor.py 的 categories 列表加入 "3d-render"

2. 【合并】建议合并 "product-photography" → "commercial"
   - 理由：簇 3 只有 15 条，且和 video-generation 有边界模糊

3. 【保留】cinematic 和 video-generation 当前覆盖良好，暂不调整

4. 【监控】"other" 类别若超过 20%，需重新审视分类框架
```

---

## 3. 实现细节

### 3.1 技术栈

- 聚类：`scikit-learn`（`KMeans` 或 `AgglomerativeClustering`）
- Embedding：已有 `embed_text()` 函数（Gemini API）
- 关键词提取：词频统计（简单实现）或 LLM 辅助（更准但更慢）

### 3.2 核心代码（伪代码）

```python
# scripts/analyze_categories.py

def analyze_category_framework():
    """运行聚类分析，返回诊断报告。"""
    from sklearn.cluster import KMeans
    from src.agent.memory.embedding import embed_text
    from src.memory.schema import _conn

    conn = _conn()
    rows = conn.execute(
        "SELECT id, prompt_text, title, category FROM prompts WHERE image_status = 'done'"
    ).fetchall()

    if len(rows) < 10:
        return "样本不足（<10），无法分析"

    # Step 1: 获取 embedding
    texts = [f"{r['title']}: {r['prompt_text']}" for r in rows]
    embeddings = [embed_text(t) for t in texts]  # 可优化为批量

    # Step 2: K-means 聚类
    n_clusters = min(8, len(rows) // 10)  # 每簇至少 10 条
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    labels = kmeans.fit_predict(embeddings)

    # Step 3: 收集每个簇的文本，计算词频
    clusterTexts = {i: [] for i in range(n_clusters)}
    for row, label in zip(rows, labels):
        clusterTexts[label].append(row['prompt_text'])

    clusterReports = []
    for cid, texts in clusterTexts.items():
        keywords = extract_keywords(texts, top_n=5)
        count = len(texts)
        suggestions = generate_suggestion(keywords, count)

        # 对比现有 category
        existing_match = guess_existing_match(keywords)

        clusterReports.append({
            "cluster_id": cid,
            "count": count,
            "keywords": keywords,
            "existing_category": existing_match,
            "suggestion": suggestions,
        })

    return build_report(clusterReports, rows)
```

### 3.3 关键词提取

```python
from collections import Counter
import re

def extract_keywords(texts: list[str], top_n: int = 5) -> list[str]:
    """从文本列表中提取高频词（去除停用词后）。"""
    STOPWORDS = {'the', 'a', 'an', 'of', 'in', 'to', 'and', 'with', 'for', 'of', 'on', 'is', 'are', 'as'}
    words = []
    for text in texts:
        tokens = re.findall(r'\b[a-z]{3,}\b', text.lower())
        words.extend([w for w in tokens if w not in STOPWORDS])
    counter = Counter(words)
    return [w for w, _ in counter.most_common(top_n)]
```

### 3.4 现有 Category 匹配

```python
# 根据关键词猜测现有 category
def guess_existing_match(keywords: list[str]) -> str | None:
    KEYWORD_MAP = {
        "cinematic": ["cinematic", "lighting", "shot", "scene", "film"],
        "video-generation": ["video", "animation", "motion", "clip"],
        "character-design": ["character", "portrait", "person", "face", "design"],
        "product-photography": ["product", "commercial", "studio", "advertising"],
    }
    for cat, kws in KEYWORD_MAP.items():
        if any(kw in keywords for kw in kws):
            return cat
    return "other"
```

---

## 4. 集成到工作流

### 4.1 运行时机

```
import_v2_data.py（批量导入）
    ↓
analyze_categories.py（分析）
    ↓
输出诊断报告（人工确认）
    ↓
如需调整 → 修改 extractor.py 的 categories 列表
    ↓
下次导入时使用新分类框架
```

### 4.2 独立运行

```bash
python scripts/analyze_categories.py
python scripts/analyze_categories.py --min-samples 20  # 至少 20 条才分析
python scripts/analyze_categories.py --output report.md  # 输出到文件
```

---

## 5. 实施任务分解

| 步骤 | 任务 | 改动文件 |
|---|---|---|
| 1 | 写 `extract_keywords()` 函数 | `scripts/analyze_categories.py`（新） |
| 2 | 写 K-means 聚类逻辑 | 同上 |
| 3 | 写诊断报告生成 | 同上 |
| 4 | 写 CLI 入口（argparse） | 同上 |
| 5 | 集成到 `import_v2_data.py` 末尾（可选自动调用） | `scripts/import_v2_data.py` |
| 6 | 验证：跑 `analyze_categories.py`，对比人工判断 | 手动测试 |

**预计工作量**：中（约 100-120 行新代码）

---

## 6. 风险与限制

| 风险 | 缓解 |
|---|---|
| embedding 质量差导致聚类不准 | K-means 对初始质心敏感，用 `kmeans++` init 缓解 |
| 关键词提取只看词频不看语义（"cinematic" 出现多不一定是最重要的） | 可选加 LLM 辅助：用 LLM 描述每个簇的特征 |
| 聚类数量 K 需人工设定 | 用 `len(rows) // 10` 动态估算（每簇至少 10 条） |
| "other" 过多的根因可能是 extractor prompt 不够严格，而非 category 数量 | 报告区分：是 category 覆盖不足，还是 extractor 过滤太松 |
| 当前 embedding 可能未完整实现（Code-4 任务） | 等 embedding.py 实现后再联调 |

---

## 7. 长期：闭环的 Category 迭代

```
定期运行 analyze_categories.py
    ↓
报告生成 + 人工确认
    ↓
更新 extractor categories
    ↓
新数据用新分类
    ↓
再分析 → 迭代
```

这形成一个数据驱动的分类迭代闭环，不需要人工每年重新审视一次。|