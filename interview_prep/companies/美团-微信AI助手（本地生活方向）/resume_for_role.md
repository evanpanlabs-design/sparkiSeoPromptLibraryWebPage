# 针对 [美团] [微信AI助手本地生活方向] 的简历项目描述

---

## 项目一：Sparki — AI Prompt 库平台

**项目描述**：

> Sparki 是一个从 Twitter 采集高质量 AI 视频生成 Prompt 并发布到 GitHub Pages 的全栈平台。我在项目中独立完成了从需求分析到上线部署的全流程，核心工作包括：**设计了一套多维度 Prompt 质量评测体系**，用 Gemini Embedding 实现了语义搜索方案，并基于 LangGraph 搭建了可自然语言驱动的 ReAct Agent，实现了多步骤任务的自主规划与执行。

**核心亮点**：

- **评测体系设计**：设计了 Specificity / Visual Detail / Novelty / Generatability 4 维度评分体系（权重 25/30/20/25%），低于 0.4 分自动过滤，量化内容质量；入库 131 条高质量 Prompt，过滤率约 60%
- **语义搜索方案**：使用 Gemini embedding API 生成 768 维向量存入 SQLite，搜索时通过余弦相似度排序返回 top-k 结果，将散落内容结构化供用户检索，理解 RAG 类应用的核心实现逻辑
- **ReAct Agent 架构**：基于 LangGraph StateGraph 实现对话式 Agent，封装 12 个独立 Skill（爬虫/评分/图生成/发布等），支持用户说"跑全程"自动串起完整 Pipeline，具备与算法团队进行技术对话的实战经验