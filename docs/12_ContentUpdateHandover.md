# Veo Prompt Library 内容更新交接文档

> **版本**: v1.0 | **日期**: 2026-07-03 | **维护人**: 开发团队
> **受众**: 业务运营团队（非技术人员）

---

## 1. 产品概述

Veo Prompt Library 是 Sparki 的 SEO 落地页，托管在 `https://veo.sparki.io`。

| 组件 | 说明 |
|---|---|
| 首页 | `https://veo.sparki.io/` — 卡片网格展示所有 Prompt |
| 详情页 | `https://veo.sparki.io/prompts/{slug}.html` — 每个 Prompt 的独立页面 |
| 分类筛选 | 首页按 category 过滤（cinematic, commercial, ai-art 等） |
| 搜索 | 首页支持标题/作者/Prompt 文本搜索 |

### 当前数据规模

- **148 条 Prompt**（2026-07-03 统计）
- 覆盖约 20+ 个分类

---

## 2. 内容更新流程（两种方式）

### 方式一：全自动 Pipeline（推荐，用于批量更新）

**适用场景**：有新数据源、需要全量更新

**操作步骤**：

1. 登录开发服务器或有权限的终端
2. 进入项目目录：`cd 16_NewCrawler`
3. 运行 Agent 对话模式：
   ```bash
   python -m src.agent.chat
   ```
4. 输入命令触发全流程 Pipeline：
   ```
   全程 / 完整流程 / 跑一遍
   ```
5. Pipeline 自动执行：
   ```
   crawl_tweets → extract_prompts → score_prompts → generate_images → sync_images → build_html → publish
   ```
6. 等待完成（约 30-60 分钟，取决于数据量）

**注意事项**：
- crawl_tweets 需要有效的 X.com 登录状态
- generate_images 需要 Gemini API 配额
- publish 会将 HTML 推送到 GitHub Pages，线上约 2-3 分钟生效

---

### 方式二：仅重建 HTML（适用于已有数据不变，只要刷新页面）

**适用场景**：数据库已有新 Prompt 且图片已生成，只需重建页面

**操作步骤**：

1. 进入项目目录
2. 运行重建命令：
   ```bash
   python scripts/build_html.py
   ```
3. 验证生成结果：
   - 检查 `outputs/index.html` 是否更新
   - 检查 `outputs/prompts/` 目录下是否有新的 `.html` 文件
4. 发布到线上：
   ```bash
   python scripts/build_site.py --deploy-only
   ```

---

### 方式三：仅生成新图片（适用于已有 Prompt 但图片缺失）

**操作步骤**：

1. 进入项目目录
2. 运行 Agent 对话模式：
   ```bash
   python -m src.agent.chat
   ```
3. 输入：
   ```
   生成图片
   ```
4. 等待图片生成完成
5. 然后运行方式二（重建 HTML + 发布）

---

## 3. 验收标准

每次内容更新后，请按以下 checklist 验证：

### 3.1 首页验证

- [ ] 访问 `https://veo.sparki.io/` 正常加载
- [ ] 首页卡片数量与预期一致
- [ ] 点击卡片能正常跳转到详情页（URL 格式：`/prompts/{slug}.html`）
- [ ] 分类筛选按钮正常工作
- [ ] 搜索框能正常过滤
- [ ] 卡片图片正常显示（无 404 图片）

### 3.2 详情页验证

- [ ] 详情页图片正常显示
- [ ] Prompt 文本完整可读
- [ ] Copy Prompt 按钮能复制文本
- [ ] Share 按钮能正常分享链接
- [ ] 底部 "Same Category" 推荐卡片链接正确
- [ ] 返回首页按钮正常

### 3.3 已知问题 URL 验证

- [ ] `https://veo.sparki.io/prompts/dior-lipstick-forging-cinematic-ad-2040753443040809168.html` → 正常访问
- [ ] `https://veo.sparki.io/prompts/the-mirrors-reflection-2048318771547549709.html` → 正常访问

### 3.4 SEO 验证

- [ ] `https://veo.sparki.io/sitemap.xml` 可访问，包含所有 prompt 页面
- [ ] 每个 URL 格式为 `https://veo.sparki.io/prompts/{slug}.html`（有 `.html` 后缀）

---

## 4. 常见问题排查

### Q1: 页面 404 或跳转异常

**现象**：访问 URL 后反复跳转，或显示 404

**原因**：URL 路径问题（已在 2026-07-03 修复）
- 旧问题：相对路径导致 `/prompts/prompts/prompts/...` 嵌套
- 修复方案：所有链接改为绝对路径 `/prompts/{slug}.html`

**如果再次出现**：
1. 检查 `outputs/templates/index.html` 中链接是否以 `/` 开头
2. 检查 `scripts/build_html.py` 中详情页模板链接是否以 `/` 开头
3. 重新运行 `python scripts/build_html.py` 重建

### Q2: 图片不显示

**现象**：页面加载但图片为空白或显示 fallback 图片

**排查**：
1. 检查 `outputs/generated_images/` 目录下是否有对应 `{db_id}.png` 文件
2. 检查数据库 `prompts` 表中 `image_status` 字段是否为 `done`
3. 如果图片缺失，运行 `python scripts/build_html.py --sync-images` 重试

### Q3: 发布后线上没变化

**现象**：本地构建成功，但线上页面没更新

**排查**：
1. 检查 GitHub Pages 部署状态：`https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage/deployments`
2. 确认 push 到了 `gh-pages` 分支
3. 手动运行：`git push origin gh-pages`
4. GitHub Pages 有 1-3 分钟缓存延迟

### Q4: sitemap.xml 中包含死链接

**现象**：Google Search Console 报告 404 错误

**排查**：
1. 运行 `python scripts/generate_sitemap.py` 重新生成
2. 检查 `outputs/sitemap.xml` 中 URL 格式是否正确（应有 `.html` 后缀）
3. 重新发布

---

## 5. 新增 Prompt 分类（Sub-page）

当需要为特定主题（如"品牌广告"、"教育视频"等）创建独立的子页面时：

### 当前已支持的方式

1. **分类筛选**：首页已内置按 `category` 字段筛选，每个分类自动生成一个筛选视图
2. **URL 格式**：`https://veo.sparki.io/?category=cinematic`（通过 JS 筛选，无需额外页面）

### 如果需要独立的 SEO 落地页

需要开发介入，涉及以下改动：
1. 创建新的 HTML 模板（如 `outputs/templates/cinematic-prompts.html`）
2. 修改 `scripts/build_html.py` 的 `build()` 函数，增加按分类独立构建的逻辑
3. 更新 `scripts/generate_sitemap.py` 增加新页面的 URL
4. 更新导航栏链接

**触发条件**：当业务方需要独立 SEO 页面时，提前 1 周提出需求，开发团队评估工作量。

---

## 6. 关键文件清单

| 文件 | 用途 | 修改频率 |
|---|---|---|
| `outputs/templates/index.html` | 首页模板 | 低（UI 改版时） |
| `scripts/build_html.py` | 构建脚本（含详情页模板） | 低（功能增强时） |
| `scripts/generate_sitemap.py` | Sitemap 生成器 | 低 |
| `scripts/build_site.py` | 统一构建+部署工具 | 低 |
| `outputs/index.html` | **构建产物**—线上首页 | 高（每次更新） |
| `outputs/prompts/*.html` | **构建产物**—详情页 | 高（每次更新） |
| `outputs/sitemap.xml` | **构建产物**—站点地图 | 高（每次更新） |
| `outputs/404.html` | **构建产物**—404 错误页 | 低 |
| `outputs/generated_images/*.png` | **构建产物**—封面图 | 高（每次更新） |

> **注意**：`outputs/` 目录下的文件都是构建产物，不要手动编辑。修改应通过 `scripts/` 下的脚本或模板进行。

---

## 7. 紧急联系

| 问题类型 | 处理方式 |
|---|---|
| 页面无法访问 | 检查 GitHub Pages 状态，确认 `gh-pages` 分支存在 |
| 数据异常 | 检查数据库 `data/veo_prompts.db`，运行 `python -m src.main status` |
| 构建失败 | 查看 `outputs/regen_run.log` 和 `outputs/retry_run.log` |
| SEO 告警 | 检查 GSC 中 404 URL 格式，重新生成 sitemap |

---

## 附录：2026-07-03 Bug 修复记录

**问题**：GSC 提示 `https://veo.sparki.io/prompts/prompts/prompts/prompts/the-mirrors-reflection-2048318771547549709.html` 和 `https://veo.sparki.io/prompts/2040753443040809168.html` 点击后反复跳转首页。

**根因**：
1. 模板中所有链接使用相对路径（`prompts/xxx.html`），导致从 clean URL 访问时路径累积
2. Sitemap 中 URL 缺少 `.html` 后缀
3. 缺少 404 页面处理错误 URL

**修复**：
1. 所有模板和构建脚本中的链接改为绝对路径（`/prompts/xxx.html`）
2. Sitemap 生成器加上 `.html` 后缀，并去重旧 URL
3. 新增 `outputs/404.html` 处理错误 URL
4. 修复 `core_tools.py` 中 `tool_build_html` 和 `tool_publish` 的代码 bug