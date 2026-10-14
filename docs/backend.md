# 后端接口检查点与本地联调

这是 #1 的 M1 接口检查点及 #5 的阶段性交付。课程数据尚未取得；合成样例只验证程序行为，不代表漏洞检测效果。#1 保持开启，待数据核对和 M3 真实集成验收；#5 待接入实际 RAG、版本准备、仓库工具及课程导出模块。

## 安装与运行

在仓库根目录使用 Python 3.11+ 和 uv：

```sh
uv sync --locked
uv run uvicorn app.demo:build_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs` 查看可执行的接口文档。此入口显式使用**合成代码、合成历史记录和脚本模型**，无需 API 密钥、网络或课程数据。脚本模型只为固定样例提供预先安排的工具选择，不用于真实检测；实际 Agent 内核的分支和终止由注入的模型输出决定。

演示批量请求：

```sh
curl -F "file=@examples/synthetic.jsonl" -F "mode=conditions" http://127.0.0.1:8000/api/batches
```

返回 `task_id` 后查询 `/api/tasks/{task_id}`、`/reports`、`/events`、`/measurements`，完成后请求 `/result.jsonl`。样例故意同时使用整数 `1` 和字符串 `"1"`，供 Web 验证类型隔离。所有样例内容来自本项目人工编写，无真实课程记录。

生产适配入口（依赖仍待各负责人接入）：

```sh
uv run uvicorn app.main:build_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

配置清单见根目录 `.env.example`；通过终端设置环境变量，应用不会自动读取 `.env`。`FVA_MODEL` 使用所选模型服务的模型名，密钥仅在本机环境中保存。`OPENAI_BASE_URL` 可指定兼容服务。模型设置和预算由同一 `RunConfig` 提供给三组实验，调用重试不在服务内部隐式追加。无用量信息时 token 字段为 `null`。

`RunConfig` 创建后不可修改。自定义 `Runner` 须暴露实际使用的 `config`；与 `Services` 配置不一致时装配失败，测量返回不同配置时样本执行失败。模型服务支持的 temperature 等参数仍须在实际提供方接入时核对。

`app.main` 的缺失适配器明确返回错误；不会自动使用演示数据。接入后用自己的组合工厂构造 `AgentRunner` 和 `Services`，传给 `create_app`，无需修改检测循环。关闭外部 LangSmith tracing，避免课程函数经观测系统外发。

## 模块交接

共享 Pydantic 类型位于 `backend/app/schemas/models.py`，异步模块协议位于 `backend/app/schemas/ports.py`。

| 负责人 / Issue | 接入协议 | 关键保证 |
| --- | --- | --- |
| 安晟毅 #2 | `Retriever.search_cases(query, limit)` | 只搜索课程历史数据；无匹配为空列表，故障抛 `IntegrationError`；条件关联来源和片段 |
| 史鹏飞 #3 | `Preparation.prepare_course/prepare_snapshot` | 返回 `DetectionInput`，去掉标签、提交及选版语义；函数与快照一致 |
| 史鹏飞 #3/#4 | `Repository.locate_function/search_code/read_file/find_symbol` | 仅当前快照；返回原文和相对位置；拒绝越界路径、Git 元数据及其他版本；快照引用及路径不携带标签 |
| 臧天心 #7 | `ResultExporter.export(input_ids, reports)` | 输出仅有 `idx/prediction` 的完整有序 JSONL；保留标识类型 |
| 周德铭 #6 | HTTP、SSE、`ReportsSnapshot` | 初始快照加 seq 续接，样本内 ID 更新，不合并整数和字符串 idx |

`POST /api/snapshots` 的请求为 `{idx, func, commit_url, revision}`，`revision` 必填，响应为可直接提交检测的 `{idx, func, snapshot_ref}`。单条检测增加可选 `mode`；批量表单字段名为 `file` 和 `mode`。课程 JSONL 暂只接受已确认的四字段，拿到数据后由 #1 核对扩展字段，而不是将未审查的字段传给模型。

准备层不得改变输入的 `idx/func`，API 会核对返回值。默认每批上限为 10 MiB JSONL 内容和 1000 个样本，超限返回 413；可通过应用工厂的 `max_batch_bytes/max_batch_samples` 参数调整。multipart 解析可能先将上传内容暂存到磁盘，公开部署仍需入口层请求大小限制。

仓库结果使用 `RepositoryResult(matches, scope)`，`scope` 记录符号解析或搜索范围。`CodeLocation` 为 `{snapshot_ref,path,start_line,end_line,content}`，行号从 1 起。当前函数通过 `locate_function` 建立可引用代码证据；工具返回的代码和历史材料由运行时分配证据 ID，模型只能引用这些 ID。

Agent 与 `CodeLocation` 使用同一相对路径规则，统一分隔符并拒绝 `.GIT`、`.git.`、`.. ` 等歧义组件。真实仓库工具还必须校验解析链接后的最终路径位于快照内。历史案例按 `case_id` 复用证据，但同一 ID 的来源或正文冲突会明确失败。

`IntegrationError(code, message)` 的消息必须适合向 API 用户展示，不含凭据或准备层标签。模型上下文不含准备层对象、`target`、`commit_url`、`revision`；工具 schema 不允许模型传入或改变快照引用。无真实适配器时不能验收其 Git/文件隔离实现。

## 三组实验与记录

- `function_only`：模型仅见函数，不提供检索、仓库工具或条件更新；可直接作最终判断。
- `rag_context`：原始历史案例与自主仓库工具，不向模型附加提取出的成立/安全条件。
- `conditions`：在同一基础上加入历史条件、漏洞假设、条件更新与反证检查。

`RunConfig` 记录模型、temperature、输出上限、模型/工具调用预算、超时、数据/索引版本和提示词版本。`GET /api/tasks/{task_id}/measurements` 返回每个样本的实际 mode、配置、调用次数、token、耗时和执行状态。工具预算统计定位/检索/读取操作，条件更新及结束调用只消耗模型轮次；三组模式共用预算上限。正式实验须在课程数据到达后固定同一配置及开发/测试划分。

模型通过 `finish` 结束分析，预算耗尽或工具/模型失败返回执行失败；待确认条件不触发自动安全预测。历史证据不能独立支撑 `supported/refuted`。结构校验验证引用与来源；证据是否真正覆盖同一路径及最终二元判断仍由模型分析，需课程评测检验。

提示词版本 `conditions-v2` 将原始函数放在 JSON 的 `source_code` 字段内，并明确其不具备指令权限。合成测试验证消息封装及工具权限，不代表真实模型已免疫提示词注入。未提出漏洞假设时，条件列表仍允许为空，不强制编造条件或固定工具调用。

API 测量的 `elapsed_seconds` 包含准备与分析，成功和失败使用相同口径，不包括排队、结果落库和导出。直接调用 `AgentRunner.run` 时只测量分析阶段。

## 状态、SSE 与恢复

任务、事件、报告、失败和测量保存到 SQLite。默认正式库 `artifacts/tasks.sqlite3`，演示库 `artifacts/demo-tasks.sqlite3`，均受 Git 忽略。状态变更和事件序号在同一事务提交，报告读取返回一致的 `seq`。前端先获取 `/reports`，再连接 `/events?after_seq={seq}`；查询参数优先于 `Last-Event-ID`。终止事件重放后连接结束。

每个样本独立模型会话，批量并发由 `FVA_CONCURRENCY` 控制。批量部分失败仍保留成功报告，整体为 `failed`。导出只接受全量成功任务，按输入顺序交给 #7 适配器，不用 0 补齐失败项。

后台任务发生未处理异常时，先取消并等待同批未完成的子任务，再尝试记录失败状态；已经完成的报告保留。若数据库持续不可写，失败状态可能暂时无法落库，修复存储后重启服务，由中断恢复流程收尾。意外异常日志包含操作、任务/样本标识、异常类型和调用栈位置，不输出异常消息、源码或局部变量；API 继续返回简化错误。

重启时尚处于 `queued/running` 的任务标记为失败，未完成样本记为中断；保留已完成报告和已有分析记录。失败后的部分分析在 `/reports` 的 `failed_samples` 返回，不列为 `active_samples`；前端按原类型 `idx` 关联 `failures`。中断的运行中样本无法恢复的调用次数和耗时记为 `null`，仍在排队而未开始的样本记为 0，配置保留任务创建时的值。不会自动重放模型调用；重新提交原始单条请求或 JSONL 会创建新任务。修改模型或实验配置后也应创建新任务。

本阶段只支持绑定 `127.0.0.1` 的本地单用户、单 Uvicorn worker；不要用 `--workers` 共用该任务库。任务标识不是访问凭证。多人或公开部署前，#5 必须补齐身份验证与任务归属校验（含事件、报告、测量和导出），当前实现不声称支持多人部署。

## 验证与剩余验收

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

自动验证使用合成材料与脚本模型，不调用付费 API。重点覆盖支持证据、反证、未知条件、跨函数上下文、错误与预算、会话隔离、SSE 断线恢复、批量部分失败及进程重启恢复。CI 在 Python 3.11 执行同一组检查。

课程数据到达后仍需核对：实际字段和 idx 类型、配对信息、历史/待测划分、commit_url 形式、父提交规则、函数定位、课程 `evaluate.py`。实际模型连通性与自主分析质量、真实快照工具隔离、Web 联调和三组效果/成本对照尚未验收；本阶段不关闭 #1/#5。
