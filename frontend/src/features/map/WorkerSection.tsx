import { TierPill } from "../../components/ui/TierPill";
import {
  formatNumber,
  formatReported,
  formatSchedule,
  formatWithUnit,
  orNotReported,
} from "../../lib/format";
import { evidenceText, volatilityText } from "../../lib/worker";
import type { Facility, OccupationalExposure, WorkerCase } from "../../types/workspace";
import { Metric } from "../overview/Metric";
import { ActivityList, MonitoringBlock, RoutesList } from "./WorkerDetail";

function CaseRow({ title, result, digits }: { title: string; result: WorkerCase; digits: number }) {
  return (
    <section aria-label={title} className="rounded-lg bg-fg2/5 p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h5 className="m-0 text-xs font-semibold">{title}</h5>
        <TierPill tier={result.risk_tier} />
      </div>
      <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
        <Metric label="8-hr TWA">{formatWithUnit(result.twa_mg_m3, "mg/m³", digits)}</Metric>
        <Metric label="TWA / limit (R_OEL)">{formatNumber(result.oel_ratio, digits)}</Metric>
        <Metric label="Worker HQ">{formatNumber(result.hq, digits)}</Metric>
        <Metric label="Worker cancer risk">{formatNumber(result.cancer_risk, digits)}</Metric>
      </dl>
    </section>
  );
}

function Evidence({ worker }: { worker: OccupationalExposure }) {
  const text = evidenceText({ evidence: worker.evidence, drivingLabel: worker.driving_activity?.label ?? null });
  return (
    <p className="m-0 mb-1 text-xs">
      <span className="text-fg2">Evidence: </span>
      <span className="font-medium">{text ?? orNotReported(worker.activity_reason)}</span>
    </p>
  );
}

function Chemistry({ worker, digits }: { worker: OccupationalExposure; digits: number }) {
  const range = volatilityText(worker.volatility);
  const source = worker.vapor_pressure_source ? ` · ${worker.vapor_pressure_source}` : "";
  const pressure = formatWithUnit(worker.vapor_pressure_mmhg, "mmHg", digits);
  return (
    <dl className="m-0 mb-1 grid grid-cols-2 gap-x-3 gap-y-1">
      <Metric label={`Vapor pressure${source}`}>
        {range && worker.vapor_pressure_mmhg !== null ? `${pressure}, ${range}` : pressure}
      </Metric>
      <Metric label="Occupational limit (TWA)">{formatWithUnit(worker.oel_twa_mg_m3, "mg/m³", digits)}</Metric>
      <Metric label="Limit source">{orNotReported(worker.oel_source)}</Metric>
    </dl>
  );
}

function Context({ worker, digits }: { worker: OccupationalExposure; digits: number }) {
  const year = worker.fugitive_reporting_year === null ? "" : ` (${worker.fugitive_reporting_year})`;
  return (
    <div className="mt-1.5">
      <dl className="m-0">
        <Metric label={`Fugitive release, context only${year}`}>
          {formatWithUnit(worker.fugitive_release_kg_per_year, "kg/yr", digits)}
        </Metric>
      </dl>
      {worker.fugitive_statement && <p className="m-0 text-[11px] text-fg2">{worker.fugitive_statement}</p>}
    </div>
  );
}

function Notes({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="m-0 mt-1 grid list-none gap-0.5 p-0 text-xs text-fg2">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function Profile({ facility }: { facility: Facility }) {
  const { operational_profile: profile, occupational_exposure: worker } = facility;
  const schedule = profile ?? {
    operating_days_per_year: worker?.operating_days_per_year ?? null,
    hours_per_day: worker?.hours_per_day ?? null,
    annual_operating_hours: null,
  };
  const sector = profile?.cdr_sector;
  const stage = profile?.life_cycle_stage.join(", ");
  const use = profile?.cou_category.join(", ");
  return (
    <div className="mb-1 grid gap-0.5 text-xs text-fg2">
      <p className="m-0">
        Operating schedule: {formatSchedule(schedule)}
        {sector ? ` · CDR ${sector.code}, ${sector.name}` : ""}
      </p>
      {stage && <p className="m-0">Life cycle stage: {stage}</p>}
      {use && <p className="m-0">Condition of use: {use}</p>}
    </div>
  );
}

/** The worker screening of one facility: the evidence, the activities and the two cases. */
export function WorkerSection({ facility, digits }: { facility: Facility; digits: number }) {
  const worker = facility.occupational_exposure;
  if (worker === null) {
    return (
      <>
        <Profile facility={facility} />
        <p className="m-0 text-xs text-fg2">Worker exposure: {formatReported(null)}.</p>
      </>
    );
  }
  return (
    <>
      <Evidence worker={worker} />
      <Profile facility={facility} />
      <Chemistry worker={worker} digits={digits} />
      {worker.monitoring ? (
        <MonitoringBlock monitoring={worker.monitoring} digits={digits} />
      ) : (
        <p className="m-0 text-xs text-fg2">OSHA monitoring: {orNotReported(worker.monitoring_reason)}</p>
      )}
      <ActivityList
        activities={worker.activities}
        drivingKey={worker.driving_activity?.key ?? null}
        reason={worker.activity_reason}
        digits={digits}
      />
      <div className="mt-1.5 grid gap-1.5">
        <CaseRow title="Baseline" result={worker.baseline} digits={digits} />
        <CaseRow title="Worst case" result={worker.worst_case} digits={digits} />
      </div>
      <RoutesList routes={worker.routes} />
      <Context worker={worker} digits={digits} />
      <Notes items={worker.assumptions} />
      <Notes items={worker.warnings} />
    </>
  );
}
