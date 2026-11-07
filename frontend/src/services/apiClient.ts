import type {
  ChatRequest,
  ClientConfig,
  KeyName,
  KeysStatusResponse,
  KeyStatusResponse,
  SessionDetailResponse,
  SessionsResponse,
  StreamEvent,
  ThreadSnapshot,
} from "../types/workspace";
import { parseSseFrames } from "./sse";

const BASE = "/api/v1";
const JSON_HEADERS = { "content-type": "application/json" };

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      const { error } = body as { error: unknown };
      if (typeof error === "string") return error;
    }
  } catch {
    // not a JSON error body
  }
  return `Request failed (${response.status}).`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(BASE + path, init);
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return response;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  // First-party API whose shapes are generated from its schemas (see src/types).
  return (await (await request(path, init)).json()) as T;
}

export const getClientConfig = (): Promise<ClientConfig> => json("/settings/client");

const KEY_PATHS: Record<KeyName, string> = {
  openai: "openai-key",
  census: "census-key",
  comptox: "comptox-key",
};

export const getKeysStatus = (): Promise<KeysStatusResponse> => json("/settings/keys");

export const saveKey = (name: KeyName, apiKey: string): Promise<KeyStatusResponse> =>
  json(`/settings/${KEY_PATHS[name]}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ api_key: apiKey }),
  });

export const clearKey = (name: KeyName): Promise<KeyStatusResponse> =>
  json(`/settings/${KEY_PATHS[name]}`, { method: "DELETE" });

/** A held thread's messages, workspace and usage; rejects with a 404 `ApiError` when gone. */
export const getThread = (threadId: string): Promise<ThreadSnapshot> =>
  json(`/chat/threads/${encodeURIComponent(threadId)}`);

/** The most recent recorded sessions, newest first (or the reason there are none). */
export const getMonitoringSessions = (): Promise<SessionsResponse> => json("/monitoring/sessions");

/** One recorded session with its turns; rejects with a 404 `ApiError` when none was recorded. */
export const getMonitoringSession = (sessionId: string): Promise<SessionDetailResponse> =>
  json(`/monitoring/sessions/${encodeURIComponent(sessionId)}`);

// The server names the file; this is used only if a response arrives without that header.
const REPORT_FALLBACK_NAME = "assessment-report.docx";
const ATTACHMENT_NAME = /filename="([^"]+)"/;

/** A file from the server, ready to save. */
export interface DownloadedFile {
  name: string;
  blob: Blob;
}

/** The thread's Word report; rejects with an `ApiError` (404 gone, 409 busy or nothing yet). */
export async function getReport(threadId: string): Promise<DownloadedFile> {
  const response = await request(`/chat/threads/${encodeURIComponent(threadId)}/report`);
  const header = response.headers.get("content-disposition") ?? "";
  const name = ATTACHMENT_NAME.exec(header)?.[1] ?? REPORT_FALLBACK_NAME;
  return { name, blob: await response.blob() };
}

export async function resetThread(threadId: string): Promise<void> {
  await request(`/chat/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
}

/** Read a server-sent event stream into its events as they arrive. */
async function* events(response: Response): AsyncGenerator<StreamEvent> {
  if (!response.body) throw new ApiError("The server sent no stream.", response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events: parsed, rest } = parseSseFrames(buffer);
    buffer = rest;
    yield* parsed;
  }
}

/** Stream the events of one chat turn as they arrive. */
export async function* streamChat(
  body: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await request("/chat/stream", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  yield* events(response);
}

/**
 * Continue the thread's interrupted turn where it stopped and stream the rest of it; rejects
 * with a 409 `ApiError` (fixed message) when there is nothing to resume, the turn was resumed
 * too often, a turn is running or no key is set, and 404 when the thread is gone.
 */
export async function* resumeChat(threadId: string, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const path = `/chat/threads/${encodeURIComponent(threadId)}/resume`;
  yield* events(await request(path, { method: "POST", signal }));
}
