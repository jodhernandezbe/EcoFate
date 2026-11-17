import { describe, expect, it } from "vitest";

import { facility, worker } from "../test/fixtures";
import { PATHWAYS, pathwayInfo } from "./pathways";

describe("PATHWAYS", () => {
  it("lists the outdoor pathway first with the API's pathway keys", () => {
    expect(PATHWAYS.map((p) => [p.key, p.pathwayKey])).toEqual([
      ["outdoor", "community_inhalation"],
      ["indoor", "worker_inhalation"],
    ]);
    expect(PATHWAYS.map((p) => p.label)).toEqual([
      "Outdoor Air → Inhalation → General Population",
      "Indoor Air → Inhalation → Worker",
    ]);
  });

  it("reads the community status outdoors and the worker tier indoors", () => {
    const f = facility({ status: "low", occupational_exposure: worker({ risk_tier: "high" }) });
    expect(pathwayInfo("outdoor").band(f)).toBe("low");
    expect(pathwayInfo("indoor").band(f)).toBe("high");
  });

  it("gives no band when the pathway has no result, or one this build does not know", () => {
    expect(pathwayInfo("outdoor").band(facility({ status: null }))).toBeNull();
    expect(pathwayInfo("indoor").band(facility())).toBeNull();
    expect(pathwayInfo("outdoor").band(facility({ status: "exceedance" as never }))).toBeNull();
  });
});
