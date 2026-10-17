import { CONDITION_STATUS_LABELS, type ConditionStatus, type Idx, type TaskStatus } from "../api/types";
import { idxKindLabel, idxLabel } from "../state/idx";
import type { SampleStatus } from "../state/store";

const TASK_STATUS_LABELS: Record<TaskStatus | "idle", string> = {
  idle: "未开始",
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  failed: "失败",
};

const SAMPLE_STATUS_LABELS: Record<SampleStatus, string> = {
  running: "分析中",
  completed: "已完成",
  failed: "失败",
};

/** 样本标识：同时显示类型，避免整数 1 与字符串 "1" 被看成一个样本。 */
export function IdxBadge({ idx }: { idx: Idx }) {
  return (
    <span className="idx-badge" title={`样本标识，类型：${idxKindLabel(idx)}`}>
      <span className="idx-badge__value">{idxLabel(idx)}</span>
      <span className="idx-badge__kind">{idxKindLabel(idx)}</span>
    </span>
  );
}

export function TaskStatusChip({ status }: { status: TaskStatus | "idle" }) {
  return <span className={`chip chip--task chip--${status}`}>{TASK_STATUS_LABELS[status]}</span>;
}

export function SampleStatusChip({ status }: { status: SampleStatus }) {
  return <span className={`chip chip--${status}`}>{SAMPLE_STATUS_LABELS[status]}</span>;
}

export function ConditionStatusChip({ status }: { status: ConditionStatus }) {
  return (
    <span className={`chip chip--condition chip--${status}`}>
      {CONDITION_STATUS_LABELS[status]}
    </span>
  );
}

export function PredictionChip({ prediction }: { prediction: 0 | 1 | null }) {
  if (prediction === null) {
    return <span className="chip chip--pending">尚无判定</span>;
  }
  return (
    <span className={`chip chip--prediction chip--prediction-${prediction}`}>
      {prediction === 1 ? "判定有漏洞（1）" : "判定无漏洞（0）"}
    </span>
  );
}
