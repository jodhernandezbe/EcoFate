import { formatReported, formatWithUnit, NOT_REPORTED, orNotReported } from "../../lib/format";
import { estimatorText } from "../../lib/worker";
import type { MonitoringSummary, StageRoute, WorkerActivity } from "../../types/workspace";
import { Metric } from "../overview/Metric";
import { FoldSection } from "./FoldSection";

const years = (first: number | null, last: number | null): string => {
  if (first === null && last === null) return formatReported(null);
  return first === last || last === null || first === null ? String(first ?? last) : `${first}–${last}`;
};

/** What OSHA's measured samples say for the industry; a median below detection says why. */
export function MonitoringBlock({ monitoring, digits }: { monitoring: MonitoringSummary; digits: number }) {
  const median =
    monitoring.median_mg_m3 === null
      ? `below detection${monitoring.reason ? ` (${monitoring.reason})` : ""}`
      : formatWithUnit(monitoring.median_mg_m3, "mg/m³", digits);
  return (
    <div aria-label="OSHA monitoring" role="group" className="mt-1 rounded-lg bg-fg2/5 p-2">
      <p className="m-0 mb-1 text-xs font-semibold">OSHA monitoring</p>
      <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
        <Metric label="Industry level">{orNotReported(monitoring.naics_level)}</Metric>
        <Metric label="Samples">{formatReported(monitoring.n_values)}</Metric>
        <Metric label="Non-detects">{formatReported(monitoring.n_nondetect)}</Metric>
        <Metric label="Years">{years(monitoring.first_year, monitoring.last_year)}</Metric>
        <Metric label="Median">{median}</Metric>
        <Metric label="95th percentile">{formatWithUnit(monitoring.p95_mg_m3, "mg/m³", digits)}</Metric>
      </dl>
      <p className="m-0 mt-1 text-[11px] text-fg2">{monitoring.source}</p>
      {[monitoring.level_note, monitoring.unit_note, ...monitoring.statements].map((note) =>
        note ? (
          <p key={note} className="m-0 mt-0.5 text-[11px] text-fg2">
            {note}
          </p>
        ) : null,
      )}
    </div>
  );
}

function ActivityRow({ activity, drives, digits }: { activity: WorkerActivity; drives: boolean; digits: number }) {
  const { typical, worst_case: worst } = activity;
  return (
    <li className="rounded-lg bg-fg2/5 p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">{activity.label}</span>
        {drives && <span className="text-[11px] font-medium text-accent">Drives the worst case</span>}
      </div>
      <p className="m-0 mb-1 text-[11px] text-fg2">
        {activity.setting} · {formatReported(activity.hours)} h/day · {estimatorText(typical.estimator)} typical,{" "}
        {estimatorText(worst.estimator)} worst case
      </p>
      <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
        <Metric label="8-hr average, typical">{formatWithUnit(typical.twa_mg_m3, "mg/m³", digits)}</Metric>
        <Metric label="8-hr average, worst case">{formatWithUnit(worst.twa_mg_m3, "mg/m³", digits)}</Metric>
      </dl>
      {activity.statement && <p className="m-0 mt-1 text-[11px] text-fg2">{activity.statement}</p>}
      {activity.warnings.map((warning) => (
        <p key={warning} className="m-0 mt-0.5 text-[11px] text-fg2">
          {warning}
        </p>
      ))}
    </li>
  );
}

/** Every evaluated activity, the one that drives the worst case marked; else why there are none. */
export function ActivityList({
  activities,
  drivingKey,
  reason,
  digits,
}: {
  activities: WorkerActivity[];
  drivingKey: string | null;
  reason: string | null;
  digits: number;
}) {
  if (activities.length === 0) {
    return <p className="m-0 mt-1 text-xs text-fg2">Activities: {orNotReported(reason)}</p>;
  }
  return (
    <ul aria-label="Evaluated activities" className="m-0 mt-1 grid list-none gap-1.5 p-0">
      {activities.map((activity) => (
        <ActivityRow key={activity.key} activity={activity} drives={activity.key === drivingKey} digits={digits} />
      ))}
    </ul>
  );
}

/** How each life cycle stage's activities were chosen: the generic operations and the documents. */
export function RoutesList({ routes }: { routes: StageRoute[] }) {
  if (routes.length === 0) return null;
  return (
    <FoldSection title="How the activities were chosen" aside={<span className="text-xs text-fg2">{routes.length}</span>} initiallyOpen={false}>
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {routes.map((route) => (
          <li key={route.stage} className="rounded-lg bg-fg2/5 p-2 text-xs">
            <p className="m-0 font-medium">{route.stage}</p>
            <p className="m-0 text-fg2">Generic operations: {route.generic_operation.join(", ") || NOT_REPORTED}</p>
            {route.scenarios.map((scenario) => (
              <p key={`${scenario.title}-${scenario.pages}`} className="m-0 text-[11px] text-fg2">
                {scenario.title} ({scenario.category}) · {scenario.source}, {scenario.pages}
              </p>
            ))}
            {route.note && <p className="m-0 text-[11px] text-fg2">{route.note}</p>}
          </li>
        ))}
      </ul>
    </FoldSection>
  );
}
