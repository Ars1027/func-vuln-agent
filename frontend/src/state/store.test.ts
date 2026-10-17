import { describe, expect, it } from "vitest";

import type {
  CodeEvidence,
  EventEnvelope,
  EventType,
  Idx,
  ReportsSnapshot,
  TaskView,
} from "../api/types";
import { conditionsByHypothesis, createInitialTaskState, sampleList, taskProgress, taskReducer } from "./store";

function event(
  type: EventType,
  seq: number,
  options: { idx?: Idx | null; payload?: Record<string, unknown>; taskId?: string } = {},
): EventEnvelope {
  return {
    task_id: options.taskId ?? "task-1",
    seq,
    timestamp: "2026-01-01T00:00:00Z",
    type,
    payload: options.payload ?? {},
    idx: options.idx ?? null,
  };
}

function apply(state: ReturnType<typeof createInitialTaskState>, events: EventEnvelope[]) {
  return events.reduce(
    (current, item) => taskReducer(current, { type: "event", event: item }),
    state,
  );
}

function codeEvidence(id: string, content = "memcpy(dst, src, n);"): CodeEvidence {
  return {
    id,
    kind: "code",
    snapshot_ref: "s-a83f",
    path: "src/copy.c",
    start_line: 1,
    end_line: 1,
    content,
  };
}

describe("taskReducer 快照", () => {
  const snapshot: ReportsSnapshot = {
    task_id: "task-1",
    seq: 7,
    reports: [
      {
        idx: 1,
        prediction: 1,
        reason: "复制长度无上界。",
        hypotheses: [{ id: "h1", statement: "复制长度可能超过目标容量" }],
        conditions: [
          {
            id: "c1",
            hypothesis_id: "h1",
            statement: "复制长度可超过剩余容量",
            status: "supported",
            evidence_ids: ["e1"],
            reason: "没有容量参数。",
          },
        ],
        evidence: [codeEvidence("e1")],
        trace: [],
      },
    ],
    active_samples: [
      {
        idx: "1",
        hypotheses: [],
        conditions: [],
        evidence: [],
        trace: [
          { tool: "search_cases", arguments: { query: "memcpy" }, summary: "Found 1", evidence_ids: [] },
        ],
      },
    ],
    failed_samples: [
      {
        idx: "broken",
        hypotheses: [],
        conditions: [],
        evidence: [],
        trace: [],
      },
    ],
    failures: [{ idx: "broken", code: "model_failed", message: "模型初始化失败。" }],
  };

  it("恢复完成、运行中和失败样本，并记录 seq", () => {
    const state = taskReducer(createInitialTaskState(), {
      type: "task_view",
      view: { task_id: "task-1", status: "running", mode: "conditions", total: 3, completed: 1, failures: [] },
    });
    const next = taskReducer(state, { type: "snapshot", snapshot });

    expect(next.seq).toBe(7);
    expect(next.order).toEqual(["n:1", "s:1", "s:broken"]);
    expect(next.samples["n:1"].status).toBe("completed");
    expect(next.samples["n:1"].prediction).toBe(1);
    expect(next.samples["s:1"].status).toBe("running");
    expect(next.samples["s:broken"].status).toBe("failed");
    expect(next.samples["s:broken"].failure?.code).toBe("model_failed");
    expect(taskProgress(next)).toEqual({ total: 3, completed: 1, failed: 1, running: 1 });
  });

  it("迟到且更旧的快照不覆盖当前状态", () => {
    let state = taskReducer(createInitialTaskState(), { type: "snapshot", snapshot });
    state = apply(state, [event("task_status", 8, { payload: { status: "running" } })]);

    const stale: ReportsSnapshot = { ...snapshot, seq: 4, reports: [], failures: [] };
    const next = taskReducer(state, { type: "snapshot", snapshot: stale });

    expect(next.seq).toBe(8);
    expect(next.order).toEqual(["n:1", "s:1", "s:broken"]);
  });

  it("序号不早于本地的快照按权威状态重建", () => {
    const state = taskReducer(createInitialTaskState(), { type: "snapshot", snapshot });
    const newer: ReportsSnapshot = { ...snapshot, seq: 9, reports: [], active_samples: [], failed_samples: [], failures: [] };
    const next = taskReducer(state, { type: "snapshot", snapshot: newer });

    expect(next.seq).toBe(9);
    expect(sampleList(next)).toHaveLength(0);
  });
});

describe("taskReducer 事件", () => {
  it("忽略其它任务或更旧序号的事件", () => {
    const view: TaskView = {
      task_id: "task-1",
      status: "running",
      mode: "conditions",
      total: 1,
      completed: 0,
      failures: [],
    };
    let state = taskReducer(createInitialTaskState(), { type: "task_view", view });
    state = apply(state, [event("task_status", 5, { payload: { status: "running" } })]);
    state = apply(state, [
      event("task_status", 5, { payload: { status: "failed" } }),
      event("task_status", 6, { payload: { status: "failed" }, taskId: "task-other" }),
    ]);

    expect(state.seq).toBe(5);
    expect(state.status).toBe("running");
  });

  it("同一任务内不同样本的同名局部 ID 互不覆盖，整数与字符串 idx 分开", () => {
    const payload = {
      hypotheses: [{ id: "h1", statement: "假设一" }],
      conditions: [
        {
          id: "c1",
          hypothesis_id: "h1",
          statement: "条件一",
          status: "unknown",
          evidence_ids: ["e1"],
          reason: "待确认。",
        },
      ],
      evidence: [codeEvidence("e1")],
    };
    const state = apply(createInitialTaskState(), [
      event("condition_update", 1, { idx: 1, payload }),
      event("condition_update", 2, { idx: "1", payload }),
    ]);

    expect(state.order).toEqual(["n:1", "s:1"]);
    expect(state.samples["n:1"].analysis.conditions[0].id).toBe("c1");
    expect(state.samples["s:1"].analysis.conditions[0].id).toBe("c1");
    const evidence = state.samples["n:1"].analysis.evidence[0];
    expect(evidence.kind).toBe("code");
    expect(evidence.kind === "code" && evidence.path).toBe("src/copy.c");
  });

  it("condition_update 在样本内按 id 合并更新", () => {
    const first = {
      hypotheses: [{ id: "h1", statement: "假设一" }],
      conditions: [],
      evidence: [codeEvidence("e1", "旧片段")],
    };
    const second = {
      hypotheses: [],
      conditions: [
        {
          id: "c1",
          hypothesis_id: "h1",
          statement: "条件一",
          status: "supported",
          evidence_ids: ["e1"],
          reason: "缺少容量参数。",
        },
      ],
      evidence: [codeEvidence("e1", "新片段")],
    };

    const state = apply(createInitialTaskState(), [
      event("condition_update", 1, { idx: 1, payload: first }),
      event("condition_update", 2, { idx: 1, payload: second }),
    ]);
    const sample = state.samples["n:1"];

    expect(sample.analysis.hypotheses).toHaveLength(1);
    expect(sample.analysis.conditions).toHaveLength(1);
    expect(sample.analysis.evidence).toHaveLength(1);
    expect(sample.analysis.evidence[0].content).toBe("新片段");
    expect(sample.analysis.conditions[0].status).toBe("supported");
  });

  it("检索与仓库读取事件按顺序追加分析记录", () => {
    const state = apply(createInitialTaskState(), [
      event("retrieval", 1, {
        idx: "a",
        payload: { query: "memcpy", limit: 2, summary: "Found 2 historical cases", evidence_ids: ["e1"] },
      }),
      event("repository_read", 2, {
        idx: "a",
        payload: {
          tool: "read_file",
          arguments: { path: "src/helper.c", start_line: 1, end_line: 3 },
          summary: "Found 1 code locations",
          evidence_ids: ["e2"],
        },
      }),
    ]);
    const sample = state.samples["s:a"];

    expect(sample.analysis.trace).toHaveLength(2);
    expect(sample.analysis.trace[0].tool).toBe("search_cases");
    expect(sample.analysis.trace[0].arguments).toEqual({ query: "memcpy", limit: 2 });
    expect(sample.analysis.trace[1].tool).toBe("read_file");
    expect(sample.analysis.trace[1].evidence_ids).toEqual(["e2"]);
  });

  it("sample_completed 覆盖为完整报告并清除失败记录", () => {
    let state = apply(createInitialTaskState(), [
      event("error", 1, { idx: 2, payload: { idx: 2, code: "analysis_timeout", message: "超时。" } }),
    ]);
    expect(state.samples["n:2"].status).toBe("failed");
    expect(state.failures).toHaveLength(1);

    state = apply(state, [
      event("sample_completed", 2, {
        idx: 2,
        payload: {
          report: {
            idx: 2,
            prediction: 0,
            reason: "已检查主要假设。",
            hypotheses: [],
            conditions: [],
            evidence: [],
            trace: [],
          },
        },
      }),
    ]);

    expect(state.samples["n:2"].status).toBe("completed");
    expect(state.samples["n:2"].prediction).toBe(0);
    expect(state.samples["n:2"].failure).toBeNull();
    expect(state.failures).toHaveLength(0);
  });

  it("error 事件保留已有分析并把样本移入失败，idx 为空时为任务级错误", () => {
    let state = apply(createInitialTaskState(), [
      event("condition_update", 1, {
        idx: "a",
        payload: { hypotheses: [{ id: "h1", statement: "假设一" }], conditions: [], evidence: [] },
      }),
    ]);
    state = apply(state, [
      event("error", 2, { idx: "a", payload: { code: "tool_failed", message: "仓库读取失败。" } }),
      event("error", 3, { payload: { code: "internal_error", message: "任务执行失败。" } }),
      event("task_completed", 4, { payload: { status: "failed" } }),
    ]);

    const sample = state.samples["s:a"];
    expect(sample.status).toBe("failed");
    expect(sample.failure?.code).toBe("tool_failed");
    expect(sample.analysis.hypotheses).toHaveLength(1);
    expect(state.failures[0].idx).toBe("a");
    expect(state.taskError).toEqual({ code: "internal_error", message: "任务执行失败。" });
    expect(state.status).toBe("failed");
    expect(state.connection).toBe("closed");
  });
});

describe("conditionsByHypothesis", () => {
  it("按假设分组，未匹配的条件单独列出而不丢弃", () => {
    const state = apply(createInitialTaskState(), [
      event("condition_update", 1, {
        idx: 1,
        payload: {
          hypotheses: [{ id: "h1", statement: "假设一" }],
          conditions: [
            {
              id: "c1",
              hypothesis_id: "h1",
              statement: "条件一",
              status: "refuted",
              evidence_ids: [],
              reason: "存在上界检查。",
            },
            {
              id: "c2",
              hypothesis_id: "h2",
              statement: "条件二",
              status: "unknown",
              evidence_ids: [],
              reason: "证据不足。",
            },
          ],
          evidence: [],
        },
      }),
    ]);
    const groups = conditionsByHypothesis(state.samples["n:1"]);

    expect(groups).toHaveLength(2);
    expect(groups[0].hypothesis.id).toBe("h1");
    expect(groups[0].conditions.map((item) => item.id)).toEqual(["c1"]);
    expect(groups[1].hypothesis.id).toBe("h2");
    expect(groups[1].conditions.map((item) => item.id)).toEqual(["c2"]);
  });
});
