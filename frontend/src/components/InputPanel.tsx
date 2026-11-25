import { FileCode2, Files, PanelLeftClose, SlidersHorizontal } from "lucide-react";
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
  onCollapse?: () => void;
}

export function InputPanel({ mode, onModeChange, disabled, onStarted, onCollapse }: Props) {
  const [tab, setTab] = useState<Tab>("single");
  // 任一表单正在提交时锁定切换：切走会卸载表单，但不会取消它已经在飞的请求，
  // 两次提交都可能触发 onStarted，让任务流互相覆盖。
  const [pending, setPending] = useState(false);

  return (
    <section className="panel panel--sticky">
      <div className="panel__head">
        <h2 className="panel__title">
          <span className="panel__title-icon" aria-hidden="true">
            <SlidersHorizontal size={14} />
          </span>
          检测输入
        </h2>
        {onCollapse !== undefined && (
          <button
            type="button"
            className="icon-btn"
            onClick={onCollapse}
            title="收起输入面板，放大右侧报告视图"
          >
            <PanelLeftClose size={14} aria-hidden="true" />
            <span>收起</span>
          </button>
        )}
      </div>

      {disabled && (
        <p className="notice notice--info mb-3">
          当前任务仍在分析中，为避免丢失正在查看的过程记录，完成后再提交新任务。
        </p>
      )}

      <ModeSelect mode={mode} onChange={onModeChange} disabled={disabled} />

      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "single"}
          className={`tab ${tab === "single" ? "is-active" : ""}`}
          disabled={pending}
          onClick={() => setTab("single")}
        >
          <FileCode2 size={14} aria-hidden="true" />
          单样本
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "batch"}
          className={`tab ${tab === "batch" ? "is-active" : ""}`}
          disabled={pending}
          onClick={() => setTab("batch")}
        >
          <Files size={14} aria-hidden="true" />
          批量 JSONL
        </button>
      </div>

      {pending && (
        <p className="notice notice--info mb-3">提交请求处理中，完成前不能切换输入方式。</p>
      )}

      {tab === "single" ? (
        <SingleInputForm
          mode={mode}
          disabled={disabled}
          onPendingChange={setPending}
          onStarted={onStarted}
        />
      ) : (
        <BatchUploadForm
          mode={mode}
          disabled={disabled}
          onPendingChange={setPending}
          onStarted={onStarted}
        />
      )}
    </section>
  );
}
