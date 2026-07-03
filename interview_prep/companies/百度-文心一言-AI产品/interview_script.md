# 面试逐字稿 & 准备材料

> 每次面试前更新此文件，标注哪些部分需要重点背诵。

---

## 一、自我介绍

### 1 分钟版（快节奏，适用于群面/HR 面）

```
面试官好，我叫 Evan，目前独立开发了一个叫 Sparki 的 AI Prompt 库平台。

核心功能是从 Twitter 采集高质量的 AI 视频生成 Prompt，
经过质量评分筛选、生成封面图后发布到网站，供 AI 创作者检索使用。

整个项目我独立完成：需求分析、架构设计、编码实现、部署维护。
技术栈主要是 Python + LangGraph + SQLite + Gemini API。

在项目中，我设计了一套 4 维度 Prompt 质量评测体系，
并且用 Gemini Embedding 实现了语义搜索功能。

这个项目让我对 AI 产品开发和 Agent 系统设计都有了实战经验。
谢谢。
```

### 3 分钟版（技术面重点展开）

```
面试官好，我叫 Evan。

我现在在独立开发一个叫 Sparki 的项目，是一个 AI Prompt 库平台。

整个项目的背景是这样的：Twitter 上有大量 AI 视频创作者在分享高质量的生成 Prompt，
但它们散落在海量推文里，没有一个集中的平台。
我希望能做一个工具，自动采集这些 Prompt，筛选质量，整理发布。

技术架构分几块：
- 数据采集层用 Apify 爬 Twitter，配合 Playwright 做动态页面处理
- LLM 层接 Gemini API，做三件事：Prompt 提取、质量评分、封面图生成
- 数据存储用 SQLite，加了 Embedding 向量做语义搜索
- V3 版本我开发了一个对话式 Agent，用 LangGraph 实现 ReAct 架构，
  用户说"跑全程"Agent 就能自动串起整个流程

在质量评估方面，我设计了一套 4 维度评测体系：
Specificity、Visual Detail、Novelty、Generatability，
各有权重，加权求和后低于 0.4 的过滤淘汰。

我独立负责整个项目的开发，从爬虫、数据处理、Agent 架构到部署上线。
这个项目让我对数据管道、LLM 应用开发和 Agent 系统设计都有了比较深入的理解。

谢谢。
```

---

## 二、项目介绍 — STAR 法则

### S（Situation）：项目背景

> **当时是什么情况？遇到什么问题？**

**回答**：
> Twitter 上有大量 AI 视频生成爱好者在分享高质量的生成 Prompt，比如 Veo 3、Sora、Runway 的玩家。但这些 Prompt 散落在海量推文里，没有一个集中的平台供创作者检索。我希望做一个工具，能自动把这些 Prompt 采集下来，筛选质量，整理发布。

### T（Task）：我的任务

> **我负责什么？**

**回答**：
> 独立负责整个项目：需求分析、架构设计、编码实现、部署维护。这是我的个人项目，没有团队分工，所以我需要独立完成从爬虫到网站发布的全链路。

### A（Action）：具体行动

> **我做了什么？用了什么技术方案？**

**按主题展开**（根据面试官追问选择）：

**主题1：Prompt 质量评测体系（JD 最匹配）**
> 采集下来的推文里，大部分是无效内容——太短、没有指令、或者只是感叹句。
> 我设计了两层过滤：
> - 第一层：关键词 + 长度过滤（至少 15 词，包含"prompt"/"AI video"等关键词）
> - 第二层：LLM 4 维度评分，低于 0.4 直接淘汰
>
> 4 个维度是我根据文生视频产品的特性来定义的：
> - Specificity（25%）：指令是否具体清晰
> - Visual Detail（30%）：视觉细节是否丰富——颜色、构图、运镜
> - Novelty（20%）：创意是否新颖
> - Generatability（25%）：这个 Prompt 是否真的能被 AI 模型执行
>
> 视觉细节权重最高，因为这是生成质量的关键。

**主题2：数据采集（爬虫）**
> 爬虫用 Apify Actor，配置了 max_scrolls=20 和 stale_threshold=3 控制爬取深度。
> Apify 有自己的 proxy pool 和 browser fingerprint，不需要我自己处理防封。
> 推文采集后先存 SQLite，用 INSERT OR IGNORE 防止重复。

**主题3：语义搜索（Embedding）**
> 每条 Prompt 入库时调用 Gemini embedding API 生成 768 维向量，存到 SQLite BLOB。
> 用户搜索时把 query 也 embedding，和库里向量做余弦相似度排序，返回 top-k。
> 这个功能对应 JD 里"需求洞察"的能力——用户输入一个想法，系统能找到最相关的 Prompt。

**主题4：ReAct Agent 架构（偏技术）**
> V3 版本我正在开发对话式 Agent，用 LangGraph 的 StateGraph 实现 ReAct。
> 6 个 Node：start / think / plan / act / observe / final_reply。
> observe_node 根据 tool_result 判断是否继续下一步，实现自主规划多步任务。
> 所有工具都是独立的 Skill 注册到 Registry 里，LLM 通过 get_tool_schemas() 获取所有工具定义。

### R（Result）：成果

> **结果怎么样？**

**回答**：
> 采集了 131 条高质量 Prompt，发布到 GitHub Pages。
> 质量评分过滤掉了约 60% 的低质量内容。
> 图片生成通过 429 重试机制，成功率超过 95%。

---

## 三、高频问题 & 回答要点

### Q1：这个项目最大的难点是什么？

**要点**：
> X.com 的 SSL proxy 问题导致 LLM 调用失败。还有 Windows 路径问题（GCS 的 download_to_file() 不能接受 WindowsPath 对象）。解决：配置 OPENAI_API_BASE 绕过代理，用 open(path, 'wb') 包装 Path 对象。

### Q2：你们怎么评估 Prompt 质量？

**要点**：
> 4 个维度：Specificity（具体性）、Visual Detail（视觉细节）、Novelty（新颖度）、Generatability（可生成性）。各有权重（25/30/20/25%），加权求和，低于 0.4 的过滤掉。

### Q3：为什么用 LangGraph 而不是 LangChain？

**要点**：
> LangChain 太重，我们只需要 StateGraph + checkpointer。自己封装更轻量，完全控制代码结构。LangGraph 是 LangChain 的底层核心，概念更直接。

### Q4：ReAct 和 Function Calling 的区别？

**要点**：
> Function Calling 是"用户说啥，LLM 直接调工具"，适合单步操作。ReAct 有显式的 Thought + Observation，LLM 先推理再行动，可以自主规划多步任务链，每一步的 Observation 写入记忆供下一步使用。

### Q5：Embedding 怎么存的？

**要点**：
> SQLite BLOB，每条 Prompt 一个 embedding，存 JSON 序列化的 list[float]。搜索时 query 也 embedding，然后 cosine similarity 排序，返回 top-k。

### Q6：怎么避免 API 429？

**要点**：
> 图片生成用了 RateLimitSafeGenerator，串行执行 + 2 秒间隔，遇到 429 指数退避重试（最多 3 次）。爬虫通过 Apify 的 proxy pool 控制请求频率。

### Q7：如果让你重来，会怎么改进？

**要点**：
> V1 pipeline 的 phase 耦合太紧，V3 把它们拆成了独立的 Skill。这样每个 phase 可以单独测试和替换，也方便 Agent 精确控制每一步。

### Q8：为什么想做 AI 产品经理？

**要点**：
> 我本身就在用 AI 工具做产品开发，对 AI 能力边界有直观感受。我对 Prompt 质量敏感，能判断什么是"好 Prompt"，这在做 AI 产品时是很重要的能力。Sparki 项目让我学会了从用户需求出发设计评测体系，这也是产品经理的核心工作。

### Q9：你觉得 AI 产品和传统产品有什么区别？

**要点**：
> 传统产品输出是确定的（点击哪个按钮发生什么），AI 产品输出是不确定的（同一个 Prompt 每次结果不同）。所以 AI 产品经理需要设计评测体系来衡量效果，需要接受概率性结果，需要设计"好"的标准。

### Q10：你能为这个岗位带来什么？

**要点**：
> 1. 对 AI 能力边界的直观理解——我天天在用 LLM，知道它擅长什么、不擅长什么
> 2. 数据驱动的评测思维——Sparki 的 4 维度评分体系是我自己设计的
> 3. 工程落地能力——我能独立把一个 AI 产品从 0 到 1 跑通，不只是画原型

---

## 四、反问环节准备

当面试官说"你有什么问题要问我"时，准备 2-3 个问题：

1. **如果技术面**：
   - "文心助手的记忆与个性化功能，现在主要的技术难点是什么？"
   - "团队日常怎么评估 Prompt/产品效果？有人工评估也有自动评估吗？"
   - "日常 LLM 调用的成本和稳定性是怎么控制的？"

2. **如果 HR 面**：
   - "这个岗位的新人培养机制是什么样的？"
   - "如果我加入，前三个月的主要工作是什么？"
   - "团队平时的技术交流方式是怎样的？"

---

## 五、标记：哪些需要重点准备

- [ ] 1min 自我介绍（背诵）
- [ ] 3min 自我介绍（背诵）
- [ ] STAR 法则项目介绍（能脱稿）
- [ ] Q1-Q10 每题能回答 1 分钟以上
- [ ] 反问问题准备 2 个
- [ ] 确认了解项目所有技术细节（能被追问）