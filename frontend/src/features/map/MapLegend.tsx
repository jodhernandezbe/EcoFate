import type { Ref } from "react";

import { BAND_LOOK, BANDS, isBand } from "../../lib/band";
import type { Facility, OccupationalTier, ScenarioDriver, Status } from "../../types/workspace";

export const SECTOR_CAPTION = "schematic downwind sector, not a modelled plume footprint";

/** A marker's status key: its risk status, or "none" while no risk is computed. */
export type StatusKey = NonNullable<Status> | "none" | "worker_only";

const ITEMS: { key: StatusKey; label: string; tone: string }[] = [
  ...BANDS.map((band) => ({ key: band, label: BAND_LOOK[band].label, tone: BAND_LOOK[band].fill })),
  { key: "none", label: "Not computed", tone: "bg-fg2" },
  { key: "worker_only", label: "No stack release", tone: "border-2 border-fg2" },
];

const RINGS: { key: OccupationalTier; label: string; tone: string }[] = BANDS.map((band) => ({
  key: band,
  label: BAND_LOOK[band].label,
  tone: BAND_LOOK[band].ring,
}));

export const statusKey = (facility: Facility): StatusKey => {
  if (facility.worker_only) return "worker_only";
  return isBand(facility.status) ? facility.status : "none";
};

interface Props {
  facilities: Facility[];
  /** Status keys whose markers are hidden; clicking a legend entry toggles one. */
  hidden: ReadonlySet<StatusKey>;
  onToggle: (key: StatusKey) => void;
  /** The facilities that have the highest value of some result (they get an outer ring). */
  drivers?: readonly ScenarioDriver[];
  ref?: Ref<HTMLElement>;
}

/** The ring around a marker is the worker screening tier (listed only when some facility has one). */
function WorkerRings({ facilities }: { facilities: Facility[] }) {
  const counts = new Map<OccupationalTier, number>();
  for (const facility of facilities) {
    const tier = facility.occupational_exposure?.risk_tier;
    if (isBand(tier)) counts.set(tier, (counts.get(tier) ?? 0) + 1);
  }
  if (counts.size === 0) return null;
  return (
    <div aria-label="Worker screening rings" role="group" className="mt-1.5 border-t border-hairline pt-1.5">
      <p className="m-0 mb-0.5 text-fg2">Ring: worker screening</p>
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {RINGS.map((ring) => (
          <li key={ring.key} className="flex items-center gap-1.5 px-1">
            <span aria-hidden className={`inline-block size-2.5 shrink-0 rounded-full border-2 ${ring.tone}`} />
            <span>{ring.label}</span>
            <span className="ml-auto pl-1.5 text-fg2">{counts.get(ring.key) ?? 0}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What the marker colours and sizes mean; each entry shows or hides its markers. */
export function MapLegend({ facilities, hidden, onToggle, drivers = [], ref }: Props) {
  const showsSector = facilities.some((f) => f.sector !== null);
  // Counts are shown only once there is something to count; before that a zero would read as data.
  const empty = facilities.length === 0;
  const counts = new Map<StatusKey, number>();
  for (const facility of facilities) {
    const key = statusKey(facility);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return (
    <aside
      ref={ref}
      aria-label="Map legend"
      className="glass absolute bottom-3 left-3 z-10 max-w-64 rounded-xl p-2.5 text-xs"
    >
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {ITEMS.filter((item) => item.key !== "worker_only" || (counts.get(item.key) ?? 0) > 0).map((item) => {
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
      <WorkerRings facilities={facilities} />
      {empty && <p className="m-0 mt-1.5 text-fg2">No facilities mapped yet.</p>}
      <p className="m-0 mt-1.5 text-fg2">Marker size follows the emission rate (g/s).</p>
      {(counts.get("worker_only") ?? 0) > 0 && (
        <p className="m-0 mt-1 text-fg2">
          Outlined marker: no stack release, so no community result and a fixed size; only the worker ring applies.
        </p>
      )}
      <p className="m-0 mt-1 text-fg2">Click an entry to hide or show its markers.</p>
      {drivers.length > 0 && (
        <p className="m-0 mt-1 text-accent">
          Outer ring: the facility that drives a worst case. Pin it to see the tracts it affects most.
        </p>
      )}
      {showsSector && <p className="m-0 mt-1 text-warn">Shaded wedge: {SECTOR_CAPTION}.</p>}
    </aside>
  );
}
