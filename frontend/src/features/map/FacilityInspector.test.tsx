import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { FakeMap } from "../../test/fakeMaplibre";
import {
  facility,
  monitoredWorker,
  monitoring,
  profile,
  scenario,
  worker,
  workerOnly,
  workspace,
} from "../../test/fixtures";
import type { Facility, Stack } from "../../types/workspace";
import { ExposureMapCanvas } from "./ExposureMapCanvas";

const config = {
  light_style: "https://example.test/light.json",
  dark_style: "https://example.test/dark.json",
  marker_min_px: 6,
  marker_max_px: 22,
  initial_view: { west: -125, south: 24.5, east: -66.9, north: 49.5 },
};

const stack = (over: Partial<Stack> = {}): Stack => ({
  stack_number: null,
  height_m: 10,
  diameter_m: 1,
  exit_velocity_m_s: 2,
  exit_temperature_k: 300,
  source: "NEI",
  tier: 1,
  tier_label: "Tier 1: Empirical NEI",
  scc: null,
  scc_description: null,
  scc_score: null,
  worst_case: null,
  representative: null,
  dose: null,
  warnings: [],
  ...over,
});

const extreme = (low: number, high: number) => ({ low, high, low_stack: 1, high_stack: 3 });

function show(...facilities: Facility[]) {
  FakeMap.reset();
  return render(
    <ExposureMapCanvas
      digits={2}
      workspace={workspace({ framing_version: 1, facilities })}
      config={config}
    />,
  );
}

const marker = (name: RegExp) => screen.getByRole("button", { name });

describe("markers", () => {
  it("are reachable by keyboard and announce the facility name", () => {
    show(facility({ name: "Plant F1", status: "high" }));
    expect(marker(/Plant F1, high/)).toBeInTheDocument();
  });

  it("say when no risk is computed", () => {
    show(facility({ name: "Plant F1" }));
    expect(marker(/Plant F1, risk not computed/)).toBeInTheDocument();
  });
});

describe("opening and closing", () => {
  it("opens for keyboard focus and closes on Escape", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.tab();
    expect(marker(/Plant F1/)).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Plant F1");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("opens on hover and closes when the pointer leaves", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.hover(marker(/Plant F1/));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.unhover(marker(/Plant F1/));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("closes on blur", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.tab();
    await user.tab();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("is described by the card while open", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.tab();
    const id = screen.getByRole("tooltip").id;
    expect(marker(/Plant F1/)).toHaveAttribute("aria-describedby", id);
  });

  it("shows only the facility that is hovered", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "A", name: "Alpha", longitude: -20 }), facility({ frs_id: "B", name: "Beta", longitude: -10 }));
    await user.hover(marker(/Beta/));
    expect(screen.getAllByRole("tooltip")).toHaveLength(1);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Beta");
  });
});

describe("pinned card", () => {
  const stacks = [stack({ stack_number: 1 }), stack({ stack_number: 2 }), stack({ stack_number: 3 })];

  it("stays open after the pointer leaves once the marker is clicked, and closes by its control", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "F1", name: "Plant F1" }));
    await user.click(marker(/Plant F1/));
    expect(screen.getByRole("dialog", { name: "Plant F1" })).toBeInTheDocument();
    await user.unhover(marker(/Plant F1/));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(marker(/Plant F1/)).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Close facility details" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes with Escape and with a click on the map", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "F1", name: "Plant F1" }));
    await user.click(marker(/Plant F1/));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(marker(/Plant F1/));
    act(() => FakeMap.last.emit("click"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not switch to a hovered facility while another is pinned", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "F1", name: "Alpha" }), facility({ frs_id: "F2", name: "Beta", latitude: 11 }));
    await user.click(marker(/Alpha/));
    await user.hover(marker(/Beta/));
    expect(screen.getByRole("dialog", { name: "Alpha" })).toBeInTheDocument();
    await user.click(marker(/Beta/));
    expect(screen.getByRole("dialog", { name: "Beta" })).toBeInTheDocument();
  });

  it("folds the stacks when there are many, and each section toggles", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "F1", name: "Plant F1", stacks }));
    await user.click(marker(/Plant F1/));
    const toggle = screen.getByRole("button", { name: "Stacks" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("stack 3")).not.toBeVisible();
    await user.click(toggle);
    expect(screen.getByText("stack 3")).toBeVisible();
    const risk = screen.getByRole("button", { name: "Receptor risk" });
    expect(risk).toHaveAttribute("aria-expanded", "true");
    await user.click(risk);
    expect(risk).toHaveAttribute("aria-expanded", "false");
  });

  it("shows two stacks unfolded", async () => {
    const user = userEvent.setup();
    show(facility({ frs_id: "F1", name: "Plant F1", stacks: stacks.slice(0, 2) }));
    await user.hover(marker(/Plant F1/));
    expect(screen.getByRole("button", { name: "Stacks" })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("card content", () => {
  it("shows the identifiers, industry, release and schedule", async () => {
    const user = userEvent.setup();
    show(
      facility({
        industry: { naics_code: "111111", naics_title: "Synthetic industry", code_origin: "reported", source: "s" },
      }),
    );
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("FRS F1");
    expect(card).toHaveTextContent("TRI doc. control no. DOC1");
    expect(card).toHaveTextContent("NAICS 111111 · Synthetic industry");
    expect(card).toHaveTextContent("100 Pounds/yr");
    expect(card).toHaveTextContent("1 g/s");
    expect(card).toHaveTextContent("8760 h/yr");
    expect(card).toHaveTextContent("1-1-1");
  });

  it("lists every stack with its tier pill", async () => {
    const user = userEvent.setup();
    show(facility({ stacks: [stack({ height_m: 5 }), stack({ height_m: 10 }), stack({ height_m: 15 })] }));
    await user.tab();
    expect(screen.getAllByText("Tier 1: Empirical NEI")).toHaveLength(3);
    expect(screen.getByText("5 m")).toBeInTheDocument();
    expect(screen.getByText("15 m")).toBeInTheDocument();
  });

  it("shows absent values as not reported", async () => {
    const user = userEvent.setup();
    show(facility({ stacks: [stack({ exit_temperature_k: null, tier: null, tier_label: null })] }));
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("Exit temperaturenot reported");
    expect(card).toHaveTextContent("No source reported");
    expect(card).toHaveTextContent("NAICS not reported · not reported");
  });

  it("says a facility without stacks was not assessed yet, rather than that data is missing", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.tab();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Not assessed yet");
  });

  it("says a facility screened out on the bound needs no stacks, with its value and reason", async () => {
    const user = userEvent.setup();
    const reason = "screened out: the bound is below HQ 0.1";
    show(
      facility({
        status: "low",
        screening: {
          outcome: "screened_out_at_bound",
          bound_hq: 0.05,
          bound_cancer_risk: null,
          value_hq: 0.05,
          value_cancer_risk: null,
          reason,
        },
      }),
    );
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("None needed: screened out on a conservative bound");
    expect(card).toHaveTextContent("Screened out on the bound (HQ 0.05)");
    expect(card).toHaveTextContent(reason);
  });

  it("says when only the worst case was computed", async () => {
    const user = userEvent.setup();
    show(
      facility({
        stacks: [stack()],
        screening: {
          outcome: "worst_case_only",
          bound_hq: 2,
          bound_cancer_risk: null,
          value_hq: null,
          value_cancer_risk: null,
          reason: null,
        },
      }),
    );
    await user.tab();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Worst case only, with this facility's own stacks");
  });

  it("shows the SCC and its description for a PSTK stack", async () => {
    const user = userEvent.setup();
    show(facility({ stacks: [stack({ tier_label: "Tier 2: PSTK by SCC", scc: "30600101", scc_description: "Synthetic process", scc_score: 0.5 })] }));
    await user.tab();
    expect(screen.getByRole("tooltip")).toHaveTextContent("SCC 30600101 · Synthetic process (score 0.5)");
  });

  it("shows the risk ranges across the stacks and the population", async () => {
    const user = userEvent.setup();
    show(
      facility({
        status: "high",
        receptors: { total_population: 1234, radius_km: 3, age_distribution: {}, source: "s", screening_default: false, warnings: [] },
        exposure: {
          stacks_given: 3,
          stacks_evaluated: 3,
          hq_worst: extreme(0.2, 2.5),
          hq_representative: extreme(0.1, 0.5),
          cancer_risk_worst: extreme(0.000001, 0.00002),
          cancer_risk_representative: null,
          concentration_worst: extreme(4, 8),
          concentration_representative: null,
          dose: null,
          warnings: [],
        },
      }),
    );
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("HQ, worst case0.2 – 2.5");
    expect(card).toHaveTextContent("HQ, representative0.1 – 0.5");
    expect(card).toHaveTextContent("1 × 10⁻⁶ – 2 × 10⁻⁵");
    expect(card).toHaveTextContent("4 – 8 µg/m³");
    expect(card).toHaveTextContent("Residents within 3 km1,234");
    expect(card).toHaveTextContent("High");
  });

  it("says risk is not reported before an exposure is computed", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent("HQ, worst casenot reported");
    expect(card).toHaveTextContent("Not computed");
    expect(card).toHaveTextContent("Not assessed yet: the batch assessment has not covered this facility.");
    expect(card).not.toHaveTextContent("no stack parameters were obtained");
  });

  it("gives the real reason when the batch did not assess the facility", async () => {
    const user = userEvent.setup();
    const reason = "more than 5000 facilities reach a threshold; refining them all was not attempted";
    show(
      facility({
        screening: {
          outcome: "not_assessed",
          bound_hq: null,
          bound_cancer_risk: null,
          value_hq: null,
          value_cancer_risk: null,
          reason,
        },
      }),
    );
    await user.tab();
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent(`Not assessed: ${reason}`);
    expect(card).not.toHaveTextContent("Screened out");
    expect(card).not.toHaveTextContent("Not assessed yet");
  });
});


describe("conditions of use in the facility card", () => {
  it("lists the stages and each condition the API sent", async () => {
    const conditions = [
      { tri_activity: "As a reactant", tri_section: "3.2a", lifecycle_stage: "Processing", cou_category: "Processing as a reactant", mapping_strength: "Direct" },
      { tri_activity: "Ancillary or other use", tri_section: "3.3c", lifecycle_stage: "Industrial use", cou_category: "Industrial function category and chemical sector", mapping_strength: "Direct (group)" },
    ];
    show(facility({ conditions_of_use: conditions, lifecycle_stages: ["Processing", "Industrial use"] }));
    await userEvent.hover(screen.getByRole("button", { name: /Plant F1/ }));
    expect(await screen.findByText("Life cycle stages")).toBeInTheDocument();
    const stages = screen.getByRole("list", { name: "Life cycle stages" });
    expect(stages).toHaveTextContent("Processing");
    expect(stages).toHaveTextContent("Industrial use");
    const list = screen.getByRole("list", { name: "Conditions of use" });
    expect(list).toHaveTextContent("Processing as a reactant");
    expect(list).toHaveTextContent("Life cycle stage: Processing");
    expect(list).toHaveTextContent("From TRI “As a reactant” (Form R 3.2a) · mapping Direct");
    expect(list.querySelectorAll("li")).toHaveLength(2);
  });

  it("says not reported, with the reason, when there are none", async () => {
    show(facility({ conditions_note: "TRI reported no activity for this submission" }));
    await userEvent.hover(screen.getByRole("button", { name: /Plant F1/ }));
    expect(await screen.findByText(/Not reported: TRI reported no activity/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Conditions of use" })).toBeNull();
  });
});

describe("card height", () => {
  it("is no taller than the room on the side it opens, so nothing is clipped out of reach", async () => {
    FakeMap.reset();
    show(facility({ frs_id: "F1", name: "Plant F1" }));
    const overlay = document.querySelector('[class*="absolute inset-0"]') as HTMLElement | null;
    expect(overlay).not.toBeNull();
    vi.spyOn(overlay as HTMLElement, "getBoundingClientRect").mockReturnValue({
      width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => "",
    });
    await userEvent.hover(screen.getByRole("button", { name: /Plant F1/ }));
    const card = await screen.findByRole("tooltip");
    const maxHeight = Number.parseFloat(card.style.maxHeight);
    expect(maxHeight).toBeGreaterThan(0);
    expect(maxHeight).toBeLessThanOrEqual(600);
  });
});

describe("community and worker badges", () => {
  it("show the community band and hazard quotient beside the worker band and ratio", async () => {
    const user = userEvent.setup();
    show(
      facility({
        status: "high",
        exposure: {
          stacks_given: 1,
          stacks_evaluated: 1,
          hq_worst: extreme(1, 3),
          hq_representative: null,
          cancer_risk_worst: null,
          cancer_risk_representative: null,
          concentration_worst: null,
          concentration_representative: null,
          dose: null,
          warnings: [],
        },
        occupational_exposure: worker(),
      }),
    );
    await user.hover(marker(/Plant F1/));
    const badges = within(screen.getByRole("tooltip")).getByRole("group", {
      name: "Community and worker risk",
    });
    expect(badges).toHaveTextContent("Community High HQ 3");
    expect(badges).toHaveTextContent("Worker Moderate");
    expect(badges).toHaveTextContent("R_OEL 0.4");
  });

  it("say not computed for the worker when there is no result", async () => {
    const user = userEvent.setup();
    show(facility());
    await user.hover(marker(/Plant F1/));
    const badges = screen.getByRole("group", { name: "Community and worker risk" });
    expect(badges).toHaveTextContent("Worker Not computed");
    expect(badges).toHaveTextContent("HQ not reported");
  });
});

describe("worker section and ring", () => {
  const pinned = async (f: Facility) => {
    const user = userEvent.setup();
    show(f);
    await user.click(marker(/Plant F1/));
    return screen.getByRole("dialog");
  };

  it("lists evidence, schedule, vapor pressure, limit, both cases and the fugitive context", async () => {
    const dialog = await pinned(facility({ occupational_exposure: worker(), operational_profile: profile() }));
    expect(within(dialog).getByRole("button", { name: /Worker exposure/ })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Evidence: Drum loading");
    expect(dialog).toHaveTextContent("250 days/yr • 16 hr/day • 4,240 hr/yr");
    expect(dialog).toHaveTextContent("Life cycle stage: Processing");
    expect(dialog).toHaveTextContent("Condition of use: Processing as a reactant");
    expect(dialog).toHaveTextContent("10 mmHg, within the vapor-model range");
    expect(dialog).toHaveTextContent("OSHA PEL-TWA (PubChem)");
    expect(within(dialog).getByRole("region", { name: "Baseline" })).toHaveTextContent("Moderate");
    expect(within(dialog).getByRole("region", { name: "Worst case" })).toHaveTextContent("High");
    expect(dialog).toHaveTextContent("Fugitive release, context only (2020)1000 kg/yr");
    expect(dialog).toHaveTextContent("context only; no worker value uses it");
    expect(dialog).toHaveTextContent("a well-mixed zone");
    expect(dialog).toHaveTextContent("no IUR");
  });

  it("lists each activity with its two averages and marks the one that drives", async () => {
    const dialog = await pinned(facility({ occupational_exposure: worker() }));
    const rows = within(within(dialog).getByRole("list", { name: "Evaluated activities" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Drum loading");
    expect(rows[0]).toHaveTextContent("Drives the worst case");
    expect(rows[0]).toHaveTextContent("8-hr average, typical2 mg/m³");
    expect(rows[0]).toHaveTextContent("8-hr average, worst case6 mg/m³");
    expect(rows[0]).toHaveTextContent("Mass balance typical, Two-zone model worst case");
    expect(rows[1]).not.toHaveTextContent("Drives the worst case");
  });

  it("says OSHA monitoring when the result rests on it, with the summary and the modelled activities", async () => {
    const dialog = await pinned(facility({ occupational_exposure: monitoredWorker({ activities: worker().activities }) }));
    expect(dialog).toHaveTextContent("Evidence: OSHA monitoring");
    const summary = within(dialog).getByRole("group", { name: "OSHA monitoring" });
    expect(summary).toHaveTextContent("Industry level4-digit NAICS");
    expect(summary).toHaveTextContent("Samples40");
    expect(summary).toHaveTextContent("Non-detects5");
    expect(summary).toHaveTextContent("Years2005–2020");
    expect(summary).toHaveTextContent("Median1.5 mg/m³");
    expect(summary).toHaveTextContent("95th percentile6 mg/m³");
    expect(within(dialog).getByRole("list", { name: "Evaluated activities" })).toBeInTheDocument();
  });

  it("says why the median is below detection, never zero", async () => {
    const dialog = await pinned(
      facility({
        occupational_exposure: monitoredWorker({
          monitoring: monitoring({ median_mg_m3: null, reason: "most samples were not detected" }),
        }),
      }),
    );
    expect(dialog).toHaveTextContent("Medianbelow detection (most samples were not detected)");
  });

  it("says why there is no monitoring or activity, and keeps the routes folded", async () => {
    const dialog = await pinned(
      facility({ occupational_exposure: worker({ activities: [], activity_reason: "no activity for the stage" }) }),
    );
    expect(dialog).toHaveTextContent("OSHA monitoring: no samples for the industry");
    expect(dialog).toHaveTextContent("Activities: no activity for the stage");
    const routes = within(dialog).getByRole("button", { name: /How the activities were chosen/ });
    expect(routes).toHaveAttribute("aria-expanded", "false");
  });

  it("lists the routes with the scenario documents and pages once opened", async () => {
    const user = userEvent.setup();
    const dialog = await pinned(facility({ occupational_exposure: worker() }));
    await user.click(within(dialog).getByRole("button", { name: /How the activities were chosen/ }));
    expect(dialog).toHaveTextContent("Generic operations: drum_loading");
    expect(dialog).toHaveTextContent("A synthetic scenario (published ESD) · a synthetic citation, pp. 1-2");
  });

  it("says not reported when there is no worker result", async () => {
    const dialog = await pinned(facility());
    expect(dialog).toHaveTextContent("Worker exposure: not reported");
  });

  it("announces the worker tier on the marker and draws the ring in the legend", () => {
    show(facility({ status: "high", occupational_exposure: worker() }));
    expect(marker(/Plant F1, high, worker moderate/)).toBeInTheDocument();
    const rings = screen.getByRole("group", { name: "Worker screening rings" });
    expect(rings).toHaveTextContent("Moderate1");
    expect(rings).toHaveTextContent("Low0");
  });

  it("has no ring legend without any worker result", () => {
    show(facility());
    expect(screen.queryByRole("group", { name: "Worker screening rings" })).toBeNull();
  });
});

describe("worker-only facilities", () => {
  it("announce that they report no stack release, with the worker band", () => {
    show(workerOnly({ name: "Plant W1" }));
    expect(marker(/Plant W1, reports no stack release, worker moderate/)).toBeInTheDocument();
  });

  it("are counted in the legend with the outlined marker explained", () => {
    show(workerOnly(), facility({ status: "low" }));
    const legend = screen.getByRole("complementary", { name: "Map legend" });
    expect(within(legend).getByRole("button", { name: /No stack release/ })).toHaveTextContent("No stack release1");
    expect(legend).toHaveTextContent("Outlined marker: no stack release");
    expect(within(legend).getByRole("button", { name: /Not computed/ })).toHaveTextContent("Not computed0");
  });

  it("leave the legend without the entry when none is on the map", () => {
    show(facility({ status: "low" }));
    const legend = screen.getByRole("complementary", { name: "Map legend" });
    expect(within(legend).queryByRole("button", { name: /No stack release/ })).toBeNull();
    expect(legend).not.toHaveTextContent("Outlined marker");
  });

  it("say in the inspector that no community result applies, and show the worker section", async () => {
    const user = userEvent.setup();
    show(workerOnly({ name: "Plant W1" }));
    await user.click(marker(/Plant W1/));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Community No stack release");
    expect(dialog).toHaveTextContent("The facility reports no stack release, so no community result applies.");
    expect(within(dialog).getByRole("button", { name: /Worker exposure/ })).toHaveAttribute("aria-expanded", "true");
    expect(within(dialog).queryByRole("button", { name: /Receptor risk/ })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: /Stacks/ })).toBeNull();
    expect(dialog).not.toHaveTextContent("Emission rate");
  });
});

describe("onPin", () => {
  function showPinnable(onPin: (frsId: string) => void) {
    FakeMap.reset();
    render(
      <ExposureMapCanvas
        digits={2}
        workspace={workspace({ framing_version: 1, facilities: [facility({ name: "Plant F1" })] })}
        config={config}
        onPin={onPin}
      />,
    );
  }

  it("reports a click but not a hover, and not the unpin", async () => {
    const onPin = vi.fn();
    showPinnable(onPin);
    await userEvent.hover(marker(/Plant F1/));
    expect(onPin).not.toHaveBeenCalled();
    await userEvent.click(marker(/Plant F1/));
    expect(onPin).toHaveBeenCalledExactlyOnceWith("F1");
    await userEvent.click(marker(/Plant F1/));
    expect(onPin).toHaveBeenCalledTimes(1);
  });
});


describe("worst-case scenarios", () => {
  const named = (number: number) => ({
    key: "stack_number",
    group: "source" as const,
    label: "Stack",
    value: number,
    unit: "",
    source: null,
    reason: null,
  });
  const three = [
    stack({ stack_number: 1, height_m: 5 }),
    stack({ stack_number: 2, height_m: 10 }),
    stack({ stack_number: 3, height_m: 15 }),
  ];

  it("come first, open, with the factors behind the value", async () => {
    const user = userEvent.setup();
    show(facility({ stacks: three, scenarios: [scenario({ value: 2, factors: [named(2)] })] }));
    await user.tab();
    const toggle = screen.getByRole("button", { name: "Worst-case scenarios" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const headings = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(headings.indexOf("Worst-case scenarios")).toBeLessThan(headings.indexOf("Stacks"));
    expect(screen.getByRole("article", { name: /Hazard quotient/ })).toBeInTheDocument();
  });

  it("mark the stack that drives them and fold the stack list", async () => {
    const user = userEvent.setup();
    show(facility({ stacks: three, scenarios: [scenario({ factors: [named(2)] })] }));
    await user.tab();
    expect(screen.getByText("Drives the worst case: Hazard quotient")).toBeInTheDocument();
    expect(screen.getAllByText(/Drives the worst case/)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Stacks" })).toHaveAttribute("aria-expanded", "false");
  });

  it("switch between the results of the facility", async () => {
    const user = userEvent.setup();
    const risk = scenario({ quantity: "cancer_risk", quantity_label: "Lifetime cancer risk", value: 1e-6 });
    show(facility({ name: "Plant F1", scenarios: [scenario({}), risk] }));
    await user.click(marker(/Plant F1/));
    await user.click(screen.getByRole("button", { name: "Lifetime cancer risk" }));
    expect(screen.getByRole("article", { name: /Lifetime cancer risk/ })).toBeInTheDocument();
  });

  it("leave the section out when the facility has none", async () => {
    const user = userEvent.setup();
    show(facility({ scenarios: [] }));
    await user.tab();
    expect(screen.queryByRole("button", { name: "Worst-case scenarios" })).toBeNull();
    expect(screen.queryByText(/Drives the worst case/)).toBeNull();
  });
});
