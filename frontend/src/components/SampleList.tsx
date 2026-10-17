import type { CSSProperties } from "react";

import { CONDITION_ORDER, summarizeConditions } from "../lib/conditions";
import { idxKey } from "../state/idx";
import { sampleList, type TaskState } from "../state/store";
import { IdxBadge, SampleStatusChip } from "./chips";

interface Props {
  state: TaskState;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

const PREDICTION_LABELS: Record<0 | 1, string> = { 0: "无漏洞", 1: "有漏洞" };

/** 样本列表：每个条目用原类型 idx 定位，整数 1 与字符串 "1" 分开显示。 */
export function SampleList({ state, selectedKey, onSelect }: Props) {
  const samples = sampleList(state);

  return (
    <div className="sample-list">
      <h3 className="section-title">
        样本
        <span className="muted"> {samples.length}</span>
      </h3>
      {samples.length === 0 && <p className="field__hint">等待样本事件。</p>}
      <ul>
        {samples.map((sample, index) => {
          const key = idxKey(sample.idx);
          const counts = summarizeConditions(sample.analysis.conditions);
          // 错峰延迟封顶，长列表不会排队等入场
          return (
            <li key={key} style={{ "--i": Math.min(index, 8) } as CSSProperties}>
              <button
                type="button"
                className={`sample-list__item ${key === selectedKey ? "is-active" : ""}`}
                data-status={sample.status}
                onClick={() => onSelect(key)}
                aria-current={key === selectedKey}
              >
                <IdxBadge idx={sample.idx} />
                <span className="sample-list__meta">
                  <SampleStatusChip status={sample.status} />
                  {sample.prediction !== null && (
                    <span className={`prediction-text prediction-text--${sample.prediction}`}>
                      {PREDICTION_LABELS[sample.prediction]}
                    </span>
                  )}
                </span>
                <span className="sample-list__counts muted">
                  {counts.total} 条件 · {sample.analysis.evidence.length} 证据
                </span>
                {counts.total > 0 && (
                  <span className="mini-bar" aria-hidden="true">
                    {CONDITION_ORDER.map((status) =>
                      counts[status] === 0 ? null : (
                        <span
                          key={status}
                          className={`mini-bar__seg mini-bar__seg--${status}`}
                          style={{ width: `${(counts[status] / counts.total) * 100}%` }}
                        />
                      ),
                    )}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
