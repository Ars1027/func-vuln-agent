import { afterEach, describe, expect, it, vi } from "vitest";

import { subscribeTaskEvents, taskEventsUrl } from "./sse";

class FakeEventSource extends EventTarget {
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(_url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  FakeEventSource.instances = [];
});

describe("taskEventsUrl", () => {
  it("带 after_seq 续接，避免从头重放整个任务", () => {
    expect(taskEventsUrl("abc123", 7)).toBe("/api/tasks/abc123/events?after_seq=7");
  });

  it("序号 0 用于首次连接", () => {
    expect(taskEventsUrl("abc123", 0)).toBe("/api/tasks/abc123/events?after_seq=0");
  });

  it("任务标识做 URL 编码", () => {
    expect(taskEventsUrl("a b/c", 1)).toBe("/api/tasks/a%20b%2Fc/events?after_seq=1");
  });
});

describe("subscribeTaskEvents 标识解析", () => {
  it.each([
    '"idx":9007199254740993,"payload":{}',
    '"idx":-9007199254740993,"payload":{}',
    '"idx":1,"payload":{"report":{"idx":9007199254740993}}',
  ])("拒绝失真整数而不派发事件：%s", (fields) => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const onEvent = vi.fn();
    const onParseError = vi.fn();
    const close = subscribeTaskEvents("task-1", 0, { onEvent, onParseError });
    const raw = `{"task_id":"task-1","seq":1,"type":"sample_completed",${fields}}`;

    FakeEventSource.instances[0].dispatchEvent(
      new MessageEvent("sample_completed", { data: raw }),
    );

    expect(onEvent).not.toHaveBeenCalled();
    expect(onParseError).toHaveBeenCalledWith(raw);
    close();
  });

  it("保留安全整数和大整数字符串的类型，终止事件仍关闭连接", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const onEvent = vi.fn();
    const onParseError = vi.fn();
    subscribeTaskEvents("task-1", 0, { onEvent, onParseError });
    const source = FakeEventSource.instances[0];
    const identifiers = [Number.MAX_SAFE_INTEGER, -Number.MAX_SAFE_INTEGER, "9007199254740993"];
    for (const [index, idx] of identifiers.entries()) {
      source.dispatchEvent(new MessageEvent("sample_completed", {
        data: JSON.stringify({
          task_id: "task-1", seq: index + 1, type: "sample_completed", idx,
          payload: { report: { idx } },
        }),
      }));
    }
    source.dispatchEvent(new MessageEvent("task_completed", {
      data: JSON.stringify({
        task_id: "task-1", seq: 4, type: "task_completed", idx: null,
        payload: { status: "completed" },
      }),
    }));

    expect(onEvent.mock.calls.slice(0, 3).map(([event]) => event.idx)).toEqual(identifiers);
    expect(onEvent).toHaveBeenCalledTimes(4);
    expect(onParseError).not.toHaveBeenCalled();
    expect(source.readyState).toBe(FakeEventSource.CLOSED);
  });
});
