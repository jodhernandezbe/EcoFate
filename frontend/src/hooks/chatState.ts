import type {
  ConfirmationPrompt,
  StreamEvent,
  ThreadSnapshot,
  TurnInterruption,
  TurnStatus,
  UsageTotals,
} from "../types/workspace";

export interface ToolStep {
  callId: string;
  label: string;
  state: "running" | "done" | "error";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  error: string | null;
  streaming: boolean;
  tools: ToolStep[];
  /** Why the turn stopped before its answer, when it was interrupted (it may be resumable). */
  interrupted: TurnInterruption | null;
}

/** What the usage meter shows: the session, and the last turn when one was streamed here. */
export interface UsageView {
  turn: UsageTotals | null;
  session: UsageTotals;
}

/** What the running turn is doing now, for the status line under the streaming message. */
export interface LiveStatus {
  phase: TurnStatus["phase"];
  /** The step's label, while a step runs. */
  label: string | null;
  /** About how many turns wait before this one, while it is queued. */
  position: number | null;
}

export interface ChatState {
  messages: ChatMessage[];
  busy: boolean;
  /** The latest status of the running turn (null when none runs or none was reported yet). */
  status: LiveStatus | null;
  usage: UsageView | null;
  /** The open request for missing values the user must answer, if the turn stopped for one. */
  confirmation: ConfirmationPrompt | null;
}

export type ChatAction =
  | { type: "user_sent"; id: string; assistantId: string; text: string }
  | { type: "resume_sent" }
  | { type: "event"; event: StreamEvent }
  | { type: "failed"; message: string }
  | { type: "closed" }
  | { type: "rejected"; prompt: ConfirmationPrompt | null }
  | { type: "refused" }
  | { type: "restore"; snapshot: ThreadSnapshot; ids: string[] }
  | { type: "reattach"; userId: string; assistantId: string; question: string | null; resumed: boolean }
  | { type: "reset" };

export const initialChatState: ChatState = {
  messages: [],
  busy: false,
  status: null,
  usage: null,
  confirmation: null,
};

function updateLastAssistant(
  state: ChatState,
  change: (message: ChatMessage) => ChatMessage,
): ChatState {
  const index = state.messages.findLastIndex((message) => message.role === "assistant");
  const target = state.messages[index];
  if (!target) return state;
  const messages = [...state.messages];
  messages[index] = change(target);
  return { ...state, messages };
}

type ToolEvent = Extract<StreamEvent, { type: "tool_status" }>;

function withToolStatus(message: ChatMessage, event: ToolEvent): ChatMessage {
  if (event.phase === "started") {
    if (message.tools.some((step) => step.callId === event.call_id)) return message;
    const text = message.text && !message.text.endsWith("\n\n") ? message.text + "\n\n" : message.text;
    const step: ToolStep = { callId: event.call_id, label: event.label, state: "running" };
    return { ...message, text, tools: [...message.tools, step] };
  }
  const state: ToolStep["state"] = event.status === "error" ? "error" : "done";
  const known = message.tools.some((step) => step.callId === event.call_id);
  const tools = known
    ? message.tools.map((step) => (step.callId === event.call_id ? { ...step, state } : step))
    : [...message.tools, { callId: event.call_id, label: event.label, state }];
  return { ...message, tools };
}

function onEvent(state: ChatState, event: StreamEvent): ChatState {
  switch (event.type) {
    case "turn_status":
      return {
        ...state,
        status: { phase: event.phase, label: event.label ?? null, position: event.position ?? null },
      };
    case "token":
      return updateLastAssistant(state, (m) => ({ ...m, text: m.text + event.text }));
    case "assistant_message":
      // Streamed tokens already carry the text; this fills in for a model that did not stream.
      return updateLastAssistant(state, (m) => (m.text ? m : { ...m, text: event.text }));
    case "guardrail_pivot":
      // An off-topic turn is answered like any other: the redirect is the assistant's message.
      return updateLastAssistant(state, (m) => (m.text ? m : { ...m, text: event.text }));
    case "tool_status":
      return updateLastAssistant(state, (m) => withToolStatus(m, event));
    case "confirmation_request":
      return {
        ...state,
        confirmation: { request_id: event.request_id, entries: event.entries },
      };
    case "usage":
      return { ...state, usage: { turn: event.turn, session: event.session } };
    case "turn_started":
      // A resumed turn continues the interrupted assistant message: its stop is over.
      return event.resumed ? updateLastAssistant(state, (m) => ({ ...m, interrupted: null })) : state;
    case "turn_interrupted": {
      const interrupted = { reason: event.reason, resumable: event.resumable, message: event.message };
      return {
        ...updateLastAssistant(state, (m) => ({ ...m, interrupted, streaming: false })),
        status: null,
      };
    }
    case "error":
      return updateLastAssistant(state, (m) => ({ ...m, error: event.message }));
    case "turn_finished":
      return {
        ...updateLastAssistant(state, (m) => ({ ...m, streaming: false })),
        busy: false,
        status: null,
      };
    default:
      return state;
  }
}

const assistant = (id: string, text: string, streaming: boolean): ChatMessage => ({
  id,
  role: "assistant",
  text,
  error: null,
  streaming,
  tools: [],
  interrupted: null,
});

/** Attach a held thread's interruption to its last assistant message (one is added when the
 * turn stopped before writing any text). */
function withInterruption(messages: ChatMessage[], interrupted: TurnInterruption | null): ChatMessage[] {
  if (!interrupted) return messages;
  const last = messages[messages.length - 1];
  if (last?.role === "assistant") return [...messages.slice(0, -1), { ...last, interrupted }];
  return [...messages, { ...assistant(`restored-${messages.length}`, "", false), interrupted }];
}

/** A held thread's text messages, session usage and interruption; its tool steps are not stored. */
function restored(snapshot: ThreadSnapshot, ids: string[]): ChatState {
  const messages = snapshot.messages.map((message, index): ChatMessage => ({
    ...assistant(ids[index] ?? `restored-${index}`, message.text, false),
    role: message.role,
  }));
  const usage = snapshot.usage.calls > 0 ? { turn: null, session: snapshot.usage } : null;
  return {
    messages: withInterruption(messages, snapshot.interrupted ?? null),
    busy: false,
    status: null,
    usage,
    confirmation: snapshot.confirmation ?? null,
  };
}

/**
 * Show a turn that is still running after a reload: its question and the answer its events will
 * fill in. A resumed turn continues the last answer instead (its question is already shown).
 */
function reattached(state: ChatState, action: Extract<ChatAction, { type: "reattach" }>): ChatState {
  const lastIsAnswer = state.messages[state.messages.length - 1]?.role === "assistant";
  if (action.resumed && lastIsAnswer) {
    return { ...updateLastAssistant(state, (m) => ({ ...m, streaming: true })), busy: true };
  }
  const question = action.question
    ? [{ ...assistant(action.userId, action.question, false), role: "user" as const }]
    : [];
  return {
    ...state,
    busy: true,
    messages: [...state.messages, ...question, assistant(action.assistantId, "", true)],
  };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "user_sent":
      // A new message abandons an interrupted turn: its Resume control goes away.
      return {
        ...state,
        busy: true,
        status: null,
        confirmation: null,
        messages: [
          ...state.messages.map((m) => (m.interrupted ? { ...m, interrupted: null } : m)),
          { ...assistant(action.id, action.text, false), role: "user" },
          assistant(action.assistantId, "", true),
        ],
      };
    case "resume_sent":
      // The resumed events continue the interrupted message; its stop clears once they start.
      return {
        ...updateLastAssistant(state, (m) => ({ ...m, error: null, streaming: true })),
        busy: true,
        status: null,
      };
    case "event":
      return onEvent(state, action.event);
    case "failed":
      return {
        ...updateLastAssistant(state, (m) => ({ ...m, error: action.message, streaming: false })),
        busy: false,
        status: null,
      };
    case "closed":
      return {
        ...updateLastAssistant(state, (m) => ({ ...m, streaming: false })),
        busy: false,
        status: null,
      };
    case "rejected":
      // The server refused the reply and recorded nothing: take back the optimistic turn and
      // show the same request again so the user can correct the answer.
      return {
        ...state,
        messages: state.messages.slice(0, -2),
        busy: false,
        status: null,
        confirmation: action.prompt,
      };
    case "refused":
      // Over the daily quota: nothing ran or was recorded, so take back the optimistic turn.
      return { ...state, messages: state.messages.slice(0, -2), busy: false, status: null };
    case "restore":
      return restored(action.snapshot, action.ids);
    case "reattach":
      return reattached(state, action);
    case "reset":
      return initialChatState;
  }
}
