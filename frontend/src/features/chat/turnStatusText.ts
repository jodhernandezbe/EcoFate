import type { LiveStatus } from "../../hooks/chatState";

/** The one-line status under the streaming answer: waiting for a worker, thinking, or the step
 * that is running (its label as the server sent it). */
export function turnStatusText(status: LiveStatus | null): string {
  if (status?.phase === "queued") {
    const ahead = status.position ?? 0;
    return ahead > 0 ? `Waiting for a worker (about ${ahead} ahead)` : "Waiting for a worker";
  }
  if (status?.phase === "running_tool" && status.label) return `Running: ${status.label}`;
  return "Thinking";
}

/** Said while a stop was asked for and the turn is finishing its current step. */
export const STOPPING = "Stopping after the current step";
