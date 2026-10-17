import type { Condition, Mode } from "../api/types";
import { useChangeFlash } from "../hooks/useChangeFlash";
import { conditionsByHypothesis, type SampleState } from "../state/store";
import { ConditionStatusChip } from "./chips";

interface Props {
  sample: SampleState;
  mode: Mode | null;
  selectedEvidenceId: string | null;
  onSelectEvidence: (id: string) => void;
}

interface ConditionRowProps {
  condition: Condition;
  selectedEvidenceId: string | null;
  onSelectEvidence: (id: string) => void;
}

/** 单个条件：状态变化时闪一下，提示“这条刚被更新”。 */
function ConditionRow({ condition, selectedEvidenceId, onSelectEvidence }: ConditionRowProps) {
  const flashing = useChangeFlash(condition.status);

  return (
    <li className={`condition ${flashing ? "is-flashing" : ""}`} data-status={condition.status}>
      <div className="condition__head">
        <code className="condition__id">{condition.id}</code>
        <ConditionStatusChip status={condition.status} />
      </div>
      <p className="condition__statement">{condition.statement}</p>
      <p className="condition__reason">{condition.reason}</p>
      <div className="chip-row">
        {condition.evidence_ids.length === 0 && <span className="muted">未引用证据</span>}
        {condition.evidence_ids.map((id) => (
          <button
            key={id}
            type="button"
            className={`evidence-chip ${id === selectedEvidenceId ? "is-active" : ""}`}
            onClick={() => onSelectEvidence(id)}
            title="在证据列表中查看来源"
          >
            {id}
          </button>
        ))}
      </div>
    </li>
  );
}

/**
 * 按漏洞假设组织条件，逐条显示“有支持证据 / 有反证 / 待确认”。
 * 条件统一表述为漏洞成立所需的命题，因此 supported 始终表示支持漏洞条件。
 */
export function HypothesisGroups({ sample, mode, selectedEvidenceId, onSelectEvidence }: Props) {
  const groups = conditionsByHypothesis(sample);
  const hasConditions = sample.analysis.conditions.length > 0;

  return (
    <div className="section">
      <h3 className="section-title">漏洞假设与成立条件</h3>

      {!hasConditions && (
        <p className="field__hint">
          {mode === "function_only"
            ? "函数基线模式不提出假设与条件，只给出最终判定。"
            : "尚未提出假设或条件；条件待确认不同于执行失败。"}
        </p>
      )}

      {groups.map((group) => (
        <article key={group.hypothesis.id} className="hypothesis">
          <header className="hypothesis__head">
            <code className="hypothesis__id">{group.hypothesis.id}</code>
            <p className="hypothesis__statement">{group.hypothesis.statement}</p>
          </header>

          {group.conditions.length === 0 ? (
            <p className="field__hint">该假设暂无可展示条件。</p>
          ) : (
            <ul className="condition-list">
              {group.conditions.map((condition) => (
                <ConditionRow
                  key={condition.id}
                  condition={condition}
                  selectedEvidenceId={selectedEvidenceId}
                  onSelectEvidence={onSelectEvidence}
                />
              ))}
            </ul>
          )}
        </article>
      ))}

      {hasConditions && (
        <p className="field__hint">
          一个条件被反驳只否定对应假设的成立条件，不代表整个函数安全；<code>unknown</code> 也不等于无漏洞。
        </p>
      )}
    </div>
  );
}
