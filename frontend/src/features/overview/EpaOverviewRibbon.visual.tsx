import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import { EMPTY_WORKSPACE } from "../../hooks/useWorkspaceStore";
import { extremum, workspace } from "../../test/fixtures";
import { EpaOverviewRibbon } from "./EpaOverviewRibbon";

afterEach(cleanup);

/** The overview panel's well: a container-query root, as `OverviewPanel` provides. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="frame"
      style={{ width: 1120, height: 860, padding: 16, display: "flex", flexDirection: "column", containerType: "inline-size", background: "var(--bg)", color: "var(--fg)" }}
    >
      {children}
    </div>
  );
}

const frame = () => page.getByTestId("frame");
/** Light and dark run as two projects; each keeps its own references. */
const shot = (name: string) => `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

/** Synthetic round numbers, never real measurements. */
const READY = workspace({
  risk: {
    ...EMPTY_WORKSPACE.risk,
    hq_worst: extremum(2.5, "high", 3),
    hq_representative: extremum(0.4, "low"),
    cancer_risk_worst: extremum(0.000012, "moderate"),
    reason: null,
  },
  worker_risk: {
    baseline: {
      oel_ratio: { value: 0.4, frs_id: "W1", facility_name: "Plant W1", risk_tier: "moderate", evidence: "monitoring", driving_activity: null },
      hq: { value: 0.2, frs_id: "F1", facility_name: "Plant F1", risk_tier: "low", evidence: "activity_model", driving_activity: "Drum loading" },
      cancer_risk: null,
    },
    worst_case: {
      oel_ratio: { value: 1.2, frs_id: "W1", facility_name: "Plant W1", risk_tier: "high", evidence: "monitoring", driving_activity: null },
      hq: { value: 0.6, frs_id: "F1", facility_name: "Plant F1", risk_tier: "moderate", evidence: "activity_model", driving_activity: "Drum loading" },
      cancer_risk: null,
    },
    reason: null,
  },
  chemical: {
    ...EMPTY_WORKSPACE.chemical,
    cas_number: "1-1-1",
    name: "Testane",
    molecular_weight_g_mol: 50,
    rfc_mg_m3: 0.5,
    sources: { rfc: "IRIS" },
  },
});

describe("overview ribbon, in a real browser", () => {
  it("says what is not computed yet, with reasons, before any tool ran", async () => {
    render(
      <Frame>
        <EpaOverviewRibbon workspace={EMPTY_WORKSPACE} digits={2} />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("ribbon-empty"));
  });

  it("shows risk status in words and colour, units on every value, absent ones as not reported", async () => {
    render(
      <Frame>
        <EpaOverviewRibbon workspace={READY} digits={2} />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("ribbon-ready"));
  });
});
