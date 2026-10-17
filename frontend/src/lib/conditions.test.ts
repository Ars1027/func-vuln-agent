import { describe, expect, it } from "vitest";

import type { Condition } from "../api/types";
import { CONDITION_ORDER, summarizeConditions } from "./conditions";

function condition(id: string, status: Condition["status"]): Condition {
  return {
    id,
    hypothesis_id: "h1",
    statement: `条件 ${id}`,
    status,
    evidence_ids: [],
    reason: "—",
  };
}

describe("summarizeConditions", () => {
  it("按状态计数并给出总数", () => {
    const counts = summarizeConditions([
      condition("c1", "supported"),
      condition("c2", "supported"),
      condition("c3", "refuted"),
      condition("c4", "unknown"),
    ]);

    expect(counts).toEqual({ total: 4, supported: 2, refuted: 1, unknown: 1 });
  });

  it("空列表全为 0，界面据此不渲染概览", () => {
    expect(summarizeConditions([])).toEqual({ total: 0, supported: 0, refuted: 0, unknown: 0 });
  });

  it("展示顺序固定为 支持 → 待确认 → 反证", () => {
    expect(CONDITION_ORDER).toEqual(["supported", "unknown", "refuted"]);
  });
});
