import { ApiError } from "../api/client";

export interface DisplayError {
  code: string;
  message: string;
}

export function describeError(error: unknown): DisplayError {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof Error) {
    return { code: "unexpected_error", message: error.message };
  }
  return { code: "unexpected_error", message: "发生未知错误。" };
}

/**
 * 后端 `code` 的中文说明；未收录的代码直接显示原值，避免掩盖服务端信息。
 * 取值来自 `backend/app/api/service.py`、`agent/runner.py` 与各适配器。
 */
export const ERROR_CODE_LABELS: Record<string, string> = {
  // 请求与任务
  network_error: "无法连接检测服务",
  invalid_request: "请求参数不合法",
  task_not_found: "任务不存在",
  invalid_sequence: "事件序号不合法",
  internal_error: "服务内部错误",
  // 批量上传
  invalid_jsonl: "JSONL 格式不正确",
  duplicate_idx: "存在重复的样本标识",
  empty_batch: "文件没有样本",
  batch_too_large: "文件超过大小或数量上限",
  // 准备层
  preparation_mismatch: "准备层改动了函数或标识",
  preparation_timeout: "快照准备超时",
  snapshot_not_found: "快照不存在",
  function_mismatch: "函数与快照不一致",
  synthetic_input_only: "演示入口只接受合成样例",
  dependency_unavailable: "依赖模块尚未接入",
  interrupted: "任务被服务重启中断",
  // 分析
  analysis_timeout: "分析超时",
  budget_exhausted: "模型或工具预算耗尽",
  model_failed: "模型调用失败",
  model_unconfigured: "模型未配置",
  tool_failed: "工具执行失败",
  tool_unavailable: "工具在当前模式下不可用",
  malformed_model_output: "模型输出无法解析",
  timeout: "分析超时",
  report_mismatch: "报告标识与分析输入不一致",
  measurement_mismatch: "测量信息与任务配置不一致",
  // 仓库工具
  file_not_found: "快照内没有该文件",
  invalid_line_range: "行区间超出文件范围",
  historical_case_conflict: "历史案例来源或正文冲突",
  // 导出
  result_incomplete: "结果尚未完整",
  result_mismatch: "结果与输入不一致",
};

export function errorCodeLabel(code: string): string {
  return ERROR_CODE_LABELS[code] ?? code;
}
