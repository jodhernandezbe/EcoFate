import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import type {
  ChatRequest,
  ConfirmationAnswers,
  ConfirmationPrompt,
  StreamEvent,
  WorkspaceState,
} from "../types/workspace";

import { ApiError, resetThread, resumeChat, streamChat } from "../services/apiClient";
import { chatReducer, initialChatState } from "./chatState";

const newId = (): string => crypto.randomUUID();
const NOT_FOUND = 404;
const UNPROCESSABLE = 422;
const TOO_MANY_REQUESTS = 429;
const NOT_CLEARED = "The workspace could not be cleared.";

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Try again.";
}

/** What the conversation tells the rest of the page. */
export interface StreamListeners {
  /** The id of the run the page opens on (generated here when absent). */
  firstThreadId?: string;
  /** A workspace update streamed in the current run. */
  onWorkspace?: (state: WorkspaceState) => void;
  /** The workspace replaced as a whole: emptied when the workspace is cleared. */
  onReplace?: (state: WorkspaceState | null) => void;
}

/** A message the server refused because the daily quota is used up, and when it resets. */
export interface QuotaRefusal {
  text: string;
  resetsAt: string | null;
}

/** One conversation at a time: send a message, receive the streamed answer, clear it all. */
export function useAgentStream(listeners: StreamListeners = {}) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [threadId, setThreadId] = useState(() => listeners.firstThreadId ?? newId());
  const [notice, setNotice] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<QuotaRefusal | null>(null);
  const current = useRef(threadId);
  const busy = useRef(false);
  const heard = useRef(listeners);
  useEffect(() => {
    heard.current = listeners;
    busy.current = state.busy;
  });

  /** Feed a turn's events to the conversation and the workspace until the stream ends. */
  const follow = useCallback(async (stream: AsyncGenerator<StreamEvent>) => {
    for await (const event of stream) {
      dispatch({ type: "event", event });
      if (event.type === "workspace_update") heard.current.onWorkspace?.(event.state);
    }
    dispatch({ type: "closed" });
  }, []);

  /** Stream one turn: a message, or the user's answers to the open request. */
  const turn = useCallback(
    async (body: ChatRequest, shown: string, reopen: ConfirmationPrompt | null) => {
      const abort = new AbortController();
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
    setNotice(null);
    dispatch({ type: "resume_sent" });
    try {
      await follow(resumeChat(current.current, new AbortController().signal));
    } catch (error) {
      dispatch({ type: "failed", message: describe(error) });
    }
  }, [follow]);

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
    setThreadId(id);
    setNotice(null);
    dispatch({ type: "reset" });
    heard.current.onReplace?.(null);
    return true;
  }, []);

  return { ...state, threadId, notice, refusal, send, answer, resume, clearWorkspace };
}
