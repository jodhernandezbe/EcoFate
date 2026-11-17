import { CirclePause, CircleStop } from "lucide-react";

import type { LiveStatus } from "../../hooks/chatState";
import type { TurnInterruption } from "../../types/workspace";
import { STOPPING, turnStatusText } from "./turnStatusText";

const RESUME_BLOCKED = "A turn is running; Resume is available when it ends.";
const BAR = "flex flex-wrap items-center gap-2 border-b border-hairline px-5 py-2";

interface RunningProps {
  status: LiveStatus | null;
  stopping: boolean;
  onStop?: (() => void) | undefined;
}

/** A running turn: what it is doing now, and Stop (disabled with its reason once asked). */
function Running({ status, stopping, onStop }: RunningProps) {
  return (
    <div className={BAR}>
      <span role="status" aria-live="polite" className="min-w-0 flex-1 text-xs text-fg2">
        {stopping ? STOPPING : turnStatusText(status)}…
      </span>
      {onStop ? (
        <button
          type="button"
          disabled={stopping}
          title={stopping ? STOPPING : undefined}
          aria-description={stopping ? STOPPING : undefined}
          onClick={onStop}
          className="spring inline-flex items-center gap-1 rounded-full border border-hairline px-3 py-1 text-sm text-fg transition hover:bg-hairline disabled:opacity-30"
        >
          <CircleStop className="size-4" aria-hidden="true" />
          Stop
        </button>
      ) : null}
    </div>
  );
}

interface StoppedProps {
  stop: TurnInterruption;
  busy: boolean;
  onResume?: (() => void) | undefined;
  onOpenSettings?: (() => void) | undefined;
}

/** An interrupted turn: why it stopped (the server's fixed text), Resume and, for a rejected key, Settings. */
function Stopped({ stop, busy, onResume, onOpenSettings }: StoppedProps) {
  return (
    <div role="status" className={BAR}>
      <p className="m-0 flex min-w-0 flex-1 items-start gap-2 text-sm">
        <CirclePause size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg2" />
        <span>{stop.message}</span>
      </p>
      {stop.resumable && onResume ? (
        <button
          type="button"
          disabled={busy}
          title={busy ? RESUME_BLOCKED : undefined}
          aria-description={busy ? RESUME_BLOCKED : undefined}
          onClick={onResume}
          className="spring rounded-full bg-accent px-3 py-1 text-sm font-medium text-accent-fg transition disabled:opacity-30"
        >
          Resume
        </button>
      ) : null}
      {stop.reason === "bad_key" && onOpenSettings ? (
        <button
          type="button"
          onClick={onOpenSettings}
          className="spring rounded-full border border-hairline px-3 py-1 text-sm text-accent transition hover:bg-hairline"
        >
          Open Settings
        </button>
      ) : null}
    </div>
  );
}

export interface TurnControlsProps {
  /** A turn is running. */
  busy: boolean;
  /** What the running turn is doing now (null when none runs). */
  status: LiveStatus | null;
  /** A stop was asked for and the turn is finishing its current step. */
  stopping: boolean;
  /** The latest turn's interruption, when the conversation ends on one. */
  interrupted: TurnInterruption | null;
  onStop?: (() => void) | undefined;
  onResume?: (() => void) | undefined;
  onOpenSettings?: (() => void) | undefined;
}

/**
 * The turn's controls, at the top of the chat rather than in the thread: Stop while a turn runs,
 * Resume after it was interrupted. Nothing is shown when the conversation is idle.
 */
export function TurnControls({ busy, status, stopping, interrupted, onStop, onResume, onOpenSettings }: TurnControlsProps) {
  if (busy) return <Running status={status} stopping={stopping} onStop={onStop} />;
  if (!interrupted) return null;
  return <Stopped stop={interrupted} busy={busy} onResume={onResume} onOpenSettings={onOpenSettings} />;
}
