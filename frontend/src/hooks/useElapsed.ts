import { useEffect, useState } from "react";

const DEFAULT_TICK_MS = 200;

/**
 * 任务运行计时。
 *
 * `active` 为 true 时按 `tickMs` 刷新；一旦结束就停止刷新并冻结在最后一个读数，
 * 因此已完成任务的耗时文本是稳定的（不会因为重新渲染而跳动）。
 */
export function useElapsed(
  startedAtMs: number | null,
  active: boolean,
  tickMs: number = DEFAULT_TICK_MS,
): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    // 状态切换时对齐一次读数，保证结束时拿到准确的终点。
    setNow(Date.now());
    if (!active) {
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), tickMs);
    return () => window.clearInterval(id);
  }, [active, tickMs]);

  if (startedAtMs === null) {
    return null;
  }
  return Math.max(0, now - startedAtMs);
}

/** 把毫秒格式化成便于扫读的耗时文本。 */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms} 毫秒`;
  }
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)} 秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  return `${minutes} 分 ${rest} 秒`;
}
