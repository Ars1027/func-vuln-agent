import { describe, expect, it } from "vitest";

import { taskEventsUrl } from "./sse";

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
