import { FileJson2, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { createBatch } from "../api/client";
import type { Mode, TaskView } from "../api/types";
import { describeError } from "../lib/errors";
import { ErrorNotice } from "./ErrorNotice";

interface Props {
  mode: Mode;
  disabled?: boolean;
  /** 提交开始/结束时通知容器，容器据此锁定输入方式切换。 */
  onPendingChange?: (pending: boolean) => void;
  onStarted: (view: TaskView) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** 批量输入：支持拖拽或点击上传课程 JSONL，字段名为 file，模式随表单提交。 */
export function BatchUploadForm({ mode, disabled, onPendingChange, onStarted }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (file === null) {
      setError({ code: "missing_file", message: "请选择要上传的 .jsonl 文件。" });
      return;
    }
    setBusy(true);
    onPendingChange?.(true);
    try {
      const view = await createBatch(file, mode);
      onStarted(view);
    } catch (submitError) {
      setError(describeError(submitError));
    } finally {
      setBusy(false);
      onPendingChange?.(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div className="field">
        <span className="field__label">课程 JSONL 文件</span>
        <div
          className={`dropzone ${dragging ? "is-dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped) {
              setFile(dropped);
              setError(null);
            }
          }}
        >
          <input
            ref={inputRef}
            type="file"
            aria-label="课程 JSONL 文件"
            accept=".jsonl,.json,application/x-ndjson,application/json"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setError(null);
            }}
          />
          <span className="panel__title-icon" aria-hidden="true">
            {file === null ? <UploadCloud size={16} /> : <FileJson2 size={16} />}
          </span>
          <span className="text-[13px] font-semibold">
            {file === null ? "拖拽 .jsonl 文件到此处，或点击选择" : file.name}
          </span>
          <span className="text-[11.5px] muted">
            {file === null
              ? "单批默认上限 10 MiB / 1000 条样本"
              : `已就绪 · ${formatSize(file.size)}`}
          </span>
        </div>
        <span className="field__hint">
          每行一条课程样本，字段为 idx、commit_url、target、func；重复标识、空文件和超限会在上传时返回错误。
        </span>
      </div>

      {file !== null && (
        <dl className="kv">
          <div>
            <dt>文件</dt>
            <dd className="mono">{file.name}</dd>
          </div>
          <div>
            <dt>大小</dt>
            <dd>{formatSize(file.size)}</dd>
          </div>
        </dl>
      )}

      <div className="button-row">
        <button
          type="submit"
          className="button button--primary flex-1"
          disabled={disabled || busy}
        >
          <UploadCloud size={14} aria-hidden="true" />
          {busy ? "上传中…" : "上传并开始批量检测"}
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => {
            setFile(null);
            setError(null);
            if (inputRef.current) {
              inputRef.current.value = "";
            }
          }}
        >
          <Trash2 size={13} aria-hidden="true" />
          清除
        </button>
      </div>

      <p className="field__hint">
        本地联调可用仓库内的 <code>examples/synthetic.jsonl</code>，其中同时包含整数 <code>1</code>{" "}
        与字符串 <code>"1"</code> 两个不同样本。
      </p>

      {error !== null && <ErrorNotice code={error.code} message={error.message} />}
    </form>
  );
}
