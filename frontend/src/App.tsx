import {
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Radio,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { useState } from "react";

import type { Mode } from "./api/types";
import { InputPanel } from "./components/InputPanel";
import { ResultPanel } from "./components/ResultPanel";
import { useTaskStream } from "./hooks/useTaskStream";
import { useTheme } from "./hooks/useTheme";

export default function App() {
  const [mode, setMode] = useState<Mode>("conditions");
  const [inputCollapsed, setInputCollapsed] = useState(false);
  const { theme, toggleTheme } = useTheme();
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
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar__inner">
          <div className="app__brand">
            <span className="app__mark" aria-hidden="true">
              <ShieldCheck size={21} strokeWidth={2.1} />
            </span>
            <div>
              <h1 className="app__title">函数漏洞检测 Agent</h1>
              <p className="app__subtitle">
                条件驱动的证据补全与反证检查 · 单函数单版本快照 · SSE 实时取证追踪
              </p>
            </div>
          </div>

          <div className="topbar__controls">
            <p className="app__hint">
              本地演示使用 <code>app.demo</code> 的合成材料与脚本模型，不代表真实检测效果。
            </p>

            {state.taskId !== null && (
              <span className="icon-btn mono" title="当前任务事件流序号">
                <Radio size={13} className={running ? "text-accent" : "muted"} aria-hidden="true" />
                <span>seq {state.seq}</span>
              </span>
            )}

            <button
              type="button"
              className="icon-btn"
              onClick={() => setInputCollapsed((prev) => !prev)}
              aria-expanded={!inputCollapsed}
              title={inputCollapsed ? "展开左侧检测输入栏" : "收起左侧输入栏以全宽查看报告"}
            >
              {inputCollapsed ? (
                <PanelLeftOpen size={15} aria-hidden="true" />
              ) : (
                <PanelLeftClose size={15} aria-hidden="true" />
              )}
              <span>{inputCollapsed ? "展开输入栏" : "宽屏审计"}</span>
            </button>

            <button
              type="button"
              className="icon-btn"
              onClick={toggleTheme}
              title={theme === "light" ? "切换至深色主题" : "切换至浅色主题"}
            >
              {theme === "light" ? (
                <Moon size={15} aria-hidden="true" />
              ) : (
                <Sun size={15} aria-hidden="true" />
              )}
              <span>{theme === "light" ? "深色" : "浅色"}</span>
            </button>
          </div>
        </div>
      </header>

      <main className={`workspace`}>
        <div className={`layout ${inputCollapsed ? "layout--collapsed" : ""}`}>
          {!inputCollapsed && (
            <InputPanel
              mode={mode}
              onModeChange={setMode}
              disabled={running}
              onStarted={startTask}
              onCollapse={state.taskId !== null ? () => setInputCollapsed(true) : undefined}
            />
          )}
          <ResultPanel
            state={state}
            loading={loading}
            startedAt={startedAt}
            loadError={loadError}
            downloadError={downloadError}
            onReload={reload}
            onDownload={download}
            onClearDownloadError={clearDownloadError}
            inputCollapsed={inputCollapsed}
            onExpandInput={() => setInputCollapsed(false)}
          />
        </div>
      </main>

      <footer className="app__footer">
        <span>
          接口约定见 <code>docs/interfaces.md</code> · 启动演示后端见 <code>docs/backend.md</code>
        </span>
        <span className="mono">LangGraph · FastAPI · SSE · Single-Snapshot Isolation</span>
      </footer>
    </div>
  );
}
