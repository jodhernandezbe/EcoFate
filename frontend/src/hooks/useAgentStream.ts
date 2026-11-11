import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import type {
  ChatRequest,
  ConfirmationAnswers,
  ConfirmationPrompt,
  StreamEvent,
  ThreadSnapshot,
  WorkspaceState,
} from "../types/workspace";

import {
  ApiError,
  cancelTurn,
  getCurrentThread,
  getThread,
  resetThread,
  resumeChat,
  streamChat,
  turnEvents,
} from "../services/apiClient";
import { chatReducer, initialChatState } from "./chatState";

const newId = (): string => crypto.randomUUID();
const NOT_FOUND = 404;
const CONFLICT = 409;
const GONE = 410;
const UNPROCESSABLE = 422;
const TOO_MANY_REQUESTS = 429;
const NOT_CLEARED = "The workspace could not be cleared.";
const CONNECTION_LOST =
  "The connection to the server was lost. The turn keeps running; reload the page to see it.";
// A dropped stream is read again from the last event received, a few times, waiting longer each time.
const RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 1000;

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Try again.";
}

const pause = (ms: number): Promise<void> => new Promise((done) => setTimeout(done, ms));

/** What the conversation tells the rest of the page. */
export interface StreamListeners {
  /** The id of the run the page opens on (generated here when absent). */
  firstThreadId?: string;
  /** A workspace update streamed in the current run. */
  onWorkspace?: (state: WorkspaceState) => void;
  /** The workspace replaced as a whole: emptied when the workspace is cleared, restored on load. */
  onReplace?: (state: WorkspaceState | null) => void;
}

/** A message the server refused because the daily quota is used up, and when it resets. */
export interface QuotaRefusal {
  text: string;
  resetsAt: string | null;
}

/** The turn being followed: its id (from `turn_started`) and the last event received. */
interface Position {
  turnId: string | null;
  seq: number | null;
}

/**
 * One conversation at a time: send a message, receive the streamed answer, stop it, clear it all.
 * On load it continues the user's current thread (from the server) and reattaches to a turn that
 * is still running; a dropped stream is read again from the last event received.
 */
export function useAgentStream(listeners: StreamListeners = {}) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [threadId, setThreadId] = useState(() => listeners.firstThreadId ?? newId());
  const [notice, setNotice] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<QuotaRefusal | null>(null);
  const [stopping, setStopping] = useState(false);
  const current = useRef(threadId);
  const busy = useRef(false);
  const started = useRef(false);
  const position = useRef<Position>({ turnId: null, seq: null });
  const heard = useRef(listeners);
  useEffect(() => {
    heard.current = listeners;
    busy.current = state.busy;
  });

  /** Feed events to the conversation and the workspace; whether the turn's end arrived. */
  const consume = useCallback(async (stream: AsyncGenerator<StreamEvent>): Promise<boolean> => {
    for await (const event of stream) {
      dispatch({ type: "event", event });
      position.current.seq = event.seq;
      if (event.type === "turn_started") position.current.turnId = event.turn_id;
      if (event.type === "workspace_update") heard.current.onWorkspace?.(event.state);
      if (event.type === "turn_finished") return true;
    }
    return false;
  }, []);

  /** Show a held thread as the server has it (messages, workspace, usage, stop). */
  const adopt = useCallback((snapshot: ThreadSnapshot) => {
    current.current = snapshot.thread_id;
    setThreadId(snapshot.thread_id);
    dispatch({ type: "restore", snapshot, ids: snapshot.messages.map(() => newId()) });
    heard.current.onReplace?.(snapshot.workspace);
  }, []);

  /** Read the turn again from the last event received; its events expired: show the thread. */
  const reconnect = useCallback(async (): Promise<void> => {
    const { turnId } = position.current;
    if (!turnId) throw new Error(CONNECTION_LOST);
    for (let attempt = 0; attempt < RECONNECT_ATTEMPTS; attempt++) {
      if (attempt > 0) await pause(RECONNECT_DELAY_MS * attempt);
      try {
        if (await consume(turnEvents(turnId, position.current.seq))) return;
      } catch (error) {
        if (error instanceof ApiError && error.status === GONE) {
          adopt(await getThread(current.current));
          return;
        }
        if (error instanceof ApiError) throw error;
      }
    }
    throw new Error(CONNECTION_LOST);
  }, [consume, adopt]);

  /** Follow one turn to its end; a stream that drops after the turn started is read again. */
  const follow = useCallback(
    async (stream: AsyncGenerator<StreamEvent>) => {
      let ended = false;
      try {
        ended = await consume(stream);
      } catch (error) {
        if (error instanceof ApiError || position.current.turnId === null) throw error;
      }
      if (!ended) await reconnect();
      dispatch({ type: "closed" });
      setStopping(false);
    },
    [consume, reconnect],
  );

  /** Follow a turn that was already running when the page loaded. */
  const reattach = useCallback(
    async (snapshot: ThreadSnapshot) => {
      const running = snapshot.running_turn;
      if (!running) return;
      position.current = { turnId: running.turn_id, seq: null };
      const { question, resumed } = running;
      dispatch({ type: "reattach", userId: newId(), assistantId: newId(), question, resumed });
      try {
        await follow(turnEvents(running.turn_id, null));
      } catch (error) {
        dispatch({ type: "failed", message: describe(error) });
      }
    },
    [follow],
  );

  // Continue the user's current thread, unless they already started a turn on a fresh one.
  useEffect(() => {
    let live = true;
    void (async () => {
      let snapshot: ThreadSnapshot;
      try {
        snapshot = await getCurrentThread();
      } catch {
        return; // none yet (404), or unreachable: the page starts on a fresh thread
      }
      if (!live || started.current) return;
      try {
        adopt(snapshot);
        await reattach(snapshot);
      } catch (error) {
        dispatch({ type: "failed", message: describe(error) });
      }
    })();
    return () => {
      live = false;
    };
  }, [adopt, reattach]);

  /** Stream one turn: a message, or the user's answers to the open request. */
  const turn = useCallback(
    async (body: ChatRequest, shown: string, reopen: ConfirmationPrompt | null) => {
      const abort = new AbortController();
      started.current = true;
      position.current = { turnId: null, seq: null };
      setNotice(null);
      setRefusal(null);
      dispatch({ type: "user_sent", id: newId(), assistantId: newId(), text: shown });
      try {
        await follow(streamChat(body, abort.signal));
      } catch (error) {
        if (error instanceof ApiError && error.status === TOO_MANY_REQUESTS && error.resetsAt) {
          dispatch({ type: "refused" });
          setRefusal({ text: shown, resetsAt: error.resetsAt });
          return;
        }
        // A value the server refuses leaves the request open: show it again to correct.
        if (reopen && error instanceof ApiError && error.status === UNPROCESSABLE) {
          dispatch({ type: "rejected", prompt: reopen });
          setNotice(describe(error));
          return;
        }
        dispatch({ type: "failed", message: describe(error) });
      }
    },
    [follow],
  );

  /**
   * Continue the interrupted turn where it stopped; its events continue the same assistant
   * message. A refused resume keeps the stop and says why.
   */
  const resume = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    started.current = true;
    position.current = { turnId: null, seq: null };
    setNotice(null);
    dispatch({ type: "resume_sent" });
    try {
      await follow(resumeChat(current.current, new AbortController().signal));
    } catch (error) {
      dispatch({ type: "failed", message: describe(error) });
    }
  }, [follow]);

  /**
   * Ask the running turn to stop after its current step; its stream then ends with the
   * interruption and a Resume button. A turn that already ended needs nothing.
   */
  const stop = useCallback(async () => {
    const { turnId } = position.current;
    if (!turnId || !busy.current) return;
    setStopping(true);
    try {
      await cancelTurn(turnId);
    } catch (error) {
      setStopping(false);
      if (!(error instanceof ApiError && error.status === CONFLICT)) setNotice(describe(error));
    }
  }, []);

  const send = useCallback(
    (text: string) => turn({ thread_id: current.current, message: text }, text, null),
    [turn],
  );

  /** Send the user's answers to the open request; a rejected reply leaves the request open. */
  const answer = useCallback(
    (answers: ConfirmationAnswers, shown: string, prompt: ConfirmationPrompt) =>
      turn({ thread_id: current.current, answers }, shown, prompt),
    [turn],
  );

  /**
   * Discard the conversation on the server, then empty the chat and workspace and continue on a
   * fresh thread. A thread the server no longer holds is already discarded. Any other failure
   * keeps everything as it was and says so. Resolves whether the workspace was cleared.
   */
  const clearWorkspace = useCallback(async (): Promise<boolean> => {
    if (busy.current) return false;
    try {
      await resetThread(current.current);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === NOT_FOUND)) {
        setNotice(`${NOT_CLEARED} ${describe(error)}`);
        return false;
      }
    }
    const id = newId();
    current.current = id;
    started.current = true;
    setThreadId(id);
    setNotice(null);
    dispatch({ type: "reset" });
    heard.current.onReplace?.(null);
    return true;
  }, []);

  return {
    ...state,
    threadId,
    notice,
    refusal,
    stopping,
    send,
    answer,
    resume,
    stop,
    clearWorkspace,
  };
}
