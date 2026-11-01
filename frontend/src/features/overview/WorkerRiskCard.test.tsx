import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_WORKSPACE } from "../../hooks/useWorkspaceStore";
import type { WorkerExtremum, WorkerRiskSummary } from "../../types/workspace";
import { WorkerRiskCard } from "./WorkerRiskCard";

const at = (value: number, name: string, tier: WorkerExtremum["risk_tier"] = "elevated"): WorkerExtremum => ({
  value,
  frs_id: name,
  facility_name: `Plant ${name}`,
  risk_tier: tier,
});

describe("WorkerRiskCard", () => {
  it("names the facility with the highest worker value, for both tiers", () => {
    const risk: WorkerRiskSummary = {
      baseline: { oel_ratio: at(3, "B", "exceedance"), hq: at(0.2, "A"), cancer_risk: null },
      worst_case: { oel_ratio: at(9, "B", "exceedance"), hq: at(0.7, "A"), cancer_risk: null },
      reason: null,
    };
    render(<WorkerRiskCard risk={risk} digits={2} />);
    expect(screen.getByText("Plant B")).toBeInTheDocument();
    expect(screen.getByText("Plant A")).toBeInTheDocument();
    expect(screen.getByText("Exceedance")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("says why nothing is shown, never a zero", () => {
    render(<WorkerRiskCard risk={EMPTY_WORKSPACE.worker_risk} digits={2} />);
    expect(screen.getByText(/Not shown: not yet computed/)).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.getAllByText("Not computed").length).toBe(3);
  });
});
