import type { Condition, ConditionStatus } from "../api/types";

export interface ConditionCounts {
  total: number;
  supported: number;
  refuted: number;
  unknown: number;
}

/** 状态展示顺序：支持成立 → 待确认 → 已被反证。 */
export const CONDITION_ORDER: ConditionStatus[] = ["supported", "unknown", "refuted"];

/** 条件状态计数，供概览条与样本列表共用，避免两处各写一遍规则。 */
export function summarizeConditions(conditions: Condition[]): ConditionCounts {
  const counts: ConditionCounts = { total: conditions.length, supported: 0, refuted: 0, unknown: 0 };
  for (const condition of conditions) {
    counts[condition.status] += 1;
  }
  return counts;
}
