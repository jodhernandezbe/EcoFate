import type { ReactNode } from "react";

import { CopilotToggle } from "./CopilotToggle";

export type AssistantStatus = "idle" | "thinking" | "stopped" | "error";

const STATUS: Record<AssistantStatus, { label: string; dot: string }> = {
  idle: { label: "Ready", dot: "bg-ok" },
  thinking: { label: "Thinking", dot: "bg-warn animate-pulse" },
  stopped: { label: "Stopped", dot: "bg-fg2" },
  error: { label: "Needs attention", dot: "bg-bad" },
};

interface TopHeaderBarProps {
  title: string;
  subtitle?: string | undefined;
  status: AssistantStatus;
  /** Hides the dock this header belongs to. */
  onCollapse?: (() => void) | undefined;
  children?: ReactNode;
}

/** Assistant title, live status and the control that collapses the dock. */
export function TopHeaderBar({
  title,
  subtitle,
  status,
  onCollapse,
  children,
}: TopHeaderBarProps) {
  const { label, dot } = STATUS[status];
  // Above the conversation in the stacking order, so the usage popover opens over it.
  return (
    <header className="glass relative z-10 flex items-center gap-3 border-x-0 border-t-0 px-5 py-3">
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-tight">{title}</h1>
        <p className="flex items-center gap-1.5 text-xs text-fg2" role="status">
          <span aria-hidden="true" className={`inline-block size-2 rounded-full ${dot}`} />
          {label}
          {subtitle ? <span aria-hidden="true">· {subtitle}</span> : null}
        </p>
      </div>
      {children}
      {onCollapse ? <CopilotToggle open onToggle={onCollapse} /> : null}
    </header>
  );
}
