import type { EventEnvelope } from "../../api/types";

/**
 * 真实录制的事件流。
 *
 * 来源：本地 `app.demo` 演示后端（`uv run uvicorn app.demo:build_app --factory --app-dir backend`），
 * 用 `POST /api/detections` 提交 `snapshot_ref=s-a83f`（合成漏洞版）后，
 * 从 `GET /api/tasks/{task_id}/events?after_seq=0` 原样录制的 12 条 `data:` 载荷。
 *
 * 用途：锁定前端对真实接口输出（事件类型、payload 字段、evidence 形状）的解析，
 * 后端的载荷结构变化会让本文件对应的测试失败。合成内容不代表真实检测效果。
 */
export const DEMO_TASK_ID = "dfe99e5256e849a08e9c738ba4eb802d";

export const DEMO_TASK_EVENTS: EventEnvelope[] = [
  {
    task_id: DEMO_TASK_ID,
    seq: 1,
    timestamp: "2026-10-16T16:11:49.554288Z",
    type: "task_status",
    payload: { status: "queued", mode: "conditions" },
    idx: null,
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 2,
    timestamp: "2026-10-16T16:11:49.566552Z",
    type: "task_status",
    payload: { status: "running" },
    idx: null,
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 3,
    timestamp: "2026-10-16T16:11:49.576466Z",
    type: "condition_update",
    payload: { hypotheses: [], conditions: [], evidence: [] },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 4,
    timestamp: "2026-10-16T16:11:49.586051Z",
    type: "condition_update",
    payload: {
      hypotheses: [],
      conditions: [],
      evidence: [
        {
          snapshot_ref: "s-a83f",
          path: "src/copy.c",
          start_line: 1,
          end_line: 1,
          content: "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }",
          id: "e1",
          kind: "code",
        },
      ],
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 5,
    timestamp: "2026-10-16T16:11:49.597059Z",
    type: "repository_read",
    payload: {
      tool: "locate_function",
      arguments: {},
      matches: [{ evidence_id: "e1", path: "src/copy.c", start_line: 1, end_line: 1 }],
      scope: "target function",
      evidence_ids: ["e1"],
      summary: "Located target function",
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 6,
    timestamp: "2026-10-16T16:11:49.612141Z",
    type: "condition_update",
    payload: {
      hypotheses: [],
      conditions: [],
      evidence: [
        {
          id: "e2",
          kind: "historical",
          content: "Synthetic history: memcpy into a fixed buffer without a size check.",
          case_id: "synthetic-history-001",
          source: "app.demo:artificial-history",
        },
      ],
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 7,
    timestamp: "2026-10-16T16:11:49.626892Z",
    type: "retrieval",
    payload: {
      query: "copy length and capacity",
      limit: 1,
      case_ids: ["synthetic-history-001"],
      sources: ["app.demo:artificial-history"],
      evidence_ids: ["e2"],
      summary: "Found 1 historical cases",
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 8,
    timestamp: "2026-10-16T16:11:49.641723Z",
    type: "condition_update",
    payload: {
      hypotheses: [{ id: "h1", statement: "复制长度可能超过目标容量" }],
      conditions: [
        {
          id: "c1",
          hypothesis_id: "h1",
          statement: "复制长度可超过剩余容量",
          status: "unknown",
          evidence_ids: ["e1"],
          reason: "尚未检查边界条件。",
        },
      ],
      evidence: [
        {
          snapshot_ref: "s-a83f",
          path: "src/copy.c",
          start_line: 1,
          end_line: 1,
          content: "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }",
          id: "e1",
          kind: "code",
        },
      ],
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 9,
    timestamp: "2026-10-16T16:11:49.657040Z",
    type: "repository_read",
    payload: {
      tool: "find_symbol",
      arguments: { symbol: "copy_checked" },
      matches: [],
      scope: "synthetic text matches only; not AST symbol resolution",
      evidence_ids: [],
      summary: "Found 0 code locations",
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 10,
    timestamp: "2026-10-16T16:11:49.670624Z",
    type: "condition_update",
    payload: {
      hypotheses: [{ id: "h1", statement: "复制长度可能超过目标容量" }],
      conditions: [
        {
          id: "c1",
          hypothesis_id: "h1",
          statement: "复制长度可超过剩余容量",
          status: "supported",
          evidence_ids: ["e1"],
          reason: "合成脚本：调用中没有容量参数或上界检查，按预设示例输出 1。",
        },
      ],
      evidence: [
        {
          snapshot_ref: "s-a83f",
          path: "src/copy.c",
          start_line: 1,
          end_line: 1,
          content: "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }",
          id: "e1",
          kind: "code",
        },
      ],
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 11,
    timestamp: "2026-10-16T16:11:49.684604Z",
    type: "sample_completed",
    payload: {
      report: {
        hypotheses: [{ id: "h1", statement: "复制长度可能超过目标容量" }],
        conditions: [
          {
            id: "c1",
            hypothesis_id: "h1",
            statement: "复制长度可超过剩余容量",
            status: "supported",
            evidence_ids: ["e1"],
            reason: "合成脚本：调用中没有容量参数或上界检查，按预设示例输出 1。",
          },
        ],
        evidence: [
          {
            snapshot_ref: "s-a83f",
            path: "src/copy.c",
            start_line: 1,
            end_line: 1,
            content: "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }",
            id: "e1",
            kind: "code",
          },
          {
            id: "e2",
            kind: "historical",
            content: "Synthetic history: memcpy into a fixed buffer without a size check.",
            case_id: "synthetic-history-001",
            source: "app.demo:artificial-history",
          },
        ],
        trace: [
          { tool: "locate_function", arguments: {}, summary: "Located target function", evidence_ids: ["e1"] },
          {
            tool: "search_cases",
            arguments: { query: "copy length and capacity", limit: 1 },
            summary: "Found 1 historical cases",
            evidence_ids: ["e2"],
          },
          {
            tool: "find_symbol",
            arguments: { symbol: "copy_checked" },
            summary: "Found 0 code locations",
            evidence_ids: [],
          },
        ],
        idx: "1",
        prediction: 1,
        reason: "合成脚本：调用中没有容量参数或上界检查，按预设示例输出 1。",
      },
    },
    idx: "1",
  },
  {
    task_id: DEMO_TASK_ID,
    seq: 12,
    timestamp: "2026-10-16T16:11:49.696586Z",
    type: "task_completed",
    payload: { status: "completed" },
    idx: null,
  },
];
