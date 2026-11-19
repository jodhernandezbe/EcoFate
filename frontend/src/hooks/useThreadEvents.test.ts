import { act, renderHook, waitFor } from "@testing-library/react";

import type { JobInfo, ThreadEvent, ThreadSnapshot } from "../types/workspace";
import { useThreadEvents } from "./useThreadEvents";

const JOB = "b".repeat(32);
const TURN = "c".repeat(32);
const queuedJob: JobInfo = {
  job_id: JOB,
  tool: "assess_facilities",
  status: "queued",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: null,
  ended_at: null,
  position: 1,
};
const runningJob: JobInfo = { ...queuedJob, status: "running", started_at: "2026-01-01T00:00:30Z", position: null };

const event = (change: Partial<ThreadEvent>): ThreadEvent => ({
  kind: "job.running",
  status: "running",
  job_id: JOB,
  tool: "assess_facilities",
  turn_id: null,
  automatic: null,
  ...change,
});
const entry = (id: string, e: ThreadEvent): string => `id: ${id}\ndata: ${JSON.stringify(e)}\n\n`;
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status });
const snapshot = (jobs: JobInfo[]) => ({ thread_id: "t1", jobs }) as unknown as ThreadSnapshot;

/** A stream that sends `frames`, then stays open (as the server's does) until the test ends. */
function openStream(frames: string): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(frames));
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

type Route = (url: string, init?: RequestInit) => Response | undefined;
function stub(route: Route) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      return Promise.resolve(route(url, init) ?? json({ error: "No." }, 404));
    }),
  );
  return calls;
}

const render = (held = true, initialJobs: JobInfo[] = [queuedJob], onAutomaticTurn = vi.fn()) =>
  renderHook(() => useThreadEvents({ threadId: "t1", held, initialJobs, onAutomaticTurn }));

afterEach(() => vi.unstubAllGlobals());

describe("useThreadEvents", () => {
  it("starts from the jobs of the snapshot and lists the open ones", () => {
    stub(() => undefined);
    const { result } = render(false, [queuedJob, { ...runningJob, job_id: "d".repeat(32), status: "succeeded" }]);
    expect(result.current.jobs).toHaveLength(2);
    expect(result.current.openJobs.map((j) => j.status)).toEqual(["queued"]);
  });

  it("opens no stream for a thread the server does not hold", () => {
    const calls = stub(() => undefined);
    render(false);
    expect(calls).toEqual([]);
  });

  it("reads the thread's jobs again when a job event arrives", async () => {
    stub((url) => {
      if (url.endsWith("/chat/threads/t1/events")) return openStream(entry("1-0", event({})));
      if (url.endsWith("/chat/threads/t1")) return json(snapshot([runningJob]));
      return undefined;
    });
    const { result } = render();
    await waitFor(() => expect(result.current.openJobs[0]?.status).toBe("running"));
    expect(result.current.openJobs[0]?.started_at).toBe("2026-01-01T00:00:30Z");
  });

  it("follows a turn the system started, once, and reports the turn's lifecycle", async () => {
    stub((url) => {
      if (url.endsWith("/events")) {
        const started = event({ kind: "turn.started", job_id: null, tool: null, turn_id: TURN, automatic: true });
        const own = event({ kind: "turn.started", job_id: null, tool: null, turn_id: "e".repeat(32), automatic: false });
        return openStream(entry("1-0", own) + entry("2-0", started));
      }
      return undefined;
    });
    const onAutomaticTurn = vi.fn();
    const { result } = render(true, [], onAutomaticTurn);
    await waitFor(() => expect(result.current.turn?.turnId).toBe(TURN));
    expect(result.current.turn).toEqual({ turnId: TURN, automatic: true, phase: "started" });
    expect(onAutomaticTurn).toHaveBeenCalledExactlyOnceWith(TURN);
  });

  it("reconnects after a drop from the last entry received", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let opened = 0;
    const calls = stub((url) => {
      if (!url.endsWith("/events")) return json(snapshot([]));
      opened += 1;
      return opened === 1 ? new Response(entry("7-1", event({})), { status: 200 }) : openStream("");
    });
    render();
    await waitFor(() => expect(opened).toBe(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    await waitFor(() => expect(opened).toBe(2));
    const second = calls.filter((c) => c.url.endsWith("/events"))[1];
    expect(second?.init?.headers).toEqual({ "Last-Event-ID": "7-1" });
    vi.useRealTimers();
  });

  it("does not retry a thread the server answers 404 for", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = stub(() => undefined);
    render();
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(40000);
    });
    expect(calls.filter((c) => c.url.endsWith("/events"))).toHaveLength(1);
    vi.useRealTimers();
  });

  it("cancels a job, marks it as stopping and reads the jobs again", async () => {
    const calls = stub((url, init) => {
      if (url.endsWith(`/chat/jobs/${JOB}/cancel`) && init?.method === "POST") return new Response(null, { status: 202 });
      if (url.endsWith("/events")) return openStream("");
      if (url.endsWith("/chat/threads/t1")) return json(snapshot([runningJob]));
      return undefined;
    });
    const { result } = render(true, [runningJob]);
    await act(() => result.current.cancel(JOB));
    expect(result.current.cancelling.has(JOB)).toBe(true);
    expect(calls.some((c) => c.url.endsWith(`/chat/jobs/${JOB}/cancel`))).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("says so, and lets the user try again, when the cancel fails", async () => {
    stub((url) => {
      if (url.endsWith("/cancel")) return json({ error: "Down." }, 500);
      if (url.endsWith("/events")) return openStream("");
      return json(snapshot([runningJob]));
    });
    const { result } = render(true, [runningJob]);
    await act(() => result.current.cancel(JOB));
    expect(result.current.error).toMatch(/could not be cancelled/);
    expect(result.current.cancelling.has(JOB)).toBe(false);
  });

  it("starts over when the thread changes", () => {
    stub(() => undefined);
    const { result, rerender } = renderHook((props: { id: string; jobs: JobInfo[] }) =>
      useThreadEvents({ threadId: props.id, held: false, initialJobs: props.jobs }),
    { initialProps: { id: "t1", jobs: [queuedJob] } });
    expect(result.current.jobs).toHaveLength(1);
    const none: JobInfo[] = [];
    rerender({ id: "t2", jobs: none });
    expect(result.current.jobs).toEqual([]);
  });
});
