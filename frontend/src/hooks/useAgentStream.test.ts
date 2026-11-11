import { act, renderHook, waitFor } from "@testing-library/react";

import type { StreamEvent, ThreadSnapshot } from "../types/workspace";
import { useAgentStream } from "./useAgentStream";

const TURN = "a".repeat(32);
const totals = {
  calls: 0,
  input_tokens: 0,
  cached_input_tokens: 0,
  output_tokens: 0,
  complete: true,
  cost_usd: null,
  cost_status: "unpriced" as const,
  priced_on: null,
};

const frame = (event: StreamEvent): string => `id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`;
const sse = (events: StreamEvent[]): Response =>
  new Response(events.map(frame).join(""), { status: 200, headers: { "content-type": "text/event-stream" } });
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), { status });
const missing = (): Response => json({ error: "That run is no longer available." }, 404);

const started: StreamEvent = { type: "turn_started", seq: 0, thread_id: "t1", turn_id: TURN, resumed: false };
const queued: StreamEvent = { type: "turn_status", seq: 1, phase: "queued", label: null, position: 0 };
const token = (seq: number, text: string): StreamEvent => ({ type: "token", seq, text });
const finished = (seq: number): StreamEvent => ({ type: "turn_finished", seq });

function snapshot(running: ThreadSnapshot["running_turn"]): ThreadSnapshot {
  return {
    thread_id: "t1",
    messages: [
      { role: "user", text: "first" },
      { role: "assistant", text: "First answer." },
    ],
    workspace: { chemical: { cas_number: null } } as never,
    usage: totals,
    confirmation: null,
    interrupted: null,
    running_turn: running,
  };
}

type Route = (url: string, init?: RequestInit) => Response | Promise<Response> | undefined;

function stub(route: Route) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      return Promise.resolve(route(url, init) ?? missing());
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("useAgentStream", () => {
  it("continues the current thread and reattaches to its running turn after a reload", async () => {
    const calls = stub((url) => {
      if (url.endsWith("/chat/current-thread")) return json(snapshot({ turn_id: TURN, resumed: false, question: "second" }));
      if (url.endsWith(`/chat/turns/${TURN}/events`)) return sse([started, queued, token(128, "Second answer."), finished(192)]);
      return undefined;
    });
    const replaced: unknown[] = [];
    const { result } = renderHook(() => useAgentStream({ onReplace: (state) => replaced.push(state) }));
    await waitFor(() => expect(result.current.busy).toBe(false));
    await waitFor(() => expect(result.current.messages).toHaveLength(4));
    expect(result.current.threadId).toBe("t1");
    expect(result.current.messages.map((m) => [m.role, m.text])).toEqual([
      ["user", "first"],
      ["assistant", "First answer."],
      ["user", "second"],
      ["assistant", "Second answer."],
    ]);
    expect(replaced).toHaveLength(1); // the workspace was restored from the snapshot
    const reattach = calls.find((call) => call.url.endsWith("/events"));
    expect(new Headers(reattach?.init?.headers).get("Last-Event-ID")).toBeNull(); // from the first event
  });

  it("opens on a fresh thread when the user has none", async () => {
    stub(() => undefined);
    const { result } = renderHook(() => useAgentStream());
    await waitFor(() => expect(result.current.messages).toEqual([]));
    expect(result.current.busy).toBe(false);
  });

  it("reads a dropped stream again from the last event, without repeating anything", async () => {
    const calls = stub((url) => {
      if (url.endsWith("/chat/stream")) return sse([started, token(64, "Hel")]); // drops here
      if (url.endsWith(`/chat/turns/${TURN}/events`)) return sse([token(128, "lo"), finished(192)]);
      return undefined;
    });
    const { result } = renderHook(() => useAgentStream());
    await act(() => result.current.send("hi"));
    expect(result.current.messages.at(-1)?.text).toBe("Hello");
    expect(result.current.busy).toBe(false);
    const reattach = calls.find((call) => call.url.endsWith("/events"));
    expect(new Headers(reattach?.init?.headers).get("Last-Event-ID")).toBe("64");
  });

  it("shows the thread from the server once a dropped turn's events have expired", async () => {
    let restored = false;
    stub((url) => {
      if (url.endsWith("/chat/stream")) return sse([started]);
      if (url.endsWith("/events")) return json({ error: "Expired." }, 410);
      if (url.endsWith("/chat/threads/t1") || url.includes("/chat/threads/")) {
        restored = true;
        return json(snapshot(null));
      }
      return undefined;
    });
    const { result } = renderHook(() => useAgentStream());
    await act(() => result.current.send("hi"));
    expect(restored).toBe(true);
    expect(result.current.messages.map((m) => m.text)).toEqual(["first", "First answer."]);
    expect(result.current.busy).toBe(false);
  });

  it("asks the running turn to stop", async () => {
    let finish: (() => void) | null = null;
    const encoder = new TextEncoder();
    const calls = stub((url) => {
      if (url.endsWith("/chat/stream")) {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode(frame(started)));
            finish = () => {
              controller.enqueue(encoder.encode(frame(finished(64))));
              controller.close();
            };
          },
        });
        return new Response(body, { status: 200 });
      }
      if (url.endsWith(`/chat/turns/${TURN}/cancel`)) return new Response(null, { status: 202 });
      return undefined;
    });
    const { result } = renderHook(() => useAgentStream());
    let sending: Promise<void> = Promise.resolve();
    act(() => {
      sending = result.current.send("hi");
    });
    await waitFor(() => expect(result.current.busy).toBe(true));
    await waitFor(() => expect(finish).not.toBeNull());
    await act(() => result.current.stop());
    expect(result.current.stopping).toBe(true);
    expect(calls.some((call) => call.url.endsWith(`/chat/turns/${TURN}/cancel`) && call.init?.method === "POST")).toBe(true);
    await act(async () => {
      finish?.();
      await sending;
    });
    expect(result.current.stopping).toBe(false);
  });
});
