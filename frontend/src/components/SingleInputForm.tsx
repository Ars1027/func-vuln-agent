import { useState } from "react";

import { createDetection, createSnapshot } from "../api/client";
import type { DetectionInput, Mode, TaskView } from "../api/types";
import { describeError } from "../lib/errors";
import { DEMO_SNAPSHOTS } from "../lib/demoSamples";
import { IdxInputError, parseIdxInput, type IdxInputKind } from "../state/idx";
import { ErrorNotice } from "./ErrorNotice";

interface Props {
  mode: Mode;
  disabled?: boolean;
  onStarted: (view: TaskView) => void;
}

/**
 * 单样本输入：函数 + 修复提交链接 + 明确的版本选择。
 * 先 POST /api/snapshots 准备快照，再用返回的 idx/func/snapshot_ref 提交检测。
 */
export function SingleInputForm({ mode, disabled, onStarted }: Props) {
  const [idxText, setIdxText] = useState("manual-1");
  const [idxKind, setIdxKind] = useState<IdxInputKind>("string");
  const [func, setFunc] = useState("");
  const [commitUrl, setCommitUrl] = useState("");
  const [revision, setRevision] = useState<"" | "commit" | "parent">("");
  const [prepared, setPrepared] = useState<DetectionInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPrepared(null);

    if (!func.trim()) {
      setError({ code: "missing_func", message: "请填写待测的 C/C++ 函数。" });
      return;
    }
    if (!commitUrl.trim()) {
      setError({ code: "missing_commit_url", message: "请填写修复提交链接。" });
      return;
    }
    if (!/^https?:\/\//i.test(commitUrl.trim())) {
      setError({ code: "invalid_commit_url", message: "修复提交链接需以 http:// 或 https:// 开头。" });
      return;
    }
    if (revision === "") {
      setError({ code: "missing_revision", message: "请选择检测“该提交”还是“父提交”。" });
      return;
    }
    let idx;
    try {
      idx = parseIdxInput(idxText, idxKind);
    } catch (parseError) {
      setError({
        code: "invalid_idx",
        message: parseError instanceof IdxInputError ? parseError.message : "样本标识不合法。",
      });
      return;
    }

    setBusy(true);
    try {
      const snapshot = await createSnapshot({
        idx,
        func,
        commit_url: commitUrl.trim(),
        revision,
      });
      setPrepared(snapshot);
      const view = await createDetection({
        idx: snapshot.idx,
        func: snapshot.func,
        snapshot_ref: snapshot.snapshot_ref,
        mode,
      });
      onStarted(view);
    } catch (submitError) {
      setError(describeError(submitError));
    } finally {
      setBusy(false);
    }
  }

  function fillDemo(preset: (typeof DEMO_SNAPSHOTS)[keyof typeof DEMO_SNAPSHOTS]) {
    setIdxText(preset.idx);
    setIdxKind("string");
    setFunc(preset.func);
    setCommitUrl(preset.commitUrl);
    setRevision(preset.revision);
    setError(null);
    setPrepared(null);
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div className="field-row">
        <label className="field field--grow">
          <span className="field__label">样本标识 idx</span>
          <input
            type="text"
            value={idxText}
            onChange={(event) => setIdxText(event.target.value)}
            placeholder="manual-1"
          />
        </label>
        <label className="field">
          <span className="field__label">标识类型</span>
          <select
            value={idxKind}
            onChange={(event) => setIdxKind(event.target.value as IdxInputKind)}
          >
            <option value="string">字符串</option>
            <option value="number">整数</option>
          </select>
        </label>
      </div>

      <label className="field">
        <span className="field__label">待测函数（C/C++）</span>
        <textarea
          className="code-input"
          rows={5}
          value={func}
          onChange={(event) => setFunc(event.target.value)}
          placeholder="void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }"
        />
      </label>

      <label className="field">
        <span className="field__label">修复提交链接</span>
        <input
          type="url"
          value={commitUrl}
          onChange={(event) => setCommitUrl(event.target.value)}
          placeholder="https://github.com/owner/repo/commit/<sha>"
        />
      </label>

      <fieldset className="field">
        <legend className="field__label">版本选择</legend>
        <div className="radio-row">
          <label>
            <input
              type="radio"
              name="revision"
              checked={revision === "commit"}
              onChange={() => setRevision("commit")}
            />
            该提交（revision=commit）
          </label>
          <label>
            <input
              type="radio"
              name="revision"
              checked={revision === "parent"}
              onChange={() => setRevision("parent")}
            />
            父提交（revision=parent）
          </label>
        </div>
        <p className="field__hint">
          按课程配对规则，漏洞版取修复提交的父版本，修复版取修复提交版本；必须显式选择，不提供默认值。
        </p>
      </fieldset>

      <div className="button-row">
        <button type="submit" className="button button--primary" disabled={disabled || busy}>
          {busy ? "准备快照并提交…" : "准备快照并开始检测"}
        </button>
        <button
          type="button"
          className="button"
          disabled={disabled}
          onClick={() => fillDemo(DEMO_SNAPSHOTS.vulnerable)}
        >
          {DEMO_SNAPSHOTS.vulnerable.label}
        </button>
        <button
          type="button"
          className="button"
          disabled={disabled}
          onClick={() => fillDemo(DEMO_SNAPSHOTS.fixed)}
        >
          {DEMO_SNAPSHOTS.fixed.label}
        </button>
      </div>
      <p className="field__hint">
        合成样例按钮仅配合 <code>app.demo</code> 演示入口使用，不代表真实检测效果。
      </p>

      {error !== null && <ErrorNotice code={error.code} message={error.message} />}

      {prepared !== null && (
        <div className="prepared">
          <p className="prepared__title">快照已准备</p>
          <dl className="kv">
            <div>
              <dt>idx</dt>
              <dd>{String(prepared.idx)}</dd>
            </div>
            <div>
              <dt>snapshot_ref</dt>
              <dd className="mono">{prepared.snapshot_ref}</dd>
            </div>
          </dl>
          <p className="field__hint">快照引用为不透明标识，界面与模型都不会看到标签或版本语义。</p>
        </div>
      )}
    </form>
  );
}
