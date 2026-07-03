# Sparki 项目进展报告

> 整理时间：2026-05-25 | 版本：V3.2

---

## 一、项目现状总览

### 1.1 核心功能

Sparki 是一个 AI Prompt 库平台，从 X.com 爬取高质量 AI 视频生成 Prompt（Veo、Sora 等），经过质量筛选、封面图生成后发布到 GitHub Pages，供 AI 创作者检索使用。

**数据规模**：
- 已入库 Prompts：131 条
- 已生成封面图：~83 条（published 到 GitHub Pages）
- Pending 图片：~47 条
- Failed 图片重试：可用 `tool_retry_failed`

### 1.2 技术栈

| 层级 | 技术 |
|---|---|
| Agent 框架 | LangGraph + ReAct（V3.2 开发中） |
| LLM | Gemini API（MiniMax API token 需更新） |
| 爬虫 | Apify Actor |
| 数据库 | SQLite（WAL 模式） |
| 图片存储 | Google Cloud Storage |
| 前端 | 静态 HTML + Vanilla JS（GitHub Pages） |
| 部署 | GitHub Pages（`sparki-ai/veo-prompt-station`） |

---

## 二、V3.2 架构：两模式 Agent

### 2.1 架构图

```
用户输入 → think_node（意图分类）
              │
              ├─ Agent 模式：STATUS_QUERY / SEARCH / TASK_EXECUTION
              │      LLM 自主选工具，单步或多步
              │
              └─ Pipeline 模式：MULTI_STEP + 触发词
                     ("全程" / "一键" / "跑一遍")
                     自动串：crawl_tweets → extract_prompts → score_prompts
                           → generate_images → sync_images → build_html → publish
```

### 2.2 Phase Skills（12 个核心工具）

| Skill | 功能 | 状态 |
|---|---|---|
| `crawl_tweets` | 直接调 Apify API | 待实现 |
| `extract_prompts` | LLM 提取 prompt | 待实现 |
| `score_prompts` | LLM 质量评分 | 待实现 |
| `generate_images` | GCS 封面图生成 | ✅ 已有（2s 间隔） |
| `sync_images` | GCS → 本地 | ✅ 已有 |
| `build_html` | DB → HTML | ✅ 已有 |
| `publish` | Git push | ✅ 已有 |
| `pool_status` | 查询池子状态 | ✅ 已有 |
| `search_prompts` | Embedding 搜索 | 待实现（Code-4） |
| `retry_failed` | 重试失败图片 | ✅ 已有 |
| `show_history` | 历史记录 | ✅ 已有 |
| `save_preference` / `get_preference` | 偏好设置 | ✅ 已有 |

### 2.3 两种运行模式

**Agent 模式**：用户说"池子状态怎么样" → think → plan: pool_status → act → 回复

**Pipeline 模式**：用户说"跑一遍全程" → think（MULTI_STEP）→ ReAct 循环自动串 7 个 phase

---

## 三、已验证可用的工具

| 工具 | 路径 | 验证状态 |
|---|---|---|
| 导入 Prompts | `python scripts/import_v2_data.py` | ✅ 131 条已入库 |
| 生成图片 | `tool_generate_images` via Agent | ✅ 已有，2s 间隔 |
| 同步图片 | `python scripts/sync_images_from_gcs.py` | ✅ 已修复 WindowsPath bug |
| 构建 HTML | `python scripts/build_html.py --sync-images` | ✅ 输出 `index.html` |
| 发布网站 | `tool_publish` via Agent | ✅ 已推送两个仓库 |
| 查看状态 | `pool_status` | ✅ via Agent |
| 重试失败 | `retry_failed` | ✅ 可用 |

---

## 四、待修复 / 待完善的问题

### 4.1 高优先级

| 问题 | 原因 | 状态 |
|---|---|---|
| **Author 信息全为 Unknown** | `import_v2_data.py` INSERT 语句缺少 `author_name`/`author_screen` 字段写入 | 排查中 |
| **Category 分布不清晰** | LLM 的 category 列表固定 5 个，大量 "other"，且 HTML filter 按钮硬编码 | 待修复 |
| **embedding.py 未实现** | Code-4 任务，阻塞 `search_prompts` 和详情页推荐 | 待 Code-4 |
| **MiniMax API token 过期** | `sk-cp-nXlSnCp2lWGwnofqslvn7uh__...` | 需更新 |

### 4.2 中优先级

| 问题 | 状态 |
|---|---|
| 详情页 Demo 已完成（`detail_page_demo.html`），待集成到 `index.html` | 待 V3.2 开发完成后集成 |
| Category 自动分析（聚类诊断）| 方案已写（docs/08_CategoryAnalysis_Proposal.md），待 Code-4 完成后实现 |
| V1 main.py 废弃（Phase 调用部分）| 待 Code-3 |

---

## 五、文档现状

| 文档 | 内容 | 状态 |
|---|---|---|
| `docs/01_PRD_V3.md` | V3 产品需求文档 | ✅ 完整 |
| `docs/02_DevGuide_V3.md` | V3 开发指南（含 Section 13 两模式架构） | ✅ 完整 |
| `docs/03_InterfaceContract_V3.md` | 接口契约 | ✅ 完整 |
| `docs/04_ParallelDevCommands_V3.md` | 并行开发命令手册（Code-1~6） | ✅ 完整（已重写） |
| `docs/06_build_html.md` | build_html.py 工具文档 | ✅ 完整 |
| `docs/05_publish.md` | publish 工具文档 | ✅ 完整（已更新） |
| `docs/07_DetailPage_Proposal.md` | 详情页改版方案 | ✅ 新建 |
| `docs/08_CategoryAnalysis_Proposal.md` | Category 自动分析方案 | ✅ 新建 |
| `interview_prep/README.md` | 面试准备文件夹说明 | ✅ 新建 |
| `interview_prep/PROJECT_OVERVIEW.md` | 项目通用介绍（面试用） | ✅ 新建 |
| `interview_prep/companies/TEMPLATE_company_role/` | 面试逐字稿模板 | ✅ 新建 |

---

## 六、GitHub Pages 部署现状

| 仓库 | URL | 状态 |
|---|---|---|
| `evanpanlabs-design/sparkiSeoPromptLibraryWebPage` | https://evanpanlabs-design.github.io/sparkiSeoPromptLibraryWebPage/ | ✅ 已发布 |
| `sparki-ai/veo-prompt-station` | https://sparki-ai.github.io/veo-prompt-station/ | ✅ 已发布 |

**最近发布内容**：83 条 Prompts，HTML 文件 `index.html`，图片 `generated_images/`

---

## 七、V3.2 并行开发任务（Code-1~6）

| Code | 任务 | 前置 | 状态 |
|---|---|---|---|
| Code-1 | Phase Skills 拆分（crawl_tweets, extract, score, sync_images, build_html） | 无 | 待启动 |
| Code-2 | Pipeline 模式识别（think_node MULTI_STEP）+ observe_node 增强 | Code-1 | 待启动 |
| Code-3 | V1 main.py 废弃（仅保留 init-db / status） | Code-1 | 待启动 |
| Code-4 | Embedding search 实现（`embedding.py`） | 无 | 待启动 |
| Code-5 | Keyword strategy tools | Code-1（SkillRegistry） | 待启动 |
| Code-6 | 测试 + 集成验证 | 全部 | 待启动 |

**启动命令参考**：`docs/04_ParallelDevCommands_V3.md`

---

## 八、重要文件路径

```
关键脚本：
  scripts/build_html.py              — HTML 构建
  scripts/sync_images_from_gcs.py    — GCS 图片同步
  scripts/import_v2_data.py         — V2 数据导入
  src/agent/skills/core_tools.py    — 12 个核心工具实现
  src/worker/extractor.py            — LLM Prompt 提取
  src/image_gen/generator.py        — 图片生成（含 2s 间隔保护）

模板：
  outputs/templates/index.html      — 首页模板（含 JS 路由）
  outputs/templates/detail_page_demo.html — 详情页 Demo（待集成）

数据库：
  data/veo_prompts.db               — SQLite（131 条 prompts）

配置：
  configs/queries.yaml              — 搜索关键词
  configs/llm.yaml                  — LLM 配置
  configs/gemini.yaml              — GCS + 图片模型配置
  configs/quality.yaml              — 评分权重

HTML 构建产物：
  outputs/index.html               — 推送到 GitHub Pages
  outputs/generated_images/         — 扁平图片目录
```

---

## 九、下一步行动

1. **立即可做**：等 `import_v2_data.py` 的 author 信息修复（问题 4.1），重新跑导入
2. **等 Code-4**：Embedding 实现后，详情页推荐 + `search_prompts` 可用
3. **详情页集成**：V3.2 开发完成后，将 `detail_page_demo.html` 逻辑集成到 `index.html`
4. **多 Claude Code 并行**：启动 Code-1/4/5 并行开发（见 `docs/04_ParallelDevCommands_V3.md`）

---

*本文档在 context compaction 前生成，如有出入请以源代码为准。*