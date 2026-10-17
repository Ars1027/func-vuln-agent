/**
 * 与 backend/app/schemas/models.py 对应的共享类型。
 * 前端不重新定义语义，字段名和取值以 docs/interfaces.md 为准。
 */

/** 样本标识：JSON 整数 1 与字符串 "1" 是不同的样本，不能合并。 */
export type Idx = number | string;

export type Mode = "function_only" | "rag_context" | "conditions";

export const MODES: readonly Mode[] = ["conditions", "rag_context", "function_only"];

export const MODE_LABELS: Record<Mode, string> = {
  conditions: "条件方案（默认）",
  rag_context: "课程基础方案（RAG）",
  function_only: "函数基线",
};

export type TaskStatus = "queued" | "running" | "completed" | "failed";

export type EventType =
  | "task_status"
  | "retrieval"
  | "repository_read"
  | "condition_update"
  | "sample_completed"
  | "error"
  | "task_completed";

export type ConditionStatus = "supported" | "refuted" | "unknown";

/** 报告中的条件统一表述为漏洞成立所需的命题，therefore supported 始终表示支持漏洞条件。 */
export const CONDITION_STATUS_LABELS: Record<ConditionStatus, string> = {
  supported: "有支持证据",
  refuted: "有反证",
  unknown: "待确认",
};

export interface DetectionInput {
  idx: Idx;
  func: string;
  snapshot_ref: string;
}

export interface DetectionRequest extends DetectionInput {
  mode: Mode;
}

export interface SnapshotRequest {
  idx: Idx;
  func: string;
  commit_url: string;
  revision: "commit" | "parent";
}

export interface Hypothesis {
  id: string;
  statement: string;
}

export interface Condition {
  id: string;
  hypothesis_id: string;
  statement: string;
  status: ConditionStatus;
  evidence_ids: string[];
  reason: string;
}

export interface CodeEvidence {
  id: string;
  kind: "code";
  snapshot_ref: string;
  path: string;
  start_line: number;
  end_line: number;
  content: string;
}

export interface HistoricalEvidence {
  id: string;
  kind: "historical";
  content: string;
  case_id: string;
  source: string;
}

export type Evidence = CodeEvidence | HistoricalEvidence;

export interface TraceEntry {
  tool: string;
  arguments: Record<string, unknown>;
  summary: string;
  evidence_ids: string[];
}

export interface AnalysisState {
  hypotheses: Hypothesis[];
  conditions: Condition[];
  evidence: Evidence[];
  trace: TraceEntry[];
}

export interface Report extends AnalysisState {
  idx: Idx;
  prediction: 0 | 1;
  reason: string;
}

export interface ActiveSample extends AnalysisState {
  idx: Idx;
}

export interface Failure {
  idx: Idx;
  code: string;
  message: string;
}

export interface RunConfig {
  model: string;
  temperature: number;
  max_output_tokens: number;
  max_model_calls: number;
  max_tool_calls: number;
  timeout_seconds: number;
  data_version: string | null;
  index_version: string | null;
  prompt_version: string;
}

export interface Measurement {
  idx: Idx;
  mode: Mode;
  config: RunConfig;
  model_calls: number | null;
  tool_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  elapsed_seconds: number | null;
  status: "completed" | "failed";
}

export interface ReportsSnapshot {
  task_id: string;
  seq: number;
  reports: Report[];
  active_samples: ActiveSample[];
  failed_samples: ActiveSample[];
  failures: Failure[];
}

export interface TaskView {
  task_id: string;
  status: TaskStatus;
  mode: Mode;
  total: number;
  completed: number;
  failures: Failure[];
}

/** SSE 事件的公共信封：`event` 为类型，`data` 为该对象的 JSON。 */
export interface EventEnvelope {
  task_id: string;
  seq: number;
  timestamp: string;
  type: EventType;
  payload: Record<string, unknown>;
  idx?: Idx | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  task_id?: string;
  idx?: Idx;
}

/** 所有任务事件类型，用于逐个注册 EventSource 监听器。 */
export const EVENT_TYPES: readonly EventType[] = [
  "task_status",
  "retrieval",
  "repository_read",
  "condition_update",
  "sample_completed",
  "error",
  "task_completed",
];
