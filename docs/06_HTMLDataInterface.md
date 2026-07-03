# HTML Prompt Library — 数据接口文档

> **版本**: 1.0 | **适用**: `outputs/templates/veo3-prompt-library.html` | **用途**: 新数据接入参考

---

## 1. 数据文件位置

| 文件 | 说明 |
|---|---|
| `outputs/templates/veo3-prompt-library.html` | 源模板（含 sentinel 标记，构建时替换） |
| `outputs/veo3-prompt-library.html` | 构建产物（实际在浏览器中运行） |
| `outputs/generated_images/{id}.png` | 封面图本地缓存 |

---

## 2. JavaScript 数据源

模板中通过 sentinel 标记注入数据：

```javascript
// 模板中的占位符（build_html.py 替换此区域）
const prompts = [
    { ... },
    { ... }
] // PROMPTS_ARRAY_SENTINEL;
```

数据是一个完整的 JavaScript 数组，嵌入 HTML 中无需任何网络请求。

---

## 3. Prompt 对象完整 Schema

```typescript
interface Prompt {
  // 标识
  id: number;                        // 主键，卡片图片文件名: generated_images/{id}.png
  tweet_id: string;                   // X 推文 ID，Modal 查找依据，图片容错 fallback seed

  // 基础内容
  url: string;                        // X 推文 URL，Modal "View on X" 链接
  category: string;                   // 分类 slug，决定 tag 颜色和侧边栏筛选
  title: string;                      // 卡片标题 + Modal 标题
  prompt_text: string;                // 卡片正文预览 + Modal 全文 + Try 按钮复制内容
  notes: string | null;                // Modal Notes 区，无时显示 "No additional notes."

  // 作者信息
  author: {
    name: string;                     // 显示名，Modal 作者名 + 头像首字母
    screen_name: string;              // X handle，Modal 显示 @xxx
    followers: number;               // 粉丝数，Modal 显示
  };

  // 互动数据
  engagement: {
    likes: number;                    // 点赞数，Modal 显示
    retweets: number;                  // 转发数，Modal 显示
    replies: number;                  // 回复数，Modal 显示
  };
}
```

---

## 4. 字段使用情况

### 4.1 首页卡片（`createPromptCard`）

| 展示位置 | 字段 | 说明 |
|---|---|---|
| 封面图 | `id` → `generated_images/{id}.png` | 不存在时走 onerror fallback |
| Category Tag | `category` | 决定 tag 背景色（见下表） |
| 标题 | `title` | **可点击**打开 Modal |
| 正文预览 | `prompt_text`（截断 4 行） | **可点击**打开 Modal |
| 分享按钮 | `id` | 生成 `sparki.io/prompt/{id}` 分享链接 |
| Try 按钮 | `prompt_text` | 单击复制全文，跳转 sparki.io/create |

**Category → Tag 颜色映射：**

| category 值 | Tag 背景色 |
|---|---|
| `video-generation` | `#3B82F6`（蓝色） |
| `product-photography` | `#f472b6`（粉色） |
| `cinematic` | `#fbbf24`（黄色） |
| `image-generation` | `#a855f7`（紫色） |
| `character-design` | `#22c55e`（绿色） |
| 其他 | `#3B82F6`（默认蓝色） |

### 4.2 悬浮卡片 Modal（`openModal`）

| 展示位置 | 字段 | 说明 |
|---|---|---|
| 头像 | `author.name[0]` | 首字母 |
| 作者名 | `author.name` | |
| @handle | `author.screen_name` | 带 @ 前缀 |
| Category | `category` | 原始值转空格显示 |
| 标题 | `title` | |
| 完整 Prompt | `prompt_text` | 等宽字体（JetBrains Mono） |
| Notes | `notes` | 无时显示 "No additional notes." |
| 点赞/转发/回复 | `engagement.*` | 带格式化（1.2k 形式） |
| 粉丝数 | `author.followers` | 带格式化 |
| View on X | `url` | 跳转原推文 |

---

## 5. 图片口径

### 5.1 本地路径

```
generated_images/{id}.png
```

文件不存在时触发 `onerror`：
```javascript
<img src="generated_images/${id}.png"
     onerror="this.src='https://picsum.photos/seed/${tweet_id}/550/307'">
```

### 5.2 GCS 路径（生成时）

```
gs://sparki-op-test/prompts/{category}/{YYYY-MM}/{tweet_id}.png
```

> **注意**：本地文件名用 `id`，GCS 路径用 `tweet_id`，这是历史设计差异，接入新数据时需确保两处 ID 一致或单独处理。

---

## 6. 最小可用数据集

只需以下字段即可在首页正常展示卡片（无 Modal、无 Try 功能）：

```javascript
{
  id: 1,
  tweet_id: "xxx",
  category: "video-generation",
  title: "标题",
  prompt_text: "正文内容"
}
```

**缺失数据降级处理：**

| 缺失字段 | 降级表现 |
|---|---|
| 无 `author` | 卡片正文点击正常，Modal 作者区为空 |
| 无 `engagement` | 卡片正文点击正常，Modal 互动区显示 0 |
| 无 `notes` | Modal Notes 显示 "No additional notes." |
| 无 `url` | Modal "View on X" 按钮失效（# 锚点） |
| 无图片 | 显示 Lorem Picsum fallback |
| 无 `id` | 图片 404，Modal 无法打开 |

---

## 7. 数据接入示例

### 7.1 直接替换模板（适用于一次性构建）

1. 修改 `build_html.py` 中的 SQL 查询以适配新的数据源
2. 按 Schema 转换字段名（见下表）
3. 运行 `python scripts/build_html.py` 生成 `outputs/veo3-prompt-library.html`

### 7.2 字段名映射参考

如果新数据源的字段名不同，build 脚本需要做如下映射：

```python
# 新数据源 → Prompt Schema
{
    "prompt_id": "id",
    "twitter_id": "tweet_id",
    "post_url": "url",
    "genre": "category",
    "headline": "title",
    "content": "prompt_text",
    "comment": "notes",
    "user": {
        "display_name": "author.name",
        "handle": "author.screen_name",
        "follower_count": "author.followers"
    },
    "stats": {
        "like_count": "engagement.likes",
        "rt_count": "engagement.retweets",
        "reply_count": "engagement.replies"
    }
}
```

---

## 8. 构建机制

`build_html.py` 替换流程：

```
1. 从 DB 读取 prompts（全部或按 scrape_id）
2. 扁平 DB 行 → 嵌套 JS 结构转换
3. 过滤占位符 prompt_text（"..." / "[the full prompt text]" / ""）
4. 找到模板中的 "const prompts = [" 到 "// PROMPTS_ARRAY_SENTINEL" 区间
5. 整段替换为新数组
6. 输出到 outputs/veo3-prompt-library.html
```

sentinel 标记（不可删）：
```javascript
const prompts = [
    // ... 数据 ...
] // PROMPTS_ARRAY_SENTINEL;
```