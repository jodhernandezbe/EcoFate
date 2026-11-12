import { useState, type KeyboardEvent, type ReactNode } from "react";

import type { BandBoundaries } from "../../types/api";
import type { WorkspaceState } from "../../types/workspace";
import { EpaOverviewRibbon } from "./EpaOverviewRibbon";
import { isAssessed } from "./assessment";
import { RiskGroupSection } from "./RiskGroupSection";
import { PATHWAYS, type GroupBy, type Pathway, type Quantity } from "./riskGroups";

interface Props {
  workspace: WorkspaceState;
  digits: number;
  /** Band boundaries from the client settings; the charts draw them as reference lines. */
  bands?: BandBoundaries;
  /** The exposure chain, composed by the app; drawn above the summary cards. */
  chain?: ReactNode;
}

type View = "summary" | "risk" | "chain";

const SECTIONS: GroupBy[] = ["subsector", "condition", "stage"];
const VIEWS: { key: View; label: string }[] = [
  { key: "summary", label: "Summary" },
  { key: "risk", label: "Risk by group" },
  { key: "chain", label: "Exposure chain" },
];

function ViewSwitch({ view, onView }: { view: View; onView: (view: View) => void }) {
  return (
    <div role="group" aria-label="Overview view" className="mb-3 inline-flex self-start rounded-full bg-fg2/10 p-0.5 text-xs">
      {VIEWS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          aria-pressed={view === key}
          onClick={() => onView(key)}
          className={`spring rounded-full px-3 py-1 ${view === key ? "bg-solid font-medium text-fg shadow-sm" : "text-fg2 hover:text-fg"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function PathwayPicker({ pathway, onPathway }: { pathway: Pathway; onPathway: (pathway: Pathway) => void }) {
  return (
    <select
      aria-label="Exposure pathway (medium, route, receptor)"
      value={pathway}
      onChange={(event) => onPathway(event.target.value as Pathway)}
      className="max-w-full rounded-lg bg-fg2/10 px-2 py-1 text-[11px] text-fg"
    >
      {PATHWAYS.map(({ key, label }) => (
        <option key={key} value={key}>
          {label}
        </option>
      ))}
    </select>
  );
}

/**
 * The Overview panel has two views of one workspace: the executive summary ribbon, and the three
 * risk-by-group charts (the switch is always there; the charts say what is missing). The ribbon stays
 * mounted; the charts are drawn only on their own view (Recharts cannot measure a hidden box), and
 * The pathway (outdoor air for the general population, or indoor air for workers) and the quantity shown
 * are kept here, so the three sections agree. A chart section can expand to fill the panel, hiding the others.
 */
export function OverviewPanel({ workspace, digits, bands, chain }: Props) {
  const [view, setView] = useState<View>("summary");
  const [expanded, setExpanded] = useState<GroupBy | null>(null);
  const [quantity, setQuantity] = useState<Quantity>("hq");
  const [pathway, setPathway] = useState<Pathway>("outdoor");
  // The limit ratio exists only for workers: leaving that pathway falls back to the hazard quotient.
  const choosePathway = (next: Pathway) => {
    setPathway(next);
    if (next === "outdoor" && quantity === "ratio") setQuantity("hq");
  };
  const showRisk = view === "risk";
  const assessed = workspace.facilities.filter(isAssessed).length;
  const open = showRisk && expanded !== null;
  // Escape belongs to the topmost layer: restoring a section is handled here, so the panel's
  // fullscreen (a window listener that honours defaultPrevented) is not also left.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    event.stopPropagation();
    setExpanded(null);
  };
  // A flex column at least as tall as the panel, so the ribbon can stretch to fill it.
  return (
    <div className="@container flex min-h-full flex-col p-4 outline-none" tabIndex={-1} onKeyDown={onKeyDown}>
      <ViewSwitch view={view} onView={setView} />
      <div hidden={view !== "summary"} className={view === "summary" ? "contents" : "hidden"}>
        <EpaOverviewRibbon workspace={workspace} digits={digits} />
      </div>
      <div hidden={view !== "chain"} className={view === "chain" ? "flex flex-1 flex-col" : "hidden"}>
        {chain}
      </div>
      {showRisk && (
        <>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="m-0 text-xs text-fg2">
              {workspace.facilities.length === 0 ? (
                "No facilities assessed yet."
              ) : (
                <>
                  {workspace.facilities.length} {workspace.facilities.length === 1 ? "facility" : "facilities"} in this
                  run, {assessed} with a worst-case result.
                </>
              )}
            </p>
            <PathwayPicker pathway={pathway} onPathway={choosePathway} />
          </div>
          <div className={open ? "flex min-h-0 flex-1 flex-col" : "grid grid-cols-1 gap-3 @4xl:grid-cols-3"}>
            {SECTIONS.map((by) => (
              <RiskGroupSection
                key={by}
                by={by}
                facilities={workspace.facilities}
                quantity={quantity}
                onQuantity={setQuantity}
                pathway={pathway}
                expanded={expanded === by}
                hidden={open && expanded !== by}
                onToggleExpand={() => setExpanded((now) => (now === by ? null : by))}
                bands={bands}
                digits={digits}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
