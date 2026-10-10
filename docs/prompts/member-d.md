# 成员 D：批量评测与 GitHub Bot

你是 [#7 批量评测与导出](https://github.com/Ars1027/func-vuln-agent/issues/7) 和 [#8 GitHub Bot](https://github.com/Ars1027/func-vuln-agent/issues/8) 的唯一负责人。**本轮只做一个指定 issue**：先完成 #7，再另开一轮处理 #8。未来建议归属 `backend/app/evaluation`、`backend/app/bot`；GitHub 账号待定。

## 必读

先读根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`，`docs/course-requirements.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/team.md`、[提示词公共约束](README.md)、本轮 issue 正文和已有实现。依赖 #1、#5 的实际契约；接口变更交组长 Ars1027 协调。

## 本轮目标与边界

- **若本轮是 #7：**消费组长提供的批量任务/检测结果，执行课程评测并按课程格式导出 `result.jsonl`，每行仅 `idx`、`prediction`；保留可审计的详细报告或其引用。评测标签仅用于隔离的评测逻辑，不得进入 Agent 输入。批量任务调度 API 属组长，不另建一套任务 API；不要顺带实现 Bot。
- **若本轮是 #8：**复用已稳定的检测 API 实现 GitHub Bot 集成。v1 由显式请求给出 `commit_url`、文件路径和函数名，读取该提交的单版本代码；可在 PR 会话回复报告，但不把 PR diff、描述或讨论送入检测模型，也不自动扫描整个 PR。不要通过网络搜索漏洞答案，不要重写 Agent 或批量评测，也不要猜测尚未定义的 GitHub 权限或发布流程。

## 检查与交付

按本轮 issue 验收条件验证。#7 尤其检查 JSONL 行字段严格限定、条目映射与标签隔离；#8 检查实际事件/接口契约与错误路径。若使用合成样例，标明“非课程数据”。最终汇报改动文件、运行方式、实际验证命令与结果、未决权限或接口问题；跨模块问题交对应唯一负责人。
