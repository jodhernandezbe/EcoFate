import { AlertCircle, Check, ChevronRight, LoaderCircle } from "lucide-react";
import { useId, useState } from "react";

import type { ToolStep } from "../../hooks/chatState";

const ICON = {
  running: <LoaderCircle size={13} aria-hidden="true" className="animate-spin text-fg2" />,
  done: <Check size={13} aria-hidden="true" className="text-ok" />,
  error: <AlertCircle size={13} aria-hidden="true" className="text-bad" />,
} as const;

const STATE_LABEL = { running: "running", done: "done", error: "failed" } as const;

/** One tool step: its label and whether it is running, done or failed. */
function Pill({ step }: { step: ToolStep }) {
  return (
    <li
      className="glass flex w-fit max-w-full items-start gap-1.5 rounded-xl px-2.5 py-1 text-xs text-fg2"
      aria-label={`${step.label}, ${STATE_LABEL[step.state]}`}
    >
      <span className="mt-0.5 shrink-0">{ICON[step.state]}</span>
      <span className="min-w-0">{step.label}</span>
    </li>
  );
}

/** A turn's tool steps, one per row from top to bottom as they happen; the header hides or shows them. */
export function ToolExecutionPills({ steps }: { steps: ToolStep[] }) {
  const [expanded, setExpanded] = useState(true);
  const listId = useId();
  if (steps.length === 0) return null;
  const running = steps.filter((step) => step.state === "running").length;
  const summary = running > 0 ? `Working… ${running} running` : `${steps.length} ${steps.length === 1 ? "step" : "steps"}`;

  return (
    <div className="mb-2">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setExpanded((value) => !value)}
        className="spring mb-1 flex items-center gap-1 text-xs text-fg2 transition hover:text-fg"
      >
        <ChevronRight
          size={13}
          aria-hidden="true"
          className={`transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        {summary}
      </button>
      <ul id={listId} hidden={!expanded} className="m-0 flex list-none flex-col items-start gap-1 p-0">
        {steps.map((step) => (
          <Pill key={step.callId} step={step} />
        ))}
      </ul>
    </div>
  );
}
