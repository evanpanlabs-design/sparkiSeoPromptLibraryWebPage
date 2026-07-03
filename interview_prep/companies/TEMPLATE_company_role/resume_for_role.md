# 针对 [公司名] [岗位] 的简历项目描述

> 写法：从 JD 关键词出发，挑项目中最匹配的经历，用 STAR 法则，量化成果。

---

## 项目一：Sparki — AI Prompt 库平台

**项目描述**：（改写，突出 JD 匹配点）

> Sparki 是一个从 X.com 采集高质量 AI 视频生成 Prompt 并发布到 GitHub Pages 的全栈平台。我在项目中独立完成了：
> - 设计并实现了一套可扩展的 **Skill Registry 工具系统**（类似 LangChain Tool 的注册机制），支持动态注册和 LLM 函数调用；
> - 搭建了基于 **LangGraph** 的 ReAct Agent，能够根据用户自然语言指令自主规划多步任务（爬取→提取→评分→生成图→发布），将人工操作自动化；
> - 设计了 **SQLite + Embedding** 的语义搜索方案，用 Gemini 生成向量并通过余弦相似度检索。

**技术栈**：Python / LangGraph / SQLite / Gemini API / GCS / Apify / GitHub Pages

---

## 项目二：（如果 JD 要求爬虫/数据采集）

> [类似写法，突出爬虫、分布式数据处理经验]

---

## 项目三：（如果 JD 要求前端/全栈）

> [类似写法，突出全栈能力]

---

## 关键：JD 关键词对照表

| JD 关键词 | 项目中对应点 |
|---|---|
| Agent / LLM | LangGraph ReAct Agent，Skill Registry |
| 工具注册 | SkillRegistry.register() 动态注册 |
| 多步骤任务规划 | observe_node 的 continue 决策逻辑 |
| 数据采集 / 爬虫 | Apify + Playwright 爬 X.com |
| 语义搜索 / Embedding | Gemini embedding + cosine similarity |
| SQL / 数据库 | SQLite WAL 模式，schema migration |
| Python | 全程 Python 3.11 |
| API 集成 | Gemini API、GCS API、GitHub API |