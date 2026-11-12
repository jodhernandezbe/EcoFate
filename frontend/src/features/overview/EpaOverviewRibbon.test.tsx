import { render, screen, within } from "@testing-library/react";

import { EMPTY_WORKSPACE } from "../../hooks/useWorkspaceStore";
import { extremum, facility, workspace } from "../../test/fixtures";
import { EpaOverviewRibbon } from "./EpaOverviewRibbon";

const card = (name: string) => screen.getByRole("region", { name });

describe("risk card", () => {
  it("says nothing is computed yet, with the reason", () => {
    render(<EpaOverviewRibbon workspace={EMPTY_WORKSPACE} digits={2} />);
    const risk = within(card("Hazard quotient & cancer risk"));
    expect(risk.getAllByText("Not computed")).toHaveLength(2);
    expect(risk.getByText(/not yet computed/)).toBeInTheDocument();
  });

  it("shows the worst case with its status and where it came from", () => {
    const state = workspace({
      risk: { ...EMPTY_WORKSPACE.risk, hq_worst: extremum(2.5, "high", 3), hq_representative: extremum(1.24, "high"), reason: null },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    const risk = within(card("Hazard quotient & cancer risk"));
    expect(risk.getByText("2.5")).toBeInTheDocument();
    expect(risk.getByText("1.2")).toBeInTheDocument();
    expect(risk.getByText("High")).toBeInTheDocument();
    expect(risk.getByText("Plant F1 · stack 3")).toBeInTheDocument();
  });

  it("writes cancer risk in scientific notation", () => {
    const state = workspace({
      risk: { ...EMPTY_WORKSPACE.risk, cancer_risk_worst: extremum(0.000012, "moderate"), reason: null },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    expect(screen.getByText("1.2 × 10⁻⁵")).toBeInTheDocument();
    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });
});

describe("ribbon layout", () => {
  it("gives every row its content height without scenarios, so empty cards are not padded", () => {
    render(<EpaOverviewRibbon workspace={EMPTY_WORKSPACE} digits={2} />);
    expect(screen.getByRole("group", { name: "Executive summary" })).toHaveClass("auto-rows-auto", "content-start");
  });

  it("lets every row share the panel once there are scenarios", () => {
    const driver = { facility_name: "Plant F1", frs_id: "F1", pathway_key: "community", quantity: "hq", stack_number: 1, value: 2 };
    render(<EpaOverviewRibbon workspace={workspace({ scenario_drivers: [driver] })} digits={2} />);
    expect(screen.getByRole("group", { name: "Executive summary" })).not.toHaveClass("auto-rows-auto", "content-start");
  });
});

describe("provenance card", () => {
  it("shows no badge until the read-across tool ran", () => {
    render(<EpaOverviewRibbon workspace={EMPTY_WORKSPACE} digits={2} />);
    const provenance = within(card("Chemical & provenance"));
    expect(provenance.queryByText("Not evaluated")).toBeNull();
    expect(provenance.queryByText("Direct TRI match")).toBeNull();
    expect(provenance.queryByText("Unresolved")).toBeNull();
  });

  it("shows the properties with their sources, and absent ones as not reported", () => {
    const state = workspace({
      chemical: {
        ...EMPTY_WORKSPACE.chemical,
        cas_number: "1-1-1",
        molecular_weight_g_mol: 50,
        vapor_pressure_mmhg: 7.5,
        density_g_cm3: 0.88,
        oel_twa_mg_m3: 3.2,
        rfc_mg_m3: 0.5,
        sources: { rfc: "IRIS", vapor_pressure: "CompTox (experimental)", oel_twa: "user-provided" },
      },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    const chem = within(card("Chemical & provenance"));
    expect(chem.getByText("50 g/mol")).toBeInTheDocument();
    expect(chem.getByText("0.5 mg/m³")).toBeInTheDocument();
    expect(chem.getByText("7.5 mmHg")).toBeInTheDocument();
    expect(chem.getByText("0.88 g/cm³")).toBeInTheDocument();
    expect(chem.getByText("3.2 mg/m³")).toBeInTheDocument();
    expect(chem.getByText(/Occupational limit \(8-hr\) · user-provided/)).toBeInTheDocument();
    expect(chem.getByText(/Vapor pressure · CompTox \(experimental\)/)).toBeInTheDocument();
    expect(chem.getByText(/Inhalation RfC · IRIS/)).toBeInTheDocument();
    expect(chem.getByText("not reported")).toBeInTheDocument(); // the unit risk
  });

  it("shows the chemical's name before the CAS number only when the state has one", () => {
    const named = workspace({
      chemical: { ...EMPTY_WORKSPACE.chemical, cas_number: "1-1-1", name: "Testane" },
    });
    const { unmount } = render(<EpaOverviewRibbon workspace={named} digits={2} />);
    const chem = within(card("Chemical & provenance"));
    expect(chem.getByTestId("chemical-name")).toHaveTextContent("Testane");
    expect(chem.getByText("1-1-1")).toBeInTheDocument();
    unmount();
    const bare = workspace({ chemical: { ...EMPTY_WORKSPACE.chemical, cas_number: "1-1-1" } });
    render(<EpaOverviewRibbon workspace={bare} digits={2} />);
    expect(within(card("Chemical & provenance")).queryByTestId("chemical-name")).toBeNull();
  });

  it("shows a surrogate with its scores inside the applicability domain", () => {
    const state = workspace({
      chemical: {
        ...EMPTY_WORKSPACE.chemical,
        read_across: {
          ...EMPTY_WORKSPACE.chemical.read_across,
          kind: "read_across",
          surrogate_cas: "9-9-9",
          surrogate_name: "Synthetic surrogate",
          hybrid_score: 0.4,
          cosine_similarity: 0.5,
          tanimoto_similarity: 0.25,
          within_applicability_domain: true,
        },
      },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    const chem = within(card("Chemical & provenance"));
    expect(chem.getByText("Read-across surrogate")).toBeInTheDocument();
    expect(chem.getByText("Synthetic surrogate")).toBeInTheDocument();
    expect(chem.getByText("0.4")).toBeInTheDocument();
    expect(chem.getByText("Within applicability domain")).toBeInTheDocument();
  });

  it("flags a surrogate outside the applicability domain", () => {
    const state = workspace({
      chemical: {
        ...EMPTY_WORKSPACE.chemical,
        read_across: { ...EMPTY_WORKSPACE.chemical.read_across, kind: "read_across", within_applicability_domain: false },
      },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    expect(screen.getByText("Outside applicability domain")).toBeInTheDocument();
  });

  it.each([
    ["direct_tri_match", "Direct TRI match"],
    ["unresolved", "Unresolved"],
  ] as const)("badges %s", (kind, label) => {
    const state = workspace({
      chemical: { ...EMPTY_WORKSPACE.chemical, read_across: { ...EMPTY_WORKSPACE.chemical.read_across, kind } },
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("population card", () => {
  const receptors = {
    total_population: 12345,
    radius_km: 3,
    age_distribution: { "0-4": 10, "5-17": 20, "18-64": 50, "65+": 20 },
    source: "synthetic ACS",
    screening_default: false,
    warnings: [],
  };

  it("is empty until receptors are reported", () => {
    render(<EpaOverviewRibbon workspace={EMPTY_WORKSPACE} digits={2} />);
    expect(screen.getByText("Population not reported yet.")).toBeInTheDocument();
  });

  it("shows residents, radius and the four age bands", () => {
    render(<EpaOverviewRibbon workspace={workspace({ receptors })} digits={2} />);
    const pop = within(card("Exposed population"));
    expect(pop.getByText("12,345")).toBeInTheDocument();
    expect(pop.getByText("3 km")).toBeInTheDocument();
    expect(pop.getByRole("img", { name: "0-4: 10%, 5-17: 20%, 18-64: 50%, 65+: 20%" })).toBeInTheDocument();
    expect(pop.queryByText("screening default")).toBeNull();
  });

  it("leaves out a band the API did not send and names it, instead of drawing it as 0 %", () => {
    const partial = { ...receptors, age_distribution: { "0-4": 10, "18-64": 90 } };
    render(<EpaOverviewRibbon workspace={workspace({ receptors: partial })} digits={2} />);
    const pop = within(card("Exposed population"));
    expect(pop.getByRole("img", { name: "0-4: 10%, 18-64: 90%" })).toBeInTheDocument();
    expect(pop.getByText("Not reported: ages 5-17, 65+")).toBeInTheDocument();
    expect(pop.queryByText("0%")).toBeNull();
  });

  it("shows the dose of each age band for the selected facility, the highest marked", () => {
    const exposure = {
      stacks_given: 1, stacks_evaluated: 1, hq_worst: null, cancer_risk_worst: null,
      concentration_worst: null, hq_representative: null, cancer_risk_representative: null,
      concentration_representative: null, warnings: [],
      dose: { highest_mg_kg_day: 0.5, highest_band: "0-4", by_band: { "0-4": 0.5, "18-64": 0.25 } },
    };
    const state = workspace({
      receptors,
      selected_frs_id: "F1",
      facilities: [facility({ frs_id: "F1", exposure })],
    });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    const pop = within(card("Exposed population"));
    expect(pop.getByText("Age 0-4 (highest)")).toBeInTheDocument();
    expect(pop.getByText("0.5")).toBeInTheDocument();
    expect(pop.getByText("0.25")).toBeInTheDocument();
  });

  it("shows no dose when no tool reported one", () => {
    render(<EpaOverviewRibbon workspace={workspace({ receptors })} digits={2} />);
    expect(within(card("Exposed population")).queryByText(/Inhalation dose/)).toBeNull();
  });

  it("marks a screening default", () => {
    render(<EpaOverviewRibbon workspace={workspace({ receptors: { ...receptors, screening_default: true } })} digits={2} />);
    expect(screen.getByText("screening default")).toBeInTheDocument();
  });
});

describe("meteorology card", () => {
  const weather = {
    wind_speed_m_s: 3,
    wind_from_deg: 270,
    wind_toward_deg: 90,
    ambient_temperature_k: 290,
    stability_class: "D",
    source: "synthetic 2020",
    screening_default: false,
    latitude: 29.72,
    longitude: -95.25,
    frs_id: "F1",
    facility_name: "Plant F1",
    warnings: [],
  };

  it("says which facility the weather is for", () => {
    render(<EpaOverviewRibbon workspace={workspace({ meteorology: weather })} digits={2} />);
    expect(within(card("Meteorology")).getByText("For Plant F1")).toBeInTheDocument();
  });

  it("says when the weather is for a point that is not one of the facilities", () => {
    const state = workspace({ meteorology: { ...weather, frs_id: null, facility_name: null } });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    expect(within(card("Meteorology")).getByText("At 29.720, -95.250 (not one of the facilities)")).toBeInTheDocument();
  });

  it("shows the wind, temperature and class with the arrow pointing downwind", () => {
    const { container } = render(<EpaOverviewRibbon workspace={workspace({ meteorology: weather })} digits={2} />);
    const met = within(card("Meteorology"));
    expect(met.getByText("3 m/s")).toBeInTheDocument();
    expect(met.getByText("270°")).toBeInTheDocument();
    expect(met.getByText("290 K")).toBeInTheDocument();
    expect(met.getByText("D")).toBeInTheDocument();
    expect(container.querySelector<SVGElement>("svg")?.style.transform).toBe("rotate(90deg)");
  });

  it("marks default weather as a screening default", () => {
    const state = workspace({ meteorology: { ...weather, source: "screening default", screening_default: true } });
    render(<EpaOverviewRibbon workspace={state} digits={2} />);
    expect(within(card("Meteorology")).getByText("screening default", { selector: "span" })).toBeInTheDocument();
  });
});
