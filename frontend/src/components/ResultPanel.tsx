import { PanelLeftOpen, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getMeasurements } from "../api/client";
import type { Failure, Measurement } from "../api/types";
import { describeError, type DisplayError } from "../lib/errors";
import { idxKey, idxLabel } from "../state/idx";
import { sampleList, type SampleState, type TaskState } from "../state/store";
import { FailureList } from "./FailureList";
import { ReportDiscussion } from "./ReportDiscussion";
import { SampleDetail } from "./SampleDetail";
import { SampleList } from "./SampleList";
import { TaskSummary } from "./TaskSummary";
import { EmptyState } from "./ui/EmptyState";
import { Skeleton } from "./ui/Skeleton";

type SampleFilter = "all" | "vuln" | "safe" | "running" | "failed";

const FILTER_OPTIONS: ReadonlyArray<{ key: SampleFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "vuln", label: "有漏洞" },
  { key: "safe", label: "无漏洞" },
  { key: "running", label: "分析中" },
  { key: "failed", label: "失败" },
];

function matchesFilter(sample: SampleState, filter: SampleFilter, query: string): boolean {
  if (filter === "vuln" && sample.prediction !== 1) {
    return false;
  }
  if (filter === "safe" && sample.prediction !== 0) {
    return false;
  }
  if (filter === "running" && sample.status !== "running") {
    return false;
  }
  if (filter === "failed" && sample.status !== "failed") {
    return false;
  }
  const trimmed = query.trim().toLowerCase();
  if (trimmed.length > 0) {
    return (
      String(sample.idx).toLowerCase().includes(trimmed) ||
      idxLabel(sample.idx).toLowerCase().includes(trimmed)
    );
  }
  return true;
}

interface Props {
  state: TaskState;
  loading: boolean;
  startedAt: number | null;
  loadError: DisplayError | null;
  downloadError: DisplayError | null;
  onReload: () => void;
  onDownload: () => void;
  onClearDownloadError: () => void;
  inputCollapsed?: boolean;
  onExpandInput?: () => void;
}

export function ResultPanel({
  state,
  loading,
  startedAt,
  loadError,
  downloadError,
  onReload,
  onDownload,
  onClearDownloadError,
  inputCollapsed = false,
  onExpandInput,
}: Props) {
  const samples = sampleList(state);
  const firstKey = state.order[0] ?? null;
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [filter, setFilter] = useState<SampleFilter>("all");
  const [query, setQuery] = useState("");

  // 按需请求实验测量，避免未授权的自动请求干扰基础事件流
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [measurements, setMeasurements] = useState<Measurement[] | null>(null);
  const [measurementsLoading, setMeasurementsLoading] = useState(false);
  const [measurementsError, setMeasurementsError] = useState<DisplayError | null>(null);
  const telemetryReqId = useRef(0);

  useEffect(() => {
    if (selectedKey === null || state.samples[selectedKey] === undefined) {
      setSelectedKey(firstKey);
    }
  }, [firstKey, selectedKey, state.samples]);

  // 切换任务时重置筛选与遥测面板状态
  useEffect(() => {
    telemetryReqId.current += 1;
    setFilter("all");
    setQuery("");
    setTelemetryOpen(false);
    setMeasurements(null);
    setMeasurementsError(null);
    setMeasurementsLoading(false);
  }, [state.taskId]);

  const loadTelemetry = useCallback(async (taskId: string) => {
    telemetryReqId.current += 1;
    const reqId = telemetryReqId.current;
    setMeasurementsLoading(true);
    setMeasurementsError(null);
    try {
      const items = await getMeasurements(taskId);
      if (telemetryReqId.current === reqId) {
        setMeasurements(items);
      }
    } catch (err) {
      if (telemetryReqId.current === reqId) {
        setMeasurementsError(describeError(err));
      }
    } finally {
      if (telemetryReqId.current === reqId) {
        setMeasurementsLoading(false);
      }
    }
  }, []);

  const toggleTelemetry = useCallback(() => {
    setTelemetryOpen((prev) => {
      const next = !prev;
      if (next && measurements === null && state.taskId !== null) {
        void loadTelemetry(state.taskId);
      }
      return next;
    });
  }, [loadTelemetry, measurements, state.taskId]);

  const refreshTelemetry = useCallback(() => {
    if (state.taskId !== null) {
      void loadTelemetry(state.taskId);
    }
  }, [loadTelemetry, state.taskId]);

  const measurementsByKey = useMemo(() => {
    const map = new Map<string, Measurement>();
    for (const item of measurements ?? []) {
      map.set(idxKey(item.idx), item);
    }
    return map;
  }, [measurements]);

  const filteredSamples = useMemo(
    () => samples.filter((s) => matchesFilter(s, filter, query)),
    [samples, filter, query],
  );

  if (state.taskId === null) {
    return (
      <section className="panel panel--placeholder">
        <EmptyState
          title="检测过程与报告"
          description="提交单样本或批量任务后，这里实时展示任务计数、漏洞假设与成立条件矩阵、带行号源码证据及自主取证轨迹。"
          hint={
            <>
              演示入口只接受 <code>examples/synthetic.jsonl</code> 中的合成样例。
            </>
          }
        >
          <div className="workflow-steps">
            <div className="workflow-step">
              <span className="workflow-step__num">01</span>
              <p className="workflow-step__title">准备单版本快照</p>
              <p className="workflow-step__desc">
                输入 C/C++ 函数并显式指定修复提交或父提交，严格隔离标签与 diff。
              </p>
            </div>
            <div className="workflow-step">
              <span className="workflow-step__num">02</span>
              <p className="workflow-step__title">条件驱动自主取证</p>
              <p className="workflow-step__desc">
                结合历史案例线索提出待核实条件，按需搜索并读取当前快照源码。
              </p>
            </div>
            <div className="workflow-step">
              <span className="workflow-step__num">03</span>
              <p className="workflow-step__title">核对反证与导出</p>
              <p className="workflow-step__desc">
                区分支持证据、反证与待确认条件，支持一键导出标准 result.jsonl。
              </p>
            </div>
          </div>
          {inputCollapsed && onExpandInput !== undefined && (
            <button type="button" className="button mt-4" onClick={onExpandInput}>
              <PanelLeftOpen size={14} aria-hidden="true" />
              展开检测输入面板
            </button>
          )}
        </EmptyState>
      </section>
    );
  }

  const selected = selectedKey === null ? undefined : state.samples[selectedKey];
  const selectFailure = (failure: Failure) => setSelectedKey(idxKey(failure.idx));

  return (
    <section className="panel">
      <TaskSummary
        state={state}
        loading={loading}
        startedAt={startedAt}
        loadError={loadError}
        downloadError={downloadError}
        onReload={onReload}
        onDownload={onDownload}
        onClearDownloadError={onClearDownloadError}
        telemetryOpen={telemetryOpen}
        measurements={measurements}
        measurementsLoading={measurementsLoading}
        measurementsError={measurementsError}
        onToggleTelemetry={toggleTelemetry}
        onRefreshTelemetry={refreshTelemetry}
      />

      <FailureList
        failures={state.failures}
        taskError={state.taskError}
        onSelect={selectFailure}
      />

      {samples.length === 0 ? (
        loading ? (
          <div className="section">
            <Skeleton variant="card" lines={3} />
          </div>
        ) : (
          <p className="field__hint mt-4">任务已创建，等待第一个样本事件。</p>
        )
      ) : (
        <div className="result-body">
          <div className="sample-rail">
            {samples.length > 1 && (
              <div className="sample-filter">
                <div className="relative">
                  <Search
                    size={13}
                    className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 muted"
                    aria-hidden="true"
                  />
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="按 idx 搜索样本…"
                    aria-label="按 idx 搜索样本"
                    style={{ paddingLeft: "28px", minHeight: "32px", fontSize: "12px" }}
                  />
                </div>
                <div className="sample-filter__pills">
                  {FILTER_OPTIONS.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      className={`filter-pill ${filter === item.key ? "is-active" : ""}`}
                      onClick={() => setFilter(item.key)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <SampleList
              state={state}
              samplesOverride={samples.length > 1 ? filteredSamples : undefined}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
            />
          </div>

          <div className="result-detail">
            {selected === undefined ? (
              <p className="field__hint">请在左侧选择一个样本。</p>
            ) : (
              <>
              <SampleDetail
                sample={selected}
                mode={state.mode}
                measurement={selectedKey !== null ? measurementsByKey.get(selectedKey) : undefined}
              />
              {selected.prediction !== undefined && selected.prediction !== null && (
                <ReportDiscussion key={JSON.stringify([state.taskId, selected.idx])}
                  taskId={state.taskId} idx={selected.idx} />
              )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
