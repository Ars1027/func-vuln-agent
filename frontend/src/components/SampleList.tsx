import type { CSSProperties } from "react";

import { CONDITION_ORDER, summarizeConditions } from "../lib/conditions";
import { idxKey } from "../state/idx";
import { sampleList, type SampleState, type TaskState } from "../state/store";
import { IdxBadge, SampleStatusChip } from "./chips";

interface Props {
  state: TaskState;
  samplesOverride?: SampleState[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

const PREDICTION_LABELS: Record<0 | 1, string> = { 0: "无漏洞", 1: "有漏洞" };

/** 样本列表：每个条目用原类型 idx 定位，整数 1 与字符串 "1" 分开显示。 */
export function SampleList({ state, samplesOverride, selectedKey, onSelect }: Props) {
  const allSamples = sampleList(state);
  const samples = samplesOverride ?? allSamples;

  return (
    <div className="sample-list">
      <h3 className="section-title">
        样本
        <span className="muted">
          {" "}
          {samples.length === allSamples.length
            ? allSamples.length
            : `${samples.length}/${allSamples.length}`}
        </span>
      </h3>
      {samples.length === 0 && (
        <p className="field__hint">
          {allSamples.length === 0 ? "等待样本事件。" : "当前筛选条件下没有匹配样本。"}
        </p>
      )}
      <ul>
        {samples.map((sample, index) => {
          const key = idxKey(sample.idx);
          const counts = summarizeConditions(sample.analysis.conditions);
          return (
            <li key={key} style={{ "--i": Math.min(index, 8) } as CSSProperties}>
              <button
                type="button"
                className={`sample-list__item ${key === selectedKey ? "is-active" : ""}`}
                data-status={sample.status}
                onClick={() => onSelect(key)}
                aria-current={key === selectedKey}
              >
                <div className="flex items-center justify-between gap-2">
                  <IdxBadge idx={sample.idx} />
                  {sample.prediction !== null && (
                    <span className={`prediction-text prediction-text--${sample.prediction}`}>
                      {PREDICTION_LABELS[sample.prediction]}
                    </span>
                  )}
                </div>
                <span className="sample-list__meta">
                  <SampleStatusChip status={sample.status} />
                  <span className="sample-list__counts muted">
                    {counts.total} 条件 · {sample.analysis.evidence.length} 证据
                  </span>
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
