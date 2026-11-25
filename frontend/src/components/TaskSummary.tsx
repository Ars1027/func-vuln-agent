import { Activity, Check, Copy, Download, Gauge, RefreshCw } from "lucide-react";

import { MODE_LABELS, type Measurement } from "../api/types";
import { useChangeFlash } from "../hooks/useChangeFlash";
import { useCopyToClipboard } from "../hooks/useCopyToClipboard";
import { useElapsed } from "../hooks/useElapsed";
import type { DisplayError } from "../lib/errors";
import { taskProgress, type TaskState } from "../state/store";
import { ErrorNotice } from "./ErrorNotice";
import { TelemetryDrawer } from "./TelemetryDrawer";
import { TaskStatusChip } from "./chips";
import { ElapsedTime } from "./ui/ElapsedTime";
import { ProgressBar } from "./ui/ProgressBar";

const CONNECTION_LABELS: Record<TaskState["connection"], string> = {
  idle: "未连接",
  connecting: "事件流连接中",
  open: "事件流已连接",
  closed: "事件流已结束",
  error: "事件流异常",
};

const COPY_LABELS = { idle: "复制", copied: "已复制", failed: "复制失败" } as const;

interface Props {
  state: TaskState;
  loading: boolean;
  startedAt: number | null;
  loadError: DisplayError | null;
  downloadError: DisplayError | null;
  onReload: () => void;
  onDownload: () => void;
  onClearDownloadError: () => void;
  telemetryOpen?: boolean;
  measurements?: Measurement[] | null;
  measurementsLoading?: boolean;
  measurementsError?: DisplayError | null;
  onToggleTelemetry?: () => void;
  onRefreshTelemetry?: () => void;
}

export function TaskSummary({
  state,
  loading,
  startedAt,
  loadError,
  downloadError,
  onReload,
  onDownload,
  onClearDownloadError,
  telemetryOpen = false,
  measurements = null,
  measurementsLoading = false,
  measurementsError = null,
  onToggleTelemetry,
  onRefreshTelemetry,
}: Props) {
  const progress = taskProgress(state);
  const downloadDisabled = state.taskId === null;
  const running = state.status === "queued" || state.status === "running";
  const elapsed = useElapsed(startedAt, running);
  const { state: copyState, copy } = useCopyToClipboard();

  // 计数变化时闪一下，让“正在推进”可见。
  const completedFlash = useChangeFlash(progress.completed);
  const runningFlash = useChangeFlash(progress.running);
  const failedFlash = useChangeFlash(progress.failed);

  const taskId = state.taskId;

  return (
    <div className="task-summary">
      <div className="task-summary__head">
        <div className="task-summary__ident">
          <h2 className="panel__title">
            <span className="panel__title-icon" aria-hidden="true">
              <Activity size={14} />
            </span>
            任务进度
          </h2>
          <p className="task-summary__id" title={taskId ?? ""}>
            <span className="muted">task_id</span>{" "}
            <code>{taskId === null ? "—" : taskId}</code>
            {taskId !== null && (
              <button
                type="button"
                className={`copy-button ${copyState === "copied" ? "is-done" : ""}`}
                onClick={() => void copy(taskId)}
              >
                {copyState === "copied" ? (
                  <Check size={11} aria-hidden="true" />
                ) : (
                  <Copy size={11} aria-hidden="true" />
                )}
                {COPY_LABELS[copyState]}
              </button>
            )}
          </p>
        </div>

        <div className="task-summary__actions">
          {onToggleTelemetry !== undefined && (
            <button
              type="button"
              className={`button ${telemetryOpen ? "border-accent text-accent" : ""}`}
              onClick={onToggleTelemetry}
              disabled={downloadDisabled}
              aria-expanded={telemetryOpen}
            >
              <Gauge size={14} aria-hidden="true" />
              实验测量
            </button>
          )}
          <button
            type="button"
            className="button"
            onClick={onReload}
            disabled={loading || downloadDisabled}
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} aria-hidden="true" />
            {loading ? "加载中…" : "刷新快照并续接"}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onDownload}
            disabled={downloadDisabled}
          >
            <Download size={14} aria-hidden="true" />
            下载 result.jsonl
          </button>
        </div>
      </div>

      <div className="task-summary__live">
        <ProgressBar
          completed={progress.completed}
          failed={progress.failed}
          running={progress.running}
          total={progress.total}
          active={running}
        />
        <ElapsedTime ms={elapsed} running={running} />
      </div>

      <dl className="stats">
        <div>
          <dt>状态</dt>
          <dd>
            <TaskStatusChip status={state.status} />
          </dd>
        </div>
        <div>
          <dt>模式</dt>
          <dd>{state.mode === null ? "—" : MODE_LABELS[state.mode]}</dd>
        </div>
        <div>
          <dt>完成</dt>
          <dd className={completedFlash ? "is-flashing" : undefined}>
            {progress.completed}
            <span className="muted"> / {progress.total === 0 ? "—" : progress.total}</span>
          </dd>
        </div>
        <div>
          <dt>分析中</dt>
          <dd className={runningFlash ? "is-flashing" : undefined}>{progress.running}</dd>
        </div>
        <div>
          <dt>失败</dt>
          <dd className={failedFlash ? "is-flashing" : undefined}>{progress.failed}</dd>
        </div>
        <div>
          <dt>事件流</dt>
          <dd>
            <span>{CONNECTION_LABELS[state.connection]}</span>
            <span className="muted"> · seq {state.seq}</span>
          </dd>
        </div>
      </dl>

      {telemetryOpen && onRefreshTelemetry !== undefined && (
        <TelemetryDrawer
          measurements={measurements}
          loading={measurementsLoading}
          error={measurementsError}
          onRefresh={onRefreshTelemetry}
        />
      )}

      {state.status !== "completed" && taskId !== null && (
        <p className="field__hint mt-3">
          导出只接受全部样本成功且标识唯一的任务；含失败项或仍在运行时点击下载会返回原因。
        </p>
      )}

      {loadError !== null && (
        <ErrorNotice title="加载任务失败" code={loadError.code} message={loadError.message} />
      )}

      {downloadError !== null && (
        <ErrorNotice
          title="无法导出结果"
          code={downloadError.code}
          message={downloadError.message}
          action={
            <button type="button" className="button button--small" onClick={onClearDownloadError}>
              知道了
            </button>
          }
        />
      )}

      {state.notice !== null && <p className="notice notice--info">{state.notice}</p>}
    </div>
  );
}
