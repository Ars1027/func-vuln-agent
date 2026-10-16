# 史鹏飞：评测与 GitHub Bot

你是史鹏飞的编码 Agent，本轮处理指定的 #7 或 #8，按先评测后 Bot 的顺序推进。阅读 AGENTS.md、issue、docs/interfaces.md、docs/method.md 和已有实现。

## #7 评测

在 backend/app/evaluation 中消费检测 API 的报告，导出仅含 idx/prediction 的 JSONL，并核对课程配对与评分规则。检查完整性、重复标识、失败项和降级阈值。

创建任务时通过 mode=function_only、rag_context、conditions 执行三组对照，并核对返回的实际模式。固定模型、样本和预算等配置，统计成对指标、误报/漏报、工具调用、token 和耗时。开发样本用于调试，最终测试前固定配置，报告实际差异及典型案例。任务调度与模式支持由 #5 提供。

## #8 Bot

M3 验收后，在 backend/app/bot 中接入显式提交、文件和函数请求，复用准备层与检测 API，在 GitHub 回复判定、关键条件证据和报告入口。模型仅接收指定版本的函数及上下文。

验证触发到回复、重复事件、权限失败与检测失败，写明本地调试方式和持续在线部署所需配置。

交付当前 issue 的 PR，说明运行方式、验证结果和剩余依赖。
