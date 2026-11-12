import { describe, expect, it } from "vitest";

import { estimatorText, evidenceText, volatilityText } from "./worker";

describe("evidenceText", () => {
  it("names OSHA monitoring, never an activity, for measured samples", () => {
    expect(evidenceText({ evidence: "monitoring", drivingLabel: "Drum loading" })).toBe("OSHA monitoring");
  });

  it("names the driving activity for the activity model", () => {
    expect(evidenceText({ evidence: "activity_model", drivingLabel: "Drum loading" })).toBe("Drum loading");
    expect(evidenceText({ evidence: "activity_model", drivingLabel: null })).toBe("Activity model");
  });

  it("is absent when the API named no evidence", () => {
    expect(evidenceText({ evidence: null, drivingLabel: null })).toBeNull();
  });
});

describe("estimatorText and volatilityText", () => {
  it("write the API's keys in words and keep an unknown estimator as sent", () => {
    expect(estimatorText("two_zone")).toBe("Two-zone model");
    expect(estimatorText("something_new")).toBe("something_new");
    expect(estimatorText(null)).toBeNull();
    expect(volatilityText("within")).toBe("within the vapor-model range");
    expect(volatilityText(null)).toBeNull();
    expect(volatilityText("sideways")).toBeNull();
  });
});

describe("unknown words from the API", () => {
  it("never return a built-in property for a key such as constructor", () => {
    expect(estimatorText("constructor")).toBe("constructor");
    expect(volatilityText("constructor")).toBeNull();
    expect(volatilityText("toString")).toBeNull();
  });
});
