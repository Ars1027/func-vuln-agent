import { useState } from "react";

import type { Mode, TaskView } from "../api/types";
import { BatchUploadForm } from "./BatchUploadForm";
import { ModeSelect } from "./ModeSelect";
import { SingleInputForm } from "./SingleInputForm";

type Tab = "single" | "batch";

interface Props {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  disabled?: boolean;
  onStarted: (view: TaskView) => void;
}

export function InputPanel({ mode, onModeChange, disabled, onStarted }: Props) {
  const [tab, setTab] = useState<Tab>("single");

  return (
    <section className="panel">
      <h2 className="panel__title">检测输入</h2>
      {disabled && (
        <p className="notice notice--info">
          当前任务仍在分析中，为避免丢失正在查看的过程记录，完成后再提交新任务。
        </p>
      )}
      <ModeSelect mode={mode} onChange={onModeChange} disabled={disabled} />

      <div className="tabs" role="tablist">        <button
          type="button"
          role="tab"
          aria-selected={tab === "single"}
          className={`tab ${tab === "single" ? "is-active" : ""}`}
          onClick={() => setTab("single")}
        >
          单样本
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "batch"}
          className={`tab ${tab === "batch" ? "is-active" : ""}`}
          onClick={() => setTab("batch")}
        >
          批量 JSONL
        </button>
      </div>

      {tab === "single" ? (
        <SingleInputForm mode={mode} disabled={disabled} onStarted={onStarted} />
      ) : (
        <BatchUploadForm mode={mode} disabled={disabled} onStarted={onStarted} />
      )}
    </section>
  );
}
