import type { StreamEvent, ThreadEvent } from "../types/workspace";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseEvent(data: string): StreamEvent {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new Error("Malformed event from the server.");
  }
  if (!isRecord(value) || typeof value.type !== "string") {
    throw new Error("Malformed event from the server.");
  }
  // The server's events follow the generated contract (checked by the contract tests).
  return value as unknown as StreamEvent;
}

/** Split buffered SSE text into complete events and the unfinished remainder. */
export function parseSseFrames(buffer: string): { events: StreamEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const frame of frames) {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => line.slice("data: ".length))
      .join("\n");
    if (data) events.push(parseEvent(data));
  }
  return { events, rest };
}

/** One entry of a thread's stream: its id (the next `Last-Event-ID`) and the event. */
export interface ThreadEntry {
  id: string;
  event: ThreadEvent;
}

const THREAD_KINDS = ["job.queued", "job.running", "job.ended", "turn.started", "turn.ended"];

function parseThreadEvent(data: string): ThreadEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  const kind = isRecord(value) ? value.kind : null;
  // An event this build does not know is skipped, never guessed at (its id still advances).
  return typeof kind === "string" && THREAD_KINDS.includes(kind) ? (value as ThreadEvent) : null;
}

/**
 * Split buffered text of a thread's stream into its entries and the unfinished remainder.
 * Keep-alive comments and frames without an id or a known event are skipped.
 */
export function parseThreadFrames(buffer: string): { entries: ThreadEntry[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const entries: ThreadEntry[] = [];
  for (const frame of frames) {
    const lines = frame.split("\n");
    const id = lines.find((line) => line.startsWith("id: "))?.slice("id: ".length);
    const data = lines
      .filter((line) => line.startsWith("data: "))
      .map((line) => line.slice("data: ".length))
      .join("\n");
    const event = id && data ? parseThreadEvent(data) : null;
    if (id && event) entries.push({ id, event });
  }
  return { entries, rest };
}
