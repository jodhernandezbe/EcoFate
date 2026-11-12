import { describe, expect, it } from "vitest";

import { facility, monitoredWorker, worker, workerOnly } from "../../test/fixtures";
import type { Facility } from "../../types/workspace";
import { describeBar, groupFacilities, topGroups } from "./riskGroups";

const extreme = (high: number) => ({ low: high / 2, high, low_stack: 1, high_stack: 2 });
const exposure = (hq: number | null, risk: number | null, conc: number | null = 10) => ({
  stacks_given: 1,
  stacks_evaluated: 1,
  hq_worst: hq === null ? null : extreme(hq),
  hq_representative: null,
  cancer_risk_worst: risk === null ? null : extreme(risk),
  cancer_risk_representative: null,
  concentration_worst: conc === null ? null : extreme(conc),
  concentration_representative: null,
  dose: null,
  warnings: [],
});
const cond = (stage: string, category: string) => ({
  tri_activity: "x", tri_section: "3.2a", lifecycle_stage: stage, cou_category: category, mapping_strength: "Direct",
});
/** A value a test knows exists. */
function must<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("expected a value");
  return value;
}
const make = (id: string, over: Partial<Facility>): Facility => facility({ frs_id: id, name: `Plant ${id}`, ...over });
const sub = (code: string | null, title: string | null = "Title") => ({ naics_subsector: code, naics_subsector_title: title });
const screenedOut = { outcome: "screened_out_at_bound" as const, bound_hq: 0.1, bound_cancer_risk: null, value_hq: 0.1, value_cancer_risk: null, reason: "r" };

describe("groupFacilities by subsector", () => {
  const facilities = [
    make("A", { ...sub("325", "Chemicals"), exposure: exposure(2, 1e-6, 4) }),
    make("B", { ...sub("325", "Chemicals"), exposure: exposure(5, 1e-7, 8) }),
    make("C", { ...sub("324", "Petroleum"), exposure: exposure(0.5, null) }),
    make("D", sub(null, null)),
  ];

  it("takes the highest value of each quantity from one facility, never a combination", () => {
    const chem = must(groupFacilities(facilities, "subsector").groups.find((g) => g.key === "325"));
    expect(chem.label).toBe("325 · Chemicals");
    expect(chem.hq).toEqual({ value: 5, frsId: "B", name: "Plant B", concentration: 8, twa: null, stack: 2, evidence: null });
    expect(chem.risk).toEqual({ value: 1e-6, frsId: "A", name: "Plant A", concentration: 4, twa: null, stack: 2, evidence: null });
    expect([chem.facilities, chem.assessed]).toEqual([2, 2]);
  });

  it("counts a facility with no subsector as ungrouped, not as a group", () => {
    const result = groupFacilities(facilities, "subsector");
    expect(result.ungrouped).toBe(1);
    expect(result.groups.map((g) => g.key).sort()).toEqual(["324", "325"]);
  });

  it("labels a subsector without a title by its code", () => {
    const [group] = groupFacilities([make("A", sub("999", null))], "subsector").groups;
    expect(group?.label).toBe("999");
  });
});

describe("assessed and screened-out facilities", () => {
  it("leaves screened-out and unassessed facilities out of the bars but counts them", () => {
    const facilities = [
      make("A", { ...sub("325"), exposure: exposure(1, null) }),
      make("B", { ...sub("325"), screening: screenedOut }),
      make("C", sub("325")),
    ];
    const [g] = groupFacilities(facilities, "subsector").groups;
    expect([g?.facilities, g?.assessed, g?.screenedOut]).toEqual([3, 1, 1]);
    expect(g?.hq?.frsId).toBe("A");
  });

  it("has no bar for a group where nothing was assessed", () => {
    const [g] = groupFacilities([make("B", { ...sub("325"), screening: screenedOut })], "subsector").groups;
    expect(g?.hq).toBeNull();
    expect(topGroups([must(g)], "hq").shown).toEqual([]);
  });

  it("ignores non-finite values", () => {
    const [g] = groupFacilities([make("A", { ...sub("325"), exposure: exposure(Number.NaN, Number.POSITIVE_INFINITY) })], "subsector").groups;
    expect([g?.hq, g?.risk]).toEqual([null, null]);
  });

  it("keeps a concentration that was not sent as null", () => {
    const [g] = groupFacilities([make("A", { ...sub("325"), exposure: exposure(2, null, null) })], "subsector").groups;
    expect(g?.hq?.concentration).toBeNull();
  });
});

describe("groupFacilities by condition of use and stage", () => {
  const two = make("A", {
    exposure: exposure(3, null),
    conditions_of_use: [cond("Processing", "Reactant"), cond("Industrial use", "Function")],
    lifecycle_stages: ["Processing", "Industrial use"],
  });

  it("puts a facility in every one of its conditions, once each", () => {
    const duplicated = make("B", {
      exposure: exposure(1, null),
      conditions_of_use: [cond("Processing", "Reactant"), cond("Processing", "Reactant")],
      lifecycle_stages: ["Processing"],
    });
    const result = groupFacilities([two, duplicated], "condition");
    const reactant = must(result.groups.find((g) => g.key === "Processing · Reactant"));
    expect(reactant.facilities).toBe(2);
    expect(result.groups).toHaveLength(2);
  });

  it("groups by life cycle stage", () => {
    const stages = groupFacilities([two, make("C", {})], "stage");
    expect(stages.groups.map((g) => g.key)).toEqual(["Processing", "Industrial use"]);
    expect(stages.ungrouped).toBe(1);
  });
});

describe("topGroups", () => {
  const many = ["a", "b", "c", "d", "e", "f", "g"].map((k, i) =>
    make(k, { ...sub(`3${i}${i}`, `Title ${k}`), exposure: exposure(i + 1, 10 - i) }),
  );
  const groups = groupFacilities(many, "subsector").groups;

  it("keeps the five highest hazard quotients, highest first, and says how many were cut", () => {
    const { shown, hidden } = topGroups(groups, "hq");
    expect(shown.map((g) => g.hq?.value)).toEqual([7, 6, 5, 4, 3]);
    expect(hidden).toBe(2);
  });

  it("ranks the cancer risk on its own", () => {
    expect(topGroups(groups, "risk").shown.map((g) => g.risk?.value)).toEqual([10, 9, 8, 7, 6]);
  });

  it("breaks ties by label and drops groups without the quantity", () => {
    const tied = groupFacilities(
      [
        make("A", { ...sub("200", "Zeta"), exposure: exposure(1, null) }),
        make("B", { ...sub("100", "Alpha"), exposure: exposure(1, null) }),
        make("C", { ...sub("300", "Mid"), exposure: exposure(null, 1e-5) }),
      ],
      "subsector",
    ).groups;
    expect(topGroups(tied, "hq").shown.map((g) => g.label)).toEqual(["100 · Alpha", "200 · Zeta"]);
    expect(topGroups(tied, "risk").shown.map((g) => g.label)).toEqual(["300 · Mid"]);
  });
});

describe("describeBar", () => {
  const [group] = groupFacilities(
    [
      make("A", { ...sub("325", "Chemicals"), exposure: exposure(5, 2e-4, 12) }),
      make("B", { ...sub("325", "Chemicals"), screening: screenedOut }),
    ],
    "subsector",
  ).groups;

  it("tells the quantity's value, its facility and the counts", () => {
    expect(describeBar(must(group), "hq", 2)).toEqual({
      group: "325 · Chemicals",
      lines: [{ label: "Highest hazard quotient", value: "5", detail: "Plant A · stack 2 · 12 µg/m³ worst case" }],
      counts: "2 facilities in this group · 1 assessed, 1 screened out",
    });
    expect(describeBar(must(group), "risk", 2).lines).toEqual([
      { label: "Highest lifetime cancer risk", value: "2 × 10⁻⁴", detail: "Plant A · stack 2 · 12 µg/m³ worst case" },
    ]);
  });

  it("says not reported for a missing quantity and when the concentration was not sent", () => {
    const [g] = groupFacilities([make("C", { ...sub("311"), exposure: exposure(3, null, null) })], "subsector").groups;
    expect(describeBar(must(g), "hq", 2).lines[0]?.detail).toBe("Plant C · stack 2 · concentration not reported");
    expect(describeBar(must(g), "risk", 2).lines[0]).toEqual({
      label: "Highest lifetime cancer risk",
      value: "not reported",
      detail: null,
    });
  });
});

describe("the indoor air pathway (workers)", () => {
  const tier = (over: Record<string, number | null>) => ({ ...worker().baseline, ...over });
  const withWorker = (id: string, code: string, baseline: ReturnType<typeof tier>, over: Partial<Facility> = {}) =>
    make(id, {
      ...sub(code, "Chemicals"),
      exposure: exposure(9, 9e-3, 99), // the outdoor result must not leak into the indoor bars
      occupational_exposure: worker({ baseline }),
      ...over,
    });
  const facilities = [
    withWorker("A", "325", tier({ hq: 0.2, cancer_risk: 3e-6, oel_ratio: 0.4, twa_mg_m3: 2 })),
    withWorker("B", "325", tier({ hq: 0.9, cancer_risk: null, oel_ratio: 3, twa_mg_m3: 7 })),
    make("C", { ...sub("324", "Petroleum"), exposure: exposure(1, 1e-5, 5) }),
  ];

  it("takes the worker values of each facility, never the outdoor ones", () => {
    const chem = must(groupFacilities(facilities, "subsector", "indoor").groups.find((g) => g.key === "325"));
    expect(chem.hq).toMatchObject({ value: 0.9, frsId: "B", twa: 7, concentration: null });
    expect(chem.risk).toMatchObject({ value: 3e-6, frsId: "A" });
    expect(chem.ratio).toMatchObject({ value: 3, frsId: "B" });
  });

  it("leaves a facility with no worker result out of the bars", () => {
    const petro = must(groupFacilities(facilities, "subsector", "indoor").groups.find((g) => g.key === "324"));
    expect(petro.hq).toBeNull();
    expect(petro.ratio).toBeNull();
  });

  it("keeps the outdoor pathway as it was, and without a limit ratio", () => {
    const chem = must(groupFacilities(facilities, "subsector").groups.find((g) => g.key === "325"));
    expect(chem.hq).toMatchObject({ value: 9, concentration: 99, twa: null });
    expect(chem.ratio).toBeNull();
  });

  it("describes a bar with the 8-hour average, and says when it was not sent", () => {
    const grouping = groupFacilities(facilities, "subsector", "indoor");
    const chem = must(grouping.groups.find((g) => g.key === "325"));
    expect(describeBar(chem, "ratio", 2, "indoor").lines[0]).toMatchObject({
      label: "Highest 8-hour average over the occupational limit",
      detail: "Plant B · 7 mg/m³ 8-hour average · Drum loading",
    });
    const unsent = groupFacilities([withWorker("D", "999", tier({ hq: 1, twa_mg_m3: null }))], "subsector", "indoor");
    expect(describeBar(must(unsent.groups[0]), "hq", 2, "indoor").lines[0]?.detail).toBe(
      "Plant D · 8-hour average not reported · Drum loading",
    );
  });
});

describe("screened-out facilities on the indoor pathway", () => {
  const out = make("S", {
    ...sub("325", "Chemicals"),
    screening: screenedOut,
    occupational_exposure: worker(),
  });

  it("are ranked by their worker result: the community screen does not apply to workers", () => {
    const [group] = groupFacilities([out], "subsector", "indoor").groups;
    expect(group).toMatchObject({ facilities: 1, assessed: 1, screenedOut: 0 });
    expect(group?.ratio?.frsId).toBe("S");
  });

  it("stay out of the outdoor bars, counted as screened out", () => {
    const [group] = groupFacilities([out], "subsector").groups;
    expect(group).toMatchObject({ facilities: 1, assessed: 0, screenedOut: 1 });
    expect(group?.hq).toBeNull();
  });
});

describe("worker-only facilities", () => {
  const only = workerOnly({ ...sub("325", "Chemicals"), occupational_exposure: monitoredWorker() });
  const stack = make("A", { ...sub("325", "Chemicals"), exposure: exposure(2, 1e-5, 5) });

  it("are ranked on the indoor pathway, with their evidence in the tooltip", () => {
    const [group] = groupFacilities([only, stack], "subsector", "indoor").groups;
    // Indoors, "assessed" counts the facilities with a worker result; the stack one has none.
    expect(group).toMatchObject({ facilities: 2, assessed: 1, screenedOut: 0 });
    expect(group?.ratio).toMatchObject({ frsId: "W1", evidence: "OSHA monitoring" });
    expect(describeBar(must(group), "ratio", 2, "indoor").lines[0]?.detail).toBe(
      "Plant W1 · 1.5 mg/m³ 8-hour average · OSHA monitoring",
    );
  });

  it("are absent from the outdoor pathway, even from the counts", () => {
    const [group] = groupFacilities([only, stack], "subsector").groups;
    expect(group).toMatchObject({ facilities: 1, assessed: 1 });
    expect(group?.hq?.frsId).toBe("A");
    const alone = groupFacilities([only], "subsector");
    expect(alone.groups).toEqual([]);
    expect(alone.ungrouped).toBe(0);
  });
});
