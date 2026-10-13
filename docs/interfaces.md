# 模块接口约定 v1（M1 检查点）

陈子星维护共享接口，#1 的 M1 检查点确认字段。课程数据接入后核对具体类型和配对方式。

共享可执行类型见 `backend/app/schemas/models.py`，模块接入协议见 `backend/app/schemas/ports.py`；请求示例、错误处理、持久化和剩余依赖见[后端联调说明](backend.md)。

## 1. 输入与版本准备

课程 JSONL 包含 `idx`、`commit_url`、`target`、`func`。`idx` 保留原值，暂按字符串或整数处理。

史鹏飞的准备模块按 `target=1` 取修复提交父版本，按 `target=0` 取修复提交版本。多父提交或函数与快照不一致时返回错误，由 #1 核对数据规则。

Web 单样本输入函数与修复提交链接，明确选择“该提交”或“父提交”，分别传 `revision=commit` 或 `revision=parent`。缺少选择时提示补齐。Bot 的显式提交请求传 `revision=commit`。

| 检测请求字段 | 含义 |
| --- | --- |
| `idx` | 输入样本标识 |
| `func` | 待测 C/C++ 函数 |
| `snapshot_ref` | 单版本快照的不透明引用 |

标签、配对关系和版本选择留在准备/评测层。快照引用、模型可读路径及工具结果不携带这些信息。

## 2. RAG 检索

安晟毅提供 `search_cases(query, limit)`，每条结果包含：

| 字段 | 含义 |
| --- | --- |
| `case_id` | 历史案例标识 |
| `content` | 课程历史记录或代码内容 |
| `source` | 数据文件及记录位置 |
| `trigger_conditions` | 历史漏洞成立条件列表 |
| `safety_conditions` | 历史修复建立的安全条件列表 |

条件项包含 `statement`、`source`、`excerpt`，将总结关联到原始记录及原文片段。材料不足时列表可为空。项目、CVE/CWE 等元信息按课程数据实际内容返回。

索引只使用课程历史数据，可包含历史漏洞/修复对；待测集隔离。无匹配返回空列表，检索失败返回错误。

## 3. 仓库上下文工具

史鹏飞提供以下能力：

| 能力 | 最小输入 | 输出 |
| --- | --- | --- |
| 代码搜索 | `snapshot_ref`、查询文本 | 路径、行号、片段 |
| 文件读取 | `snapshot_ref`、相对路径、行区间 | 原文、路径、起止行号 |
| 定义/调用位置查找 | `snapshot_ref`、符号名称 | 匹配证据及解析范围说明 |

行号从 1 起始，工具绑定当前快照。“未找到”和“读取失败”分别返回。工具负责定位容量、长度来源、边界检查和调用路径等代码，Agent 判断其对条件的支持或反驳关系。

## 4. 检测 API

陈子星负责 API、任务调度与共享类型。

| 接口 | 用途 |
| --- | --- |
| `POST /api/detections` | 提交单条检测请求 |
| `POST /api/batches` | multipart 上传课程 JSONL，经准备层逐条处理 |
| `GET /api/tasks/{task_id}` | 查询状态、完成计数和失败项 |
| `GET /api/tasks/{task_id}/events` | SSE 过程事件 |
| `GET /api/tasks/{task_id}/reports` | 完整报告与失败项 |
| `GET /api/tasks/{task_id}/result.jsonl` | 导出覆盖全部输入的课程结果 |
| `POST /api/snapshots` | 按 `commit_url`、`revision` 准备快照 |
| `GET /api/tasks/{task_id}/measurements` | 查询逐样本实验配置、调用/token/耗时与执行状态 |

快照请求另含 `idx` 和 `func`，响应为可直接提交单条检测的 `idx/func/snapshot_ref`。批量 multipart 上传字段名为 `file`。

创建任务返回 `task_id`，状态为 `queued`、`running`、`completed`、`failed`。批量任务保留已完成报告，含失败项时返回失败状态。

单条请求的 JSON 顶层及批量请求的 multipart 表单均接受可选 `mode`：`function_only`（函数基线）、`rag_context`（课程基础方案）、`conditions`（条件方案，默认值）。`mode` 属于运行配置，由服务选择工具与提示词，不加入样本内容；未知值返回参数错误。任务状态响应回传实际 `mode`，供评测核对。

错误使用 `code`、`message`，按上下文关联 `task_id`、`idx`。参数错误返回 HTTP 422，任务不存在返回 404，结果尚未完整或任务失败导致不可导出返回 409，缺失模块依赖返回 503。异步样本失败保存在任务失败项和 `error` 事件中，不将已接受的任务响应改为同步报错。

## 5. 证据与条件

报告的 `evidence` 为证据列表，每项含唯一 `id`、`kind` 和 `content`。历史证据用 `kind=historical` 并关联 `case_id/source`；代码证据用 `kind=code` 并关联 `snapshot_ref/path/start_line/end_line`。

`hypotheses` 中每项包含 `id` 和 `statement`，表示当前函数的一个漏洞假设。`conditions` 中每项包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 报告内条件标识 |
| `hypothesis_id` | 所属漏洞假设 |
| `statement` | 待核实的漏洞成立条件 |
| `status` | `supported` / `refuted` / `unknown` |
| `evidence_ids` | 引用报告中已有证据的标识列表 |
| `reason` | 状态判断或证据缺口的简述 |

报告条件统一表述为漏洞成立所需的命题。RAG 的 `safety_conditions` 用于引导反证查询，不直接作为同极性的报告条件。例如报告条件为“复制长度可超过剩余容量”，当前路径上的有效长度检查是反驳它的证据；`supported` 始终表示支持漏洞条件。

`supported/refuted` 必须有当前快照的代码证据；待测函数本身也可作为代码证据，由准备层定位。`unknown` 可包含已有片段及尚未解决的问题。历史类比用于提出假设，不单独证明待测条件成立。

条件和假设可随新证据更新。排除一个假设不等于证明函数整体安全，最终判断按 [检测方法](method.md)综合解释。

## 6. SSE 事件

事件类型为 `task_status`、`retrieval`、`repository_read`、`condition_update`、`sample_completed`、`error`、`task_completed`。SSE 的 `event` 为类型，`data` 为 JSON。

公共字段：`task_id`、`seq`、`timestamp`、`type`、`payload`；样本事件含 `idx`。`seq` 在任务内递增，SSE 的 `id` 使用该序号。

报告接口返回 `{task_id, seq, reports, active_samples, failed_samples, failures}`，是截至 `seq` 的一致状态快照。`reports` 为成功完成的完整报告；`active_samples` 包含运行中样本的 `idx`、当前 `hypotheses/conditions/evidence/trace`，尚无最终 `prediction`。`failed_samples` 保留失败或中断样本最后的部分分析，结构与 `active_samples` 相同，失败原因在 `failures` 中按原类型 `idx` 关联。UI 收到 `error` 时将对应样本从运行中移到失败状态，保留已有分析。任务仍可查询期间，事件接口支持 `after_seq`（首次连接默认 0）或 `Last-Event-ID`，先重放该序号之后的事件，再连续推送新事件；两者同时提供时以 `after_seq` 为准。

初次加载或重连时，UI 读取报告快照，再从其 `seq` 订阅事件。UI 只应用比本地已应用序号更新的事件；迟到且 `seq` 更小的快照不覆盖当前状态。这样可恢复进行中的分析，并避免重连时回滚状态。

- 检索事件：查询、案例标识和来源摘要。
- 仓库事件：工具、参数、路径/行号和结果摘要。
- 条件事件：本次变化的 `hypotheses`、`conditions` 和所引用的 `evidence` 项；UI 先按 `task_id`、原类型的 `idx` 定位样本，再在各列表内按 `id` 更新。不同样本可使用相同局部 ID，整数 `1` 与字符串 `"1"` 不合并。
- 完成/错误事件：报告关联或失败原因。

展示操作、证据与判断摘要。最终报告提供完整状态，供界面重新加载。

## 7. 完整报告与导出

完整报告包含 `idx`、`prediction`、`reason`、`hypotheses`、`conditions`、`evidence`、`trace`。`trace` 保留按序排列的检索和仓库操作记录。未提出假设或基础实验模式下，假设/条件列表可为空。

成功检测的 `prediction` 是整数 0 或 1。条件待确认属于分析状态，理由说明其影响；执行失败单独返回错误，不能补为 0。

课程 `result.jsonl` 仅含 `idx`、`prediction`，保持输入顺序和标识类型。导出前核对标识唯一、结果完整、预测合法；缺失、重复或执行失败时返回原因。

臧天心的评测模块接收该文件和课程数据，按提供的脚本配对评分。标签只用于准备与评测。

## 8. 实验配置与测量

#5 提供函数基线、课程基础方案和条件方案三种实验配置，#7 通过创建任务时的 `mode` 选择，并核对响应中的实际模式。正式 Web/Bot 使用 `conditions`。

每次运行记录模式、模型与解码设置、数据/索引版本、运行预算、工具调用次数、token 用量、耗时和执行状态。服务未返回的用量标为缺失。进程中断后无法恢复的调用次数和耗时为 `null`，未开始的排队样本这些值为 0，不将未知成本计作 0。工具次数包含函数定位和检索/仓库操作，不含 `update_conditions/finish` 控制调用；全部模型轮次仍受模型调用预算约束。测量信息单独保存，课程导出保持两字段格式。
