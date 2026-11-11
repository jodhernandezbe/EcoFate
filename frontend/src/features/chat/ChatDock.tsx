import { TopHeaderBar, type AssistantStatus } from "../../components/layout/TopHeaderBar";
import type { ChatMessage, LiveStatus, UsageView } from "../../hooks/chatState";
import type { ConfirmationAnswers, ConfirmationPrompt, QuotaStatus } from "../../types/workspace";
import { ChatComposer } from "./ChatComposer";
import { ClearChatButton } from "./ClearChatButton";
import { clearBlockedReason } from "./clearBlockedReason";
import { ConfirmationCard } from "./ConfirmationCard";
import { MessageStream } from "./MessageStream";
import { QuotaMeter } from "./QuotaMeter";
import { limitReachedReason } from "./quotaText";
import { UsageMeter } from "./UsageMeter";

interface ChatDockProps {
  messages: ChatMessage[];
  busy: boolean;
  hasKey: boolean;
  model?: string | undefined;
  suggestions?: string[] | undefined;
  usage: UsageView | null;
  /** The user's daily turn quota (null until loaded; `applies` false shows nothing). */
  quota?: QuotaStatus | null | undefined;
  /** A message the server refused over the quota, put back in the input. */
  refusedText?: string | null | undefined;
  /** A message about switching runs (for example, that one is no longer available). */
  notice?: string | null | undefined;
  /** The open request for missing values, if the turn stopped for one. */
  confirmation?: ConfirmationPrompt | null | undefined;
  onSend: (text: string) => void;
  onClear: () => void;
  onAnswer?: ((answers: ConfirmationAnswers, summary: string) => void) | undefined;
  /** Resume the interrupted turn where it stopped. */
  onResume?: (() => void) | undefined;
  /** What the running turn is doing now (null when none runs). */
  status?: LiveStatus | null | undefined;
  /** A stop was asked for and the turn is finishing its current step. */
  stopping?: boolean | undefined;
  /** Stop the running turn after its current step. */
  onStop?: (() => void) | undefined;
  onOpenSettings: () => void;
  onCollapse: () => void;
}

function statusOf(messages: ChatMessage[], busy: boolean, live: LiveStatus | null): AssistantStatus {
  if (busy) return live?.phase === "queued" ? "queued" : "thinking";
  const last = messages[messages.length - 1];
  if (last?.error) return "error";
  return last?.interrupted ? "stopped" : "idle";
}

/** The chat dock: header, conversation and composer. */
export function ChatDock({
  messages,
  busy,
  hasKey,
  model,
  suggestions,
  usage,
  quota,
  refusedText,
  notice,
  confirmation,
  onSend,
  onClear,
  onAnswer,
  onResume,
  status = null,
  stopping = false,
  onStop,
  onOpenSettings,
  onCollapse,
}: ChatDockProps) {
  return (
    <div className="flex h-full flex-col">
      <TopHeaderBar
        title="Assistant"
        subtitle={model}
        status={statusOf(messages, busy, status)}
        onCollapse={onCollapse}
      >
        <QuotaMeter quota={quota ?? null} />
        <UsageMeter usage={usage} />
        <ClearChatButton blocked={clearBlockedReason(busy, messages.length)} onClear={onClear} />
      </TopHeaderBar>
      <MessageStream
        messages={messages}
        suggestions={suggestions ?? []}
        canSend={hasKey && !busy && limitReachedReason(quota ?? null) === null}
        onSend={onSend}
        busy={busy}
        onResume={onResume}
        status={status}
        stopping={stopping}
        onStop={onStop}
        onOpenSettings={onOpenSettings}
      />
      {confirmation && onAnswer ? (
        <ConfirmationCard prompt={confirmation} busy={busy} onConfirm={onAnswer} />
      ) : null}
      {notice ? (
        <p role="status" className="px-5 pb-1 text-center text-xs text-fg2">
          {notice}
        </p>
      ) : null}
      <ChatComposer
        busy={busy}
        hasKey={hasKey}
        onSend={onSend}
        onOpenSettings={onOpenSettings}
        limitReason={limitReachedReason(quota ?? null)}
        restore={refusedText}
      />
    </div>
  );
}
