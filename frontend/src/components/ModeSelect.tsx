import { MODES, MODE_LABELS, type Mode } from "../api/types";

const MODE_HINTS: Record<Mode, string> = {
  conditions: "历史案例条件 + 漏洞假设 + 条件更新与反证检查。",
  rag_context: "原始历史案例 + 自主仓库读取，不附加提取出的条件。",
  function_only: "仅输入待测函数，不提供检索、仓库工具和条件更新。",
};

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
  disabled?: boolean;
}

/** 运行配置由服务端选择工具与提示词，不进入样本内容。 */
export function ModeSelect({ mode, onChange, disabled }: Props) {
  return (
    <fieldset className="field" disabled={disabled}>
      <legend className="field__label">检测模式</legend>
      <div className="mode-select">
        {MODES.map((item) => (
          <label key={item} className={`mode-option ${mode === item ? "is-active" : ""}`}>
            <input
              type="radio"
              name="mode"
              value={item}
              checked={mode === item}
              onChange={() => onChange(item)}
            />
            <span className="mode-option__name">{MODE_LABELS[item]}</span>
            <span className="mode-option__hint">{MODE_HINTS[item]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
