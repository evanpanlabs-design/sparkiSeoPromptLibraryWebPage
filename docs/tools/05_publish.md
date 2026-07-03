# Publish Tool — V3 Agent Skill

**状态：** ✅ 已验证

**Skill name：** `publish`

**调用位置：** `src/agent/skills/core_tools.py` → `tool_publish(args)`

---

## Agent 对话中调用

```
你: 发布这些提示词
Sparki: 执行 publish → 发布成功！
HTML 文件路径: outputs/veo3-prompt-library.html
推送到: evanpanlabs-design/sparkiSeoPromptLibraryWebPage (gh-pages)
        sparki-ai/veo-prompt-station (main)
```

---

## 直接 Python 调用

```python
import sys
sys.path.insert(0, '.')
from src.agent.skills.core_tools import tool_publish

# 完整发布（同步图片 + 构建 HTML + Git push）
result = tool_publish({})
print(result)

# 带参数
result = tool_publish({
    'category': 'cinematic',       # 可选：只发指定 category
    'min_score': 0.6,             # 可选：最低质量分过滤
    'repo': './veo-prompt-station' # 可选：指定 Git 仓库
})
```

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `category` | string | None | 只发布指定分类的 prompt |
| `min_score` | float | None | 最低 quality score 过滤 |
| `repo` | string | PROJECT_ROOT/.git | Git 仓库路径 |
| `message` | string | "Update prompt library" | Git commit message |

---

## 完整流程（pipeline）

```
DB (image_status='done')
  → build_html.py --sync-images   # 复制图片到 generated_images/ + 生成 HTML
  → build_html.py                 # 用模板 + DB 数据生成 index.html
  → Git add + commit + push       # 推送到目标仓库
```

**涉及脚本：**

| 脚本 | 功能 |
|------|------|
| `scripts/build_html.py` | 从 DB 读取 prompts，生成 `veo3-prompt-library.html` |
| `scripts/build_html.py --sync-images` | 将 `outputs/images/{category}/` 图片复制到扁平目录 `outputs/generated_images/` |
| `scripts/sync_images_from_gcs.py` | 从 GCS 下载图片到 `outputs/images/` |

**生成的目录结构：**

```
outputs/
├── veo3-prompt-library.html   # 构建产物 HTML
└── generated_images/            # 扁平图片目录（by prompt id）
    ├── 3.png
    ├── 99.png
    └── ...
```

**HTML 模板使用 `generated_images/${prompt.id}.png` 作为图片路径。**

---

## Git 仓库配置

| 仓库 | Branch | URL | 用途 |
|------|--------|------|------|
| evanpanlabs-design/sparkiSeoPromptLibraryWebPage | `gh-pages` | https://evanpanlabs-design.github.io/sparkiSeoPromptLibraryWebPage/ | 验证库 |
| sparki-ai/veo-prompt-station | `main` | https://sparki-ai.github.io/veo-prompt-station/ | 正式库 |

---

## V3 Agent 集成

### Skill 注册（已注册）

```python
# src/agent/skills/registry.py 或 core_tools.py
Skill(
    name="publish",
    description="将已完成的 prompts 发布到 GitHub Pages",
    parameters=[
        Parameter("category", str, False, "只发布此分类"),
        Parameter("min_score", float, False, "最低质量分"),
        Parameter("repo", str, False, "Git 仓库路径"),
    ],
    fn=tool_publish,
)
```

### Agent 对话示例

```
用户: "发布到 GitHub Pages"
  → tool_publish({})

用户: "把 cinemtic 分类的发到正式库"
  → tool_publish({'category': 'cinematic', 'repo': './veo-prompt-station'})

用户: "发布之前先看一下状态"
  → tool_pool_status({})  # 先查池子状态
```

---

## 已知问题 & 解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| Chrome 显示空白卡片 | 图片路径 404 | `build_html.py --sync-images` 复制到扁平目录 |
| JS SyntaxError | prompt_text 含特殊字符 | 使用 `json.dumps()` 转义 |
| `Commercial / Product` 目录创建失败 | Windows 路径不支持 `/` | `_safe_category()` sanitize 目录名 |
| 双层数组 `[[{...}]]` | 模板已有 `[`，代码又加 `[` | 去除 `_build_prompts_array` 返回值外层括号 |

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 创建文档 | ✅ 验证通过 |