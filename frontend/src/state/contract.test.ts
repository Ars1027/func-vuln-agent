import { describe, expect, it } from "vitest";

import type { TaskView } from "../api/types";
import { DEMO_TASK_EVENTS, DEMO_TASK_ID } from "./fixtures/demoEvents";
import { createInitialTaskState, sampleList, taskProgress, taskReducer } from "./store";

const VIEW: TaskView = {
  task_id: DEMO_TASK_ID,
  status: "queued",
  mode: "conditions",
  total: 1,
  completed: 0,
  failures: [],
};

/** 按真实顺序重放录制的事件流：先 task_view，再逐条应用。 */
function replay() {
  let state = taskReducer(createInitialTaskState(), { type: "task_view", view: VIEW });
  for (const event of DEMO_TASK_EVENTS) {
    state = taskReducer(state, { type: "event", event });
  }
  return state;
}

describe("真实事件流回放（录制自 app.demo）", () => {
  it("逐条应用后得到与后端一致的报告快照", () => {
    const state = replay();
    const samples = sampleList(state);
    expect(samples).toHaveLength(1);

    const sample = samples[0];
    expect(sample.idx).toBe("1");
    expect(sample.status).toBe("completed");
    expect(sample.prediction).toBe(1);
    expect(state.status).toBe("completed");
    expect(state.mode).toBe("conditions");
    expect(state.seq).toBe(12);
    expect(taskProgress(state)).toEqual({ total: 1, completed: 1, failed: 0, running: 0 });
  });

  it("按 id 合并的假设、条件与证据与 /reports 一致", () => {
    const sample = replay().samples["s:1"];

    expect(sample.analysis.hypotheses).toEqual([
      { id: "h1", statement: "复制长度可能超过目标容量" },
    ]);
    expect(sample.analysis.conditions).toHaveLength(1);
    expect(sample.analysis.conditions[0].status).toBe("supported");
    expect(sample.analysis.conditions[0].evidence_ids).toEqual(["e1"]);

    // e1 由三条 condition_update 反复推送，只保留一条；e2 由检索产生。
    expect(sample.analysis.evidence.map((item) => item.id)).toEqual(["e1", "e2"]);
    const code = sample.analysis.evidence[0];
    const historical = sample.analysis.evidence[1];
    expect(code.kind === "code" && `${code.path}:${code.start_line}-${code.end_line}`).toBe(
      "src/copy.c:1-1",
    );
    expect(historical.kind === "historical" && historical.case_id).toBe("synthetic-history-001");
  });

  it("检索与仓库读取事件按类型追加到分析记录", () => {
    const trace = replay().samples["s:1"].analysis.trace;
    expect(trace.map((entry) => entry.tool)).toEqual([
      "locate_function",
      "search_cases",
      "find_symbol",
    ]);
  });

  it("重复推送与迟到的旧快照不改变最终状态", () => {
    let state = replay();
    const before = JSON.stringify(state);

    // 断线重连时服务端重放整段事件，UI 必须忽略已应用的序号。
    for (const event of DEMO_TASK_EVENTS) {
      state = taskReducer(state, { type: "event", event });
    }
    // 迟到的旧快照 seq 更小，不覆盖当前状态。
    state = taskReducer(state, {
      type: "snapshot",
      snapshot: {
        task_id: DEMO_TASK_ID,
        seq: 3,
        reports: [],
        active_samples: [],
        failed_samples: [],
        failures: [],
      },
    });

    expect(JSON.stringify(state)).toBe(before);
  });

  it("从中间序号续接时补齐剩余状态", () => {
    let state = taskReducer(createInitialTaskState(), { type: "task_view", view: VIEW });
    const resumed = DEMO_TASK_EVENTS.filter((event) => event.seq > 9);
    for (const event of resumed) {
      state = taskReducer(state, { type: "event", event });
    }

    expect(state.seq).toBe(12);
    expect(state.samples["s:1"].status).toBe("completed");
    expect(state.samples["s:1"].prediction).toBe(1);
  });
});
