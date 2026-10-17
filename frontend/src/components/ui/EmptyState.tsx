import type { ReactNode } from "react";

interface Props {
  title: string;
  description: string;
  hint?: ReactNode;
}

/** 空状态：说明这里会出现什么，以及需要先做什么。 */
export function EmptyState({ title, description, hint }: Props) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon" aria-hidden="true">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H9l-5 4v-13Z" />
          <path d="M8 8.5h8M8 11.5h5" />
        </svg>
      </span>
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__description">{description}</p>
      {hint !== undefined && <p className="empty-state__hint">{hint}</p>}
    </div>
  );
}
