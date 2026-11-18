import { X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AccordionSection } from "../../components/ui/Accordion";
import { Banner } from "../../components/ui/Banner";
import { BottomDrawer } from "../../components/ui/BottomDrawer";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import type { KeyOutcome } from "../../hooks/useKeyStatus";
import type { KeysStatusResponse } from "../../types/workspace";

const OPENAI_PURPOSE = "Runs the assistant. It is billed to your own OpenAI account. Required.";
const BUTTON = "spring rounded-full px-4 py-1.5 text-sm transition disabled:opacity-30";
const STATUS = "rounded-xl border border-hairline px-3 py-2 text-sm";

interface KeyFormProps {
  configured: boolean;
  busy: boolean;
  outcome: KeyOutcome | undefined;
  onSave: (key: string) => Promise<boolean>;
  onClear: () => Promise<boolean>;
}

function KeyForm({ configured, busy, outcome, onSave, onClear }: KeyFormProps) {
  const [draft, setDraft] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = draft;
    setDraft("");
    if (value.trim()) void onSave(value);
  };
  return (
    <section aria-label="OpenAI API key">
      <form onSubmit={submit} className="flex w-full flex-col gap-3">
        <div className="flex items-center gap-1">
          <h4 className="text-sm font-semibold">OpenAI API key</h4>
          <InfoTooltip label="About the OpenAI key" text={OPENAI_PURPOSE} />
        </div>
        <p role="status" className={`${STATUS} ${configured ? "text-ok" : "text-fg2"}`}>
          {configured ? "Key stored encrypted for your account" : "No key configured"}
        </p>
        {outcome ? <Banner kind={outcome.kind}>{outcome.message}</Banner> : null}
        {/* One row (input, then its actions) once the drawer is wide enough; stacked below that. */}
        <div className="flex flex-col gap-3 @xl:flex-row @xl:items-center">
          <div className="relative min-w-0 flex-1">
            <input
              type="password"
              name="openai-api-key"
              aria-label="OpenAI API key"
              autoComplete="off"
              spellCheck={false}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Paste key"
              className="w-full rounded-xl border border-hairline bg-transparent py-2 pl-3 pr-9 text-[15px] outline-none focus:border-accent"
            />
            {draft ? (
              <button
                type="button"
                aria-label="Clear OpenAI key input"
                onClick={() => setDraft("")}
                className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-fg2 hover:text-fg"
              >
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center justify-between gap-3 @xl:justify-end">
            <button
              type="button"
              aria-label="Clear OpenAI key"
              disabled={busy || !configured}
              onClick={() => void onClear()}
              className={`${BUTTON} px-3 text-bad`}
            >
              Clear key
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                aria-label="Reset OpenAI key input"
                disabled={busy || draft.length === 0}
                onClick={() => setDraft("")}
                className={`${BUTTON} text-fg2`}
              >
                Reset
              </button>
              <button
                type="submit"
                aria-label="Save OpenAI key"
                disabled={busy || draft.trim().length === 0}
                className={`${BUTTON} bg-accent font-medium text-accent-fg`}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      </form>
    </section>
  );
}

/** The state of the Assistant section in words, so a collapsed section still says what it holds. */
export function keySummary(configured: boolean): string {
  return configured ? "Key saved" : "Key missing";
}

interface ContentProps {
  statuses: KeysStatusResponse | null;
  busy: boolean;
  outcome: KeyOutcome | undefined;
  loadError: string | null;
  onSave: (key: string) => Promise<boolean>;
  onClear: () => Promise<boolean>;
}

function DrawerContent({ statuses, busy, outcome, loadError, onSave, onClear }: ContentProps) {
  const configured = statuses?.openai.configured === true;
  // The Assistant section opens by itself while the required key is missing.
  const [expanded, setExpanded] = useState<string[]>(configured ? [] : ["assistant"]);
  const toggle = (id: string) =>
    setExpanded((now) => (now.includes(id) ? now.filter((item) => item !== id) : [...now, id]));

  return (
    <div className="@container w-full">
      {loadError ? <Banner kind="error">{loadError}</Banner> : null}
      <AccordionSection
        title="Assistant"
        summary={statuses ? keySummary(configured) : null}
        open={expanded.includes("assistant")}
        onToggle={() => toggle("assistant")}
      >
        <KeyForm configured={configured} busy={busy} outcome={outcome} onSave={onSave} onClear={onClear} />
      </AccordionSection>
    </div>
  );
}

interface SettingsDrawerProps extends ContentProps {
  open: boolean;
  onClose: () => void;
}

/**
 * The user's own OpenAI key (stored encrypted for their account) in a bottom drawer. The operator's
 * data services are not listed: users never configure them. No key is kept in the browser.
 */
export function SettingsDrawer({ open, onClose, ...content }: SettingsDrawerProps) {
  return (
    <BottomDrawer open={open} title="Settings" onClose={onClose} fitContent>
      <DrawerContent {...content} />
    </BottomDrawer>
  );
}
