// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportsSnapshot, TaskView } from "../api/types";
import { idxKey } from "../state/idx";
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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

  it.each(["completed", "failed"] as const)(
    "快照之后任务变为 %s 时重新读取最终报告与失败项",
    async (status) => {
      const failure = { idx: 1, code: "interrupted", message: "服务重启中断" };
      const report = {
        idx: 1,
        prediction: 1 as const,
        reason: "最终判定",
        hypotheses: [],
        conditions: [],
        evidence: [],
        trace: [],
      };
      const finalSnapshot = snapshot({
        seq: 4,
        reports: status === "completed" ? [report] : [],
        failures: status === "failed" ? [failure] : [],
      });
      let reportReads = 0;
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: string) => {
          if (String(input).endsWith("/reports")) {
            reportReads += 1;
            return jsonResponse(reportReads === 1 ? snapshot({ seq: 2 }) : finalSnapshot);
          }
          return jsonResponse(taskView({
            status,
            completed: status === "completed" ? 1 : 0,
            failures: status === "failed" ? [failure] : [],
          }));
        }),
      );

      const { result } = renderHook(() => useTaskStream());
      act(() => result.current.startTask(taskView()));

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.state.seq).toBe(4);
      expect(result.current.state.status).toBe(status);
      expect(result.current.state.samples[idxKey(1)].status).toBe(status);
      expect(result.current.state.samples[idxKey(1)].prediction).toBe(
        status === "completed" ? 1 : null,
      );
      expect(result.current.state.connection).toBe("closed");
      expect(FakeEventSource.instances).toHaveLength(0);
    },
  );

  it("补读的终态快照迟到时不覆盖新任务", async () => {
    const finalRead = deferred<Response>();
    let reportReads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.includes("task-b")) {
          return jsonResponse(url.endsWith("/reports")
            ? snapshot({ task_id: "task-b", seq: 8 })
            : taskView({ task_id: "task-b" }));
        }
        if (url.endsWith("/reports")) {
          reportReads += 1;
          return reportReads === 1 ? jsonResponse(snapshot()) : finalRead.promise;
        }
        return jsonResponse(taskView({ status: "completed", completed: 1 }));
      }),
    );

    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));
    await waitFor(() => expect(reportReads).toBe(2));
    act(() => result.current.startTask(taskView({ task_id: "task-b" })));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    await act(async () => finalRead.resolve(jsonResponse(snapshot({ seq: 20 }))));

    expect(result.current.state.taskId).toBe("task-b");
    expect(result.current.state.seq).toBe(8);
    expect(result.current.state.status).toBe("running");
    expect(result.current.state.connection).toBe("connecting");
  });
});

describe("useTaskStream 下载", () => {
  function setupDownloads() {
    const responses: ReturnType<typeof deferred<Response>>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string) => {
      const url = String(input);
      if (url.endsWith("/result.jsonl")) {
        const response = deferred<Response>();
        responses.push(response);
        return response.promise;
      }
      const taskId = url.includes("task-b") ? "task-b" : "task-1";
      return jsonResponse(url.endsWith("/reports")
        ? snapshot({ task_id: taskId })
        : taskView({ task_id: taskId }));
    }));
    const createUrl = vi.fn(() => "blob:result");
    vi.stubGlobal("URL", { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    return { responses, createUrl, click };
  }

  function resultResponse(): Response {
    return { ok: true, text: async () => '{"idx":1,"prediction":1}\n' } as Response;
  }

  function incompleteResponse(): Response {
    return jsonResponse({ code: "result_incomplete", message: "结果尚未完整" }, 409);
  }

  it("重试下载成功后忽略前一次迟到的失败", async () => {
    const { responses, click } = setupDownloads();
    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.download());
    act(() => result.current.download());
    await act(async () => responses[1].resolve(resultResponse()));
    await act(async () => responses[0].resolve(incompleteResponse()));

    expect(click).toHaveBeenCalledTimes(1);
    expect(result.current.downloadError).toBeNull();
  });

  it.each(["success", "failure"])("切换任务后忽略旧下载的 %s 响应", async (outcome) => {
    const { responses, createUrl } = setupDownloads();
    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.download());
    act(() => result.current.startTask(taskView({ task_id: "task-b" })));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => responses[0].resolve(
      outcome === "success" ? resultResponse() : incompleteResponse(),
    ));

    expect(result.current.state.taskId).toBe("task-b");
    expect(result.current.downloadError).toBeNull();
    expect(createUrl).not.toHaveBeenCalled();
  });

  it("新任务清除上一任务已经显示的下载失败", async () => {
    const { responses } = setupDownloads();
    const { result } = renderHook(() => useTaskStream());
    act(() => result.current.startTask(taskView()));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.download());
    await act(async () => responses[0].resolve(incompleteResponse()));
    expect(result.current.downloadError?.code).toBe("result_incomplete");

    act(() => result.current.startTask(taskView({ task_id: "task-b" })));
    expect(result.current.downloadError).toBeNull();
  });
});
