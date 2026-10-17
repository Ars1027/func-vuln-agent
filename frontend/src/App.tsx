import { useState } from "react";

import type { Mode } from "./api/types";
import { InputPanel } from "./components/InputPanel";
import { ResultPanel } from "./components/ResultPanel";
import { useTaskStream } from "./hooks/useTaskStream";

export default function App() {
  const [mode, setMode] = useState<Mode>("conditions");
  const {
    state,
    loading,
    loadError,
    downloadError,
    startedAt,
    startTask,
    reload,
    download,
    clearDownloadError,
  } = useTaskStream();
  const running = state.status === "queued" || state.status === "running";

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <span className="app__mark" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 3.2 5 6v5.6c0 4 2.9 7.4 7 8.4 4.1-1 7-4.4 7-8.4V6l-7-2.8Z" />
              <path d="m9.2 12.1 2 2 3.6-3.9" />
            </svg>
          </span>
          <div>
            <h1 className="app__title">函数漏洞检测 Agent</h1>
            <p className="app__subtitle">
              条件驱动的证据补全与反证检查 · 单函数单版本快照 · 过程事件经 SSE 实时推送
            </p>
          </div>
        </div>
        <p className="app__hint">
          本地演示使用 <code>app.demo</code> 的合成材料与脚本模型，不代表真实检测效果。
        </p>
      </header>

      <main className="layout">
        <InputPanel
          mode={mode}
          onModeChange={setMode}
          disabled={running}
          onStarted={startTask}
        />
        <ResultPanel
          state={state}
          loading={loading}
          startedAt={startedAt}
          loadError={loadError}
          downloadError={downloadError}
          onReload={reload}
          onDownload={download}
          onClearDownloadError={clearDownloadError}
        />
      </main>

      <footer className="app__footer">
        <p>
          接口约定见 <code>docs/interfaces.md</code>；启动演示后端见 <code>docs/backend.md</code>。
        </p>
      </footer>
    </div>
  );
}
