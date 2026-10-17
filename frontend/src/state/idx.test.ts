import { describe, expect, it } from "vitest";

import { IdxInputError, idxKey, idxKindLabel, idxLabel, parseIdxInput } from "./idx";

describe("idxKey", () => {
  it("整数 1 与字符串 \"1\" 得到不同的键", () => {
    expect(idxKey(1)).not.toBe(idxKey("1"));
  });

  it("同类型同值得到相同的键", () => {
    expect(idxKey(1)).toBe(idxKey(1));
    expect(idxKey("unknown")).toBe(idxKey("unknown"));
  });

  it("标签区分类型，便于界面辨认", () => {
    expect(idxLabel(1)).toBe("1");
    expect(idxLabel("1")).toBe('"1"');
    expect(idxKindLabel(1)).toBe("整数");
    expect(idxKindLabel("1")).toBe("字符串");
  });
});

describe("parseIdxInput", () => {
  it("按选择类型返回标识", () => {
    expect(parseIdxInput("1", "number")).toBe(1);
    expect(parseIdxInput("1", "string")).toBe("1");
  });

  it("字符串类型去掉首尾空白，保留其余文本", () => {
    expect(parseIdxInput("  sample-01  ", "string")).toBe("sample-01");
  });

  it("整数类型拒绝非数字文本", () => {
    expect(() => parseIdxInput("abc", "number")).toThrow(IdxInputError);
  });

  it("空标识报错", () => {
    expect(() => parseIdxInput("   ", "number")).toThrow(IdxInputError);
  });
});
