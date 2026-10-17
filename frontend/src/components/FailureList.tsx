import type { Failure } from "../api/types";
import { errorCodeLabel } from "../lib/errors";
import { IdxBadge } from "./chips";
import { ErrorNotice } from "./ErrorNotice";

interface Props {
  failures: Failure[];
  taskError: { code: string; message: string } | null;
  onSelect?: (failure: Failure) => void;
}

/** 执行失败是独立结果，不会补成 prediction=0；这里保留失败原因与原类型 idx。 */
export function FailureList({ failures, taskError, onSelect }: Props) {
  if (failures.length === 0 && taskError === null) {
    return null;
  }
  return (
    <div className="failures">
      <h3 className="section-title">执行失败</h3>
      {taskError !== null && (
        <ErrorNotice
          title="任务级错误"
          code={taskError.code}
          message={taskError.message}
        />
      )}
      {failures.length > 0 && (
        <ul className="failure-list">
          {failures.map((failure) => (
            <li key={`${typeof failure.idx}:${String(failure.idx)}`}>
              <button
                type="button"
                className="failure-list__item"
                onClick={() => onSelect?.(failure)}
                disabled={onSelect === undefined}
              >
                <IdxBadge idx={failure.idx} />
                <span className="failure-list__code">{errorCodeLabel(failure.code)}</span>
                <code className="failure-list__raw">{failure.code}</code>
                <span className="failure-list__message">{failure.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="field__hint">
        失败样本若已有部分分析，会保留在样本详情中，但不会被当作“无漏洞”计入结果。
      </p>
    </div>
  );
}
