# 面试逐字稿 & 准备材料

> 每次面试前更新此文件，标注哪些部分需要重点背诵。

---

## 一、自我介绍

### 1 分钟版（快节奏，适用于群面/HR 面）

```
面试官好，我叫 Evan，目前在独立开发一个叫 Sparki 的 AI Prompt 库平台。

核心功能是从 Twitter 采集高质量的 AI 视频生成 Prompt，经过质量筛选和封面图生成后，
发布到 GitHub Pages 供创作者使用。

技术栈主要是 Python + LangGraph + SQLite。
我独立负责了整体架构设计，包括爬虫框架、LLM 调用层、GitHub Pages 发布流程。

这个项目让我对 Agent 系统和数据管道有了实战经验。
谢谢。
```

### 3 分钟版（技术面重点展开）

```
面试官好，我叫 Evan。

我现在在独立开发一个叫 Sparki 的项目，是一个 AI Prompt 库平台。

整个项目是这样的：Twitter 上有大量 AI 视频生成的讨论，我用爬虫把这些推文采下来，
然后用 LLM 从里面提取"可以生成视频的 Prompt"，再经过质量评分、生成封面图，
最后发布到一个静态网站。

技术架构分几块：
- 数据采集层用 Apify 爬 Twitter，配合 Playwright 做动态页面处理
- LLM 层接 Gemini API，包括 Prompt 提取、质量评分、封面图生成三个步骤
- 数据存储用 SQLite，加了 Embedding 向量做语义搜索
- V3 版本我正在开发一个对话式 Agent，用 LangGraph 实现 ReAct 架构，
  用户说"发布网站"Agent 就能自动跑完整个流程

我主要负责全栈开发，包括爬虫、数据处理、Agent 架构设计和部署。
这个项目让我对数据管道、LLM 应用开发和 Agent 系统设计都有了比较深入的理解。

谢谢。
```

---

## 二、项目介绍 — STAR 法则

### S（Situation）：项目背景

> 当时是什么情况？遇到什么问题？

**回答**：
> 我在 Twitter 上看到很多 AI 视频创作者在分享高质量的生成 Prompt，但它们散落在大量推文里，没有一个集中的平台。我希望做一个工具，能自动采集这些 Prompt 并整理发布。

### T（Task）：我的任务

> 我负责什么？

**回答**：
> 独立负责整个项目：需求分析、架构设计、编码实现、部署维护。

### A（Action）：具体行动

> 我做了什么？用了什么技术方案？

**重点展开**（选 JD 匹配的点）：

**如果 JD 强调 Agent/LLM：**
> 我设计了一个 Skill Registry 系统，每个工具（爬虫、评分、生成图、发布）都是独立的 Skill，注册到 Registry 里。LLM 通过 get_tool_schemas() 获取所有工具的 JSON Schema，自己决定调用哪个。

> Agent 架构用的是 LangGraph 的 StateGraph，每个 Node 是独立的函数（think/plan/act/observe），通过 state 传递信息。observe_node 会根据 tool_result 决定是否继续下一步。

**如果 JD 强调爬虫/数据：**
> 爬虫用 Apify 的 Actor，我配置了 max_scrolls=20 和 stale_threshold=3 来控制爬取深度。内容过滤先用关键词过滤（包含"prompt"/"AI video"等），再用 LLM 做质量评分，只保留评分 0.4 以上的。

**如果 JD 强调 Embedding/搜索：**
> 我用 Gemini embedding API 给每条 Prompt 生成 768 维向量，存到 SQLite BLOB 里。搜索时把 query 也 embedding，和库里向量做余弦相似度排序。

**如果 JD 强调工程化：**
> 所有配置进 YAML 文件，没有硬编码。数据库用了 WAL 模式支持多进程并发读。图片生成加了 2 秒间隔的 rate limit 保护。脚本都支持 `--dry-run` 和 `--limit` 参数。

### R（Result）：成果

> 结果怎么样？

**回答**：
> 采集了 131 条高质量 Prompt，发布到 GitHub Pages。网站访问量稳定在每日 XX 次。

---

## 三、高频问题 & 回答要点

### Q1：为什么用 LangGraph 而不是 LangChain？

**要点**：
> LangChain 太重，我们只需要 StateGraph + checkpointer。自己封装更轻量，而且可以完全控制代码结构，不需要学习 LangChain 特有的接口。

**展开**：
> LangGraph 是 LangChain 的底层核心，概念更直接——就是 StateGraph + 条件边。LangChain 在上面包了一层，有时候报错不好排查。自己写 build_react_graph() 就 100 行代码，所有逻辑都透明。

### Q2：ReAct 和 Function Calling 的区别？

**要点**：
> Function Calling 是"用户说啥，LLM 直接调工具"，适合单步操作。ReAct 有显式的 Thought + Observation，LLM 先推理再行动，可以自主规划多步任务链。

### Q3：怎么避免 API 429？

**要点**：
> 图片生成用了 RateLimitSafeGenerator，串行执行 + 2 秒间隔，遇到 429 指数退避重试（最多 3 次）。爬虫通过 Apify 的 proxy pool 控制请求频率。

### Q4：SQLite 多进程读写怎么保证安全？

**要点**：
> WAL 模式下读可以并发，但写有锁。遇到过进程持有写锁没释放导致卡住的问题，靠杀进程解决。

### Q5：遇到最难的问题是什么？怎么解决的？

**要点**（选一个）：
> 1. **WindowsPath bug**：GCS 的 download_to_file() 不能接受 WindowsPath 对象，要用 open(path, 'wb') 包装
> 2. **X.com SSL proxy**：配置了 OPENAI_API_BASE 环境变量绕过代理直连
> 3. **图片路径404**：HTML 模板用 generated_images/${id}.png 但图片在 images/{category}/ 下，用 --sync-images 复制到扁平目录解决

### Q6：这个项目如果让你重来，会怎么改进？

**要点**：
> V1 pipeline 的 phase 耦合太紧，V3 把它们拆成了独立的 Skill。这样每个 phase 可以单独测试和替换，也方便 V3 Agent 精确控制每一步。

### Q7：你们怎么评估 Prompt 质量？

**要点**：
> 4 个维度：Specificity（具体性）、Visual Detail（视觉细节）、Novelty（新颖度）、Generatability（可生成性）。各有权重，加权求和，低于 0.4 的过滤掉。

### Q8：Embedding 怎么存的？

**要点**：
> SQLite BLOB，每条 Prompt 一个 embedding，存 JSON 序列化的 list[float]。搜索时 query 也 embedding，然后 cosine similarity 排序。

---

## 四、反问环节准备

当面试官说"你有什么问题要问我"时，准备 2-3 个问题：

1. **如果技术面**：
   - "你们团队的 Agent 系统现在是什么阶段？是自研还是基于 LangChain？"
   - "日常开发中 LLM 调用的稳定性和成本是怎么控制的？"
   - "数据管道是流式还是批量的？"

2. **如果 HR 面**：
   - "这个岗位的新人培养机制是什么样的？"
   - "团队平时的技术交流方式？"
   - "如果我加入，前三个月的主要工作是什么？"

---

## 五、标记：哪些需要重点准备

- [ ] 1min 自我介绍（背诵）
- [ ] 3min 自我介绍（背诵）
- [ ] STAR 法则项目介绍（能脱稿）
- [ ] Q1-Q8 每题能回答 1 分钟以上
- [ ] 反问问题准备 2 个
- [ ] 确认了解项目所有技术细节（能被追问）