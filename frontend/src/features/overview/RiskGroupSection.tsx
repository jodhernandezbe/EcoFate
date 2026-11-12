import { Maximize2, Minimize2 } from "lucide-react";
import { useMemo } from "react";

import type { BandBoundaries } from "../../types/api";
import type { Facility } from "../../types/workspace";
import { isAssessed } from "./assessment";
import { RiskGroupChart } from "./RiskGroupChart";
import {
  groupFacilities,
  type GroupBy,
  type Pathway,
  type Quantity,
  topGroups,
  TOP_N,
} from "./riskGroups";

const COPY: Record<GroupBy, { title: string; ungrouped: string; overlap: boolean }> = {
  subsector: { title: "Risk by industry (NAICS subsector)", ungrouped: "industry not reported", overlap: false },
  condition: { title: "Risk by condition of use", ungrouped: "no condition of use reported", overlap: true },
  stage: { title: "Risk by life cycle stage", ungrouped: "no life cycle stage reported", overlap: true },
};

interface Chart {
  quantity: Quantity;
  label: string;
  title: string;
  missing: string;
}

const OUTDOOR_CHARTS: Chart[] = [
  {
    quantity: "hq",
    label: "Hazard quotient",
    title: "Hazard quotient (non-cancer, unitless)",
    missing: "No group has a worst-case hazard quotient to rank.",
  },
  {
    quantity: "risk",
    label: "Cancer risk",
    title: "Lifetime cancer risk (unitless)",
    missing: "No group has a worst-case lifetime cancer risk to rank (the chemical may have no unit risk).",
  },
];

const INDOOR_CHARTS: Chart[] = [
  {
    quantity: "hq",
    label: "Hazard quotient",
    title: "Worker hazard quotient (non-cancer, unitless)",
    missing: "No group has a worker hazard quotient to rank (no fugitive release, or no RfC).",
  },
  {
    quantity: "risk",
    label: "Cancer risk",
    title: "Worker lifetime cancer risk (unitless)",
    missing: "No group has a worker cancer risk to rank (no fugitive release, or no unit risk).",
  },
  {
    quantity: "ratio",
    label: "Limit ratio",
    title: "8-hour average over the occupational limit (unitless)",
    missing: "No group has a limit ratio to rank (no fugitive release, or no occupational limit).",
  },
];

/** The quantities a pathway offers. */
export const chartsFor = (pathway: Pathway): Chart[] => (pathway === "indoor" ? INDOOR_CHARTS : OUTDOOR_CHARTS);

const SHORT_LABEL_CHARS = 16;
const LONG_LABEL_CHARS = 30;

interface Props {
  by: GroupBy;
  facilities: Facility[];
  /** Which quantity the chart shows; chosen with the switch in the section's header. */
  quantity: Quantity;
  onQuantity: (quantity: Quantity) => void;
  /** The exposure pathway (medium, route, receptor) shown; chosen with the one dropdown above the sections. */
  pathway: Pathway;
  expanded: boolean;
  /** Another section is expanded: this one stays mounted but is not shown. */
  hidden: boolean;
  onToggleExpand: () => void;
  bands: BandBoundaries | undefined;
  digits: number;
}

function Notes({ by, ungrouped, cut }: { by: GroupBy; ungrouped: number; cut: number }) {
  const copy = COPY[by];
  const lines = [
    `The ${TOP_N} groups with the highest value of the chosen quantity; a bar is the highest worst-case value among the group's assessed facilities.`,
    copy.overlap ? "A facility with several conditions of use appears in each, so bars can overlap." : null,
    cut > 0 ? `${cut} more ${cut === 1 ? "group" : "groups"} not shown.` : null,
    ungrouped > 0 ? `${ungrouped} ${ungrouped === 1 ? "facility" : "facilities"}: ${copy.ungrouped}.` : null,
  ].filter((line): line is string => line !== null);
  return (
    <ul className="m-0 list-none p-0 text-[11px] text-fg2">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

function QuantitySwitch({
  charts,
  quantity,
  onQuantity,
}: {
  charts: Chart[];
  quantity: Quantity;
  onQuantity: (quantity: Quantity) => void;
}) {
  return (
    <div role="group" aria-label="Quantity shown" className="inline-flex rounded-full bg-fg2/10 p-0.5 text-[11px]">
      {charts.map(({ quantity: key, label }) => (
        <button
          key={key}
          type="button"
          aria-pressed={quantity === key}
          onClick={() => onQuantity(key)}
          className={`spring rounded-full px-2 py-0.5 ${quantity === key ? "bg-solid font-medium text-fg shadow-sm" : "text-fg2 hover:text-fg"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function EmptyChart({ title, text, tall }: { title: string; text: string; tall: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className="m-0 text-xs font-medium">{title}</h3>
      <div className={`grid place-items-center rounded-lg border border-dashed border-hairline px-3 text-center ${tall ? "h-[56vh] min-h-56" : "h-52"}`}>
        <p className="m-0 text-sm text-fg2">{text}</p>
      </div>
    </div>
  );
}

/** Two charts of the worst-case hazard quotient and cancer risk by a grouping of the facilities. */
export function RiskGroupSection(props: Props) {
  const { by, facilities, quantity, pathway, expanded, hidden, bands, digits } = props;
  const copy = COPY[by];
  const grouping = useMemo(() => groupFacilities(facilities, by, pathway), [facilities, by, pathway]);
  const { shown, hidden: cut } = useMemo(() => topGroups(grouping.groups, quantity), [grouping, quantity]);
  const charts = chartsFor(pathway);
  const chart = charts.find((c) => c.quantity === quantity) ?? charts[0];
  // A worker-only facility has a worker result to rank, and no stack result to.
  const anyAssessed = useMemo(
    () => facilities.some((f) => isAssessed(f) || (pathway === "indoor" && f.worker_only)),
    [facilities, pathway],
  );
  const Icon = expanded ? Minimize2 : Maximize2;
  const emptyText = (missing: string) =>
    facilities.length === 0
      ? "Nothing to show yet. Run an assessment and this chart ranks its facilities."
      : anyAssessed
        ? missing
        : "Nothing assessed yet: no facility has a worst-case result.";
  return (
    <section
      aria-label={copy.title}
      hidden={hidden}
      className={`glass flex min-w-0 flex-col gap-2 rounded-2xl p-3.5 ${hidden ? "hidden" : ""} ${expanded ? "col-span-full flex-1" : ""}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="m-0 text-xs font-semibold uppercase tracking-wide text-fg2">{copy.title}</h2>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <QuantitySwitch charts={charts} quantity={chart?.quantity ?? quantity} onQuantity={props.onQuantity} />
          <button
            type="button"
            aria-label={expanded ? "Restore section" : "Expand section"}
            aria-pressed={expanded}
            onClick={props.onToggleExpand}
            className="spring grid size-6 place-items-center rounded-full text-fg2 transition hover:bg-hairline hover:text-fg"
          >
            <Icon size={14} aria-hidden="true" />
          </button>
        </div>
      </header>
      {chart && shown.length > 0 ? (
        <RiskGroupChart
          groups={shown}
          quantity={chart.quantity}
          title={chart.title}
          bands={bands}
          pathway={pathway}
          digits={digits}
          labelChars={expanded ? LONG_LABEL_CHARS : SHORT_LABEL_CHARS}
          heightClass={expanded ? "h-[56vh] min-h-56" : "h-52"}
          angled={!expanded}
        />
      ) : (
        <EmptyChart title={chart?.title ?? ""} text={emptyText(chart?.missing ?? "")} tall={expanded} />
      )}
      <Notes by={by} ungrouped={grouping.ungrouped} cut={cut} />
    </section>
  );
}
