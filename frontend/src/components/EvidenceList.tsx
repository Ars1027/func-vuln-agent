import { BookOpen, Check, ChevronDown, Code2, Copy, FileSearch } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Evidence } from "../api/types";
import { useCopyToClipboard } from "../hooks/useCopyToClipboard";
import { highlightCpp } from "../lib/highlightCpp";

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

function CopySnippetButton({ content }: { content: string }) {
  const { state, copy } = useCopyToClipboard();
  return (
    <button
      type="button"
      className={`copy-button ${state === "copied" ? "is-done" : ""}`}
      onClick={() => void copy(content)}
    >
      {state === "copied" ? (
        <Check size={11} aria-hidden="true" />
      ) : (
        <Copy size={11} aria-hidden="true" />
      )}
      {state === "copied" ? "已复制" : "复制片段"}
    </button>
  );
}

/**
 * 证据检视器：代码证据按真实 start_line..end_line 映射源码行号并做 C/C++ 词法着色，
 * 历史证据展示 case_id、数据来源与原文片段。
 */
export function EvidenceList({ evidence, referencedIds, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLUListElement>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (selectedId === null) {
      return;
    }
    setExpanded((previous) =>
      previous[selectedId] ? previous : { ...previous, [selectedId]: true },
    );
    const node = containerRef.current?.querySelector(
      `[data-evidence-id="${CSS.escape(selectedId)}"]`,
    );
    node?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  if (evidence.length === 0) {
    return (
      <div className="section section--flush">
        <h3 className="section-title">
          <FileSearch size={14} aria-hidden="true" />
          证据
        </h3>
        <p className="field__hint">
          该样本还没有可用证据。函数基线模式不产生证据；其他模式在检索或仓库读取完成后出现。
        </p>
      </div>
    );
  }

  return (
    <div className="section section--flush">
      <h3 className="section-title">
        <FileSearch size={14} aria-hidden="true" />
        证据
        <span className="muted"> {evidence.length}</span>
      </h3>
      <ul className="evidence-list" ref={containerRef}>
        {evidence.map((item) => {
          const isOpen = expanded[item.id] ?? false;
          const isSelected = item.id === selectedId;
          const rawLines = item.content.split("\n");
          // 若末尾有单个换行符则不额外渲染空行号
          const lineCount =
            rawLines.length > 1 && rawLines[rawLines.length - 1] === ""
              ? rawLines.length - 1
              : rawLines.length;

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
                <span className={`tag tag--${item.kind}`}>
                  {item.kind === "code" ? (
                    <Code2 size={11} aria-hidden="true" />
                  ) : (
                    <BookOpen size={11} aria-hidden="true" />
                  )}
                  {KIND_LABELS[item.kind]}
                </span>
                <span className="evidence__location mono">{evidenceLocation(item)}</span>
                {!referencedIds.has(item.id) && (
                  <span className="tag tag--muted" title="当前没有被任何条件引用">
                    未被引用
                  </span>
                )}
                <ChevronDown
                  size={14}
                  className={`evidence__chevron ${isOpen ? "is-open" : ""}`}
                  aria-hidden="true"
                />
              </button>

              {isOpen && (
                <div className="evidence__body">
                  <div className="evidence__toolbar">
                    <p className="evidence__source">
                      <span className="muted">
                        {item.kind === "code" ? "snapshot_ref" : "source"}
                      </span>{" "}
                      <code className="mono">
                        {item.kind === "code" ? item.snapshot_ref : item.source}
                      </code>
                    </p>
                    <CopySnippetButton content={item.content} />
                  </div>

                  {item.kind === "code" ? (
                    <div className="code-viewer">
                      <div className="code-gutter" aria-hidden="true">
                        {Array.from({ length: lineCount }, (_, idx) => (
                          <span key={item.start_line + idx}>{item.start_line + idx}</span>
                        ))}
                      </div>
                      <pre className="code-block">
                        <code>{highlightCpp(item.content)}</code>
                      </pre>
                    </div>
                  ) : (
                    <div className="code-viewer code-viewer--plain">
                      <pre className="code-block">{item.content}</pre>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
