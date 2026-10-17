import { apiUrl, findUnrepresentableIdx } from "./client";
import { EVENT_TYPES, type EventEnvelope } from "./types";

export type SseState = "connecting" | "open" | "closed" | "error";

export interface SseHandlers {
  onEvent: (event: EventEnvelope) => void;
  onState?: (state: SseState) => void;
  onParseError?: (raw: string) => void;
}

/** 事件连接地址；`after_seq` 优先于 `Last-Event-ID`（docs/interfaces.md 第 6 节）。 */
export function taskEventsUrl(taskId: string, afterSeq: number): string {
  return apiUrl(
    `/api/tasks/${encodeURIComponent(taskId)}/events?after_seq=${encodeURIComponent(String(afterSeq))}`,
  );
}

function parseEvent(raw: string): EventEnvelope | null {
  try {
    const value = JSON.parse(raw) as EventEnvelope;
    if (
      typeof value !== "object" ||
      value === null ||
      typeof value.task_id !== "string" ||
      typeof value.seq !== "number" ||
      typeof value.type !== "string" ||
      findUnrepresentableIdx(value) !== null
    ) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

/**
 * 订阅任务事件流。
 *
 * - 服务端的 `event:` 是类型名，因此按类型逐个注册监听器。
 * - 断线时浏览器自动重连，并带上最后一次收到的 `id`；由于 URL 固定了 `after_seq`，
 *   服务端会从该序号起重放，归约器按 seq 去重，重复事件不会污染状态。
 * - 收到 `task_completed` 后服务端会结束流，这里主动关闭，避免自动重连形成空转。
 */
export function subscribeTaskEvents(
  taskId: string,
  afterSeq: number,
  handlers: SseHandlers,
): () => void {
  const source = new EventSource(taskEventsUrl(taskId, afterSeq));
  let closed = false;

  const close = () => {
    if (!closed) {
      closed = true;
      source.close();
      handlers.onState?.("closed");
    }
  };

  const listener = (message: MessageEvent<string>) => {
    const event = parseEvent(message.data);
    if (event === null) {
      handlers.onParseError?.(message.data);
      return;
    }
    handlers.onEvent(event);
    if (event.type === "task_completed") {
      close();
    }
  };

  source.onopen = () => handlers.onState?.("open");
  source.onerror = () => {
    if (closed) {
      return;
    }
    // CLOSED 表示浏览器放弃重连（例如任务不存在或流被终止）。
    handlers.onState?.(source.readyState === EventSource.CLOSED ? "error" : "connecting");
  };
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, listener as EventListener);
  }

  return close;
}
