import type { JobInfo } from "../../types/workspace";

/** Said while the user asked to stop a job and it is finishing its current step. */
export const JOB_STOPPING = "Stopping after the current step";

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
// What the user calls the work of a background tool; a tool this build does not know is a job.
const LABELS: Record<string, string> = { assess_facilities: "Assessment" };
const FALLBACK_LABEL = "Background job";

/** The name of what a job does, for its status line. */
export const jobLabel = (job: JobInfo): string => LABELS[job.tool] ?? FALLBACK_LABEL;

/** Whole seconds as "45 s", "1 min 20 s", "2 min" or "1 h 5 min". */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = seconds % SECONDS_PER_MINUTE;
  if (minutes === 0) return `${rest} s`;
  if (minutes < MINUTES_PER_HOUR) return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  const left = minutes % MINUTES_PER_HOUR;
  return left === 0 ? `${hours} h` : `${hours} h ${left} min`;
}

/**
 * The one-line status of a queued or running job: how many jobs are ahead while it waits, and how
 * long it has run (from the server's start time) once it does. `now` is the browser's clock in ms.
 */
export function jobStatusText(job: JobInfo, now: number, stopping: boolean): string {
  const label = jobLabel(job);
  if (stopping) return `${label}: ${JOB_STOPPING.toLowerCase()}`;
  if (job.status === "queued") {
    const ahead = job.position ?? 0;
    return ahead > 0 ? `${label} queued (${ahead} ahead)` : `${label} queued`;
  }
  const started = job.started_at ? Date.parse(job.started_at) : Number.NaN;
  return Number.isFinite(started) ? `${label} running, ${formatElapsed((now - started) / 1000)}` : `${label} running`;
}
