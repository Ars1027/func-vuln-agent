import type {
  AnalysisState,
  Condition,
  ConditionStatus,
  EventEnvelope,
  Evidence,
  Failure,
  Hypothesis,
  Idx,
  Mode,
  Report,
  ReportsSnapshot,
  TaskStatus,
  TaskView,
  TraceEntry,
} from "../api/types";
import { idxKey } from "./idx";

export type SampleStatus = "running" | "completed" | "failed";

export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export interface SampleState {
  idx: Idx;
  status: SampleStatus;
  analysis: AnalysisState;
  prediction: 0 | 1 | null;
  reason: string | null;
  failure: Failure | null;
}

export interface TaskState {
  taskId: string | null;
  /** 已应用的最后一个事件序号；比它旧的事件与快照一律忽略。 */
  seq: number;
  status: TaskStatus | "idle";
  mode: Mode | null;
  total: number;
  order: string[];
  samples: Record<string, SampleState>;
  failures: Failure[];
  /** idx 为空的 error 事件，属于任务级错误。 */
  taskError: { code: string; message: string } | null;
  connection: ConnectionState;
  notice: string | null;
}

export type TaskAction =
  | { type: "reset" }
  | { type: "task_view"; view: TaskView }
  | { type: "snapshot"; snapshot: ReportsSnapshot }
  | { type: "event"; event: EventEnvelope }
  | { type: "connection"; connection: ConnectionState }
  | { type: "notice"; notice: string | null };

// --- 载荷规范化：payload 是 dict[str, Any]，读取前先做最小校验。 ---

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asIdx(value: unknown): Idx | null {
  if (typeof value === "number" || typeof value === "string") {
    return value;
  }
  return null;
}

const CONDITION_STATUSES: readonly ConditionStatus[] = ["supported", "refuted", "unknown"];

function toHypotheses(value: unknown): Hypothesis[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: Hypothesis[] = [];
  for (const item of value) {
    if (isRecord(item) && typeof item.id === "string" && typeof item.statement === "string") {
      result.push({ id: item.id, statement: item.statement });
    }
  }
  return result;
}

function toConditions(value: unknown): Condition[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: Condition[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.id !== "string") {
      continue;
    }
    const status = item.status;
    if (typeof status !== "string" || !CONDITION_STATUSES.includes(status as ConditionStatus)) {
      continue;
    }
    result.push({
      id: item.id,
      hypothesis_id: asString(item.hypothesis_id),
      statement: asString(item.statement),
      status: status as ConditionStatus,
      evidence_ids: asStringArray(item.evidence_ids),
      reason: asString(item.reason),
    });
  }
  return result;
}

function toEvidence(value: unknown): Evidence[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: Evidence[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.id !== "string") {
      continue;
    }
    if (item.kind === "code") {
      result.push({
        id: item.id,
        kind: "code",
        snapshot_ref: asString(item.snapshot_ref),
        path: asString(item.path),
        start_line: typeof item.start_line === "number" ? item.start_line : 1,
        end_line: typeof item.end_line === "number" ? item.end_line : 1,
        content: asString(item.content),
      });
    } else if (item.kind === "historical") {
      result.push({
        id: item.id,
        kind: "historical",
        content: asString(item.content),
        case_id: asString(item.case_id),
        source: asString(item.source),
      });
    }
  }
  return result;
}

function toTrace(value: unknown): TraceEntry[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: TraceEntry[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.tool !== "string") {
      continue;
    }
    result.push({
      tool: item.tool,
      arguments: isRecord(item.arguments) ? item.arguments : {},
      summary: asString(item.summary),
      evidence_ids: asStringArray(item.evidence_ids),
    });
  }
  return result;
}

function toAnalysis(value: unknown): AnalysisState {
  const source = isRecord(value) ? value : {};
  return {
    hypotheses: toHypotheses(source.hypotheses),
    conditions: toConditions(source.conditions),
    evidence: toEvidence(source.evidence),
    trace: toTrace(source.trace),
  };
}

function toFailures(value: unknown): Failure[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const result: Failure[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    const idx = asIdx(item.idx);
    if (idx === null) {
      continue;
    }
    result.push({ idx, code: asString(item.code), message: asString(item.message) });
  }
  return result;
}

export function emptyAnalysis(): AnalysisState {
  return { hypotheses: [], conditions: [], evidence: [], trace: [] };
}

/** 与后端 store._merge_by_id 一致：按 id 覆盖或追加，保持既有顺序。 */
function mergeById<T extends { id: string }>(previous: T[], changes: T[]): T[] {
  if (changes.length === 0) {
    return previous;
  }
  const positions = new Map(previous.map((item, position) => [item.id, position]));
  const result = [...previous];
  for (const item of changes) {
    const position = positions.get(item.id);
    if (position === undefined) {
      positions.set(item.id, result.length);
      result.push(item);
    } else {
      result[position] = item;
    }
  }
  return result;
}

export function createInitialTaskState(): TaskState {
  return {
    taskId: null,
    seq: 0,
    status: "idle",
    mode: null,
    total: 0,
    order: [],
    samples: {},
    failures: [],
    taskError: null,
    connection: "idle",
    notice: null,
  };
}

function createSample(idx: Idx, status: SampleStatus): SampleState {
  return {
    idx,
    status,
    analysis: emptyAnalysis(),
    prediction: null,
    reason: null,
    failure: null,
  };
}

/** 取回样本；不存在时按需要新建并登记顺序。 */
function withSample(
  state: TaskState,
  idx: Idx,
  status: SampleStatus = "running",
): { samples: Record<string, SampleState>; order: string[]; key: string } {
  const key = idxKey(idx);
  if (state.samples[key]) {
    return { samples: state.samples, order: state.order, key };
  }
  return {
    samples: { ...state.samples, [key]: createSample(idx, status) },
    order: [...state.order, key],
    key,
  };
}

function updateSample(
  state: TaskState,
  key: string,
  patch: Partial<SampleState>,
): Record<string, SampleState> {
  const current = state.samples[key];
  if (!current) {
    return state.samples;
  }
  return { ...state.samples, [key]: { ...current, ...patch } };
}

function traceFromRetrieval(payload: Record<string, unknown>): TraceEntry {
  const query = asString(payload.query);
  const limit = payload.limit;
  return {
    tool: "search_cases",
    arguments: typeof limit === "number" ? { query, limit } : { query },
    summary: asString(payload.summary),
    evidence_ids: asStringArray(payload.evidence_ids),
  };
}

function traceFromRepository(payload: Record<string, unknown>): TraceEntry {
  return {
    tool: asString(payload.tool, "repository"),
    arguments: isRecord(payload.arguments) ? payload.arguments : {},
    summary: asString(payload.summary),
    evidence_ids: asStringArray(payload.evidence_ids),
  };
}

function appendFailure(failures: Failure[], failure: Failure): Failure[] {
  const key = idxKey(failure.idx);
  const rest = failures.filter((item) => idxKey(item.idx) !== key);
  return [...rest, failure];
}

/** 用报告快照整体重建样本状态；seq 不早于本地时快照权威。 */
function applySnapshot(state: TaskState, snapshot: ReportsSnapshot): TaskState {
  if (state.taskId !== null && state.taskId !== snapshot.task_id) {
    return state;
  }
  if (state.taskId !== null && snapshot.seq < state.seq) {
    // 迟到且更旧的快照不覆盖当前状态。
    return state;
  }
  const samples: Record<string, SampleState> = {};
  const order: string[] = [];
  const push = (sample: SampleState) => {
    const key = idxKey(sample.idx);
    if (!samples[key]) {
      order.push(key);
    }
    samples[key] = sample;
  };
  for (const report of snapshot.reports as Report[]) {
    push({
      idx: report.idx,
      status: "completed",
      analysis: toAnalysis(report),
      prediction: report.prediction,
      reason: report.reason,
      failure: null,
    });
  }
  for (const active of snapshot.active_samples) {
    push({ ...createSample(active.idx, "running"), analysis: toAnalysis(active) });
  }
  for (const failed of snapshot.failed_samples) {
    push({ ...createSample(failed.idx, "failed"), analysis: toAnalysis(failed) });
  }
  const failures = toFailures(snapshot.failures);
  for (const failure of failures) {
    const key = idxKey(failure.idx);
    const sample = samples[key];
    if (sample) {
      samples[key] = { ...sample, failure };
    } else {
      // 服务重启后 abort() 会给没有 active_json 的排队输入只留下 failures 记录，
      // 没有对应的 failed_samples；这里补一个失败态样本，避免漏项与失败计数偏小。
      push({ ...createSample(failure.idx, "failed"), failure });
    }
  }
  return {
    ...state,
    taskId: snapshot.task_id,
    seq: snapshot.seq,
    samples,
    order,
    failures,
  };
}

export function taskReducer(state: TaskState, action: TaskAction): TaskState {
  switch (action.type) {
    case "reset":
      return createInitialTaskState();

    case "task_view": {
      const view = action.view;
      if (state.taskId !== null && state.taskId !== view.task_id) {
        // 切换到另一个任务时重建状态，只保留尚未建立的连接标记。
        return { ...createInitialTaskState(), ...viewToState(view), connection: "connecting" };
      }
      return {
        ...state,
        taskId: view.task_id,
        status: view.status,
        mode: view.mode,
        total: view.total,
        failures: view.failures,
      };
    }

    case "snapshot":
      return applySnapshot(state, action.snapshot);

    case "connection":
      return state.connection === action.connection
        ? state
        : { ...state, connection: action.connection };

    case "notice":
      return { ...state, notice: action.notice };

    case "event":
      return applyEvent(state, action.event);

    default:
      return state;
  }
}

function viewToState(view: TaskView): Partial<TaskState> {
  return {
    taskId: view.task_id,
    status: view.status,
    mode: view.mode,
    total: view.total,
    failures: view.failures,
  };
}

function applyEvent(state: TaskState, event: EventEnvelope): TaskState {
  if (state.taskId !== null && event.task_id !== state.taskId) {
    return state;
  }
  if (event.seq <= state.seq) {
    // 重连重放或重复推送：同一个任务内序号单调递增。
    return state;
  }
  const base: TaskState = { ...state, taskId: event.task_id, seq: event.seq };
  const payload = isRecord(event.payload) ? event.payload : {};

  switch (event.type) {
    case "task_status": {
      const status = asString(payload.status);
      if (status !== "queued" && status !== "running" && status !== "completed" && status !== "failed") {
        return base;
      }
      const mode = typeof payload.mode === "string" ? (payload.mode as Mode) : base.mode;
      return { ...base, status, mode };
    }

    case "task_completed": {
      const status = asString(payload.status);
      const next = status === "completed" || status === "failed" ? status : base.status;
      return { ...base, status: next, connection: "closed" };
    }

    case "condition_update": {
      const idx = asIdx(event.idx);
      if (idx === null) {
        return base;
      }
      const { samples, order, key } = withSample(base, idx);
      const current = samples[key];
      return {
        ...base,
        samples: {
          ...samples,
          [key]: {
            ...current,
            analysis: {
              hypotheses: mergeById(current.analysis.hypotheses, toHypotheses(payload.hypotheses)),
              conditions: mergeById(current.analysis.conditions, toConditions(payload.conditions)),
              evidence: mergeById(current.analysis.evidence, toEvidence(payload.evidence)),
              trace: current.analysis.trace,
            },
          },
        },
        order,
      };
    }

    case "retrieval":
    case "repository_read": {
      const idx = asIdx(event.idx);
      if (idx === null) {
        return base;
      }
      const { samples, order, key } = withSample(base, idx);
      const current = samples[key];
      const entry =
        event.type === "retrieval" ? traceFromRetrieval(payload) : traceFromRepository(payload);
      return {
        ...base,
        samples: {
          ...samples,
          [key]: {
            ...current,
            analysis: { ...current.analysis, trace: [...current.analysis.trace, entry] },
          },
        },
        order,
      };
    }

    case "sample_completed": {
      const report = payload.report;
      if (!isRecord(report)) {
        return base;
      }
      const idx = asIdx(report.idx);
      if (idx === null) {
        return base;
      }
      const prediction = report.prediction === 1 ? 1 : report.prediction === 0 ? 0 : null;
      if (prediction === null) {
        return base;
      }
      const analysis = toAnalysis(report);
      const { samples, order, key } = withSample(base, idx);
      return {
        ...base,
        samples: {
          ...samples,
          [key]: {
            idx,
            status: "completed",
            analysis,
            prediction,
            reason: asString(report.reason),
            failure: null,
          },
        },
        order,
        failures: base.failures.filter((item) => idxKey(item.idx) !== key),
      };
    }

    case "error": {
      const idx = asIdx(event.idx);
      const code = asString(payload.code, "unknown_error");
      const message = asString(payload.message, "分析失败。");
      if (idx === null) {
        return { ...base, taskError: { code, message } };
      }
      const { samples, order, key } = withSample(base, idx);
      const failure: Failure = { idx, code, message };
      return {
        ...base,
        samples: updateSample({ ...base, samples }, key, { status: "failed", failure }),
        order,
        failures: appendFailure(base.failures, failure),
      };
    }

    default:
      return base;
  }
}

// --- 选择器 ---

export function sampleList(state: TaskState): SampleState[] {
  return state.order
    .map((key) => state.samples[key])
    .filter((sample): sample is SampleState => sample !== undefined);
}

export interface TaskProgress {
  total: number;
  completed: number;
  failed: number;
  running: number;
}

export function taskProgress(state: TaskState): TaskProgress {
  let completed = 0;
  let failed = 0;
  let running = 0;
  for (const sample of sampleList(state)) {
    if (sample.status === "completed") {
      completed += 1;
    } else if (sample.status === "failed") {
      failed += 1;
    } else {
      running += 1;
    }
  }
  return { total: state.total, completed, failed, running };
}

export function findEvidence(sample: SampleState, evidenceId: string): Evidence | undefined {
  return sample.analysis.evidence.find((item) => item.id === evidenceId);
}

export function conditionsByHypothesis(sample: SampleState): Array<{
  hypothesis: Hypothesis;
  conditions: Condition[];
}> {
  const { hypotheses, conditions } = sample.analysis;
  const groups = hypotheses.map((hypothesis) => ({
    hypothesis,
    conditions: conditions.filter((condition) => condition.hypothesis_id === hypothesis.id),
  }));
  const known = new Set(hypotheses.map((hypothesis) => hypothesis.id));
  // 事件可能先带来条件再带来假设；未匹配的按 hypothesis_id 单独分组，不丢弃。
  const orphanIds = [...new Set(conditions.map((c) => c.hypothesis_id).filter((id) => !known.has(id)))];
  for (const id of orphanIds) {
    groups.push({
      hypothesis: { id, statement: "未在当前假设列表中（等待 condition_update 补充）" },
      conditions: conditions.filter((condition) => condition.hypothesis_id === id),
    });
  }
  return groups;
}
