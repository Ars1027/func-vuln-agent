// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { EventEnvelope, ReportsSnapshot, TaskView } from "./api/types";
import { DEMO_TASK_EVENTS, DEMO_TASK_ID } from "./state/fixtures/demoEvents";

const DEMO_FUNC = "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }";

/** 用可控替身替换 EventSource：由测试决定何时推送哪条事件。 */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readyState = FakeEventSource.OPEN;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readonly url: string;
  private readonly listeners = new Map<string, Set<(message: MessageEvent<string>) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (message: MessageEvent<string>) => void): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(event: EventEnvelope): void {
    for (const listener of this.listeners.get(event.type) ?? []) {
      listener({ data: JSON.stringify(event) } as MessageEvent<string>);
    }
  }

  static latest(): FakeEventSource {
    const instance = FakeEventSource.instances.at(-1);
    if (instance === undefined) {
      throw new Error("事件流尚未建立");
    }
    return instance;
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }
}

const EMPTY_ANALYSIS = { hypotheses: [], conditions: [], evidence: [], trace: [] };

function taskView(overrides: Partial<TaskView> = {}): TaskView {
  return {
    task_id: DEMO_TASK_ID,
    status: "running",
    mode: "conditions",
    total: 1,
    completed: 0,
    failures: [],
    ...overrides,
  };
}

function reportsSnapshot(overrides: Partial<ReportsSnapshot> = {}): ReportsSnapshot {
  return {
    task_id: DEMO_TASK_ID,
    seq: 0,
    reports: [],
    active_samples: [],
    failed_samples: [],
    failures: [],
    ...overrides,
  };
}

interface ServerState {
  view: TaskView;
  snapshot: ReportsSnapshot;
  resultStatus: number;
  resultBody: unknown;
  resultText: string;
}

let server: ServerState;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

async function handleRequest(url: string): Promise<Response> {
  if (url.endsWith("/api/snapshots")) {
    return jsonResponse({ idx: "1", func: DEMO_FUNC, snapshot_ref: "s-a83f" });
  }
  if (url.endsWith("/api/detections") || url.endsWith("/api/batches")) {
    return jsonResponse(server.view, 202);
  }
  if (url.endsWith("/result.jsonl")) {
    return server.resultStatus === 200
      ? ({
          ok: true,
          status: 200,
          statusText: "",
          text: async () => server.resultText,
          json: async () => ({}),
        } as unknown as Response)
      : jsonResponse(server.resultBody, server.resultStatus);
  }
  if (url.endsWith("/reports")) {
    return jsonResponse(server.snapshot);
  }
  if (/\/api\/tasks\/[^/]+$/.test(url)) {
    return jsonResponse(server.view);
  }
  throw new Error(`未预期的请求：${url}`);
}

async function emit(events: EventEnvelope[]): Promise<void> {
  const source = FakeEventSource.latest();
  await act(async () => {
    for (const event of events) {
      source.emit(event);
    }
  });
}

/** 走一遍单条检测的输入流程。 */
async function submitSingleSample(): Promise<FakeEventSource> {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: /合成样例·漏洞版/ }));
  fireEvent.click(screen.getByRole("button", { name: "准备快照并开始检测" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  return FakeEventSource.latest();
}

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
  server = {
    view: taskView(),
    snapshot: reportsSnapshot(),
    resultStatus: 200,
    resultBody: {},
    resultText: '{"idx":"1","prediction":1}\n',
  };
  vi.stubGlobal("fetch", vi.fn((input: string) => handleRequest(String(input))));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App 单条检测流程", () => {
  it("先读报告快照，再从其 seq 续接事件流", async () => {
    server.snapshot = reportsSnapshot({ seq: 5 });
    const source = await submitSingleSample();

    expect(source.url).toContain(`/api/tasks/${DEMO_TASK_ID}/events?after_seq=5`);
    await act(async () => {
      source.onopen?.();
    });
    expect(await screen.findByText("事件流已连接")).toBeTruthy();
  });

  it("展示条件状态、解释与证据，并可导航到代码位置", async () => {
    await submitSingleSample();
    await emit(DEMO_TASK_EVENTS);

    // 判定与任务计数
    expect(await screen.findByText("判定有漏洞（1）")).toBeTruthy();
    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);

    // 条件按假设组织，显示“有支持证据”与解释
    expect(screen.getByText("h1")).toBeTruthy();
    expect(screen.getByText("复制长度可能超过目标容量")).toBeTruthy();
    expect(screen.getByText("有支持证据")).toBeTruthy();
    expect(screen.getByText("复制长度可超过剩余容量")).toBeTruthy();
    // 同一句理由同时出现在条件的 reason 与判定理由中。
    expect(
      screen.getAllByText("合成脚本：调用中没有容量参数或上界检查，按预设示例输出 1。"),
    ).toHaveLength(2);

    // 证据：代码路径/行号与历史来源
    const evidenceList = screen.getByText("证据").closest(".section") as HTMLElement;
    expect(within(evidenceList).getByText("src/copy.c:1-1")).toBeTruthy();
    expect(within(evidenceList).getByText("case_id=synthetic-history-001")).toBeTruthy();

    // 点击条件引用的 evidence_id 后，对应证据展开并显示原文片段
    expect(document.querySelector("pre.code-block")).toBeNull();
    fireEvent.click(within(evidenceList).getByRole("button", { name: /^e1/ }));
    await waitFor(() =>
      expect(document.querySelector("pre.code-block")?.textContent).toContain("memcpy(dst, src, n)"),
    );

    // 分析记录包含检索与仓库读取
    const traceList = screen.getByText("分析记录").closest(".section") as HTMLElement;
    expect(within(traceList).getByText("检索历史案例")).toBeTruthy();
    expect(within(traceList).getByText("定位目标函数")).toBeTruthy();
  });

  it("忽略重放的重复事件与迟到的旧快照", async () => {
    await submitSingleSample();
    await emit(DEMO_TASK_EVENTS);
    const before = document.body.textContent;

    await emit(DEMO_TASK_EVENTS);
    await emit([{ ...DEMO_TASK_EVENTS[0], seq: 1 }]);

    expect(document.body.textContent).toBe(before);
  });
});

describe("App 批量流程", () => {
  it("同名局部 ID 的样本按原类型 idx 分开显示与切换", async () => {
    const reportFor = (idx: number | string, prediction: 0 | 1) => ({
      idx,
      prediction,
      reason: `idx=${String(idx)} 的判定理由。`,
      ...EMPTY_ANALYSIS,
    });
    server.view = taskView({ total: 2, completed: 2, status: "completed" });
    server.snapshot = reportsSnapshot({
      seq: 4,
      reports: [reportFor(1, 1), reportFor("1", 0)],
    });

    render(<App />);
    fireEvent.click(screen.getByRole("tab", { name: "批量 JSONL" }));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"idx":1}\n'], "synthetic.jsonl", { type: "application/x-ndjson" });
    Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
    fireEvent.change(fileInput);
    fireEvent.click(screen.getByRole("button", { name: "上传并开始批量检测" }));

    const list = (await screen.findByText("样本")).closest(".sample-list") as HTMLElement;
    const items = within(list).getAllByRole("button");
    expect(items).toHaveLength(2);
    expect(within(list).getByText("整数")).toBeTruthy();
    expect(within(list).getByText("字符串")).toBeTruthy();
    expect(within(list).getByText('"1"')).toBeTruthy();

    // 两个样本各自保留自己的判定，不互相覆盖
    fireEvent.click(items[1]);
    expect(await screen.findByText("idx=1 的判定理由。")).toBeTruthy();
    expect(screen.getByText("判定无漏洞（0）")).toBeTruthy();
  });
});

describe("App 失败与导出", () => {
  it("样本失败后保留已有分析并列出失败原因", async () => {
    await submitSingleSample();
    await emit([
      { ...DEMO_TASK_EVENTS[2], seq: 1 },
      {
        task_id: DEMO_TASK_ID,
        seq: 2,
        timestamp: "2026-01-01T00:00:02Z",
        type: "error",
        payload: { code: "analysis_timeout", message: "分析超时。" },
        idx: "1",
      },
      {
        task_id: DEMO_TASK_ID,
        seq: 3,
        timestamp: "2026-01-01T00:00:03Z",
        type: "task_completed",
        payload: { status: "failed" },
        idx: null,
      },
    ]);

    const failures = (await screen.findByText("执行失败")).closest(".failures") as HTMLElement;
    expect(within(failures).getByText("分析超时")).toBeTruthy();
    expect(within(failures).getByText("分析超时。")).toBeTruthy();
    expect(screen.getAllByText("失败").length).toBeGreaterThan(0);
  });

  it("导出不完整时展示后端返回的原因", async () => {
    server.resultStatus = 409;
    server.resultBody = {
      code: "result_incomplete",
      message: "Task does not have a complete unique result set.",
    };
    await submitSingleSample();

    fireEvent.click(screen.getByRole("button", { name: "下载 result.jsonl" }));

    const notice = (await screen.findByText("无法导出结果")).closest(".notice") as HTMLElement;
    expect(within(notice).getByText("result_incomplete")).toBeTruthy();
    expect(
      within(notice).getByText("Task does not have a complete unique result set."),
    ).toBeTruthy();
  });
});
