// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportsSnapshot, TaskView } from "../api/types";
import { useTaskStream } from "./useTaskStream";

/** 只记录连接与地址的 EventSource 替身；用例不推送事件。 */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readyState = FakeEventSource.OPEN;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(): void {}

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function taskView(overrides: Partial<TaskView> = {}): TaskView {
  return {
    task_id: "task-1",
    status: "running",
    mode: "conditions",
    total: 1,
    completed: 0,
    failures: [],
    ...overrides,
  };
}

function snapshot(overrides: Partial<ReportsSnapshot> = {}): ReportsSnapshot {
  return {
    task_id: "task-1",
    seq: 0,
    reports: [],
    active_samples: [],
    failed_samples: [],
    failures: [],
    ...overrides,
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useTaskStream 生命周期", () => {
  it("任务已受理但读取状态失败时保留 task_id，之后可以重试续接", async () => {
    let failTask = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.endsWith("/reports")) {
          return jsonResponse(snapshot({ seq: 2 }));
        }
        if (/\/api\/tasks\/[^/]+$/.test(url)) {
          return failTask
            ? jsonResponse({ code: "internal_error", message: "服务内部错误" }, 500)
            : jsonResponse(taskView());
        }
        throw new Error(`未预期的请求：${url}`);
      }),
    );

    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));

    await waitFor(() => expect(result.current.loadError?.code).toBe("internal_error"));
    // 已受理的任务不能退回空状态：task_id 仍在，用户可以直接重试。
    expect(result.current.state.taskId).toBe("task-1");
    expect(FakeEventSource.instances).toHaveLength(0);

    failTask = false;
    act(() => result.current.reload());

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toContain("/api/tasks/task-1/events?after_seq=2");
    await waitFor(() => expect(result.current.loadError).toBeNull());
  });

  it("已终止的任务不再打开事件流，避免对结束的流反复重连", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.endsWith("/reports")) {
          return jsonResponse(snapshot({ seq: 4 }));
        }
        return jsonResponse(taskView({ status: "completed", completed: 1 }));
      }),
    );

    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));

    await waitFor(() => expect(result.current.state.status).toBe("completed"));
    expect(result.current.state.connection).toBe("closed");
    expect(result.current.state.seq).toBe(4);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("先发起但晚返回的请求不覆盖后一次提交", async () => {
    const deferred: Array<() => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        const taskId = url.includes("task-b") ? "task-b" : "task-a";
        if (url.endsWith("/reports")) {
          const seq = deferred.length === 0 ? 11 : 22;
          return new Promise<Response>((resolve) => {
            deferred.push(() => resolve(jsonResponse(snapshot({ task_id: taskId, seq }))));
          });
        }
        return Promise.resolve(jsonResponse(taskView({ task_id: taskId })));
      }),
    );

    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView({ task_id: "task-a" })));
    act(() => result.current.startTask(taskView({ task_id: "task-b" })));

    // 后一次提交先完成，第一次的快照随后才到。
    await act(async () => deferred[1]());
    await act(async () => deferred[0]());

    expect(result.current.state.taskId).toBe("task-b");
    expect(result.current.state.seq).toBe(22);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toContain("/api/tasks/task-b/events");
  });
});
