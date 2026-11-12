import { TierPill } from "../../components/ui/TierPill";
import { formatNumber, NOT_REPORTED } from "../../lib/format";
import { evidenceText } from "../../lib/worker";
import type { WorkerExtremum, WorkerRiskSummary } from "../../types/workspace";
import { CardFrame, Metric } from "./Metric";

function where(extremum: WorkerExtremum): string {
  return extremum.facility_name ?? `FRS ${extremum.frs_id}`;
}

/** The facility, its band in words and the evidence a highest figure comes from. */
function Source({ extremum }: { extremum: WorkerExtremum }) {
  const evidence = evidenceText({ evidence: extremum.evidence, drivingLabel: extremum.driving_activity });
  return (
    <div className="grid min-w-0 justify-items-start gap-0.5">
      <TierPill tier={extremum.risk_tier} />
      <p className="m-0 truncate text-xs text-fg2">{where(extremum)}</p>
      <p className="m-0 truncate text-xs text-fg2">{evidence ?? "Evidence not reported"}</p>
    </div>
  );
}

function Figure({ label, extremum, digits, large }: { label: string; extremum: WorkerExtremum | null; digits: number; large?: boolean }) {
  return (
    <div className="grid min-w-0 content-start gap-1">
      <dl className="m-0">
        <Metric label={label} large={large}>
          {formatNumber(extremum?.value, digits)}
        </Metric>
      </dl>
      {extremum && <Source extremum={extremum} />}
    </div>
  );
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
      <span className="text-sm font-semibold">{title}</span>
      <div className="grid grid-cols-2 gap-2">
        <Figure label="Baseline" extremum={baseline} digits={digits} large />
        <Figure label="Worst case" extremum={worst} digits={digits} />
      </div>
    </div>
  );
}

/** The workers' highest limit ratio, hazard quotient and cancer risk over the assessed facilities. */
export function WorkerRiskCard({ risk, digits }: { risk: WorkerRiskSummary; digits: number }) {
  const { baseline, worst_case: worst } = risk;
  const none = [baseline, worst].every((tier) => !tier.oel_ratio && !tier.hq && !tier.cancer_risk);
  return (
    <CardFrame title="Worker exposure">
      <Row title="8-hr TWA / occupational limit (unitless)" baseline={baseline.oel_ratio} worst={worst.oel_ratio} digits={digits} />
      <Row title="Worker hazard quotient (unitless)" baseline={baseline.hq} worst={worst.hq} digits={digits} />
      <Row title="Worker lifetime cancer risk (unitless)" baseline={baseline.cancer_risk} worst={worst.cancer_risk} digits={digits} />
      {none && <p className="m-0 text-xs text-fg2">{risk.reason ?? NOT_REPORTED}</p>}
    </CardFrame>
  );
}
