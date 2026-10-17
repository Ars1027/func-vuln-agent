interface Props {
  /** 已完成样本数。 */
  completed: number;
  /** 失败样本数。 */
  failed: number;
  /** 仍在分析的样本数。 */
  running: number;
  /** 任务总数，0 表示尚未拿到计数。 */
  total: number;
  /** 任务是否仍在推进（决定运行段是否显示条纹动画）。 */
  active: boolean;
}

function percent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((value / total) * 100));
}

/**
 * 任务完成进度条。
 * 完成/失败/进行中分别着色，总数未知时降级为不定量条纹，表示“还在推进但没有分母”。
 */
export function ProgressBar({ completed, failed, running, total, active }: Props) {
  const indeterminate = total === 0 && active;
  const done = Math.min(completed, total || completed);
  const remaining = Math.max(0, total - done - failed - running);

  return (
    <div className={`progress ${active ? "is-active" : ""}`}>
      <div
        className="progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total || undefined}
        aria-valuenow={total ? done : undefined}
        aria-label="样本完成进度"
      >
        {indeterminate ? (
          <span className="progress__bar progress__bar--indeterminate" />
        ) : (
          <>
            <span className="progress__bar progress__bar--done" style={{ width: `${percent(done, total)}%` }} />
            <span
              className="progress__bar progress__bar--failed"
              style={{ width: `${percent(failed, total)}%` }}
            />
            <span
              className="progress__bar progress__bar--running"
              style={{ width: `${percent(running, total)}%` }}
            />
            <span className="progress__bar progress__bar--rest" style={{ width: `${percent(remaining, total)}%` }} />
          </>
        )}
      </div>
      <span className="progress__value">
        {total === 0 ? (active ? "准备中" : "—") : `${done}/${total}`}
      </span>
    </div>
  );
}
