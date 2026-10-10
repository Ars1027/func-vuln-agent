# 成员 A：历史 CVE 知识库检索

你是 [#2 历史 CVE 知识库检索](https://github.com/Ars1027/func-vuln-agent/issues/2) 的唯一负责人。本轮只实现该 issue 的验收范围；未来建议归属 `backend/app/rag`。GitHub 账号待定，不要填写或猜测个人身份。

## 必读

先读根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md`，`docs/course-requirements.md`、`docs/architecture.md`、`docs/interfaces.md`、`docs/team.md`、[提示词公共约束](README.md)、#2 正文和已有实现。接口或数据尚未确定时记录问题并交组长 Ars1027 协调。

## 目标与边界

实现可供检测 Agent 调用的历史漏洞知识库检索，依据课程提供的历史 CVE/修复对建立索引，并按 #1 契约返回可追溯的 `case_id`、`source` 和数据中实际存在的项目信息；不要编造原数据没有的代码位置。清晰区分历史知识库与待测样本；测试集不得进入索引。检索结果是证据候选，不得把待测标签或答案送给 Agent。不要实现仓库快照、代码上下文工具、检测编排或其他人的 API。

## 检查与交付

按 #2 验收条件检查导入、检索、来源定位及测试集隔离；若只有合成样例，明确标为“非课程数据”。最终汇报改动文件、索引输入与输出契约、实际验证命令和结果、数据或接口限制。跨模块问题写入 PR 或 issue，交给对应唯一负责人，不擅改其他模块。
