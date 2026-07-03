# 详情页改版方案

> 需求来源：mt | 评估日期：2026-05-25

---

## 1. 现状 vs 目标

### 现状

用户点击 Prompt 卡片 → 弹出 `.filter-overlay` 悬浮窗（modal）

```
┌─────────────────────────────────────┐
│  [×] 关闭                            │
│                                     │
│  ┌───────────────────────┐           │
│  │    Cover Image        │           │
│  └───────────────────────┘           │
│                                     │
│  Category: Cinematic                │
│  Author: @user                      │
│  Likes: 123  Retweets: 45            │
│                                     │
│  ─────────────────────────────────  │
│                                     │
│  Prompt 正文内容...                  │
│                                     │
└─────────────────────────────────────┘
```

### 目标

点击卡片 → 跳转详情页（替换当前 overlay）

```
┌─────────────────────────────────────────────────────────┐
│  [← 返回]                    [分享] [Try it →]          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Cover Image（大图）                  │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Cinematic                                              │
│  作者: @user  ·  1,234 likes  ·  45 retweets          │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  Prompt                                                │
│  A breathtaking shot of a lone traveler...             │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  推荐类似 Prompt                                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│  │  Cover  │ │  Cover  │ │  Cover  │                   │
│  │  ···    │ │  ···    │ │  ···    │                   │
│  └─────────┘ └─────────┘ └─────────┘                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 技术方案

### 约束：GitHub Pages 静态网站

无后端服务器，所有数据在构建时（`build_html.py`）注入 JS，所有交互在前端完成。

### 方案：Hash 路由（单页应用）

利用 URL hash 实现路由，不依赖服务器：

```
index.html                    → 卡片网格（首页）
index.html#/prompt/99         → Prompt 99 详情页
index.html#/prompt/77         → Prompt 77 详情页
```

```javascript
// 路由解析
function getRoute() {
    const hash = location.hash; // e.g. "#/prompt/99"
    if (hash.startsWith('#/prompt/')) {
        return { page: 'detail', id: parseInt(hash.split('/')[2]) };
    }
    return { page: 'home' };
}
```

### 页面切换逻辑

```javascript
// 初始化
const route = getRoute();
if (route.page === 'detail') {
    renderDetail(route.id);
} else {
    renderGrid();
}

// 监听 hash 变化
window.addEventListener('hashchange', () => {
    const route = getRoute();
    if (route.page === 'detail') {
        showDetailPage(route.id);
    } else {
        showGridPage();
    }
});
```

---

## 3. 数据准备：推荐类似 Prompt

### 问题

详情页的"推荐类似 Prompt"需要相似度搜索，但静态网站没有后端 API。

### 方案：build 时预计算推荐

在 `scripts/build_html.py` 的 `build_html()` 函数中，新增一步：

```python
def _precompute_recommendations(conn, prompt_ids: list[int]) -> dict[int, list[dict]]:
    """对每个 done prompt，搜索 top-K 相似 prompt。"""
    from src.agent.memory.embedding import search_prompts

    recommendations = {}
    for pid in prompt_ids:
        # 读取该 prompt 的文本
        row = conn.execute(
            "SELECT prompt_text, title FROM prompts WHERE id = ?", (pid,)
        ).fetchone()
        if not row:
            continue
        query = f"{row['title']}: {row['prompt_text']}"
        results = search_prompts(conn, query=query, top_k=6)
        # 排除自己，过滤到 top-5
        recs = [r for r in results if r['id'] != pid][:5]
        recommendations[pid] = recs
    return recommendations
```

注入 JS：

```python
def _transform_row(row: dict) -> dict:
    r = dict(row)
    recs = recommendations.get(r['id'], [])
    return {
        # ... 原有字段 ...
        "recommendations": [
            {"id": rec['id'], "title": rec.get('title', ''), "score": rec.get('score', 0)}
            for rec in recs
        ]
    }
```

**注意**：`search_prompts` 依赖 `embedding.py`（目前可能未完整实现，属于 Code-4 任务）。

---

## 4. Try 按钮行为

**待确认**：Try 按钮的具体行为是什么？

可能选项：

| 选项 | 行为 | 实现 |
|---|---|---|
| A | 跳转到 Google Veo / Imagen 生成页面，prompt 预填 | 外链，零成本 |
| B | 触发图片重新生成（调用 Gemini API） | 需要后端或 MCP |
| C | 复制 prompt 到剪贴板 | Web Clipboard API，低成本 |

**推荐**：选项 A + C（copy prompt），copy 是纯前端实现。

---

## 5. 分享按钮实现

```javascript
// 分享按钮
async function sharePrompt(prompt) {
    const url = `${location.origin}${location.pathname}#/prompt/${prompt.id}`;
    const shareData = {
        title: prompt.title,
        text: prompt.prompt_text.slice(0, 100) + '...',
        url: url,
    };

    if (navigator.share && navigator.canShare(shareData)) {
        await navigator.share(shareData);
    } else {
        // Fallback：复制链接
        await navigator.clipboard.writeText(url);
        showToast('链接已复制到剪贴板');
    }
}
```

---

## 6. 实施任务分解

| 步骤 | 任务 | 文件改动 |
|---|---|---|
| 1 | `build_html.py` 增加预计算推荐逻辑 | `scripts/build_html.py` |
| 2 | HTML 模板增加详情 section（骨架 + CSS） | `outputs/templates/index.html` |
| 3 | JS 实现 Hash 路由 + 页面切换 | `outputs/templates/index.html` 底部 JS |
| 4 | JS 实现详情页渲染（含推荐卡片） | 同上 |
| 5 | JS 实现分享按钮 | 同上 |
| 6 | "Try" 按钮行为（待产品确认） | 待定 |
| 7 | 验证：详情页打开、推荐显示、分享功能 | 手动测试 |

**预计工作量**：中（约 150-200 行新增代码 + 1 个文件的模板改造）

---

## 7. 向后兼容

- 不删除现有的 overlay 弹窗逻辑（如果 hash 路由有 bug，用户仍可用原来的方式）
- 现有的 `filter-overlay` 在 JS 层标记为 deprecated，但不删除 DOM

---

## 8. 风险

| 风险 | 缓解 |
|---|---|
| `embedding.py` 未实现，search_prompts 不工作 | 推荐部分加空数组 fallback |
| 推荐计算慢（131 条 × embedding 查询） | 改用 build 时批量计算，存 DB，只计算新增 prompt |
| 详情页刷新后状态丢失（无服务） | hash 本身是 URL 的一部分，刷新后状态恢复 |