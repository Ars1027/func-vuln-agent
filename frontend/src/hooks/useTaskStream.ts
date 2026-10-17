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
  /** 每次连接自增；先发起但晚返回的请求不再改动状态，避免并发提交互相覆盖。 */
  const runId = useRef(0);

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
    async (taskId: string, options: { accepted?: TaskView } = {}) => {
      detach();
      runId.current += 1;
      const currentRun = runId.current;
      const isCurrent = () => runId.current === currentRun;
      if (options.accepted) {
        dispatch({ type: "reset" });
        clearStarted();
        // 先保存已受理的任务：随后读取快照或状态失败时 task_id 仍在，
        // 界面不会退回空状态，用户可以直接重试并续接到这个已经在跑的任务。
        dispatch({ type: "task_view", view: options.accepted });
      }
      setLoadError(null);
      setLoading(true);
      try {
        // 先取快照的 seq，再取任务状态：状态不会早于快照，
        // 因此“已终止”判断能覆盖快照之后的终态。
        const snapshot = await getReports(taskId);
        if (!isCurrent()) {
          return;
        }
        dispatch({ type: "snapshot", snapshot });
        const view = await getTask(taskId);
        if (!isCurrent()) {
          return;
        }
        dispatch({ type: "task_view", view });
        if (view.status === "completed" || view.status === "failed") {
          // 快照已包含终止事件：服务端会立即结束这条流，浏览器随后反复重连。
          dispatch({ type: "connection", connection: "closed" });
          return;
        }
        dispatch({ type: "connection", connection: "connecting" });
        closeStream.current = subscribeTaskEvents(taskId, snapshot.seq, {
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
        if (!isCurrent()) {
          return;
        }
        setLoadError(describeError(error));
        dispatch({ type: "connection", connection: "error" });
      } finally {
        if (isCurrent()) {
          setLoading(false);
        }
      }
    },
    [clearStarted, detach, markStarted],
  );

  const startTask = useCallback(
    (view: TaskView) => {
      void connect(view.task_id, { accepted: view });
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

  // 组件卸载时关闭事件流，并让在途请求的结果失效。
  useEffect(
    () => () => {
      runId.current += 1;
      detach();
    },
    [detach],
  );

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
