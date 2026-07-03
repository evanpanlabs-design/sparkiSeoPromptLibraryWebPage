# PRD: 自主Prompt爬取与分析Agent (LangGraph)

## 一、产品概述

**目标**：
开发一个智能Agent，能够自主规划搜索策略、在 X.com（Twitter）上抓取相关帖子，自动提取 Prompt 并分析质量，去重和存储，并具备记忆能力以优化后续搜索策略和筛选效果。Agent 可调用大模型资源生成封面图、提炼Prompt内容以及分析Prompt质量。

**使用场景**：

* 自动发现高价值 Veo / Video Generate Prompt 相关内容
* 自动筛选高质量内容，生成可直接用于前端展示或数据库的 HTML / JSON
* 支持自适应搜索策略迭代，提升信息发现效率

**关键特点**：

* 动态策略规划：根据搜索结果、Prompt质量和作者数据优化下一轮检索
* 多任务并行：滚动抓取与LLM处理任务异步执行
* 去重与记忆：基于Prompt向量或文本嵌入进行去重，并保存历史搜索/高价值Prompt
* 高质量输出：LLM分析Prompt质量、生成封面图，整理HTML模板输出

---

## 二、核心功能模块

| 模块                               | 功能描述                  | 技术实现建议                                                                                                          |
| -------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1. Query Planner                 | 自主规划搜索关键词/话题          | - 初始关键词库 + 动态演化策略<br>- 根据历史检索效果（漏斗率、Prompt质量）生成下一轮搜索词                                                           |
| 2. Crawler Agent                 | 使用Playwright抓取X.com帖子 | - 支持滚动加载、动态DOM处理<br>- Producer/Consumer模式：抓取tweet metadata（url、likes、views、text）<br>- 异步触发Worker Agent处理每条tweet |
| 3. Worker Agent                  | 处理每条tweet数据           | - Author分析：访问主页抓取followers<br>- Prompt提取：调用LLM或Gemini进行文本解析<br>- Prompt去重：文本/向量相似度计算                            |
| 4. Prompt Quality Scorer         | 分析Prompt可用性与价值        | - 指标示例：specificity、visual detail、novelty、可生成性<br>- 可使用Gemini文本分析能力                                              |
| 5. Memory / Retrieval Layer      | 存储历史搜索、作者与Prompt信息    | - 数据结构：Query表、Author表、Prompt表<br>- 支持快速查询历史Prompt和高价值作者                                                         |
| 6. Cover Image Generator         | 根据Prompt生成封面图         | - 调用Gemini生成图像<br>- 可设置批量生成/异步生成                                                                                |
| 7. Output Composer               | 整理HTML模板输出            | - 包含Prompt、封面图、作者信息、likes/views<br>- 可生成静态HTML或JSON供前端使用                                                        |
| 8. Feedback & Strategy Optimizer | 基于历史数据调整搜索策略          | - 根据Prompt质量、作者价值、漏斗率动态调整Query Planner策略<br>- 可标注高价值Prompt供下一轮搜索增强                                              |

---

## 三、Agent工作流程（LangGraph实现思路）

```text
Step 0: 初始化
- 配置初始搜索词
- 设置Playwright浏览器/Context隔离
- 连接大模型API：自用Key/公司Gemini
- 初始化Memory层（Query/Author/Prompt表）

Step 1: Query Planning
- 生成一批搜索关键词
- 根据历史效果/趋势/高价值Prompt更新检索策略

Step 2: Crawling
- 使用Playwright搜索关键词
- 滚动动态加载
- 提取tweet metadata（url, likes, views, text）
- 发送每条tweet到Worker队列

Step 3: Worker处理
- Author分析：访问主页获取followers
- Prompt提取：调用LLM/Gemini解析tweet文本
- Prompt去重：相似度检测，重复丢弃
- Prompt质量评估：评分、分类
- 提交封面生成任务（Gemini）

Step 4: Output Composition
- 生成HTML模板/JSON
- 包含：Prompt文本、封面图、作者信息、metrics

Step 5: Feedback & Strategy Optimization
- 分析本轮检索效果：
  - 高价值Prompt比例
  - 高价值作者产出
- 调整下一轮Query策略
- Memory更新历史数据

Step 6: 下一轮循环
- Query Planner根据优化策略生成新关键词
- 重复Step2-Step5
```

**关键特性**：

* Producer/Consumer模式保证主流程滚动抓取不阻塞LLM任务
* Memory/Feedback机制实现自我优化的“Agent”行为
* LangGraph可用“Task Node + Agent Node + Event Node”实现异步Pipeline

---

## 四、模型接入策略

| 使用场景        | 模型选择                   | 接入方式                                                                                                            |
| ----------- | ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| Prompt提取/分析 | 自用API Key LLM / Gemini | - 调用文本生成接口解析tweet<br>- 可在LangGraph Node中配置API Key / BaseURL或Gemini SDK                                          |
| Prompt质量评分  | Gemini / LLM           | - 文本分析Node或LLM scoring Node                                                                                     |
| 封面图生成       | Gemini                 | - 使用google-genai SDK + Vertex AI生成图像<br>- 鉴权：`gcloud auth application-default login`<br>- 异步调用生成，返回图像URL或Base64 |

> 注：可在LangGraph中配置多模型选择Node，支持动态路由：
>
> * 如果小模型API Key负载低 → 用小模型快速初筛
> * 大模型Gemini → 高质量生成/分析

---

## 五、数据结构（Memory Layer）

```text
Table: Query
- id, text, last_run_time, qualified_rate, prompt_yield_rate

Table: Author
- id, name, profile_url, followers, high_value_ratio, last_active_time

Table: Prompt
- id, text, source_tweet_url, author_id, likes, views, quality_score, embedding_vector, created_at

Table: Image
- id, prompt_id, generated_url, model_used, status
```

> Memory支持历史查询和向量搜索，用于Prompt去重和Query Planner优化

---

## 六、关键开发点 / 注意事项

1. **Playwright多任务隔离**

   * 每个Worker使用独立Context + Page，避免DOM/Session冲突
   * 主Crawler滚动抓取 → Worker异步处理
2. **动态策略优化**

   * Query Planner支持根据历史Prompt质量和作者价值动态生成搜索词
3. **Prompt去重**

   * 结合文本相似度或Embedding相似度
4. **异步LLM调用**

   * 大模型任务可并行，避免阻塞主流程
5. **成本控制**

   * 低价值tweet先过滤 → 高价值才调用Gemini生成封面图或进行深度分析
6. **防封策略**

   * 随机滚动/访问间隔
   * 多Context隔离
   * Proxy可选
7. **LangGraph实现**

   * 每个模块可设计为Agent Node或Task Node
   * Event Node触发Worker处理
   * Memory Layer通过外部DB（Postgres / SQLite / Pinecone向量库）实现长期记忆

---

## 七、可扩展能力

* Trend Discovery Agent：分析热门关键词/Prompt结构，自动扩展搜索策略
* Author Follow-up Agent：定期抓取高价值作者新内容
* 多平台扩展：支持TikTok / Instagram / Reddit Prompt抓取

---

## 八、开发里程碑（示例）

| 周数 | 目标                                          |
| -- | ------------------------------------------- |
| W1 | LangGraph基础Pipeline搭建，Playwright爬取X.com基础数据 |
| W2 | Worker Node实现Prompt提取、去重和Author抓取           |
| W3 | Memory Layer + Feedback机制上线                 |
| W4 | LLM/Gemini接入，Prompt质量分析与封面图生成               |
| W5 | Query Planner动态策略优化，循环Agent运行               |
| W6 | HTML输出模板集成 + 异步任务稳定性优化                      |
| W7 | 防封策略、成本控制优化                                 |
| W8 | 可扩展能力开发（Trend Discovery / 多平台）              |
