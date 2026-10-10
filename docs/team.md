# 团队分工与协作约定（v0）

本文件用于课程项目的协作准备。当前仓库只初始化文档和 issue，尚无真实业务实现；下文目录是未来建议的归属约定，**不表示目录或功能已存在**。训练集和测试集尚未取得，数据细节由组长在 [#1 接口约定与集成验收](https://github.com/Ars1027/func-vuln-agent/issues/1) 核对后更新。开发者可以用 AI 辅助编码，但交付的检测 Agent 必须由项目自身实现自主工具选择和决策，不能套用 Codex 等现成编码 Agent，也不能退化成固定的 LLM 流水线。

## 唯一负责人

每个 issue 只有一位负责人，没有协助或共同负责人。成员 GitHub 账号待确定，以下角色字母只是占位。

| Issue | 唯一负责人 | 职责与未来建议归属 |
| --- | --- | --- |
| [#1 接口约定与集成验收](https://github.com/Ars1027/func-vuln-agent/issues/1) | 组长 Ars1027 | 对齐课程要求、接口和验收；`backend/app/schemas` 等共享契约由组长负责 |
| [#2 历史 CVE 知识库检索](https://github.com/Ars1027/func-vuln-agent/issues/2) | 成员 A（账号待定） | `backend/app/rag`；历史漏洞及修复对的整理、检索和来源定位 |
| [#3 样本准备与指定版本快照](https://github.com/Ars1027/func-vuln-agent/issues/3) | 成员 B（账号待定） | `backend/app/repository`；按目标取得指定版本的待测快照 |
| [#4 仓库上下文工具](https://github.com/Ars1027/func-vuln-agent/issues/4) | 成员 B（账号待定） | `backend/app/repository`；为 Agent 提供受控的代码上下文读取工具 |
| [#5 自主 Agent 检测 API](https://github.com/Ars1027/func-vuln-agent/issues/5) | 组长 Ars1027 | `backend/app/agent`、`backend/app/api`；单函数检测闭环与事件流 |
| [#6 Web 界面](https://github.com/Ars1027/func-vuln-agent/issues/6) | 成员 C（账号待定） | `frontend/`；提交任务、查看过程与报告 |
| [#7 批量评测与导出](https://github.com/Ars1027/func-vuln-agent/issues/7) | 成员 D（账号待定） | `backend/app/evaluation`；批量运行和课程结果导出 |
| [#8 GitHub Bot](https://github.com/Ars1027/func-vuln-agent/issues/8) | 成员 D（账号待定） | `backend/app/bot`；在核心检测接口稳定后接入 GitHub |

成员 B 按 #3 → #4、成员 D 按 #7 → #8 的顺序逐项完成；组长先完成 #1 的 M1 接口检查点，再推进 #5。每次只以当前 issue 的正文和验收条件划定本轮工作范围，不把同一角色的多个 issue 一次做完。

## 里程碑

| 里程碑 | 范围 | 完成依据 |
| --- | --- | --- |
| M1 接口与数据准备 | #1 的接口检查点、#2、#3 | 契约可供各模块对接；历史检索和指定快照的边界可验证 |
| M2 单函数检测闭环 | #4、#5、#6 | 仓库工具、自主 Agent、API、Web 能围绕单个函数展示检测过程和报告 |
| M3 批量评测 | #7、#1 的最终集成验收 | 可按课程要求批量运行并导出结果；组长完成集成验收 |
| M4 GitHub Bot | #8 | Bot 复用已稳定的检测能力 |

里程碑不预设日期。#1 在 M1 建立接口检查点，但保持开启直到 M3 最终集成验收；其他 issue 依赖其接口检查点，不必等待 #1 关闭。技术路线为 Python、LangGraph、FastAPI 和 React/TypeScript；具体版本与依赖以 issue、接口文档和后续实现为准。

## 接口与数据边界

- 准备层根据目标选择 `parent` 或 `fixed` 快照；检测 Agent 只接收 `idx`、`func`、`snapshot_ref` 等待测信息，不接收标签、修复前后对照或答案。
- 历史 RAG 可以使用课程提供的历史漏洞及修复对建立知识库，但测试集不得混入。一次待测只暴露一个指定版本，不向 Agent 提供 diff 或对照版本。
- 网络访问只用于根据 `commit_url` 获取指定仓库；检测过程不通过搜索引擎或其他外部来源查答案。
- RAG 用 `case_id`、`source` 追溯历史记录；仓库代码工具返回当前快照中的路径与 1 起始行号。报告包含 `idx`、`prediction`、`reason`、`evidence`、`trace`。
- API 的 SSE 事件覆盖任务状态、检索、代码读取与错误。课程提交的 `result.jsonl` 每行只含 `idx`、`prediction`；详细报告另存，不混入该文件。
- 尚未取得课程训练集和测试集。开发期间若使用合成样例，必须明确标为“非课程数据”，不得称为真实课程验证结果。

这些约定以 [课程要求](course-requirements.md)、[架构](architecture.md) 和 [接口](interfaces.md) 的正式内容为准；若文件尚在编写或与数据实物不符，由 #1 负责人核对并更新，其他负责人不要自行改变共享契约。

## 交付与集成

每位负责人先阅读 [README](../README.md)、[AGENTS.md](../AGENTS.md)、[CONTRIBUTING.md](../CONTRIBUTING.md)、上述三份 `docs/` 文档、自己的 issue 和已有实现；按当前 issue 开分支、提交聚焦的 PR，并在 PR 中写明实现范围、验证命令与结果、仍需组长协调的接口问题。提示词见 [docs/prompts/README.md](prompts/README.md)。

跨模块发现的问题记录在 PR 或 issue 中并交给该 issue 的唯一负责人处理；不要顺手改写别人的模块。共享 schema、API 或数据契约变更由组长统一协调。组长负责集成评审、验收与合并 PR；集成评审提示词为只读，不代替负责人修复。这里的“交给负责人”是项目协作规则，不要求 AI 工具自动向任何聊天、邮箱或远程服务发送消息。
