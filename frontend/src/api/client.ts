import type {
  DetectionInput,
  DetectionRequest,
  ErrorBody,
  Measurement,
  Mode,
  ReportsSnapshot,
  SnapshotRequest,
  TaskView,
} from "./types";

/**
 * 后端基地址。留空表示同源请求：
 * 开发时由 vite.config.ts 的 /api 代理转发；部署时可由 VITE_API_BASE_URL 指定。
 */
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function apiUrl(path: string): string {
  return `${baseUrl}${path}`;
}

async function readError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as Partial<ErrorBody>;
    if (typeof body.code === "string" && body.code) {
      code = body.code;
    }
    if (typeof body.message === "string" && body.message) {
      message = body.message;
    }
  } catch {
    // 非 JSON 响应沿用状态码描述。
  }
  return new ApiError(response.status, code, message);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), init);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "未知网络错误";
    throw new ApiError(0, "network_error", `无法连接检测服务：${detail}`);
  }
  if (!response.ok) {
    throw await readError(response);
  }
  return (await response.json()) as T;
}

/** POST /api/snapshots：按 commit_url 与 revision 准备单版本快照。 */
export function createSnapshot(request: SnapshotRequest): Promise<DetectionInput> {
  return requestJson<DetectionInput>("/api/snapshots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** POST /api/detections：提交单条检测请求。 */
export function createDetection(request: DetectionRequest): Promise<TaskView> {
  return requestJson<TaskView>("/api/detections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** POST /api/batches：multipart 上传课程 JSONL，字段名为 file 与 mode。 */
export function createBatch(file: File, mode: Mode): Promise<TaskView> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  return requestJson<TaskView>("/api/batches", { method: "POST", body: form });
}

/** GET /api/tasks/{task_id}：状态、完成计数与失败项。 */
export function getTask(taskId: string): Promise<TaskView> {
  return requestJson<TaskView>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

/** GET /api/tasks/{task_id}/reports：截至 seq 的一致状态快照。 */
export function getReports(taskId: string): Promise<ReportsSnapshot> {
  return requestJson<ReportsSnapshot>(`/api/tasks/${encodeURIComponent(taskId)}/reports`);
}

/** GET /api/tasks/{task_id}/measurements：逐样本实验配置与执行状态。 */
export async function getMeasurements(taskId: string): Promise<Measurement[]> {
  const body = await requestJson<{ task_id: string; measurements: Measurement[] }>(
    `/api/tasks/${encodeURIComponent(taskId)}/measurements`,
  );
  return body.measurements;
}

/**
 * GET /api/tasks/{task_id}/result.jsonl。
 * 任务未完整时后端返回 409，前端据此展示不可导出的原因。
 */
export async function fetchResult(taskId: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/result.jsonl`));
  } catch (error) {
    const detail = error instanceof Error ? error.message : "未知网络错误";
    throw new ApiError(0, "network_error", `无法下载结果：${detail}`);
  }
  if (!response.ok) {
    throw await readError(response);
  }
  return response.text();
}
