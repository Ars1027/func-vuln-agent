import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { fetchResult, getReports, getTask } from "../api/client";
import { subscribeTaskEvents } from "../api/sse";
import type { TaskView } from "../api/types";
import { describeError, type DisplayError } from "../lib/errors";
import { createInitialTaskState, taskReducer, type TaskState } from "../state/store";

export interface TaskStreamController {
  state: TaskState;
  loading: boolean;
  /** 加载任务或事件流失败。 */
  loadError: DisplayError | null;
  /** 导出失败的代码与说明，例如 409 result_incomplete。 */
  downloadError: DisplayError | null;
  /** 本轮任务收到第一条事件的本地时间，用于运行计时；未收到事件时为 null。 */
  startedAt: number | null;
  startTask: (view: TaskView) => void;
  reload: () => void;
  download: () => void;
  clearDownloadError: () => void;
}

/**
 * 任务生命周期：先读 `/reports` 快照，再从其 `seq` 续接 SSE 事件。
 * 断线重连或手动刷新都重复同样的顺序，因此进行中的分析可以恢复。
 */
export function useTaskStream(): TaskStreamController {
  const [state, dispatch] = useReducer(taskReducer, undefined, createInitialTaskState);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<DisplayError | null>(null);
  const [downloadError, setDownloadError] = useState<DisplayError | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const closeStream = useRef<(() => void) | null>(null);
  const startedAtRef = useRef<number | null>(null);

  const detach = useCallback(() => {
    closeStream.current?.();
    closeStream.current = null;
  }, []);

  // 计时起点取本地收到的第一条事件，避免与服务端时钟做减法。
  const markStarted = useCallback(() => {
    if (startedAtRef.current !== null) {
      return;
    }
    const now = Date.now();
    startedAtRef.current = now;
    setStartedAt(now);
  }, []);

  const clearStarted = useCallback(() => {
    startedAtRef.current = null;
    setStartedAt(null);
  }, []);

  const connect = useCallback(
    async (taskId: string, options: { reset?: boolean } = {}) => {
      detach();
      if (options.reset) {
        dispatch({ type: "reset" });
        clearStarted();
      }
      setLoadError(null);
      setLoading(true);
      try {
        const view = await getTask(taskId);
        dispatch({ type: "task_view", view });
        const snapshot = await getReports(taskId);
        dispatch({ type: "snapshot", snapshot });
        dispatch({ type: "connection", connection: "connecting" });
        const initialSeq = snapshot.seq;
        closeStream.current = subscribeTaskEvents(taskId, initialSeq, {
          onEvent: (event) => {
            markStarted();
            dispatch({ type: "event", event });
          },
          onState: (next) =>
            dispatch({
              type: "connection",
              connection: next === "closed" ? "closed" : next === "error" ? "error" : next,
            }),
          onParseError: () =>
            dispatch({ type: "notice", notice: "收到无法解析的事件数据，已跳过该条记录。" }),
        });
      } catch (error) {
        setLoadError(describeError(error));
        dispatch({ type: "connection", connection: "error" });
      } finally {
        setLoading(false);
      }
    },
    [clearStarted, detach, markStarted],
  );

  const startTask = useCallback(
    (view: TaskView) => {
      void connect(view.task_id, { reset: true });
    },
    [connect],
  );

  const reload = useCallback(() => {
    if (state.taskId !== null) {
      void connect(state.taskId);
    }
  }, [connect, state.taskId]);

  const download = useCallback(() => {
    const taskId = state.taskId;
    if (taskId === null) {
      return;
    }
    setDownloadError(null);
    void (async () => {
      try {
        const text = await fetchResult(taskId);
        const blob = new Blob([text], { type: "application/x-ndjson;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `result-${taskId.slice(0, 8)}.jsonl`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      } catch (error) {
        setDownloadError(describeError(error));
      }
    })();
  }, [state.taskId]);

  const clearDownloadError = useCallback(() => setDownloadError(null), []);

  // 组件卸载时关闭事件流。
  useEffect(() => detach, [detach]);

  return {
    state,
    loading,
    loadError,
    downloadError,
    startedAt,
    startTask,
    reload,
    download,
    clearDownloadError,
  };
}
