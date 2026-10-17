import { useEffect, useRef, useState } from "react";

import type { Evidence } from "../api/types";

interface Props {
  evidence: Evidence[];
  referencedIds: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const KIND_LABELS: Record<Evidence["kind"], string> = {
  code: "当前快照代码",
  historical: "历史案例",
};

function evidenceLocation(item: Evidence): string {
  return item.kind === "code"
    ? `${item.path}:${item.start_line}-${item.end_line}`
    : `case_id=${item.case_id}`;
}

/**
 * 证据列表：代码证据给出相对路径与行号，历史证据给出 case_id 与来源，
 * 两者都可以展开查看原文片段。
 */
export function EvidenceList({ evidence, referencedIds, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLUListElement>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    setExpanded((previous) => (previous[selectedId] ? previous : { ...previous, [selectedId]: true }));
    const node = containerRef.current?.querySelector(
      `[data-evidence-id="${CSS.escape(selectedId)}"]`,
    );
    // 无布局环境（如 jsdom）没有 scrollIntoView，滚动只是增强行为。
    node?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  if (evidence.length === 0) {
    return (
      <div className="section">
        <h3 className="section-title">证据</h3>
        <p className="field__hint">
          该样本还没有可用证据。函数基线模式不产生证据；其他模式在检索或仓库读取完成后出现。
        </p>
      </div>
    );
  }

  return (
    <div className="section">
      <h3 className="section-title">
        证据
        <span className="muted"> {evidence.length}</span>
      </h3>
      <ul className="evidence-list" ref={containerRef}>
        {evidence.map((item) => {
          const isOpen = expanded[item.id] ?? false;
          const isSelected = item.id === selectedId;
          return (
            <li
              key={item.id}
              data-evidence-id={item.id}
              data-kind={item.kind}
              className={`evidence ${isSelected ? "is-selected" : ""}`}
            >
              <button
                type="button"
                className="evidence__head"
                onClick={() => {
                  setExpanded((previous) => ({ ...previous, [item.id]: !isOpen }));
                  onSelect(item.id);
                }}
                aria-expanded={isOpen}
              >
                <code className="evidence__id">{item.id}</code>
                <span className={`tag tag--${item.kind}`}>{KIND_LABELS[item.kind]}</span>
                <span className="evidence__location mono">{evidenceLocation(item)}</span>
                {!referencedIds.has(item.id) && (
                  <span className="tag tag--muted" title="当前没有被任何条件引用">
                    未被引用
                  </span>
                )}
              </button>
              {isOpen && (
                <div className="evidence__body">
                  <p className="evidence__source">
                    <span className="muted">
                      {item.kind === "code" ? "snapshot_ref" : "source"}
                    </span>{" "}
                    <code className="mono">
                      {item.kind === "code" ? item.snapshot_ref : item.source}
                    </code>
                  </p>
                  <pre className="code-block">{item.content}</pre>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
