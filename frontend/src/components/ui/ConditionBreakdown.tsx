import type { Condition } from "../../api/types";
import { CONDITION_ORDER, summarizeConditions } from "../../lib/conditions";

interface Props {
  conditions: Condition[];
}

const LABELS: Record<(typeof CONDITION_ORDER)[number], string> = {
  supported: "支持成立",
  unknown: "待确认",
  refuted: "已被反证",
};

/**
 * 条件构成概览：一眼看出这个样本的条件是“被支持”“待确认”还是“被反证”。
 * 单个条件被反证只否定对应假设，因此这里只做计数，不合成结论。
 */
export function ConditionBreakdown({ conditions }: Props) {
  const counts = summarizeConditions(conditions);
  if (counts.total === 0) {
    return null;
  }

  return (
    <div className="breakdown">
      <div className="breakdown__bar" aria-hidden="true">
        {CONDITION_ORDER.map((status) =>
          counts[status] === 0 ? null : (
            <span
              key={status}
              className={`breakdown__seg breakdown__seg--${status}`}
              style={{ width: `${(counts[status] / counts.total) * 100}%` }}
            />
          ),
        )}
      </div>
      <ul className="breakdown__legend">
        {CONDITION_ORDER.map((status) => (
          <li key={status} className={`breakdown__item breakdown__item--${status}`}>
            <span className="breakdown__dot" aria-hidden="true" />
            <span className="breakdown__label">{LABELS[status]}</span>
            <span className="breakdown__count">{counts[status]}</span>
          </li>
        ))}
        <li className="breakdown__item breakdown__item--total">
          <span className="breakdown__label">条件总数</span>
          <span className="breakdown__count">{counts.total}</span>
        </li>
      </ul>
    </div>
  );
}
