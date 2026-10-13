# 安晟毅：历史条件与 RAG

你是安晟毅的编码 Agent，本轮完成 #2。阅读 AGENTS.md、issue、docs/interfaces.md、docs/method.md 和已有实现。

在 backend/app/rag 中整理课程历史漏洞/修复对，提取漏洞成立条件与修复建立的安全条件，为每项保留来源和原文片段。材料不足时保留空列表。待测集与索引隔离。

实现 search_cases(query, limit)，返回原始内容、案例标识、来源、trigger_conditions 和 safety_conditions。索引与嵌入方案在课程约束内选择，并记录接入方法。

验证条件可追溯、检索结果格式、空结果和索引/读取失败。使用合成样例联调时注明来源。

交付 PR，说明数据处理、接口、实际验证结果和未解决依赖。
