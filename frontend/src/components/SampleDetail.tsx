import { useEffect, useMemo, useState } from "react";

import type { Mode } from "../api/types";
import { idxKey } from "../state/idx";
import type { SampleState } from "../state/store";
import { ErrorNotice } from "./ErrorNotice";
import { EvidenceList } from "./EvidenceList";
import { HypothesisGroups } from "./HypothesisGroups";
import { TraceList } from "./TraceList";
import { IdxBadge, PredictionChip, SampleStatusChip } from "./chips";
import { ConditionBreakdown } from "./ui/ConditionBreakdown";

interface Props {
  sample: SampleState;
  mode: Mode | null;
}

export function SampleDetail({ sample, mode }: Props) {
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const sampleKey = idxKey(sample.idx);

  // 切换样本时清空证据选择，避免把上一个样本的引用带到当前样本。
  useEffect(() => {
    setSelectedEvidenceId(null);
  }, [sampleKey]);

  const referencedIds = useMemo(
    () => new Set(sample.analysis.conditions.flatMap((condition) => condition.evidence_ids)),
    [sample.analysis.conditions],
  );

  const selectEvidence = (id: string) => setSelectedEvidenceId(id);

  return (
    // key 随样本变化，切换样本时重放入场动画。
    <div className="sample-detail" key={sampleKey}>
      <header className="sample-detail__head">
        <IdxBadge idx={sample.idx} />
        <SampleStatusChip status={sample.status} />
        <PredictionChip prediction={sample.prediction} />
      </header>

      <ConditionBreakdown conditions={sample.analysis.conditions} />

      {sample.status === "completed" && (
        <div className={`verdict verdict--${sample.prediction}`}>
          <h3 className="section-title">判定理由</h3>
          <p className="verdict__reason">{sample.reason}</p>
        </div>
      )}

      {sample.status === "failed" && (
        <div className="verdict verdict--failed">
          <ErrorNotice
            title="该样本执行失败"
            code={sample.failure?.code ?? "unknown_error"}
            message={sample.failure?.message ?? "分析未完成。"}
          />
          <p className="field__hint">
            失败不补成 <code>prediction=0</code>；下方保留失败前已到达的分析状态。
          </p>
        </div>
      )}

      {sample.status === "running" && (
        <p className="notice notice--info">
          分析进行中，以下内容随 <code>condition_update</code> 与仓库读取事件实时更新。
        </p>
      )}

      <HypothesisGroups
        sample={sample}
        mode={mode}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={selectEvidence}
      />

      <EvidenceList
        evidence={sample.analysis.evidence}
        referencedIds={referencedIds}
        selectedId={selectedEvidenceId}
        onSelect={selectEvidence}
      />

      <TraceList
        trace={sample.analysis.trace}
        selectedEvidenceId={selectedEvidenceId}
        onSelectEvidence={selectEvidence}
      />
    </div>
  );
}
