import type { ReactNode } from "react";

import { BottomDrawer } from "../../components/ui/BottomDrawer";
import { SuggestionChips } from "../chat/SuggestionChips";

const NO_KEY_REASON = "Add your OpenAI key first (step 1).";
const BUSY_REASON = "A reply is in progress.";

interface WelcomeSheetProps {
  open: boolean;
  /** The user's OpenAI key is stored (never any part of it). */
  hasKey: boolean;
  /** The configured example prompts. */
  suggestions: string[] | undefined;
  /** A reply is running: examples cannot be sent. */
  busy: boolean;
  /** An example was chosen; the caller closes the sheet and sends it. */
  onPick: (prompt: string) => void;
  /** Open Settings; the caller closes the sheet first. */
  onOpenSettings: () => void;
  onClose: () => void;
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="grid size-6 shrink-0 place-items-center rounded-full bg-hairline text-xs font-semibold text-fg2"
      >
        {number}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {children}
      </div>
    </li>
  );
}

function KeyStep({ hasKey, onOpenSettings }: Pick<WelcomeSheetProps, "hasKey" | "onOpenSettings">) {
  return (
    <Step number={1} title="Add your OpenAI key">
      <p className="text-sm text-fg2">
        The assistant runs on your own OpenAI key. It is billed to your OpenAI account and stored encrypted.
      </p>
      <div className="flex items-center gap-3">
        <p role="status" className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${hasKey ? "bg-ok/15 text-ok" : "bg-hairline text-fg2"}`}>
          {hasKey ? "Key stored" : "No key yet"}
        </p>
        <button
          type="button"
          onClick={onOpenSettings}
          className="spring rounded-full border border-hairline px-3 py-1 text-sm transition hover:bg-hairline"
        >
          Open Settings
        </button>
      </div>
    </Step>
  );
}

function ExamplesStep({ hasKey, suggestions, busy, onPick }: Pick<WelcomeSheetProps, "hasKey" | "suggestions" | "busy" | "onPick">) {
  const reason = !hasKey ? NO_KEY_REASON : busy ? BUSY_REASON : null;
  const examples = suggestions ?? [];
  return (
    <Step number={2} title="Ask a question">
      {examples.length === 0 ? (
        <p className="text-sm text-fg2">Type a question in the chat.</p>
      ) : (
        <>
          <p className="text-sm text-fg2">Pick an example to send it, or type your own in the chat.</p>
          <div title={reason ?? undefined} aria-description={reason ?? undefined} className="[&_ul]:mt-0">
            <SuggestionChips suggestions={examples} disabled={reason !== null} onPick={onPick} />
          </div>
          {reason ? <p className="text-xs text-fg2">{reason}</p> : null}
        </>
      )}
    </Step>
  );
}

const RESULTS: ReadonlyArray<readonly [string, string]> = [
  ["Overview", "summarises the screening results and their bands."],
  ["Map", "shows the facilities and the people around them."],
  ["Chat", "explains each step and asks when a value is missing."],
  ["Report", "in the navigation rail, downloads the assessment."],
];

function ResultsStep() {
  return (
    <Step number={3} title="Read the results">
      <ul className="flex flex-col gap-1 text-sm text-fg2">
        {RESULTS.map(([name, line]) => (
          <li key={name}>
            <span className="font-medium text-fg">{name}</span> {line}
          </li>
        ))}
      </ul>
      <p className="text-xs text-fg2">Results are screening level, not a regulatory determination.</p>
    </Step>
  );
}

/**
 * The first-visit welcome: what EcoFate does and the three things to do first. It composes the
 * bottom drawer at its content height and never holds a key input.
 */
export function WelcomeSheet({ open, onClose, onPick, onOpenSettings, hasKey, suggestions, busy }: WelcomeSheetProps) {
  return (
    <BottomDrawer open={open} title="Welcome to EcoFate" onClose={onClose} fitContent>
      <div className="mx-auto flex w-full max-w-md flex-col gap-5">
        <p className="text-sm text-fg2">
          EcoFate produces screening-level chemical exposure and risk assessments from public inventories.
        </p>
        <ol className="flex flex-col gap-5">
          <KeyStep hasKey={hasKey} onOpenSettings={onOpenSettings} />
          <ExamplesStep hasKey={hasKey} suggestions={suggestions} busy={busy} onPick={onPick} />
          <ResultsStep />
        </ol>
        <button
          type="button"
          onClick={onClose}
          className="spring self-end rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg"
        >
          Get started
        </button>
      </div>
    </BottomDrawer>
  );
}
