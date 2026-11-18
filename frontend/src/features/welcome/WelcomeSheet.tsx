import { ChartColumn, KeyRound, MessageSquareText, type LucideIcon } from "lucide-react";
import { useId, useRef, type ReactNode } from "react";

import { BrandMark } from "../../components/ui/BrandLogo";
import { useFocusTrap } from "../../components/ui/useFocusTrap";

const NO_KEY_REASON = "Add your OpenAI key first.";
const BUSY_REASON = "A reply is in progress.";

interface WelcomeSheetProps {
  open: boolean;
  /** The user's OpenAI key is stored (never any part of it). */
  hasKey: boolean;
  /** The configured example prompts; the first is offered as a one-tap example. */
  suggestions: string[] | undefined;
  /** A reply is running: the example cannot be sent. */
  busy: boolean;
  /** The example was chosen; the caller closes the sheet and sends it. */
  onPick: (prompt: string) => void;
  /** Open Settings; the caller closes the sheet first. */
  onOpenSettings: () => void;
  onClose: () => void;
}

function Feature({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-4">
      <Icon aria-hidden="true" className="mt-0.5 size-7 shrink-0 text-accent" strokeWidth={1.75} />
      <div className="flex min-w-0 flex-col gap-1">
        <h3 className="text-[15px] font-semibold">{title}</h3>
        <div className="text-sm text-fg2">{children}</div>
      </div>
    </li>
  );
}

function KeyFeature({ hasKey }: { hasKey: boolean }) {
  return (
    <Feature icon={KeyRound} title="Bring your OpenAI key">
      <p>
        The assistant runs on your own key, billed to your OpenAI account and stored encrypted.{" "}
        <span role="status" className={hasKey ? "font-medium text-ok" : "font-medium text-fg"}>
          {hasKey ? "Key stored." : "No key yet."}
        </span>
      </p>
    </Feature>
  );
}

function AskFeature({ hasKey, suggestions, busy, onPick }: Pick<WelcomeSheetProps, "hasKey" | "suggestions" | "busy" | "onPick">) {
  const example = suggestions?.[0];
  const reason = !hasKey ? NO_KEY_REASON : busy ? BUSY_REASON : null;
  return (
    <Feature icon={MessageSquareText} title="Ask in plain words">
      <p>Name a chemical or a question; the assistant finds the facilities and runs the screening.</p>
      {example ? (
        <button
          type="button"
          disabled={reason !== null}
          title={reason ?? undefined}
          aria-description={reason ?? undefined}
          onClick={() => onPick(example)}
          className="spring mt-1 text-left text-sm text-accent transition hover:opacity-80 disabled:text-fg2 disabled:opacity-60"
        >
          Try “{example}” →
        </button>
      ) : null}
    </Feature>
  );
}

function ResultsFeature() {
  return (
    <Feature icon={ChartColumn} title="See the risk at a glance">
      <p>The overview, the map and a downloadable report. Results are screening level, not a regulatory determination.</p>
    </Feature>
  );
}

/**
 * The first-visit welcome, in the manner of a "What's New" sheet: the mark, a large title, three
 * features with an accent icon each, and one primary action. A centered card over a blurred
 * scrim; focus is trapped, Escape or the scrim closes, and it never holds a key input.
 */
export function WelcomeSheet({ open, onClose, onPick, onOpenSettings, hasKey, suggestions, busy }: WelcomeSheetProps) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const primary = useRef<HTMLElement>(null);
  useFocusTrap(open, panel, onClose, [primary]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/30 p-4 backdrop-blur-sm"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="sheet-in flex w-full max-w-md flex-col items-center gap-8 rounded-2xl border border-hairline bg-solid px-8 pb-6 pt-10 shadow-[var(--shadow)]"
      >
        <header className="flex flex-col items-center gap-3 text-center">
          <BrandMark size={56} />
          <h2 id={titleId} className="text-3xl font-semibold tracking-tight">
            Welcome to EcoFate
          </h2>
          <p className="text-sm text-fg2">Screening-level chemical exposure and risk, from public inventories.</p>
        </header>
        <ul className="flex w-full flex-col gap-6">
          <KeyFeature hasKey={hasKey} />
          <AskFeature hasKey={hasKey} suggestions={suggestions} busy={busy} onPick={onPick} />
          <ResultsFeature />
        </ul>
        <footer ref={primary} className="flex w-full flex-col items-center gap-3">
          <button
            type="button"
            onClick={onClose}
            className="spring w-full rounded-xl bg-accent py-2.5 text-[15px] font-semibold text-accent-fg transition hover:opacity-90"
          >
            Continue
          </button>
          {hasKey ? null : (
            <button type="button" onClick={onOpenSettings} className="spring text-sm text-accent transition hover:opacity-80">
              Add your key in Settings
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}
