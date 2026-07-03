# 06 — build_html.py (Agent Skill)

**状态：** ✅ Verified

**调用方式：** 直接 Python 执行

```bash
python scripts/build_html.py
python scripts/build_html.py --sync-images        # 同步图片 + 生成 HTML
python scripts/build_html.py --limit 50           # 只取前 50 条
python scripts/build_html.py --category cinematic   # 只取某分类
python scripts/build_html.py --min-score 0.6       # 质量分门槛
python scripts/build_html.py --no-image-filter     # 包含无图的 prompts
```

---

## 功能

从 SQLite DB（`data/veo_prompts.db`）读取 `image_status='done'` 的 prompts，生成可浏览的 HTML 页面。

**数据流：**

```
DB 查询 (image_status='done')
  ↓
_build_prompts_array() — 将 DB 行转换为 JS 对象数组
  ↓
模板替换 (outputs/templates/veo3-prompt-library.html 的 sentinel 区间)
  ↓
输出到 outputs/index.html
```

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `outputs/index.html` | 构建产物 HTML（不再用 `veo3-prompt-library.html`） |
| `outputs/generated_images/` | 扁平图片目录，由 `--sync-images` 生成 |

---

## `--sync-images` 详解

此选项将 GCS 已下载到 `outputs/images/{category}/{yyyy-mm}/` 的图片**复制到扁平目录** `outputs/generated_images/{id}.png`。

为什么需要这个中间步骤：

- GCS 图片路径含 category（如 `video-generation/2026-05/99.png`）
- HTML 模板用 `generated_images/{id}.png`（扁平、按 id 命名）
- `--sync-images` 做目录名 sanitize + 复制

**Sanitize 规则：** `<>:"/\|?*` → `_`（避免 Windows 路径问题）

---

## 生成的 HTML 结构

```html
<!-- 模板部分（不变）-->
<script>
  const prompts = [
    // 从 DB 注入的 JSON 数据
    { "id": 99, "tweet_id": "...", "category": "...", ... }
  ] // PROMPTS_ARRAY_SENTINEL;
  // renderPrompts() 渲染卡片网格
</script>
```

**图片路径：** `generated_images/${prompt.id}.png`
**Fallback：** `https://picsum.photos/seed/${tweet_id}/550/307`

---

## 与其他工具的关系

| 上游工具 | 关系 |
|----------|------|
| `tool_generate_images` | 生成封面图并上传 GCS |
| `sync_images_from_gcs.py` | 将 GCS 图片同步到 `outputs/images/` |
| `--sync-images` | 将 `outputs/images/` 复制到 `outputs/generated_images/` |
| `tool_publish` | 调用 `build_html.py` 生成 HTML 后 git push |

---

## 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `--sync-images` | flag | 复制图片到扁平目录后再生成 HTML |
| `--limit N` | int | 限制 prompt 数量 |
| `--category X` | string | 只取指定分类 |
| `--min-score X` | float | 最低 quality score |
| `--no-image-filter` | flag | 不过滤无图 prompts |
| `--repo PATH` | string | git 仓库路径（用于 --repo 模式） |

---

## 使用示例

```python
import sys
sys.path.insert(0, '.')
from scripts.build_html import build_html

# 同步图片 + 构建 HTML
stats = build_html(sync_images=True)  # 注意这个参数在 main() 里用 args.sync_images
print(f"Built: {stats['source_rows']} prompts")
```

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 创建文档 | ✅ |
| 2026-05-21 | 输出文件名改为 index.html | ✅ |