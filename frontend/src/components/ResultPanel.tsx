import { useEffect, useState } from "react";

import type { Failure } from "../api/types";
import type { DisplayError } from "../lib/errors";
import { idxKey } from "../state/idx";
import { sampleList, type TaskState } from "../state/store";
import { FailureList } from "./FailureList";
import { SampleDetail } from "./SampleDetail";
import { SampleList } from "./SampleList";
import { TaskSummary } from "./TaskSummary";
import { EmptyState } from "./ui/EmptyState";
import { Skeleton } from "./ui/Skeleton";

interface Props {
  state: TaskState;
  loading: boolean;
  startedAt: number | null;
  loadError: DisplayError | null;
  downloadError: DisplayError | null;
  onReload: () => void;
  onDownload: () => void;
  onClearDownloadError: () => void;
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
}: Props) {
  const samples = sampleList(state);
  const firstKey = state.order[0] ?? null;
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  useEffect(() => {
    if (selectedKey === null || state.samples[selectedKey] === undefined) {
      setSelectedKey(firstKey);
    }
  }, [firstKey, selectedKey, state.samples]);

  if (state.taskId === null) {
    return (
      <section className="panel panel--placeholder">
        <EmptyState
          title="检测过程与报告"
          description="提交单样本或批量任务后，这里显示任务计数、每项条件的状态、证据来源与完整分析记录。"
          hint={
            <>
              演示入口只接受 <code>examples/synthetic.jsonl</code> 中的合成样例。
            </>
          }
        />
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
          <p className="field__hint">任务已创建，等待第一个样本事件。</p>
        )
      ) : (
        <div className="result-body">
          <SampleList state={state} selectedKey={selectedKey} onSelect={setSelectedKey} />
          <div className="result-detail">
            {selected === undefined ? (
              <p className="field__hint">请在左侧选择一个样本。</p>
            ) : (
              <SampleDetail sample={selected} mode={state.mode} />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
