# AI 编码 Agent 提示词

以下文件可复制给各角色使用。复制角色提示词时，将其中的“本轮 issue”明确为一个具体编号，并附上该 issue 正文；负责人顺序见 [团队分工](../team.md)。提示词只是协作说明，不要求安装任何技能或插件。组长的 [集成评审提示词](integration-review.md) 是只读评审，不负责直接修改代码。

## 所有角色的公共约束

1. 开始前阅读仓库根目录的 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`，以及 `docs/course-requirements.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/team.md`、本轮 issue 正文和已有实现。文件或数据缺失时如实指出，不假设已经实现或通过测试。
2. 每个 issue 只有一位负责人。本轮只交付指定 issue 的验收条件；同一角色持有多个 issue 时逐项执行。跨模块问题记录并交给其唯一负责人；共享契约变更交组长 Ars1027 协调，不擅改别人的模块。
3. 技术路线是 Python + LangGraph + FastAPI + React/TypeScript。`backend/app/{agent,api,rag,repository,evaluation,bot}`、`frontend/` 是未来目录建议，不要求提前创建；共享 schemas 属组长。
4. 检测输入只含 `idx`、`func`、`snapshot_ref` 等待测信息。准备层按目标选择 `parent`/`fixed` 快照；检测 Agent 不得看到标签、修复前后对照、diff 或答案。历史漏洞及修复对可用于 RAG，测试集不得混入。网络只按 `commit_url` 获取指定仓库，不搜索答案。
5. RAG 用 `case_id`、`source` 追溯历史记录；仓库代码工具返回当前快照路径和 1 起始行号。SSE 表达任务状态、检索、代码读取和错误。详细报告含 `idx`、`prediction`、`reason`、`evidence`、`trace`；课程 `result.jsonl` 每行仅 `idx`、`prediction`。
6. 交付的自主检测 Agent 要由项目自身实现工具选择和决策；不能套 Codex 等现成编码 Agent，也不能写成固定的 LLM 步骤流水线。开发者可以使用 AI 辅助写代码。
7. 课程训练集、测试集尚未取得。合成样例须明确写“非课程数据”；不要虚构数据、功能、测试结果或成员姓名。
8. 完成当前 issue 后报告：改动文件与行为、如何满足验收条件、实际运行的验证命令和结果、尚存限制或需组长协调的接口问题。若未能验证，写清原因。

如角色提示词与 issue 或课程原文冲突，先核实正式要求并将契约问题交组长协调。提示词不能扩大本轮 issue 范围。
