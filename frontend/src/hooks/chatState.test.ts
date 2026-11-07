import type { StreamEvent } from "../types/workspace";
import { chatReducer, initialChatState, type ChatState } from "./chatState";

const token = (text: string): StreamEvent => ({ type: "token", seq: 1, text });
const sent: ChatState = chatReducer(initialChatState, {
  type: "user_sent",
  id: "u1",
  assistantId: "a1",
  text: "hello",
});

describe("chatReducer", () => {
  it("adds the user message and a streaming assistant placeholder", () => {
    expect(sent.busy).toBe(true);
    expect(sent.messages.map((m) => [m.role, m.text, m.streaming])).toEqual([
      ["user", "hello", false],
      ["assistant", "", true],
    ]);
  });

  it("appends tokens to the assistant message", () => {
    let state = chatReducer(sent, { type: "event", event: token("Hel") });
    state = chatReducer(state, { type: "event", event: token("lo") });
    expect(state.messages[1]?.text).toBe("Hello");
  });

  it("keeps streamed text when the final message arrives", () => {
    let state = chatReducer(sent, { type: "event", event: token("Hello there") });
    const final: StreamEvent = { type: "assistant_message", seq: 2, text: "Hello there" };
    state = chatReducer(state, { type: "event", event: final });
    expect(state.messages[1]?.text).toBe("Hello there");
  });

  it("uses the final message when the model did not stream", () => {
    const final: StreamEvent = { type: "assistant_message", seq: 2, text: "Hello there" };
    const state = chatReducer(sent, { type: "event", event: final });
    expect(state.messages[1]?.text).toBe("Hello there");
  });

  describe("tool steps", () => {
    const status = (
      phase: "started" | "finished",
      id: string,
      label: string,
      outcome: "ok" | "error" | null = null,
    ): StreamEvent => ({
      type: "tool_status",
      seq: 1,
      phase,
      call_id: id,
      tool_name: "t",
      label,
      status: outcome,
    });
    const apply = (state: ChatState, event: StreamEvent) =>
      chatReducer(state, { type: "event", event });

    it("adds a running step and then marks it done", () => {
      let state = apply(sent, status("started", "c1", "Queried EPA TRI releases"));
      expect(state.messages[1]?.tools).toEqual([
        { callId: "c1", label: "Queried EPA TRI releases", state: "running" },
      ]);
      state = apply(state, status("finished", "c1", "Queried EPA TRI releases", "ok"));
      expect(state.messages[1]?.tools[0]?.state).toBe("done");
    });

    it("marks a failed step as error and keeps the others", () => {
      let state = apply(sent, status("started", "c1", "One"));
      state = apply(state, status("started", "c2", "Two"));
      state = apply(state, status("finished", "c2", "Two", "error"));
      expect(state.messages[1]?.tools.map((s) => [s.callId, s.state])).toEqual([
        ["c1", "running"],
        ["c2", "error"],
      ]);
    });

    it("ignores a repeated start and tolerates a finish with no start", () => {
      let state = apply(sent, status("started", "c1", "One"));
      state = apply(state, status("started", "c1", "One"));
      state = apply(state, status("finished", "c9", "Nine", "ok"));
      expect(state.messages[1]?.tools.map((s) => s.callId)).toEqual(["c1", "c9"]);
    });

    it("separates narration before a tool from the text after it", () => {
      let state = apply(sent, token("Let me check."));
      state = apply(state, status("started", "c1", "One"));
      state = apply(state, token("Done."));
      expect(state.messages[1]?.text).toBe("Let me check.\n\nDone.");
    });
  });

  it("shows an error event on the assistant message and ends the turn", () => {
    const error: StreamEvent = { type: "error", seq: 1, message: "Add your key", correlation_id: "c" };
    let state = chatReducer(sent, { type: "event", event: error });
    state = chatReducer(state, { type: "event", event: { type: "turn_finished", seq: 2 } });
    expect(state.messages[1]).toMatchObject({ error: "Add your key", streaming: false });
    expect(state.busy).toBe(false);
  });

  it("marks the turn failed when the request itself fails", () => {
    const state = chatReducer(sent, { type: "failed", message: "Request failed (500)." });
    expect(state.busy).toBe(false);
    expect(state.messages[1]).toMatchObject({ error: "Request failed (500).", streaming: false });
  });

  it("closes a stream that ended without turn_finished", () => {
    const state = chatReducer(sent, { type: "closed" });
    expect(state.busy).toBe(false);
    expect(state.messages[1]?.streaming).toBe(false);
  });

  it("shows the redirect for an off-topic turn as the assistant's message, not an error", () => {
    const scope: StreamEvent = { type: "scope", seq: 1, in_scope: false };
    const pivot: StreamEvent = { type: "guardrail_pivot", seq: 2, text: "I can't help with that." };
    let state = chatReducer(sent, { type: "event", event: scope });
    state = chatReducer(state, { type: "event", event: pivot });
    state = chatReducer(state, { type: "event", event: { type: "turn_finished", seq: 3 } });
    expect(state.messages[1]).toMatchObject({
      text: "I can't help with that.",
      error: null,
      streaming: false,
      tools: [],
    });
    expect(state.busy).toBe(false);
  });

  it("keeps the latest usage and clears it on reset", () => {
    const totals = {
      calls: 1,
      input_tokens: 5,
      cached_input_tokens: 0,
      output_tokens: 6,
      complete: true,
      cost_usd: null,
      cost_status: "unpriced" as const,
      priced_on: null,
    };
    const usage: StreamEvent = { type: "usage", seq: 3, turn: totals, session: totals };
    const state = chatReducer(sent, { type: "event", event: usage });
    expect(state.usage).toEqual({ turn: totals, session: totals });
    expect(state.busy).toBe(true); // usage does not end the turn; turn_finished does
    expect(chatReducer(state, { type: "reset" }).usage).toBeNull();
  });

  it("ignores events with no chat meaning and resets", () => {
    const scope: StreamEvent = { type: "scope", seq: 1, in_scope: true };
    expect(chatReducer(sent, { type: "event", event: scope })).toBe(sent);
    expect(chatReducer(sent, { type: "reset" })).toEqual(initialChatState);
  });
});

describe("restore", () => {
  const totals = {
    calls: 2,
    input_tokens: 10,
    cached_input_tokens: 0,
    output_tokens: 5,
    complete: true,
    cost_usd: null,
    cost_status: "unpriced" as const,
    priced_on: null,
  };
  const snapshot = {
    thread_id: "t",
    messages: [
      { role: "user" as const, text: "hi" },
      { role: "assistant" as const, text: "hello" },
    ],
    workspace: {} as never,
    usage: totals,
    confirmation: null,
    interrupted: null,
  };

  it("replaces the conversation with the held messages, idle, without tool steps", () => {
    const state = chatReducer(sent, { type: "restore", snapshot, ids: ["a", "b"] });
    expect(state.busy).toBe(false);
    expect(state.messages.map((m) => [m.id, m.role, m.text, m.streaming, m.tools])).toEqual([
      ["a", "user", "hi", false, []],
      ["b", "assistant", "hello", false, []],
    ]);
  });

  it("shows the session usage but no last turn", () => {
    const state = chatReducer(initialChatState, { type: "restore", snapshot, ids: [] });
    expect(state.usage).toEqual({ turn: null, session: totals });
  });

  it("shows no usage for a thread that made no model call", () => {
    const empty = { ...snapshot, usage: { ...totals, calls: 0 } };
    expect(chatReducer(sent, { type: "restore", snapshot: empty, ids: [] }).usage).toBeNull();
  });
});

describe("interrupted turns", () => {
  const interrupted: StreamEvent = {
    type: "turn_interrupted",
    seq: 3,
    reason: "out_of_credits",
    resumable: true,
    message: "No credits left. Add credits, then press Resume.",
  };
  const finished: StreamEvent = { type: "turn_finished", seq: 5 };
  const feed = (state: ChatState, events: StreamEvent[]): ChatState =>
    events.reduce((current, event) => chatReducer(current, { type: "event", event }), state);
  const stopped = feed(sent, [token("Partial "), interrupted, finished]);

  it("keeps the partial text, records the stop and ends the stream", () => {
    const message = stopped.messages[1];
    expect(message?.text).toBe("Partial ");
    expect(message?.interrupted).toEqual({
      reason: "out_of_credits",
      resumable: true,
      message: "No credits left. Add credits, then press Resume.",
    });
    expect(message?.streaming).toBe(false);
    expect(message?.error).toBeNull();
    expect(stopped.busy).toBe(false);
  });

  it("continues the same assistant message when resumed", () => {
    let state = chatReducer(stopped, { type: "resume_sent" });
    expect(state.busy).toBe(true);
    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]?.streaming).toBe(true);
    const started: StreamEvent = { type: "turn_started", seq: 0, thread_id: "t", turn_id: "turn-1", resumed: true };
    state = feed(state, [started, token("rest."), finished]);
    expect(state.messages).toHaveLength(2);
    expect(state.messages[1]?.text).toBe("Partial rest.");
    expect(state.messages[1]?.interrupted).toBeNull();
    expect(state.busy).toBe(false);
  });

  it("keeps the stop when the server refuses the resume", () => {
    let state = chatReducer(stopped, { type: "resume_sent" });
    state = chatReducer(state, { type: "failed", message: "Resumed too many times." });
    expect(state.messages[1]?.interrupted?.reason).toBe("out_of_credits");
    expect(state.messages[1]?.error).toBe("Resumed too many times.");
    expect(state.busy).toBe(false);
  });

  it("a new message drops the stop's Resume control", () => {
    const state = chatReducer(stopped, { type: "user_sent", id: "u2", assistantId: "a2", text: "next" });
    expect(state.messages.map((m) => m.interrupted)).toEqual([null, null, null, null]);
    expect(state.messages[1]?.text).toBe("Partial ");
  });

  const totals = {
    calls: 1,
    input_tokens: 1,
    cached_input_tokens: 0,
    output_tokens: 1,
    complete: true,
    cost_usd: null,
    cost_status: "unpriced" as const,
    priced_on: null,
  };
  const stop = { reason: "bad_key" as const, resumable: true, message: "Key rejected." };
  const held = (messages: { role: "user" | "assistant"; text: string }[]) => ({
    thread_id: "t",
    messages,
    workspace: {} as never,
    usage: totals,
    confirmation: null,
    interrupted: stop,
  });

  it("restores the stop onto the last assistant message of a held thread", () => {
    const snapshot = held([
      { role: "user", text: "hi" },
      { role: "assistant", text: "partial" },
    ]);
    const state = chatReducer(initialChatState, { type: "restore", snapshot, ids: ["a", "b"] });
    expect(state.messages.map((m) => m.interrupted)).toEqual([null, stop]);
  });

  it("adds an empty assistant message for a stop before any text", () => {
    const snapshot = held([{ role: "user", text: "hi" }]);
    const state = chatReducer(initialChatState, { type: "restore", snapshot, ids: ["a"] });
    expect(state.messages.map((m) => [m.role, m.text, m.interrupted])).toEqual([
      ["user", "hi", null],
      ["assistant", "", stop],
    ]);
  });
});

describe("confirmation requests", () => {
  const entry = {
    entry_id: "iur:A",
    quantity: "iur",
    subject: "A",
    accepted_units: ["1/(ug/m^3)"],
    minimum: 1e-9,
    maximum: 1000,
    purpose: "the cancer risk",
  };
  const asked = chatReducer(sent, {
    type: "event",
    event: { type: "confirmation_request", seq: 3, request_id: "req1", entries: [entry] },
  });

  it("opens the request in the thread when the turn stops to ask", () => {
    expect(asked.confirmation).toEqual({ request_id: "req1", entries: [entry] });
  });

  it("closes the request when the user sends their answers or a message", () => {
    const answered = chatReducer(asked, {
      type: "user_sent",
      id: "u2",
      assistantId: "a2",
      text: "Answers: ...",
    });
    expect(answered.confirmation).toBeNull();
  });

  it("shows the same request again when the server refuses the reply", () => {
    const prompt = { request_id: "req1", entries: [entry] };
    const sending = chatReducer(asked, {
      type: "user_sent",
      id: "u2",
      assistantId: "a2",
      text: "Answers: ...",
    });
    const refused = chatReducer(sending, { type: "rejected", prompt });
    expect(refused.confirmation).toEqual(prompt);
    expect(refused.busy).toBe(false);
    expect(refused.messages.map((m) => [m.role, m.text])).toEqual(
      sent.messages.map((m) => [m.role, m.text]),
    );
  });

  it("restores an open request from a held thread", () => {
    const prompt = { request_id: "req1", entries: [entry] };
    const snapshot = {
      thread_id: "t1",
      messages: [],
      workspace: {} as never,
      usage: { calls: 0 } as never,
      confirmation: prompt,
    } as never;
    expect(chatReducer(initialChatState, { type: "restore", snapshot, ids: [] }).confirmation).toEqual(
      prompt,
    );
  });
});
