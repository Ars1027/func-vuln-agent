import { useCallback, useEffect, useRef, useState } from "react";

interface Options {
  /** 触发的依赖，通常是列表长度。 */
  length: number;
  /** 用户主动离开底部后是否停止跟随。 */
  enabled?: boolean;
}

/**
 * 实时列表跟随：有新条目时滚到底部，除非用户已经主动向上滚动。
 * 返回的 `onScroll` 需要挂到可滚动容器的 onScroll 上。
 */
export function useFollowLatest<T extends HTMLElement = HTMLElement>({
  length,
  enabled = true,
}: Options) {
  const ref = useRef<T | null>(null);
  const [following, setFollowing] = useState(true);

  const onScroll = useCallback(() => {
    const node = ref.current;
    if (node === null) {
      return;
    }
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setFollowing(distance < 48);
  }, []);

  useEffect(() => {
    if (!enabled || !following) {
      return;
    }
    const node = ref.current;
    // 无布局环境（如 jsdom）没有 scrollTo，滚动只是增强行为。
    node?.scrollTo?.({ top: node.scrollHeight, behavior: "smooth" });
  }, [length, enabled, following]);

  return { ref, following, onScroll };
}
