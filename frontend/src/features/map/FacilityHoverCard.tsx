import { ChevronRight, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { StatusPill } from "../../components/ui/StatusPill";
import { TierPill } from "../../components/ui/TierPill";
import {
  formatCount,
  formatNumber,
  formatRange,
  formatReported,
  formatWithUnit,
  orNotReported,
} from "../../lib/format";
import { stackNumber } from "../../lib/scenarios";
import type { Extreme, Facility, Screening, Stack } from "../../types/workspace";
import { Metric } from "../overview/Metric";
import { ScenarioSection } from "./ScenarioSection";
import { WorkerSection } from "./WorkerSection";

// More stacks than this start folded: the card stays readable and the risk stays in view.
const STACKS_SHOWN_OPEN = 2;

const range = (extreme: Extreme | null | undefined, digits: number): string =>
  extreme ? formatRange(extreme.low, extreme.high, digits) : formatNumber(null, digits);

function StackRow({ stack, digits, drives }: { stack: Stack; digits: number; drives: string[] }) {
  return (
    <li className="rounded-lg bg-fg2/5 p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">
          {stack.tier_label ?? "No source reported"}
        </span>
        {stack.stack_number !== null && <span className="text-xs text-fg2">stack {stack.stack_number}</span>}
      </div>
      {drives.length > 0 && (
        <p className="m-0 mb-1 text-xs font-medium text-accent">Drives the worst case: {drives.join(", ")}</p>
      )}
      <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
        <Metric label="Height">{formatWithUnit(stack.height_m, "m", digits)}</Metric>
        <Metric label="Diameter">{formatWithUnit(stack.diameter_m, "m", digits)}</Metric>
        <Metric label="Exit velocity">{formatWithUnit(stack.exit_velocity_m_s, "m/s", digits)}</Metric>
        <Metric label="Exit temperature">{formatWithUnit(stack.exit_temperature_k, "K", digits)}</Metric>
      </dl>
      {stack.scc && (
        <p className="m-0 mt-1 text-xs text-fg2">
          SCC {stack.scc}
          {stack.scc_description ? ` · ${stack.scc_description}` : ""}
          {stack.scc_score !== null ? ` (score ${formatNumber(stack.scc_score, digits)})` : ""}
        </p>
      )}
    </li>
  );
}

/** The results each stack drives: stack number -> names of the results whose scenario names it. */
function drivingStacks(facility: Facility): Map<number, string[]> {
  const found = new Map<number, string[]>();
  for (const scenario of facility.scenarios) {
    const number = stackNumber(scenario);
    if (number !== null) found.set(number, [...(found.get(number) ?? []), scenario.quantity_label]);
  }
  return found;
}

const CONDITIONS_SHOWN_OPEN = 3;

/** The TSCA life cycle stages and conditions of use the API sent, or why there are none. */
function Conditions({ facility }: { facility: Facility }) {
  const { conditions_of_use: conditions, lifecycle_stages: stages, conditions_note: note } = facility;
  if (conditions.length === 0) {
    return <p className="m-0 text-xs text-fg2">Not reported{note ? `: ${note}` : ""}</p>;
  }
  return (
    <>
      <p className="m-0 text-[11px] font-medium text-fg2">Life cycle stages</p>
      <ul aria-label="Life cycle stages" className="m-0 mb-2 mt-1 flex list-none flex-wrap gap-1 p-0">
        {stages.map((stage) => (
          <li key={stage} className="rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">
            {stage}
          </li>
        ))}
      </ul>
      <p className="m-0 text-[11px] font-medium text-fg2">
        Conditions of use
      </p>
      <ul aria-label="Conditions of use" className="m-0 mt-1 grid list-none gap-1 p-0">
        {conditions.map((c) => (
          <li key={`${c.tri_section}-${c.lifecycle_stage}`} className="rounded-lg bg-fg2/5 p-2 text-xs">
            <p className="m-0 font-medium">{c.cou_category}</p>
            <p className="m-0 text-fg2">
              Life cycle stage: {c.lifecycle_stage}
            </p>
            <p className="m-0 text-[11px] text-fg2">
              From TRI “{c.tri_activity}” (Form R {c.tri_section}) · mapping {c.mapping_strength}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Why a facility has no stacks: screened out on the bound, not assessed (with the reason), or not covered. */
function noStacks(screening: Screening | null): string {
  if (screening?.outcome === "screened_out_at_bound") {
    return "None needed: screened out on a conservative bound with a generic stack.";
  }
  if (screening?.outcome === "not_assessed") {
    return `Not assessed: ${screening.reason ?? "no reason was given"}`;
  }
  return "Not assessed yet: the batch assessment has not covered this facility.";
}

/** What the screen decided, when it limited or skipped the assessment. */
function ScreeningNote({ screening, digits }: { screening: Screening | null; digits: number }) {
  if (screening === null || screening.outcome === "full" || screening.outcome === "not_assessed") return null;
  if (screening.outcome === "worst_case_only") {
    return (
      <p className="m-0 mt-1 text-xs text-fg2">
        Worst case only, with this facility's own stacks: the weather at the site, the residents and
        the representative case were not computed.
      </p>
    );
  }
  const hq = screening.value_hq !== null ? `HQ ${formatNumber(screening.value_hq, digits)}` : null;
  const risk =
    screening.value_cancer_risk !== null
      ? `cancer risk ${formatNumber(screening.value_cancer_risk, digits)}`
      : null;
  return (
    <div className="mt-1 rounded-lg bg-fg2/5 p-2 text-xs">
      <p className="m-0 font-medium">
        Screened out{screening.outcome === "screened_out_at_bound" ? " on the bound" : " with its own stacks"}
        {hq || risk ? ` (${[hq, risk].filter(Boolean).join(", ")})` : ""}
      </p>
      {screening.reason && <p className="m-0 mt-0.5 text-fg2">{screening.reason}</p>}
    </div>
  );
}

/** Community and worker risk side by side: is it the stack plume or indoor fugitive release? */
function RiskBadges({ facility, digits }: { facility: Facility; digits: number }) {
  const { exposure, occupational_exposure: worker } = facility;
  const ratio = worker?.baseline.oel_ratio ?? null;
  return (
    <div
      role="group"
      aria-label="Community and worker risk"
      className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-fg2/5 p-2 text-xs"
    >
      <span className="flex items-center gap-1.5">
        Community HQ{" "}
        <span className="font-medium tabular-nums">
          {exposure?.hq_worst ? formatNumber(exposure.hq_worst.high, digits) : formatNumber(null, digits)}
        </span>
      </span>
      <span className="flex items-center gap-1.5">
        Worker <TierPill tier={worker?.risk_tier ?? null} />{" "}
        {ratio !== null && <span className="tabular-nums text-fg2">R_OEL {formatNumber(ratio, digits)}</span>}
      </span>
    </div>
  );
}

interface SectionProps {
  title: string;
  /** Shown beside the title: a count, or the status pill. */
  aside?: ReactNode;
  initiallyOpen: boolean;
  children: ReactNode;
}

/** A titled part of the card that folds; its heading is the toggle (usable once pinned). */
function Section({ title, aside, initiallyOpen, children }: SectionProps) {
  const [open, setOpen] = useState(initiallyOpen);
  const bodyId = useId();
  return (
    <section className="mt-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="m-0 text-xs font-semibold text-fg2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((value) => !value)}
            className="flex items-center gap-1 rounded-lg hover:text-fg"
          >
            <ChevronRight
              size={12}
              aria-hidden="true"
              className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}
            />
            {title}
          </button>
        </h4>
        {aside}
      </div>
      <div id={bodyId} hidden={!open} className="mt-1">
        {children}
      </div>
    </section>
  );
}

interface CardProps {
  facility: Facility;
  digits: number;
  id: string;
  /** A pinned card takes the pointer (its sections fold, it closes by its control). */
  pinned: boolean;
  onClose: () => void;
  /** Tallest the card may be (px), so it scrolls inside the map rather than past it. */
  maxHeight: number;
}

/** The inspector of one facility: identifiers, release, stacks with their tier, and risk. */
export function FacilityHoverCard({ facility, digits, id, pinned, onClose, maxHeight }: CardProps) {
  const { industry, exposure, receptors, stacks, screening } = facility;
  const drivers = drivingStacks(facility);
  return (
    <div
      id={id}
      role={pinned ? "dialog" : "tooltip"}
      aria-label={pinned ? orNotReported(facility.name) : undefined}
      style={{ maxHeight }}
      className={`glass sheet-in flex w-80 flex-col rounded-2xl text-sm shadow-[var(--shadow)] ${
        pinned ? "pointer-events-auto" : "pointer-events-none"
      }`}
    >
      <header className="flex shrink-0 items-start gap-2 px-3.5 pt-3.5">
        <div className="min-w-0 flex-1">
          <h3 className="m-0 text-base font-semibold">{orNotReported(facility.name)}</h3>
          <p className="m-0 text-xs text-fg2">
            FRS {facility.frs_id} · TRI doc. control no. {orNotReported(facility.doc_ctrl_num)}
          </p>
          <p className="m-0 text-xs text-fg2">
            NAICS {orNotReported(industry?.naics_code)} · {orNotReported(industry?.naics_title)}
          </p>
        </div>
        {pinned ? (
          <button
            type="button"
            aria-label="Close facility details"
            onClick={onClose}
            className="spring -mr-1 -mt-1 grid size-7 shrink-0 place-items-center rounded-full text-fg2 transition hover:bg-hairline hover:text-fg"
          >
            <X size={14} aria-hidden="true" />
          </button>
        ) : (
          <span className="shrink-0 text-[11px] text-fg2">Click to pin</span>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-3.5 pb-3.5 pt-2">
        <RiskBadges facility={facility} digits={digits} />
        <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
          <Metric label="Reported release">
            {formatReported(facility.total_release)} {facility.release_unit}/yr
          </Metric>
          <Metric label="Emission rate">{formatWithUnit(facility.emission_rate_g_s, "g/s", digits)}</Metric>
          <Metric label="Operating hours">
            {formatReported(facility.operating_hours_per_year)} h/yr
          </Metric>
          <Metric label="CAS number">{orNotReported(facility.cas_number)}</Metric>
        </dl>
        <Section
          title="TSCA conditions of use"
          aside={<span className="text-xs text-fg2">{facility.conditions_of_use.length}</span>}
          initiallyOpen={facility.conditions_of_use.length <= CONDITIONS_SHOWN_OPEN}
        >
          <Conditions facility={facility} />
        </Section>
        {facility.scenarios.length > 0 && (
          <Section title="Worst-case scenarios" aside={null} initiallyOpen>
            <ScenarioSection facility={facility} digits={digits} />
          </Section>
        )}
        <Section
          title="Stacks"
          aside={<span className="text-xs text-fg2">{stacks.length}</span>}
          initiallyOpen={stacks.length <= STACKS_SHOWN_OPEN && drivers.size === 0}
        >
          {stacks.length === 0 ? (
            <p className="m-0 text-xs text-fg2">{noStacks(screening)}</p>
          ) : (
            <ul className="m-0 grid list-none gap-1.5 p-0">
              {stacks.map((stack, index) => (
                <StackRow
                  key={index}
                  stack={stack}
                  digits={digits}
                  drives={stack.stack_number === null ? [] : (drivers.get(stack.stack_number) ?? [])}
                />
              ))}
            </ul>
          )}
        </Section>
        <Section
          title="Worker exposure"
          aside={<TierPill tier={facility.occupational_exposure?.risk_tier ?? null} />}
          initiallyOpen={facility.occupational_exposure !== null}
        >
          <WorkerSection facility={facility} digits={digits} />
        </Section>
        <Section title="Receptor risk" aside={<StatusPill status={facility.status} />} initiallyOpen>
          <ScreeningNote screening={screening} digits={digits} />
          <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
            <Metric label="Concentration, worst case">
              {exposure?.concentration_worst
                ? `${range(exposure.concentration_worst, digits)} µg/m³`
                : formatNumber(null, digits)}
            </Metric>
            <Metric label="Concentration, representative">
              {exposure?.concentration_representative
                ? `${range(exposure.concentration_representative, digits)} µg/m³`
                : formatNumber(null, digits)}
            </Metric>
            <Metric label="HQ, worst case">{range(exposure?.hq_worst, digits)}</Metric>
            <Metric label="HQ, representative">{range(exposure?.hq_representative, digits)}</Metric>
            <Metric label="Cancer risk, worst case">{range(exposure?.cancer_risk_worst, digits)}</Metric>
            <Metric label="Cancer risk, representative">
              {range(exposure?.cancer_risk_representative, digits)}
            </Metric>
            <Metric label={`Residents within ${receptors ? formatNumber(receptors.radius_km, digits) : "?"} km`}>
              {receptors ? formatCount(receptors.total_population) : formatNumber(null, digits)}
            </Metric>
          </dl>
        </Section>
      </div>
    </div>
  );
}
