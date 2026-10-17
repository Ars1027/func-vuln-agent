import type { CSSProperties } from "react";

import type { TraceEntry } from "../api/types";
import { useFollowLatest } from "../hooks/useFollowLatest";

interface Props {
  trace: TraceEntry[];
  selectedEvidenceId: string | null;
  onSelectEvidence: (id: string) => void;
}

const TOOL_LABELS: Record<string, string> = {
  search_cases: "检索历史案例",
  search_code: "代码搜索",
  read_file: "读取文件",
  find_symbol: "查找符号",
  locate_function: "定位目标函数",
};

function formatArguments(arguments_: Record<string, unknown>): string {
  const parts = Object.entries(arguments_).map(([key, value]) => {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return `${key}=${text}`;
  });
  return parts.join(" · ");
}

/**
 * 分析记录：按顺序展示检索与仓库读取操作，并链接到产生的证据。
 * 新记录到达时自动滚到底部；用户手动上滚后暂停跟随。
 */
export function TraceList({ trace, selectedEvidenceId, onSelectEvidence }: Props) {
  const { ref, following, onScroll } = useFollowLatest<HTMLOListElement>({ length: trace.length });

  if (trace.length === 0) {
    return (
      <div className="section">
        <h3 className="section-title">分析记录</h3>
        <p className="field__hint">尚无检索或仓库读取记录。</p>
      </div>
    );
  }

  return (
    <div className="section">
      <h3 className="section-title">
        分析记录
        <span className="muted"> {trace.length}</span>
        {!following && <span className="follow-tag">已暂停自动跟随</span>}
      </h3>
      <ol className="trace-list" ref={ref} onScroll={onScroll}>
        {trace.map((entry, index) => (
          <li
            key={`${index}-${entry.tool}`}
            className="trace"
            style={{ "--i": Math.min(index, 8) } as CSSProperties}
          >
            <div className="trace__head">
              <span className="trace__index">{index + 1}</span>
              <span className="trace__tool">{TOOL_LABELS[entry.tool] ?? entry.tool}</span>
              <code className="trace__tool-name mono">{entry.tool}</code>
            </div>
            <p className="trace__arguments mono">{formatArguments(entry.arguments)}</p>
            {entry.summary && <p className="trace__summary">{entry.summary}</p>}
            {entry.evidence_ids.length > 0 && (
              <div className="chip-row">
                {entry.evidence_ids.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`evidence-chip ${id === selectedEvidenceId ? "is-active" : ""}`}
                    onClick={() => onSelectEvidence(id)}
                  >
                    {id}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
