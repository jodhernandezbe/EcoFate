import { X } from "lucide-react";
import { useEffect, useState } from "react";

import type { JobInfo } from "../../types/workspace";
import { JOB_STOPPING, jobLabel, jobStatusText } from "./jobStatusText";

const BAR = "flex flex-wrap items-center gap-2 border-b border-hairline px-5 py-2";
const TICK_MS = 1000;

/** The browser's clock in ms, renewed every second while `active` (the running time updates). */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

export interface JobControlsProps {
  /** The thread's queued or running jobs, oldest first. */
  jobs: readonly JobInfo[];
  /** The ids of the jobs the user asked to stop. */
  cancelling?: ReadonlySet<string> | undefined;
  /** Why the last cancel failed. */
  error?: string | null | undefined;
  onCancel?: ((jobId: string) => void) | undefined;
}

/**
 * The status of the thread's background work, in the turn controls area under the chat header: one
 * line per queued or running job with a Cancel pill. Messages can be sent while it runs, so
 * nothing here blocks the composer.
 */
export function JobControls({ jobs, cancelling, error, onCancel }: JobControlsProps) {
  const running = jobs.some((job) => job.status === "running");
  const now = useNow(running);
  if (jobs.length === 0 && !error) return null;
  return (
    <>
      {jobs.map((job) => {
        const stopping = cancelling?.has(job.job_id) ?? false;
        return (
          <div key={job.job_id} className={BAR}>
            <span role="status" aria-live="polite" className="min-w-0 flex-1 text-xs text-fg2">
              {jobStatusText(job, now, stopping)}
            </span>
            {onCancel ? (
              <button
                type="button"
                disabled={stopping}
                title={stopping ? JOB_STOPPING : undefined}
                aria-description={stopping ? JOB_STOPPING : undefined}
                aria-label={`Cancel ${jobLabel(job).toLowerCase()}`}
                onClick={() => onCancel(job.job_id)}
                className="spring inline-flex items-center gap-1 rounded-full border border-hairline px-3 py-1 text-sm text-fg transition hover:bg-hairline disabled:opacity-30"
              >
                <X className="size-4" aria-hidden="true" />
                Cancel
              </button>
            ) : null}
          </div>
        );
      })}
      {error ? (
        <p role="alert" className={`${BAR} m-0 text-xs text-bad`}>
          {error}
        </p>
      ) : null}
    </>
  );
}
