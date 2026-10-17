import { useEffect, useRef, useState } from "react";

/**
 * 值变化后短暂返回 true，用于让界面闪一下提示“这里刚刚更新了”。
 *
 * 比较基准放在 effect 里而不是渲染期：渲染期写 ref 在 StrictMode 的双次渲染下会
 * 把“上一次的值”覆盖成当前值，导致永远检测不到变化。
 * 只影响类名，不改变文本内容。
 */
export function useChangeFlash<T>(value: T, durationMs = 700): boolean {
  const [flashing, setFlashing] = useState(false);
  const lastValue = useRef<{ value: T } | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const snapshot = lastValue.current;
    lastValue.current = { value };
    if (snapshot === null || Object.is(snapshot.value, value)) {
      return;
    }
    setFlashing(true);
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => {
      timer.current = null;
      setFlashing(false);
    }, durationMs);
  }, [value, durationMs]);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    },
    [],
  );

  return flashing;
}
