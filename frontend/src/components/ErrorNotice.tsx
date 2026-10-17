import type { ReactNode } from "react";

import { errorCodeLabel } from "../lib/errors";

interface Props {
  code: string;
  message: string;
  title?: string;
  action?: ReactNode;
}

/** 统一的错误展示：错误代码来自后端 `code` 字段，message 直接面向使用者。 */
export function ErrorNotice({ code, message, title, action }: Props) {
  const label = errorCodeLabel(code);
  return (
    <div className="notice notice--error" role="alert">
      <p className="notice__head">
        <span className="notice__label">{title ?? label}</span>
        <code className="notice__code">{code}</code>
      </p>
      <p className="notice__message">{message}</p>
      {action}
    </div>
  );
}
