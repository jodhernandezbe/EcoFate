import { AiOutlineClear } from "react-icons/ai";

interface ClearChatButtonProps {
  /** Why there is nothing to clear right now; the button is enabled when absent. */
  blocked: string | null;
  onClear: () => void;
}

/** Starts a fresh conversation; the previous run stays in the rail's history. */
export function ClearChatButton({ blocked, onClear }: ClearChatButtonProps) {
  return (
    <button
      type="button"
      aria-label="Clear chat"
      aria-description={blocked ?? undefined}
      title={blocked ? `Clear chat: ${blocked}` : "Clear chat"}
      disabled={blocked !== null}
      onClick={onClear}
      className="spring grid size-9 place-items-center rounded-full text-fg2 transition hover:bg-hairline hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-fg2"
    >
      <AiOutlineClear size={18} aria-hidden="true" />
    </button>
  );
}
