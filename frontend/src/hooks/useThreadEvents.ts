import { useCallback, useEffect, useRef, useState } from "react";

import type { JobInfo, ThreadEvent } from "../types/workspace";

import { ApiError, cancelJob, getThread, threadEvents } from "../services/apiClient";

const NOT_FOUND = 404;
const CONFLICT = 409;
// A dropped thread stream is read again from the last entry received, waiting longer each time.
const RECONNECT_DELAY_MS = 1000;
const RECONNECT_DELAY_MAX_MS = 15000;
// While a job waits for a worker, how many jobs are ahead of it changes without an event.
const QUEUE_REFRESH_MS = 10000;
const NOT_CANCELLED = "The assessment could not be cancelled. Try again.";

const isOpen = (job: JobInfo): boolean => job.status === "queued" || job.status === "running";
const pause = (ms: number): Promise<void> => new Promise((done) => setTimeout(done, ms));

/** The last turn the thread stream reported: its id, whether the system started it, and where it is. */
export interface ThreadTurn {
  turnId: string;
  automatic: boolean;
  phase: "started" | "ended";
}

export interface ThreadEventsOptions {
  /** The thread to follow. */
  threadId: string;
  /** Whether the server holds the thread (a stream of an unknown thread is a 404). */
  held: boolean;
  /** The jobs of the thread's snapshot, shown until the stream says otherwise. */
  initialJobs: readonly JobInfo[];
  /** A turn the system started (a job's follow-up) began: follow it like any other turn. */
  onAutomaticTurn?: ((turnId: string) => void) | undefined;
}

/** What the page shows of a thread's background work. */
export interface ThreadJobs {
  /** The thread's jobs as the server last reported them, oldest first. */
  jobs: JobInfo[];
  /** The jobs that are queued or running. */
  openJobs: JobInfo[];
  /** The jobs the user asked to stop and that have not ended yet. */
  cancelling: ReadonlySet<string>;
  /** The latest turn the thread stream reported (null before any). */
  turn: ThreadTurn | null;
  /** Why the last cancel failed (null when none did). */
  error: string | null;
  /** Ask a queued or running job to stop. */
  cancel: (jobId: string) => Promise<void>;
}

function turnOf(event: ThreadEvent): ThreadTurn | null {
  if (!event.turn_id || (event.kind !== "turn.started" && event.kind !== "turn.ended")) return null;
  const phase = event.kind === "turn.started" ? "started" : "ended";
  return { turnId: event.turn_id, automatic: event.automatic === true, phase };
}

/**
 * Follow a thread's background jobs and the turns the system starts for them. It reads the
 * thread's stream (`/chat/threads/{id}/events`, again from the last entry after a drop); the
 * stream carries ids and statuses only, so each job event is answered by reading the thread's
 * jobs (with their times) from the server. The jobs of the snapshot are the first state.
 */
export function useThreadEvents(options: ThreadEventsOptions): ThreadJobs {
  const { threadId, held, initialJobs, onAutomaticTurn } = options;
  const [jobs, setJobs] = useState<JobInfo[]>([...initialJobs]);
  const [turn, setTurn] = useState<ThreadTurn | null>(null);
  const [asked, setAsked] = useState<ReadonlySet<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const heard = useRef(onAutomaticTurn);
  const refreshing = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  useEffect(() => {
    heard.current = onAutomaticTurn;
  });

  // A different snapshot or thread starts from what the server says (state adjusted while rendering).
  const [source, setSource] = useState({ threadId, initialJobs });
  if (source.threadId !== threadId || source.initialJobs !== initialJobs) {
    setSource({ threadId, initialJobs });
    setJobs([...initialJobs]);
    setTurn(null);
    setAsked(new Set());
    setError(null);
  }

  /** Read the thread's jobs again; calls made meanwhile are answered by one more read. */
  const refresh = useCallback(async (): Promise<void> => {
    if (refreshing.current) {
      again.current = true;
      return refreshing.current;
    }
    const read = (async () => {
      try {
        do {
          again.current = false;
          setJobs((await getThread(threadId)).jobs);
        } while (again.current);
      } catch {
        // The next event or the next poll reads them again.
      } finally {
        refreshing.current = null;
      }
    })();
    refreshing.current = read;
    return read;
  }, [threadId]);

  const apply = useCallback(
    (event: ThreadEvent) => {
      if (event.kind.startsWith("job.")) void refresh();
      const next = turnOf(event);
      if (!next) return;
      setTurn(next);
      if (next.automatic && next.phase === "started") heard.current?.(next.turnId);
    },
    [refresh],
  );

  // The stream: read again from the last entry received after a drop; none while the thread is unknown.
  useEffect(() => {
    if (!held) return;
    const abort = new AbortController();
    let lastId: string | null = null;
    void (async () => {
      for (let attempt = 0; !abort.signal.aborted; attempt++) {
        try {
          for await (const entry of threadEvents(threadId, lastId, abort.signal)) {
            lastId = entry.id;
            attempt = 0;
            apply(entry.event);
          }
        } catch (failure) {
          if (abort.signal.aborted || (failure instanceof ApiError && failure.status === NOT_FOUND)) return;
        }
        if (abort.signal.aborted) return;
        await pause(Math.min(RECONNECT_DELAY_MS * (attempt + 1), RECONNECT_DELAY_MAX_MS));
        void refresh(); // what happened while the stream was down
      }
    })();
    return () => abort.abort();
  }, [threadId, held, apply, refresh]);

  const waiting = jobs.some((job) => job.status === "queued");
  useEffect(() => {
    if (!held || !waiting) return;
    const timer = setInterval(() => void refresh(), QUEUE_REFRESH_MS);
    return () => clearInterval(timer);
  }, [held, waiting, refresh]);

  const cancel = useCallback(
    async (jobId: string) => {
      setError(null);
      setAsked((before) => new Set(before).add(jobId));
      try {
        await cancelJob(jobId);
      } catch (failure) {
        const ended = failure instanceof ApiError && failure.status === CONFLICT;
        if (!ended) {
          setAsked((before) => new Set([...before].filter((id) => id !== jobId)));
          setError(NOT_CANCELLED);
        }
      }
      void refresh();
    },
    [refresh],
  );

  const openJobs = jobs.filter(isOpen);
  const cancelling = new Set(openJobs.filter((job) => asked.has(job.job_id)).map((job) => job.job_id));
  return { jobs, openJobs, cancelling, turn, error, cancel };
}
