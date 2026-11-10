import { ApiError, getMe, getKeysStatus, onUnauthorized, resumeChat, signIn } from "./apiClient";

function sse(...events: object[]): Response {
  const body = events
    .map((event) => `data: ${JSON.stringify(event)}\n\n`)
    .join("");
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("resumeChat", () => {
  it("posts to the thread's resume endpoint and yields its events", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        sse(
          {
            type: "turn_started",
            seq: 0,
            thread_id: "t 1",
            turn_id: "x",
            resumed: true,
          },
          { type: "turn_finished", seq: 1 },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    const types: string[] = [];
    for await (const event of resumeChat("t 1")) types.push(event.type);
    expect(types).toEqual(["turn_started", "turn_finished"]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/chat/threads/t%201/resume",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("rejects with the server's fixed message when the resume is refused", async () => {
    const refusal = new Response(
      JSON.stringify({ error: "Nothing to resume." }),
      { status: 409 },
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(refusal));
    const run = resumeChat("t1");
    await expect(run.next()).rejects.toEqual(
      new ApiError("Nothing to resume.", 409),
    );
  });
});

const failure = (status: number, body: object, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

describe("errors", () => {
  it("reads the wait a 429 asks for", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(failure(429, { error: "Too many attempts." }, { "Retry-After": "30" })));
    await expect(signIn("a@example.com", "x")).rejects.toMatchObject({ status: 429, retryAfter: 30, message: "Too many attempts." });
  });

  it("shows the first field message of a 422 instead of the generic one", async () => {
    const body = { error: "Invalid request.", fields: [{ loc: ["body", "password"], msg: "Use at least 12 characters." }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(failure(422, body)));
    await expect(signIn("a@example.com", "x")).rejects.toMatchObject({ status: 422, message: "Use at least 12 characters." });
  });
});

describe("a 401 while signed in", () => {
  it("tells the listeners, but not for the sign-in or session-probe routes", async () => {
    const listener = vi.fn();
    const stop = onUnauthorized(listener);
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(failure(401, { error: "Sign in to continue." }))));
    await expect(signIn("a@example.com", "x")).rejects.toBeInstanceOf(ApiError);
    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
    await expect(getKeysStatus()).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    await expect(getKeysStatus()).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
