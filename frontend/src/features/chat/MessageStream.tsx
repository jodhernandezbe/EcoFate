import { CirclePause, CircleStop } from "lucide-react";
import { useEffect, useRef } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessage, LiveStatus } from "../../hooks/chatState";
import type { TurnInterruption } from "../../types/workspace";
import { SuggestionChips } from "./SuggestionChips";
import { ToolExecutionPills } from "./ToolExecutionPill";
import { STOPPING, turnStatusText } from "./turnStatusText";
import { Welcome } from "./Welcome";

const CELL = "border-l border-hairline px-3 py-2 first:border-l-0 whitespace-nowrap";

// Tables are wrapped in their own horizontal scroll area so a wide one never widens the message.
// Colours come from the design tokens; numerals are tabular so columns of numbers line up.
const MARKDOWN: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 max-w-full overflow-x-auto rounded-xl border border-hairline shadow-xs">
      <table className="w-full border-collapse text-xs/relaxed tabular-nums">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-hairline">{children}</thead>,
  tr: ({ children }) => <tr className="border-t border-hairline first:border-t-0 even:bg-hairline/40">{children}</tr>,
  th: ({ children }) => (
    <th scope="col" className={`${CELL} text-left text-xs font-semibold`}>
      {children}
    </th>
  ),
  td: ({ children }) => <td className={CELL}>{children}</td>,
};

const RESUME_BLOCKED = "A turn is running; Resume is available when it ends.";

interface StopActions {
  /** A turn is running: Resume is shown disabled with the reason. */
  busy: boolean;
  onResume?: (() => void) | undefined;
  onOpenSettings?: (() => void) | undefined;
}

/** Why the turn stopped (the server's fixed text) and what the user can do about it. */
function StopNotice({ stop, busy, onResume, onOpenSettings }: StopActions & { stop: TurnInterruption }) {
  return (
    <div role="status" className="mt-2 rounded-xl border border-hairline px-3 py-2 text-sm">
      <p className="flex items-start gap-2">
        <CirclePause size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg2" />
        <span>{stop.message}</span>
      </p>
      {stop.resumable || stop.reason === "bad_key" ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
          {stop.resumable && onResume ? (
            <button
              type="button"
              disabled={busy}
              title={busy ? RESUME_BLOCKED : undefined}
              aria-description={busy ? RESUME_BLOCKED : undefined}
              onClick={onResume}
              className="spring rounded-full bg-accent px-3 py-1 text-sm font-medium text-accent-fg transition disabled:opacity-30"
            >
              Resume
            </button>
          ) : null}
          {stop.reason === "bad_key" && onOpenSettings ? (
            <button
              type="button"
              onClick={onOpenSettings}
              className="spring rounded-full border border-hairline px-3 py-1 text-sm text-accent transition hover:bg-hairline"
            >
              Open Settings
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

interface LiveActions {
  /** What the running turn is doing now. */
  status?: LiveStatus | null | undefined;
  /** A stop was asked for; the turn finishes its current step first. */
  stopping?: boolean | undefined;
  /** Stop the running turn after its current step. */
  onStop?: (() => void) | undefined;
}

/** Under the streaming answer: what the turn is doing now, and a Stop control. */
function LiveLine({ status = null, stopping = false, onStop }: LiveActions) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span role="status" aria-live="polite" className="text-xs text-fg2">
        {stopping ? STOPPING : turnStatusText(status)}…
      </span>
      {onStop ? (
        <button
          type="button"
          disabled={stopping}
          title={stopping ? STOPPING : undefined}
          aria-description={stopping ? STOPPING : undefined}
          onClick={onStop}
          className="spring inline-flex items-center gap-1 rounded-full border border-hairline px-3 py-1 text-sm text-fg transition hover:bg-hairline disabled:opacity-30"
        >
          <CircleStop className="size-4" aria-hidden="true" />
          Stop
        </button>
      ) : null}
    </div>
  );
}

function Assistant({
  message,
  live,
  ...actions
}: StopActions & { message: ChatMessage; live: LiveActions }) {
  const running = message.streaming && !message.error && !message.interrupted;
  return (
    <div className="min-w-0 max-w-[92%] text-[15px] leading-relaxed">
      <ToolExecutionPills steps={message.tools} />
      {message.text ? (
        <div className="[&_a]:text-accent [&_a]:underline [&_code]:rounded [&_code]:bg-hairline [&_code]:px-1 [&_ol]:ml-5 [&_ol]:list-decimal [&_p]:my-2 [&_ul]:ml-5 [&_ul]:list-disc">
          <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN}>
            {message.text}
          </Markdown>
        </div>
      ) : null}
      {running ? <LiveLine {...live} /> : null}
      {message.interrupted ? <StopNotice stop={message.interrupted} {...actions} /> : null}
      {message.error ? (
        <p role="alert" className="mt-2 rounded-xl border border-hairline px-3 py-2 text-sm text-bad">
          {message.error}
        </p>
      ) : null}
    </div>
  );
}

function User({ message }: { message: ChatMessage }) {
  return (
    <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl bg-accent px-4 py-2 text-[15px] text-accent-fg">
      {message.text}
    </div>
  );
}

interface MessageStreamProps {
  messages: ChatMessage[];
  suggestions?: string[];
  canSend?: boolean;
  onSend?: (text: string) => void;
  /** A turn is running (an interrupted turn's Resume waits for it). */
  busy?: boolean;
  /** Resume the interrupted turn in place. */
  onResume?: (() => void) | undefined;
  /** Open the Settings drawer (offered when the key was rejected). */
  onOpenSettings?: (() => void) | undefined;
  /** What the running turn is doing now (shown under the streaming answer). */
  status?: LiveStatus | null | undefined;
  /** A stop was asked for and the turn is finishing its current step. */
  stopping?: boolean | undefined;
  /** Stop the running turn after its current step. */
  onStop?: (() => void) | undefined;
}

export function MessageStream({
  messages,
  suggestions = [],
  canSend = false,
  onSend,
  busy = false,
  onResume,
  onOpenSettings,
  status = null,
  stopping = false,
  onStop,
}: MessageStreamProps) {
  const live: LiveActions = { status, stopping, onStop };
  const end = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, last?.text, status?.phase, status?.label]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4" aria-label="Conversation">
      {messages.length === 0 ? (
        <div className="mt-10">
          <Welcome />
          <SuggestionChips
            suggestions={suggestions}
            disabled={!canSend}
            onPick={(text) => onSend?.(text)}
          />
        </div>
      ) : (
        <ol className="flex flex-col gap-4">
          {messages.map((message) => (
            <li key={message.id} className="flex min-w-0">
              {message.role === "user" ? (
                <User message={message} />
              ) : (
                <Assistant
                  message={message}
                  live={live}
                  busy={busy}
                  onResume={onResume}
                  onOpenSettings={onOpenSettings}
                />
              )}
            </li>
          ))}
        </ol>
      )}
      <div ref={end} />
    </div>
  );
}
