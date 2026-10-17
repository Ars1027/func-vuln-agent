interface Props {
  /** 占位行数。 */
  lines?: number;
  /** 附加形状：图表块更容易看出“正在读取”。 */
  variant?: "text" | "card";
}

/** 加载占位：避免首次读取任务快照时出现空白闪烁。 */
export function Skeleton({ lines = 3, variant = "text" }: Props) {
  const rows = Array.from({ length: lines }, (_, index) => index);
  return (
    <div className={`skeleton skeleton--${variant}`} aria-hidden="true">
      {variant === "card" && <span className="skeleton__block" />}
      {rows.map((row) => (
        <span
          key={row}
          className="skeleton__line"
          // 依次淡入，让占位看起来在“加载”而不是静态块
          style={{ width: `${100 - (row % 3) * 12}%`, animationDelay: `${row * 90}ms` }}
        />
      ))}
    </div>
  );
}
