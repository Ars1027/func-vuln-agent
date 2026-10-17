import { formatDuration } from "../../hooks/useElapsed";

interface Props {
  /** 已运行毫秒数；null 表示还没有起点。 */
  ms: number | null;
  /** 是否仍在推进（决定用“已运行”还是“耗时”）。 */
  running: boolean;
}

/** 任务计时：运行中持续跳动，结束后冻结在最终耗时。 */
export function ElapsedTime({ ms, running }: Props) {
  if (ms === null) {
    return null;
  }
  return (
    <span className={`elapsed ${running ? "is-running" : ""}`}>
      <span className="elapsed__dot" aria-hidden="true" />
      {running ? "已运行" : "耗时"} {formatDuration(ms)}
    </span>
  );
}
