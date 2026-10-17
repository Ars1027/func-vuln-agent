import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getReports, getTask } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function stubFetch(body: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(body, status)),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("响应中的整数 idx", () => {
  it("安全整数范围内按数字返回，与字符串标识不混淆", async () => {
    stubFetch({
      task_id: "task-1",
      seq: 1,
      reports: [{ idx: 1 }],
      active_samples: [{ idx: "1" }],
      failed_samples: [],
      failures: [],
    });

    const snapshot = await getReports("task-1");

    expect(snapshot.reports[0].idx).toBe(1);
    expect(snapshot.active_samples[0].idx).toBe("1");
  });

  it("超出安全整数范围时报错，而不是静默把两个样本合并", async () => {
    // 真实响应里这两个字面量在 JSON.parse 后都会变成 9007199254740992。
    stubFetch(JSON.parse('{"task_id":"task-1","seq":1,"reports":[{"idx":9007199254740993},{"idx":9007199254740992}],"active_samples":[],"failed_samples":[],"failures":[]}'));

    const error = await getReports("task-1").catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("idx_not_representable");
    expect((error as ApiError).message).toContain("reports[0].idx");
  });

  it("任务状态中的失败项同样不接受失真标识", async () => {
    stubFetch(JSON.parse('{"task_id":"task-1","status":"failed","mode":"conditions","total":1,"completed":0,"failures":[{"idx":9007199254740993,"code":"interrupted","message":"中断"}]}'));

    const error = await getTask("task-1").catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("idx_not_representable");
    expect((error as ApiError).message).toContain("failures[0].idx");
  });
});
