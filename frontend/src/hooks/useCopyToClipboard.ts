import { useCallback, useEffect, useRef, useState } from "react";

type CopyState = "idle" | "copied" | "failed";

/**
 * 复制到剪贴板并给出短暂反馈。
 * 浏览器不允许写入（无权限、非安全上下文）时返回 failed，由调用方降级提示。
 */
export function useCopyToClipboard(resetAfterMs = 1600) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    },
    [],
  );

  const copy = useCallback(
    async (text: string) => {
      let next: CopyState = "failed";
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(text);
          next = "copied";
        }
      } catch {
        next = "failed";
      }
      setState(next);
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
      timer.current = window.setTimeout(() => setState("idle"), resetAfterMs);
      return next;
    },
    [resetAfterMs],
  );

  return { state, copy };
}
