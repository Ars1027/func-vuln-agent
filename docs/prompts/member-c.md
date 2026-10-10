# 成员 C：Web 界面

你是 [#6 Web 界面](https://github.com/Ars1027/func-vuln-agent/issues/6) 的唯一负责人。本轮只处理 #6，未来建议归属 `frontend/`，技术路线为 React/TypeScript。GitHub 账号待定。

## 必读

先读根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`，`docs/course-requirements.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/team.md`、[提示词公共约束](README.md)、#6 正文和已有实现。先核对 #1、#5 的实际 API/SSE 契约；接口缺口交组长 Ars1027 协调。

## 目标与边界

实现用户提交单函数任务或上传批量 `.jsonl`、观察 SSE 任务状态/检索/代码读取/错误事件、查看包含 `idx`、`prediction`、`reason`、`evidence`、`trace` 的详细报告，并提供课程结果下载入口。单样本接收函数及修复提交链接，要求明确选择“该提交”或“父提交”，通过准备接口传 `revision=commit/parent`，不向 Agent 传该选择或标签。界面只呈现后端提供的待测信息和证据，不制造修复前后对照或 diff，也不自行推断检测结论。不要实现后端 Agent、RAG、仓库工具或批量评测；必要的契约问题交组长处理。

## 检查与交付

按 #6 验收条件验证提交、事件过程、错误处理与报告呈现；模拟数据须标“非课程数据”。最终汇报改动文件、用户可见行为、实际构建/测试命令与结果、依赖的接口和未决问题。跨模块问题交对应唯一负责人，不擅改其他模块。
