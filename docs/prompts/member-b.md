# 史鹏飞：快照与代码证据

你是史鹏飞的编码 Agent，本轮处理指定的 #3 或 #4。阅读 AGENTS.md、issue、docs/interfaces.md、docs/method.md 和已有实现。代码归属 backend/app/repository。

## #3 快照准备

按课程 target 选择对应版本；Web 使用明确的 revision=commit/parent，Bot 定点请求用 revision=commit。准备层输出 idx、func、snapshot_ref，并能定位待测函数在快照中的路径和行号，供后续引用。

验证选版、函数与快照一致性及获取失败。标签和版本选择信息留在准备层，工具只读取当前快照。

## #4 证据工具

实现搜索、按行读取和定义/调用位置查询，覆盖容量、长度来源、边界检查、调用路径等取证需要。返回当前快照相对路径、1 起始行号、原文与操作记录；条件状态由 Agent 判定。

验证跨函数边界检查定位、相似符号、未匹配、读取失败及快照边界。

交付当前 issue 的 PR，说明接口、验证结果和依赖问题。
