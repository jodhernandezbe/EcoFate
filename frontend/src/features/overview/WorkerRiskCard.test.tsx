import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_WORKSPACE } from "../../hooks/useWorkspaceStore";
import type { WorkerExtremum, WorkerRiskSummary } from "../../types/workspace";
import { WorkerRiskCard } from "./WorkerRiskCard";

const at = (
  value: number,
  name: string,
  tier: WorkerExtremum["risk_tier"] = "moderate",
  evidence: WorkerExtremum["evidence"] = "activity_model",
): WorkerExtremum => ({
  value,
  frs_id: name,
  facility_name: `Plant ${name}`,
  risk_tier: tier,
  evidence,
  driving_activity: evidence === "activity_model" ? "Drum loading" : null,
});

describe("WorkerRiskCard", () => {
  it("names the facility, band and evidence of the highest value, for both cases", () => {
    const risk: WorkerRiskSummary = {
      baseline: { oel_ratio: at(3, "B", "high", "monitoring"), hq: at(0.2, "A"), cancer_risk: null },
      worst_case: { oel_ratio: at(9, "B", "high", "monitoring"), hq: at(0.7, "A"), cancer_risk: null },
      reason: null,
    };
    render(<WorkerRiskCard risk={risk} digits={2} />);
    expect(screen.getAllByText("Plant B")).toHaveLength(2);
    expect(screen.getAllByText("Plant A")).toHaveLength(2);
    expect(screen.getAllByText("High")).toHaveLength(2);
    expect(screen.getAllByText("OSHA monitoring")).toHaveLength(2);
    expect(screen.getAllByText("Drum loading")).toHaveLength(2);
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("says not reported with the reason, never a zero", () => {
    render(<WorkerRiskCard risk={EMPTY_WORKSPACE.worker_risk} digits={2} />);
    expect(screen.getByText("not yet computed")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.getAllByText("not reported")).toHaveLength(6);
    expect(screen.queryByText("Not computed")).toBeNull();
  });

  it("says the evidence is not reported when the API named none", () => {
    const risk: WorkerRiskSummary = {
      baseline: { oel_ratio: at(3, "B", "low", null), hq: null, cancer_risk: null },
      worst_case: { oel_ratio: null, hq: null, cancer_risk: null },
      reason: null,
    };
    render(<WorkerRiskCard risk={risk} digits={2} />);
    expect(screen.getByText("Evidence not reported")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
  });
});
