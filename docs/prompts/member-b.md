# 成员 B：样本准备与仓库上下文工具

你是 [#3 样本准备与指定版本快照](https://github.com/Ars1027/func-vuln-agent/issues/3) 和 [#4 仓库上下文工具](https://github.com/Ars1027/func-vuln-agent/issues/4) 的唯一负责人。**本轮只做一个指定 issue**：先完成 #3，再另开一轮处理 #4。未来建议归属 `backend/app/repository`；GitHub 账号待定。

## 必读

先读根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`，`docs/course-requirements.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/team.md`、[提示词公共约束](README.md)、本轮 issue 正文和已有实现。以 #1 的契约为准，发现接口缺口交组长 Ars1027 协调。

## 本轮目标与边界

- **若本轮是 #3：**准备课程待测样本，根据目标选择父提交或修复提交的单个快照；Web 单样本按明确的 `revision=commit/parent` 选择，Bot 定点请求用 `revision=commit`。没有版本选择时要求补齐，不猜测。输出 Agent 所需的 `idx`、`func`、`snapshot_ref` 等信息。可按 `commit_url` 获取指定仓库，但不得为了寻找答案访问其他网络来源。标签、版本选择、对照版本和 diff 不进入 Agent 可见数据。不要顺带写 #4 的工具。
- **若本轮是 #4：**在 #3 的快照契约上实现受控仓库上下文读取工具。工具只查看当前 `snapshot_ref` 对应的单版本代码，返回相对路径和 1 起始行号，以便报告引用证据。禁止提供对照版本、diff、标签或答案；不要重做 #3 或检测 Agent。

## 检查与交付

按本轮 issue 验收条件验证目标版本选择、路径/行号和隔离边界。没有课程数据时只用明确标为“非课程数据”的合成样例，不虚构真实结果。最终汇报本轮改动文件、输入输出行为、实际验证命令及结果、需要组长协调的接口问题；跨模块问题交对应唯一负责人。
