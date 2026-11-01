import { X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AccordionSection } from "../../components/ui/Accordion";
import { Banner } from "../../components/ui/Banner";
import { BottomDrawer } from "../../components/ui/BottomDrawer";
import { InfoTooltip } from "../../components/ui/InfoTooltip";
import type { KeyOutcomes } from "../../hooks/useKeyStatus";
import type { KeyName, KeysStatusResponse } from "../../types/workspace";

interface KeyField {
  name: KeyName;
  label: string;
  purpose: string;
  /** What is unavailable while this optional key is missing; absent for the required key. */
  missing?: string;
}

interface Group {
  id: string;
  title: string;
  keys: KeyField[];
}

const GROUPS: Group[] = [
  {
    id: "assistant",
    title: "Assistant",
    keys: [
      {
        name: "openai",
        label: "OpenAI",
        purpose: "Runs the assistant. Required.",
      },
    ],
  },
  {
    id: "data",
    title: "Data services",
    keys: [
      {
        name: "census",
        label: "Census",
        purpose: "Counts the people living around a facility.",
        missing: "Without it, population counts fall back to a generic screening default.",
      },
      {
        name: "comptox",
        label: "CompTox",
        purpose: "Looks up chemical properties and toxicity benchmarks.",
        missing: "Without it, chemical properties and toxicity values cannot be looked up.",
      },
    ],
  },
];

const EMPTY: Record<KeyName, string> = { openai: "", census: "", comptox: "" };
const BUTTON = "spring rounded-full px-4 py-1.5 text-sm transition disabled:opacity-30";

interface FieldProps {
  field: KeyField;
  configured: boolean;
  draft: string;
  busy: boolean;
  outcome: KeyOutcomes[KeyName];
  onDraft: (value: string) => void;
  onSave: () => void;
  onClear: () => void;
}

function KeyForm({ field, configured, draft, busy, outcome, onDraft, onSave, onClear }: FieldProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSave();
  };
  return (
    <section aria-label={`${field.label} API key`} className="border-t border-hairline pt-4 first:border-t-0 first:pt-0">
      <form onSubmit={submit} className="flex w-full flex-col gap-3">
        <div className="flex items-center gap-1">
          <h4 className="text-[15px] font-medium">{field.label} API key</h4>
          <InfoTooltip label={`About the ${field.label} key`} text={field.purpose} />
        </div>
        <p
          role="status"
          className={`rounded-xl border border-hairline px-3 py-2 text-sm ${configured ? "text-ok" : "text-fg2"}`}
        >
          {configured ? "Key stored securely in OS Keychain" : "No key configured"}
        </p>
        {!configured && field.missing ? <p className="text-xs text-fg2">{field.missing}</p> : null}
        {outcome ? <Banner kind={outcome.kind}>{outcome.message}</Banner> : null}
        {/* One row (input, then its actions) once the drawer is wide enough; stacked below that. */}
        <div className="flex flex-col gap-3 @xl:flex-row @xl:items-center">
          <div className="relative min-w-0 flex-1">
            <input
              type="password"
              name={`${field.name}-api-key`}
              aria-label={`${field.label} API key`}
              autoComplete="off"
              spellCheck={false}
              value={draft}
              onChange={(event) => onDraft(event.target.value)}
              placeholder="Paste key"
              className="w-full rounded-xl border border-hairline bg-transparent py-2 pl-3 pr-9 text-[15px] outline-none focus:border-accent"
            />
            {draft ? (
              <button
                type="button"
                aria-label={`Clear ${field.label} key input`}
                onClick={() => onDraft("")}
                className="absolute right-2 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-fg2 hover:text-fg"
              >
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center justify-between gap-3 @xl:justify-end">
            <button
              type="button"
              aria-label={`Clear ${field.label} key`}
              disabled={busy || !configured}
              onClick={onClear}
              className={`${BUTTON} px-3 text-bad`}
            >
              Clear key
            </button>
            <div className="flex gap-2">
              <button
                type="button"
                aria-label={`Reset ${field.label} key input`}
                disabled={busy || draft.length === 0}
                onClick={() => onDraft("")}
                className={`${BUTTON} text-fg2`}
              >
                Reset
              </button>
              <button
                type="submit"
                aria-label={`Save ${field.label} key`}
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

interface ContentProps {
  statuses: KeysStatusResponse | null;
  busy: KeyName | null;
  outcomes: KeyOutcomes;
  loadError: string | null;
  onSave: (name: KeyName, key: string) => Promise<boolean>;
  onClear: (name: KeyName) => Promise<boolean>;
}

/** The state of a section's keys in words, so a collapsed section still says what it holds. */
export function keysSummary(saved: number, total: number): string {
  if (total === 1) return saved === 1 ? "Key saved" : "Key missing";
  return `${saved} of ${total} keys saved`;
}

function DrawerContent({ statuses, busy, outcomes, loadError, onSave, onClear }: ContentProps) {
  const [drafts, setDrafts] = useState(EMPTY);
  // The required key's section opens by itself while that key is missing.
  const [expanded, setExpanded] = useState<string[]>(
    statuses?.openai.configured === true ? [] : ["assistant"],
  );
  const toggle = (id: string) =>
    setExpanded((now) => (now.includes(id) ? now.filter((item) => item !== id) : [...now, id]));
  const save = async (name: KeyName) => {
    const value = drafts[name];
    setDrafts((now) => ({ ...now, [name]: "" }));
    if (value.trim()) await onSave(name, value);
  };

  return (
    <div className="@container w-full">
      {loadError ? <Banner kind="error">{loadError}</Banner> : null}
      {GROUPS.map((group) => (
        <AccordionSection
          key={group.id}
          title={group.title}
          summary={statuses ? keysSummary(group.keys.filter((f) => statuses[f.name].configured === true).length, group.keys.length) : null}
          open={expanded.includes(group.id)}
          onToggle={() => toggle(group.id)}
        >
          <div className="flex flex-col gap-5">
            {group.keys.map((field) => (
              <KeyForm
                key={field.name}
                field={field}
                configured={statuses?.[field.name].configured === true}
                draft={drafts[field.name]}
                busy={busy !== null}
                outcome={outcomes[field.name]}
                onDraft={(value) => setDrafts((now) => ({ ...now, [field.name]: value }))}
                onSave={() => void save(field.name)}
                onClear={() => void onClear(field.name)}
              />
            ))}
          </div>
        </AccordionSection>
      ))}
    </div>
  );
}

interface SettingsDrawerProps extends ContentProps {
  open: boolean;
  onClose: () => void;
}

/** The API keys, kept in the OS keychain, in a bottom drawer. No key is kept in the browser. */
export function SettingsDrawer({ open, onClose, ...content }: SettingsDrawerProps) {
  return (
    <BottomDrawer open={open} title="Settings" onClose={onClose} fitContent>
      <DrawerContent {...content} />
    </BottomDrawer>
  );
}
