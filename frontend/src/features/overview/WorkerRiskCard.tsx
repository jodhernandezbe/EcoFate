import { TierPill } from "../../components/ui/TierPill";
import { formatNumber } from "../../lib/format";
import type { WorkerExtremum, WorkerRiskSummary } from "../../types/workspace";
import { CardFrame, Metric } from "./Metric";

function where(extremum: WorkerExtremum | null): string | null {
  if (!extremum) return null;
  return extremum.facility_name ?? `FRS ${extremum.frs_id}`;
}

function Row({
  title,
  baseline,
  worst,
  digits,
}: {
  title: string;
  baseline: WorkerExtremum | null;
  worst: WorkerExtremum | null;
  digits: number;
}) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <TierPill tier={baseline?.risk_tier ?? null} />
      </div>
      <dl className="m-0 grid grid-cols-2 gap-2">
        <Metric label="Baseline ventilation" large>
          {formatNumber(baseline?.value, digits)}
        </Metric>
        <Metric label="Enclosed zone, worst case">{formatNumber(worst?.value, digits)}</Metric>
      </dl>
      {baseline && <p className="m-0 truncate text-xs text-fg2">{where(baseline)}</p>}
    </div>
  );
}

/** The workers' highest limit ratio, hazard quotient and cancer risk over the assessed facilities. */
export function WorkerRiskCard({ risk, digits }: { risk: WorkerRiskSummary; digits: number }) {
  const { baseline, worst_case: worst } = risk;
  return (
    <CardFrame title="Worker exposure (box model)">
      <Row title="8-hr TWA / occupational limit (unitless)" baseline={baseline.oel_ratio} worst={worst.oel_ratio} digits={digits} />
      <Row title="Worker hazard quotient (unitless)" baseline={baseline.hq} worst={worst.hq} digits={digits} />
      <Row title="Worker lifetime cancer risk (unitless)" baseline={baseline.cancer_risk} worst={worst.cancer_risk} digits={digits} />
      {risk.reason && !baseline.oel_ratio && !baseline.hq && !baseline.cancer_risk && (
        <p className="m-0 text-xs text-fg2">Not shown: {risk.reason}.</p>
      )}
    </CardFrame>
  );
}
