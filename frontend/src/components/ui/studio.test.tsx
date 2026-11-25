// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import type { Measurement, ReportsSnapshot, TaskView } from "../../api/types";
import { highlightCpp } from "../../lib/highlightCpp";

class StubEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  readyState = StubEventSource.OPEN;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  addEventListener(): void {}
  close(): void {
    this.readyState = StubEventSource.CLOSED;
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

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.classList.remove("dark");
  vi.stubGlobal("EventSource", StubEventSource);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("highlightCpp 词法着色", () => {
  it("保留完整源码文本并标注关键字、类型与危险汇聚函数", () => {
    const code = 'void copy(char *dst, size_t n) {\n  // 注释\n  memcpy(dst, "abc", n);\n}';
    const { container } = render(
      <pre className="code-block">
        <code>{highlightCpp(code)}</code>
      </pre>,
    );

    expect(container.querySelector("pre.code-block")?.textContent).toBe(code);
    expect(container.querySelector(".tok-type")?.textContent).toBe("void");
    expect(container.querySelector(".tok-sink")?.textContent).toBe("memcpy");
    expect(container.querySelector(".tok-string")?.textContent).toBe('"abc"');
    expect(container.querySelector(".tok-comment")?.textContent).toContain("// 注释");
  });
});

describe("工作台交互增强", () => {
  it("支持亮/暗双主题切换与可折叠输入栏", () => {
    render(<App />);

    const themeBtn = screen.getByRole("button", { name: /深色|浅色/ });
    const initialTheme = document.documentElement.dataset.theme;
    fireEvent.click(themeBtn);
    expect(document.documentElement.dataset.theme).not.toBe(initialTheme);

    expect(screen.getByText("检测输入")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "宽屏审计" }));
    expect(screen.queryByText("检测输入")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "展开输入栏" }));
    expect(screen.getByText("检测输入")).toBeTruthy();
  });

  it("支持批量样本筛选以及按需读取 /measurements 实验测量指标", async () => {
    const view: TaskView = {
      task_id: "task-studio",
      status: "completed",
      mode: "conditions",
      total: 2,
      completed: 2,
      failures: [],
    };
    const snapshot: ReportsSnapshot = {
      task_id: "task-studio",
      seq: 6,
      reports: [
        {
          idx: "vuln-item",
          prediction: 1,
          reason: "存在越界写。",
          hypotheses: [],
          conditions: [],
          evidence: [
            {
              id: "e1",
              kind: "code",
              snapshot_ref: "s-1",
              path: "src/buf.c",
              start_line: 40,
              end_line: 41,
              content: "char buf[8];\nmemcpy(buf, src, len);",
            },
          ],
          trace: [],
        },
        {
          idx: "safe-item",
          prediction: 0,
          reason: "已有上界检查。",
          hypotheses: [],
          conditions: [],
          evidence: [],
          trace: [],
        },
      ],
      active_samples: [],
      failed_samples: [],
      failures: [],
    };
    const measurements: Measurement[] = [
      {
        idx: "vuln-item",
        mode: "conditions",
        config: {
          model: "demo-scripted-v1",
          temperature: 0,
          max_output_tokens: 1024,
          max_model_calls: 8,
          max_tool_calls: 6,
          timeout_seconds: 60,
          data_version: null,
          index_version: null,
          prompt_version: "v1",
        },
        model_calls: 3,
        tool_calls: 2,
        input_tokens: null,
        output_tokens: null,
        elapsed_seconds: 1.25,
        status: "completed",
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.endsWith("/api/batches")) {
          return jsonResponse(view, 202);
        }
        if (url.endsWith("/reports")) {
          return jsonResponse(snapshot);
        }
        if (url.endsWith("/measurements")) {
          return jsonResponse({ task_id: "task-studio", measurements });
        }
        if (url.endsWith("/api/tasks/task-studio")) {
          return jsonResponse(view);
        }
        throw new Error(`未预期的请求：${url}`);
      }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("tab", { name: "批量 JSONL" }));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"idx":"vuln-item"}\n'], "batch.jsonl", {
      type: "application/x-ndjson",
    });
    Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
    fireEvent.change(fileInput);
    fireEvent.click(screen.getByRole("button", { name: "上传并开始批量检测" }));

    const sampleListEl = (await screen.findByText("样本")).closest(".sample-list") as HTMLElement;
    expect(within(sampleListEl).getAllByRole("button")).toHaveLength(2);

    // 筛选“无漏洞”后仅剩 safe-item
    fireEvent.click(screen.getByRole("button", { name: "无漏洞" }));
    expect(within(sampleListEl).getAllByRole("button")).toHaveLength(1);
    expect(within(sampleListEl).getByText('"safe-item"')).toBeTruthy();

    // 切回“全部”并展开代码证据，校验源码真实行号 40、41
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    fireEvent.click(screen.getByRole("button", { name: /^e1/ }));
    const gutter = document.querySelector(".code-gutter");
    expect(gutter?.textContent).toBe("4041");

    // 按需打开“实验测量”，验证未返回 token 显示为“未返回（缺失）”而非 0
    fireEvent.click(screen.getByRole("button", { name: "实验测量" }));
    await waitFor(() => expect(screen.getByText("demo-scripted-v1")).toBeTruthy());
    expect(screen.getAllByText("未返回（缺失）")).toHaveLength(2);
    expect(screen.getByText(/3 轮模型/)).toBeTruthy();
  });
});
