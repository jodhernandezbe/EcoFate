import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { scenario } from "../../test/fixtures";
import type { ScenarioFactor, ScenarioReceptor } from "../../types/workspace";
import { ScenarioView } from "./ScenarioView";

const factor = (over: Partial<ScenarioFactor>): ScenarioFactor => ({
  key: "k",
  group: "source",
  label: "Stack height",
  value: 30,
  unit: "m",
  source: null,
  reason: null,
  ...over,
});

const tract: ScenarioReceptor = {
  kind: "tract",
  label: "99001000100",
  residents: 500,
  age_distribution: { "0-4": 10, "65+": 90 },
  distance_m: 480,
  bearing_deg: 90,
  latitude: 10,
  longitude: -20,
  concentration: 0.9,
  fraction_of_maximum: 1,
  note: null,
};

describe("ScenarioView", () => {
  it("shows the value, the level and the factors by group", () => {
    render(
      <ScenarioView
        scenario={scenario({
          value: 2,
          factors: [factor({}), factor({ key: "w", group: "conditions", label: "Wind speed at 10 m", value: 3, unit: "m/s" })],
        })}
        digits={3}
      />,
    );
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Source" })).getByText("30 m")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Conditions" })).getByText("3 m/s")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Release" })).toBeNull();
  });

  it("says why a factor is absent instead of showing zero", () => {
    render(
      <ScenarioView
        scenario={scenario({ factors: [factor({ value: null, unit: "", reason: "the stack has no value for this" })] })}
        digits={3}
      />,
    );
    expect(screen.getByText("not reported")).toBeInTheDocument();
    expect(screen.getByText("the stack has no value for this")).toBeInTheDocument();
  });

  it("lists the tracts with distance, bearing and age mix", () => {
    render(<ScenarioView scenario={scenario({ receptors: [tract] })} digits={3} />);
    const receptors = screen.getByRole("region", { name: "Most affected receptors" });
    expect(within(receptors).getByText("Tract 99001000100")).toBeInTheDocument();
    expect(within(receptors).getByText(/480 m at 90° from the facility/)).toBeInTheDocument();
    expect(within(receptors).getByText("0-4 10% · 65+ 90%")).toBeInTheDocument();
  });

  it("gives the reason there are no receptors", () => {
    render(
      <ScenarioView
        scenario={scenario({ receptors: [], receptors_note: "no resident lives where the maximum falls" })}
        digits={3}
      />,
    );
    expect(screen.getByText("no resident lives where the maximum falls")).toBeInTheDocument();
  });

  it("shows workers without distances", () => {
    const workers: ScenarioReceptor = { ...tract, kind: "workers", label: "Workers", residents: null, note: "16 h/day, 250 days/yr" };
    render(<ScenarioView scenario={scenario({ receptors: [workers] })} digits={3} />);
    expect(screen.getByText("Workers")).toBeInTheDocument();
    expect(screen.queryByText(/from the facility/)).toBeNull();
  });

  it("says not reported for a level from an old saved workspace", () => {
    render(<ScenarioView scenario={scenario({ tier: "at or above threshold" })} digits={3} />);
    expect(screen.getByText("not reported")).toBeInTheDocument();
  });

  it("says no level was reported rather than inventing one", () => {
    render(<ScenarioView scenario={scenario({ tier: null, benchmark: null })} digits={3} />);
    expect(screen.getByText("no level reported")).toBeInTheDocument();
  });
});
