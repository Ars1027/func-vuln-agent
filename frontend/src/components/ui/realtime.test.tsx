// @vitest-environment jsdom
import { act, cleanup, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Condition } from "../../api/types";
import { formatDuration, useElapsed } from "../../hooks/useElapsed";
import { useChangeFlash } from "../../hooks/useChangeFlash";
import { ConditionBreakdown } from "./ConditionBreakdown";
import { EmptyState } from "./EmptyState";
import { ProgressBar } from "./ProgressBar";
import { Skeleton } from "./Skeleton";

function condition(id: string, status: Condition["status"]): Condition {
  return {
    id,
    hypothesis_id: "h1",
    statement: `条件 ${id}`,
    status,
    evidence_ids: [],
    reason: "—",
  };
}

function segWidth(container: HTMLElement, className: string): string {
  const node = container.querySelector<HTMLElement>(`.${className}`);
  if (node === null) {
    throw new Error(`找不到 ${className}`);
  }
  return node.style.width;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ProgressBar", () => {
  it("按完成/失败/分析中/剩余四段分配宽度并给出无障碍数值", () => {
    const { container } = render(
      <ProgressBar completed={1} failed={1} running={1} total={4} active />,
    );

    const track = container.querySelector('[role="progressbar"]');
    expect(track?.getAttribute("aria-valuenow")).toBe("1");
    expect(track?.getAttribute("aria-valuemax")).toBe("4");
    expect(segWidth(container, "progress__bar--done")).toBe("25%");
    expect(segWidth(container, "progress__bar--failed")).toBe("25%");
    expect(segWidth(container, "progress__bar--running")).toBe("25%");
    expect(segWidth(container, "progress__bar--rest")).toBe("25%");
  });

  it("总数未知且仍在推进时使用不定量条纹", () => {
    const { container } = render(
      <ProgressBar completed={0} failed={0} running={0} total={0} active />,
    );

    expect(container.querySelector(".progress__bar--indeterminate")).not.toBeNull();
    expect(container.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBeNull();
    expect(container.textContent).toContain("准备中");
  });

  it("全部完成时进度条没有剩余段", () => {
    const { container } = render(
      <ProgressBar completed={3} failed={0} running={0} total={3} active={false} />,
    );

    expect(segWidth(container, "progress__bar--done")).toBe("100%");
    expect(segWidth(container, "progress__bar--rest")).toBe("0%");
    expect(container.textContent).toContain("3/3");
  });
});

describe("ConditionBreakdown", () => {
  it("按状态分组计数，并标出条件总数", () => {
    const { container, getByText } = render(
      <ConditionBreakdown
        conditions={[
          condition("c1", "supported"),
          condition("c2", "supported"),
          condition("c3", "refuted"),
        ]}
      />,
    );

    expect(getByText("支持成立").parentElement?.textContent).toContain("2");
    expect(getByText("已被反证").parentElement?.textContent).toContain("1");
    expect(getByText("待确认").parentElement?.textContent).toContain("0");
    expect(getByText("条件总数").parentElement?.textContent).toContain("3");

    // 没有 unknown 条件时，条上不出现对应分段
    expect(container.querySelector(".breakdown__seg--unknown")).toBeNull();
    expect(segWidth(container, "breakdown__seg--supported")).toBe(`${(2 / 3) * 100}%`);
  });

  it("没有条件时不渲染概览", () => {
    const { container } = render(<ConditionBreakdown conditions={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("Skeleton 与 EmptyState", () => {
  it("骨架屏渲染指定行数", () => {
    const { container } = render(<Skeleton variant="card" lines={3} />);
    expect(container.querySelectorAll(".skeleton__line")).toHaveLength(3);
    expect(container.querySelector(".skeleton__block")).not.toBeNull();
  });

  it("空状态给出标题、说明与提示", () => {
    const { getByText } = render(
      <EmptyState title="检测过程与报告" description="提交任务后显示。" hint="合成样例" />,
    );
    expect(getByText("检测过程与报告")).toBeTruthy();
    expect(getByText("提交任务后显示。")).toBeTruthy();
    expect(getByText("合成样例")).toBeTruthy();
  });
});

describe("useElapsed", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });

  it("运行中按间隔刷新，结束后冻结在最后读数", () => {
    const start = Date.now();
    const { result, rerender } = renderHook(
      ({ active }: { active: boolean }) => useElapsed(start, active, 200),
      { initialProps: { active: true } },
    );

    expect(result.current).toBe(0);
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(result.current).toBe(600);

    rerender({ active: false });
    const frozen = result.current;
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current).toBe(frozen);
  });

  it("没有起点时返回 null", () => {
    const { result } = renderHook(() => useElapsed(null, true, 200));
    expect(result.current).toBeNull();
  });

  it("耗时文本按量级切换单位", () => {
    expect(formatDuration(500)).toBe("500 毫秒");
    expect(formatDuration(1500)).toBe("1.5 秒");
    expect(formatDuration(65000)).toBe("1 分 5 秒");
  });

  it.each([
    [119499, "1 分 59 秒"],
    [119500, "2 分 0 秒"],
    [119999, "2 分 0 秒"],
    [120000, "2 分 0 秒"],
    [179500, "3 分 0 秒"],
  ])("耗时 %i 毫秒在舍入后正确进位", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("useChangeFlash", () => {
  it("值变化后短暂为 true，随后复位", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ value }: { value: number }) => useChangeFlash(value, 700),
      { initialProps: { value: 0 } },
    );

    expect(result.current).toBe(false);
    rerender({ value: 1 });
    expect(result.current).toBe(true);

    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(result.current).toBe(false);
  });

  it("值不变时不触发", () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useChangeFlash(value, 700),
      { initialProps: { value: "running" } },
    );

    rerender({ value: "running" });
    expect(result.current).toBe(false);
  });
});
