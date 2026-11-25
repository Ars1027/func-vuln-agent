import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  description: string;
  hint?: ReactNode;
  children?: ReactNode;
}

/** 空状态：说明这里会出现什么，以及需要先做什么。 */
export function EmptyState({ title, description, hint, children }: Props) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon" aria-hidden="true">
        <ShieldAlert size={26} strokeWidth={1.8} />
      </span>
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__description">{description}</p>
      {hint !== undefined && <p className="empty-state__hint">{hint}</p>}
      {children}
    </div>
  );
}
