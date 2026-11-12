import { formatNumber, NOT_REPORTED } from "../../lib/format";
import { evidenceText } from "../../lib/worker";
import type { Facility } from "../../types/workspace";
import { isAssessed, isScreenedOut } from "./assessment";

/** What facilities are grouped by: NAICS subsector, TSCA condition of use, TSCA life cycle stage. */
export type GroupBy = "subsector" | "condition" | "stage";
/**
 * The exposure pathway: the medium, the route and the receptors. Outdoor air reaches the general
 * population by inhalation (the stack result); indoor air reaches the workers by inhalation (the
 * fugitive release in the plant).
 */
export type Pathway = "outdoor" | "indoor";
export const PATHWAYS: { key: Pathway; label: string }[] = [
  { key: "outdoor", label: "Outdoor Air → Inhalation → General Population" },
  { key: "indoor", label: "Indoor Air → Inhalation → Worker" },
];
/**
 * The quantities, each with a chart of its own: hazard quotient, lifetime cancer risk and, for
 * workers only, the 8-hour average over the occupational limit.
 */
export type Quantity = "hq" | "risk" | "ratio";

/** The facility a value comes from: one of the values the API sent, never a combination of them. */
export interface Best {
  value: number;
  frsId: string;
  name: string | null;
  /** That facility's worst-case concentration (µg/m³), when the API sent it (outdoor air). */
  concentration: number | null;
  /** That facility's 8-hour average in the workplace (mg/m³), when the API sent it (indoor air). */
  twa: number | null;
  /** The stack that gives the value (outdoor air), when the API named it. */
  stack: number | null;
  /** What the 8-hour average rests on, in words ("OSHA monitoring" or the driving activity); indoor air only. */
  evidence: string | null;
}

export interface Group {
  key: string;
  label: string;
  /** Facilities in the group, whatever became of them. */
  facilities: number;
  /** Of those, the ones with a worst-case result. */
  assessed: number;
  /** Of those, the ones screened out (their numbers are bounds, so they are never a bar). */
  screenedOut: number;
  /** Highest worst-case hazard quotient (unitless). */
  hq: Best | null;
  /** Highest worst-case lifetime cancer risk (unitless). */
  risk: Best | null;
  /** Highest 8-hour average over the occupational limit (unitless); workers only. */
  ratio: Best | null;
}

export interface Grouping {
  groups: Group[];
  /** Facilities that belong to no group (no subsector, no condition of use, no stage). */
  ungrouped: number;
}

export const TOP_N = 5;

const finite = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value);

interface Measured {
  concentration: number | null | undefined;
  twa: number | null | undefined;
  stack?: number | null;
  evidence?: string | null;
}

function bestOf(
  current: Best | null,
  facility: Facility,
  value: number | null | undefined,
  measured: Measured,
): Best | null {
  if (!finite(value) || (current !== null && value <= current.value)) return current;
  return {
    value,
    frsId: facility.frs_id,
    name: facility.name,
    concentration: finite(measured.concentration) ? measured.concentration : null,
    twa: finite(measured.twa) ? measured.twa : null,
    stack: finite(measured.stack) ? measured.stack : null,
    evidence: measured.evidence ?? null,
  };
}

/** The groups a facility belongs to: key and label of each, once per distinct key. */
function membership(facility: Facility, by: GroupBy): Map<string, string> {
  const found = new Map<string, string>();
  if (by === "subsector") {
    const code = facility.naics_subsector;
    if (code) found.set(code, facility.naics_subsector_title ? `${code} · ${facility.naics_subsector_title}` : code);
  } else if (by === "condition") {
    for (const c of facility.conditions_of_use) {
      const label = `${c.lifecycle_stage} · ${c.cou_category}`;
      found.set(label, label);
    }
  } else {
    for (const stage of facility.lifecycle_stages) found.set(stage, stage);
  }
  return found;
}

function emptyGroup(key: string, label: string): Group {
  return { key, label, facilities: 0, assessed: 0, screenedOut: 0, hq: null, risk: null, ratio: null };
}

function addOutdoor(group: Group, facility: Facility): void {
  const exposure = facility.exposure;
  const measured = (stack: number | undefined) => ({
    concentration: exposure?.concentration_worst?.high,
    twa: null,
    stack,
  });
  group.hq = bestOf(group.hq, facility, exposure?.hq_worst?.high, measured(exposure?.hq_worst?.high_stack));
  group.risk = bestOf(
    group.risk,
    facility,
    exposure?.cancer_risk_worst?.high,
    measured(exposure?.cancer_risk_worst?.high_stack),
  );
}

/** The worker result at the baseline, the case the API calls the facility's own. */
function addIndoor(group: Group, facility: Facility): void {
  const worker = facility.occupational_exposure;
  const tier = worker?.baseline;
  const evidence = worker
    ? evidenceText({ evidence: worker.evidence, drivingLabel: worker.driving_activity?.label ?? null })
    : null;
  const measured = { concentration: null, twa: tier?.twa_mg_m3, evidence };
  group.hq = bestOf(group.hq, facility, tier?.hq, measured);
  group.risk = bestOf(group.risk, facility, tier?.cancer_risk, measured);
  group.ratio = bestOf(group.ratio, facility, tier?.oel_ratio, measured);
}

function addTo(group: Group, facility: Facility, pathway: Pathway): void {
  group.facilities += 1;
  // The community screen bounds what reaches the neighbours, not what workers breathe: on the
  // indoor pathway every facility with a worker result is ranked, screened out or worker-only.
  if (pathway === "indoor") {
    if (facility.occupational_exposure) {
      group.assessed += 1;
      addIndoor(group, facility);
    }
    return;
  }
  if (isScreenedOut(facility)) group.screenedOut += 1;
  if (!isAssessed(facility)) return;
  group.assessed += 1;
  addOutdoor(group, facility);
}

/**
 * Group the facilities. For the outdoor pathway a group's bars are the highest worst-case hazard
 * quotient and cancer risk among its assessed facilities; for the indoor pathway they are the
 * highest worker hazard quotient, cancer risk and limit ratio. All are selected from what the API
 * sent; nothing is added, averaged or converted. A facility is counted once per group it belongs to (several
 * conditions of use are possible).
 */
export function groupFacilities(facilities: Facility[], by: GroupBy, pathway: Pathway = "outdoor"): Grouping {
  const groups = new Map<string, Group>();
  let ungrouped = 0;
  // The outdoor pathway has no place for a facility without a stack release.
  for (const facility of facilities.filter((f) => pathway === "indoor" || !f.worker_only)) {
    const member = membership(facility, by);
    if (member.size === 0) ungrouped += 1;
    for (const [key, label] of member) {
      const group = groups.get(key) ?? emptyGroup(key, label);
      groups.set(key, group);
      addTo(group, facility, pathway);
    }
  }
  return { groups: [...groups.values()], ungrouped };
}

/** The `limit` groups with the highest value of `quantity` (ties by label), and how many were cut. */
export function topGroups(
  groups: Group[],
  quantity: Quantity,
  limit: number = TOP_N,
): { shown: Group[]; hidden: number } {
  const ranked = groups
    .filter((g) => g[quantity] !== null)
    .sort((a, b) => (b[quantity]?.value ?? 0) - (a[quantity]?.value ?? 0) || a.label.localeCompare(b.label));
  return { shown: ranked.slice(0, limit), hidden: Math.max(ranked.length - limit, 0) };
}

export const QUANTITY_NAME: Record<Quantity, string> = {
  hq: "hazard quotient",
  risk: "lifetime cancer risk",
  ratio: "8-hour average over the occupational limit",
};

/** One line of a bar's tooltip. */
export interface BarLine {
  label: string;
  value: string;
  /** What the value belongs to (a facility and its concentration); null when there is nothing to add. */
  detail: string | null;
}

export interface BarDetail {
  group: string;
  lines: BarLine[];
  counts: string;
}

function facilityText(best: Best, pathway: Pathway, digits: number): string {
  const name = best.name ?? `FRS ${best.frsId}`;
  if (pathway === "indoor") {
    const twa = best.twa === null ? "8-hour average not reported" : `${formatNumber(best.twa, digits)} mg/m³ 8-hour average`;
    return best.evidence === null ? `${name} · ${twa}` : `${name} · ${twa} · ${best.evidence}`;
  }
  const concentration =
    best.concentration === null
      ? "concentration not reported"
      : `${formatNumber(best.concentration, digits)} µg/m³ worst case`;
  const stack = best.stack === null ? "" : ` · stack ${best.stack}`;
  return `${name}${stack} · ${concentration}`;
}

/** What a group's bar stands for: the highest value of `quantity`, the facility behind it, the counts. */
export function describeBar(
  group: Group,
  quantity: Quantity,
  digits: number,
  pathway: Pathway = "outdoor",
): BarDetail {
  const facilities = `${group.facilities} ${group.facilities === 1 ? "facility" : "facilities"}`;
  const screened = group.screenedOut > 0 ? `, ${group.screenedOut} screened out` : "";
  const best = group[quantity];
  const label = `Highest ${QUANTITY_NAME[quantity]}`;
  return {
    group: group.label,
    lines: [
      best
        ? { label, value: formatNumber(best.value, digits), detail: facilityText(best, pathway, digits) }
        : { label, value: NOT_REPORTED, detail: null },
    ],
    counts: `${facilities} in this group · ${group.assessed} assessed${screened}`,
  };
}
