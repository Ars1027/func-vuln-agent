import { Cpu, Gauge, RefreshCw, Wrench } from "lucide-react";

import type { Measurement } from "../api/types";
import type { DisplayError } from "../lib/errors";
import { ErrorNotice } from "./ErrorNotice";

interface Props {
  measurements: Measurement[] | null;
  loading: boolean;
  error: DisplayError | null;
  onRefresh: () => void;
}

function sumNullable(values: Array<number | null>): { total: number; missing: number } {
  let total = 0;
  let missing = 0;
  for (const v of values) {
    if (v === null) {
      missing += 1;
    } else {
      total += v;
    }
  }
  return { total, missing };
}

/**
 * 任务级实验测量抽屉（按需读取 GET /api/tasks/{task_id}/measurements）。
 * 严格遵循 docs/interfaces.md §8：服务未返回的用量标为“缺失”，不把未知成本记作 0。
 */
export function TelemetryDrawer({ measurements, loading, error, onRefresh }: Props) {
  const firstConfig = measurements?.[0]?.config ?? null;
  const modelCalls = sumNullable((measurements ?? []).map((m) => m.model_calls));
  const toolCalls = sumNullable((measurements ?? []).map((m) => m.tool_calls));
  const inputTokens = sumNullable((measurements ?? []).map((m) => m.input_tokens));
  const outputTokens = sumNullable((measurements ?? []).map((m) => m.output_tokens));

  return (
    <div className="telemetry-drawer">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <Gauge size={14} className="text-accent" aria-hidden="true" />
          <span>实验配置与运行测量</span>
          {measurements !== null && (
            <span className="muted font-normal">（已采集 {measurements.length} 条样本记录）</span>
          )}
        </div>
        <button
          type="button"
          className="button button--small"
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} aria-hidden="true" />
          {loading ? "读取中…" : "刷新测量"}
        </button>
      </div>

      {error !== null && (
        <ErrorNotice title="读取实验测量失败" code={error.code} message={error.message} />
      )}

      {measurements !== null && measurements.length === 0 && !loading && (
        <p className="field__hint mt-2">当前尚无已落盘的样本测量记录，待样本执行后再刷新查看。</p>
      )}

      {measurements !== null && measurements.length > 0 && (
        <>
          <div className="telemetry-grid">
            <div className="telemetry-card">
              <div className="telemetry-card__label flex items-center gap-1">
                <Cpu size={12} aria-hidden="true" /> 模型调用轮次
              </div>
              <div className="telemetry-card__value">
                {modelCalls.total}
                {modelCalls.missing > 0 && (
                  <span className="text-xs font-normal muted">（{modelCalls.missing} 项缺失）</span>
                )}
              </div>
            </div>
            <div className="telemetry-card">
              <div className="telemetry-card__label flex items-center gap-1">
                <Wrench size={12} aria-hidden="true" /> 工具调用次数
              </div>
              <div className="telemetry-card__value">
                {toolCalls.total}
                {toolCalls.missing > 0 && (
                  <span className="text-xs font-normal muted">（{toolCalls.missing} 项缺失）</span>
                )}
              </div>
            </div>
            <div className="telemetry-card">
              <div className="telemetry-card__label">输入 Tokens</div>
              <div className="telemetry-card__value">
                {inputTokens.missing === measurements.length
                  ? "未返回（缺失）"
                  : inputTokens.total.toLocaleString()}
              </div>
            </div>
            <div className="telemetry-card">
              <div className="telemetry-card__label">输出 Tokens</div>
              <div className="telemetry-card__value">
                {outputTokens.missing === measurements.length
                  ? "未返回（缺失）"
                  : outputTokens.total.toLocaleString()}
              </div>
            </div>
          </div>

          {firstConfig !== null && (
            <dl className="kv mt-2.5">
              <div>
                <dt>model</dt>
                <dd className="mono">{firstConfig.model}</dd>
              </div>
              <div>
                <dt>temperature</dt>
                <dd className="mono">{firstConfig.temperature}</dd>
              </div>
              <div>
                <dt>预算（模型 / 工具）</dt>
                <dd className="mono">
                  {firstConfig.max_model_calls} / {firstConfig.max_tool_calls}
                </dd>
              </div>
              <div>
                <dt>prompt_version</dt>
                <dd className="mono">{firstConfig.prompt_version}</dd>
              </div>
            </dl>
          )}
        </>
      )}
    </div>
  );
}
