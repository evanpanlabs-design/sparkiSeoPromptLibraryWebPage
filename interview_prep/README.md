# 面试准备文件夹说明

## 目录结构

```
interview_prep/
├── README.md                    # 本文件 — 文件夹整体说明
├── PROJECT_OVERVIEW.md          # 项目通用介绍 & 技术细节（所有 JD 共用）
├── companies/                   # 每个投递的公司/岗位一个文件夹
│   ├── [company_name]_[role]/   # 例：bytedance_backend_intern/
│   │   ├── job_description.txt  # 原始 JD（复制粘贴）
│   │   ├── resume_for_role.md   # 针对该 JD 改写的简历项目描述
│   │   ├── interview_script.md  # 面试逐字稿 & 准备材料
│   │   └── review.md            # 面试录音转写 + 复盘
│   └── ...
└── job_tracker.md               # 投递进度追踪（可选）
```

---

## 使用流程

### 1. 准备阶段

在投递任何公司之前，先通读 `PROJECT_OVERVIEW.md`，确保你对自己的项目了如指掌。

### 2. 收到 JD 后

1. 在 `companies/` 下创建新文件夹（命名规范：`[公司名]_[岗位]`，英文或拼音）
2. 将 JD 复制到 `job_description.txt`
3. 根据 JD 关键词，从 `PROJECT_OVERVIEW.md` 中提取相关项目经历，写入 `resume_for_role.md`
4. 用 `PROJECT_OVERVIEW.md` 的技术细节，准备 `interview_script.md`

### 3. 面试前

- 熟读 `resume_for_role.md`（完全脱稿背诵）
- 熟读 `interview_script.md` 的 1min / 3min 自我介绍
- STAR 法则每个项目至少准备 3 个具体数字/细节
- 过一遍可能的 Q&A

### 4. 面试后

1. 录音转文字，粘贴到 `review.md`
2. 写复盘：哪些答得好，哪些下次要改

---

## 如何让 AI 帮忙

给 AI 这整个文件夹的路径，提示词示例：

```
我有一个面试准备文件夹：interview_prep/
里面包含 PROJECT_OVERVIEW.md（项目介绍）和 companies/bytedance_backend_intern/（我投的字节后端实习）
请帮我：
1. 根据 JD 关键词，从项目经历中提炼匹配的亮点
2. 写一个 3 分钟自我介绍
3. 预测 10 个高频面试问题并给出回答要点
```

---

## 参考信息来源优先级

1. `PROJECT_OVERVIEW.md` — 项目技术细节（最准确）
2. `docs/01_PRD_V3.md` — 产品需求文档（了解为什么这么设计）
3. `docs/02_DevGuide_V3.md` — 开发指南（系统架构）
4. `CLAUDE.md` — 项目源码说明（代码结构）
5. 源代码 — 具体实现细节（当你需要回答"怎么实现"时）