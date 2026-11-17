import type { ReactNode, Ref } from "react";

import { BAND_LOOK, BANDS } from "../../lib/band";
import { pathwayInfo, type Pathway } from "../../lib/pathways";
import type { Facility, ScenarioDriver } from "../../types/workspace";
import { statusKey, totalOf, type StatusKey } from "./mapData";

export const SECTOR_CAPTION = "schematic downwind sector, not a modelled plume footprint";
export const NO_RESULT_LABEL = "No result on this pathway";

/** Legend order: the highest band first, then the facilities with no result on the pathway. */
const ITEMS: { key: StatusKey; label: string; tone: string }[] = [
  ...[...BANDS].reverse().map((band) => ({ key: band, label: BAND_LOOK[band].label, tone: BAND_LOOK[band].fill })),
  { key: "none", label: NO_RESULT_LABEL, tone: "border-2 border-fg2" },
];

interface Props {
  /** Every facility of the workspace (hidden ones included, so the counts do not change). */
  facilities: Facility[];
  /** The pathway whose bands colour the markers. */
  pathway: Pathway;
  /** Status keys whose markers are hidden; clicking a legend entry toggles one. */
  hidden: ReadonlySet<StatusKey>;
  onToggle: (key: StatusKey) => void;
  /** The facilities that drive a worst case of the chosen pathway (they get an outer ring). */
  drivers?: readonly ScenarioDriver[];
  /** The pathway dropdown, shown beside the legend's title. */
  picker?: ReactNode;
  ref?: Ref<HTMLElement>;
}

/** What the marker colours and sizes mean; each entry shows or hides its markers. */
export function MapLegend({ facilities, pathway, hidden, onToggle, drivers = [], picker, ref }: Props) {
  const showsSector = facilities.some((f) => f.sector !== null);
  // Counts are shown only once there is something to count; before that a zero would read as data.
  const empty = facilities.length === 0;
  const counts = new Map<StatusKey, number>();
  for (const facility of facilities) {
    const key = statusKey(facility, pathway);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const unsized = facilities.filter((f) => totalOf(f) === null).length;
  return (
    <aside
      ref={ref}
      aria-label="Map legend"
      className="glass absolute bottom-3 left-3 z-10 max-w-64 rounded-xl p-2.5 text-xs"
    >
      <p className="m-0 mb-1 text-fg2">Colour: {pathwayInfo(pathway).label}</p>
      {picker}
      <ul className="m-0 mt-1 grid list-none gap-0.5 p-0">
        {ITEMS.map((item) => {
          const off = hidden.has(item.key);
          const count = counts.get(item.key) ?? 0;
          return (
            <li key={item.key}>
              <button
                type="button"
                aria-pressed={!off}
                onClick={() => onToggle(item.key)}
                title={off ? `Show ${item.label.toLowerCase()} markers` : `Hide ${item.label.toLowerCase()} markers`}
                className={`spring flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left transition hover:bg-fg2/10 ${off ? "opacity-40" : ""}`}
              >
                <span aria-hidden className={`inline-block size-2.5 shrink-0 rounded-full ${item.tone}`} />
                <span className={off ? "line-through" : ""}>{item.label}</span>
                {empty ? null : <span className="ml-auto pl-1.5 text-fg2">{count}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      {empty && <p className="m-0 mt-1.5 text-fg2">No facilities mapped yet.</p>}
      <p className="m-0 mt-1.5 text-fg2">Size: total annual air release.</p>
      {unsized > 0 && (
        <p className="m-0 mt-1 text-fg2">
          {unsized} {unsized === 1 ? "facility" : "facilities"} with no release reported, drawn smallest.
        </p>
      )}
      <p className="m-0 mt-1 text-fg2">Click an entry to hide or show its markers.</p>
      {drivers.length > 0 && (
        <p className="m-0 mt-1 text-accent">
          Outer ring: the facility that drives a worst case.
          {pathway === "outdoor" && " Pin it to see the tracts it affects most."}
        </p>
      )}
      {showsSector && <p className="m-0 mt-1 text-warn">Shaded wedge: {SECTOR_CAPTION}.</p>}
    </aside>
  );
}
