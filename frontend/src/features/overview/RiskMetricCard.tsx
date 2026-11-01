import { StatusPill } from "../../components/ui/StatusPill";
import { formatNumber } from "../../lib/format";
import type { Extremum, RiskSummary } from "../../types/workspace";
import { CardFrame, Metric } from "./Metric";

function where(extremum: Extremum | null): string | null {
  if (!extremum) return null;
  const name = extremum.facility_name ?? `FRS ${extremum.frs_id}`;
  return `${name} · stack ${extremum.stack_number}`;
}

function Row({
  title,
  worst,
  representative,
  digits,
}: {
  title: string;
  worst: Extremum | null;
  representative: Extremum | null;
  digits: number;
}) {
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <StatusPill status={worst?.status ?? null} />
      </div>
      <dl className="m-0 grid grid-cols-2 gap-2">
        <Metric label="Worst case" large>
          {formatNumber(worst?.value, digits)}
        </Metric>
        <Metric label="Representative weather">{formatNumber(representative?.value, digits)}</Metric>
      </dl>
      {worst && <p className="m-0 truncate text-xs text-fg2">{where(worst)}</p>}
    </div>
  );
}

/** Highest hazard quotient and lifetime cancer risk, each with its status in words. */
export function RiskMetricCard({ risk, digits }: { risk: RiskSummary; digits: number }) {
  return (
    <CardFrame title="Hazard quotient & cancer risk">
      <Row
        title="Hazard quotient (unitless)"
        worst={risk.hq_worst}
        representative={risk.hq_representative}
        digits={digits}
      />
      <Row
        title="Lifetime cancer risk (unitless)"
        worst={risk.cancer_risk_worst}
        representative={risk.cancer_risk_representative}
        digits={digits}
      />
      {risk.reason && !risk.hq_worst && !risk.cancer_risk_worst && (
        <p className="m-0 text-xs text-fg2">Not shown: {risk.reason}.</p>
      )}
    </CardFrame>
  );
}
