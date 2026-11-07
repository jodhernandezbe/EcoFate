import { ApiError, resumeChat } from "./apiClient";

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
