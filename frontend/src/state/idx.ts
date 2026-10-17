import type { Idx } from "../api/types";

/**
 * 样本标识的等价键。整数 1 与字符串 "1" 必须得到不同的键，
 * 否则批量结果会把两个不同样本合并（backend/app/schemas/models.py: idx_key）。
 */
export function idxKey(idx: Idx): string {
  return typeof idx === "number" ? `n:${idx}` : `s:${idx}`;
}

/** 界面上用于显示标识本身；字符串额外加引号，避免与同名整数混淆。 */
export function idxLabel(idx: Idx): string {
  return typeof idx === "string" ? `"${idx}"` : String(idx);
}

export function idxKindLabel(idx: Idx): string {
  return typeof idx === "number" ? "整数" : "字符串";
}

export type IdxInputKind = "number" | "string";

export class IdxInputError extends Error {}

/**
 * 把输入框文本按指定类型转成提交给 API 的 idx。
 * 类型必须由用户显式选择：`1` 与 `"1"` 在后端是两个样本。
 */
export function parseIdxInput(text: string, kind: IdxInputKind): Idx {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new IdxInputError("请填写样本标识 idx。");
  }
  if (kind === "string") {
    return trimmed;
  }
  if (!/^-?\d+$/.test(trimmed)) {
    throw new IdxInputError("整数类型的样本标识只能包含数字，例如 1；如需字符串请切换类型。");
  }
  const value = Number(trimmed);
  if (!Number.isSafeInteger(value)) {
    throw new IdxInputError("整数类型的样本标识超出可安全表示的范围。");
  }
  return value;
}
