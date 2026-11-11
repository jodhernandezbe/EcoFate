import { ArrowUp } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

interface ChatComposerProps {
  busy: boolean;
  hasKey: boolean;
  onSend: (text: string) => void;
  onOpenSettings: () => void;
  /** Why the daily limit disables the input (with the local reset time); null when it does not. */
  limitReason?: string | null | undefined;
  /** A message the server refused over the quota: put back so the user keeps what they typed. */
  restore?: string | null | undefined;
}

/** The floating input bar; points to Settings while no API key is stored. */
export function ChatComposer({
  busy,
  hasKey,
  onSend,
  onOpenSettings,
  limitReason = null,
  restore = null,
}: ChatComposerProps) {
  const [text, setText] = useState("");
  const open = hasKey && limitReason === null;
  const canSend = open && !busy && text.trim().length > 0;
  const [restored, setRestored] = useState(restore);
  if (restore !== restored) {
    setRestored(restore);
    if (restore) setText(restore);
  }

  const submit = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2">
      {!hasKey ? (
        <p className="mb-2 text-center text-xs text-fg2">
          Add your OpenAI API key to start.{" "}
          <button type="button" className="text-accent underline" onClick={onOpenSettings}>
            Open Settings
          </button>
        </p>
      ) : null}
      {limitReason ? (
        <p role="status" className="mb-2 text-center text-xs text-fg2">
          {limitReason}
        </p>
      ) : null}
      <div className="glass flex items-end gap-2 rounded-2xl p-2 pl-4 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent">
        <textarea
          aria-label="Message"
          rows={1}
          value={text}
          disabled={!open}
          aria-description={limitReason ?? undefined}
          title={limitReason ?? undefined}
          placeholder="Message the assessor"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-2 text-[15px] outline-none placeholder:text-fg2"
          data-ring-on-parent
        />
        <button
          type="button"
          aria-label="Send"
          disabled={!canSend}
          aria-description={limitReason ?? undefined}
          title={limitReason ?? undefined}
          onClick={submit}
          className="spring grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-fg transition disabled:opacity-30"
        >
          <ArrowUp size={18} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
