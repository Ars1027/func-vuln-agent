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

/** 批量输入：上传课程 JSONL，字段名为 file，模式随表单提交。 */
export function BatchUploadForm({ mode, disabled, onPendingChange, onStarted }: Props) {
  const [file, setFile] = useState<File | null>(null);
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
      <label className="field">
        <span className="field__label">课程 JSONL 文件</span>
        <input
          ref={inputRef}
          type="file"
          accept=".jsonl,.json,application/x-ndjson,application/json"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span className="field__hint">
          每行一条课程样本，字段为 idx、commit_url、target、func；重复标识、空文件和超限会在上传时返回错误。
        </span>
      </label>

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
        <button type="submit" className="button button--primary" disabled={disabled || busy}>
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
