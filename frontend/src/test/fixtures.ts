import { EMPTY_WORKSPACE } from "../hooks/useWorkspaceStore";
import type {
  ActivityCase,
  Extremum,
  Facility,
  MonitoringSummary,
  WorkerActivity,
  WorkerCase,
  WorkspaceState,
  WorstCaseScenario,
} from "../types/workspace";

/** Synthetic values (round numbers), never real measurements. */
export function extremum(value: number, status: Extremum["status"], stack = 1): Extremum {
  return { value, status, frs_id: "F1", facility_name: "Plant F1", stack_number: stack };
}

export function facility(over: Partial<Facility> = {}): Facility {
  return {
    frs_id: "F1",
    name: "Plant F1",
    address: "1 Test Road",
    city: "Testville",
    county: "Test",
    state: "TX",
    zip_code: "00000",
    latitude: 10,
    longitude: -20,
    cas_number: "1-1-1",
    doc_ctrl_num: "DOC1",
    naics_subsector: null,
    naics_subsector_title: null,
    medium: "AIR STACK",
    reporting_year: 2020,
    total_release: 100,
    release_unit: "Pounds",
    emission_rate_g_s: 1,
    operating_hours_per_year: 8760,
    operating_hours_source: null,
    fugitive_release_kg_per_year: null,
    fugitive_reporting_year: null,
    worker_only: false,
    community_reason: null,
    conditions_of_use: [],
    lifecycle_stages: [],
    conditions_note: null,
    industry: null,
    stacks: [],
    receptors: null,
    meteorology: null,
    exposure: null,
    occupational_exposure: null,
    operational_profile: null,
    scenarios: [],
    exposure_graph: null,
    status: null,
    screening: null,
    buffer: null,
    sector: null,
    ...over,
  };
}

export function workspace(over: Partial<WorkspaceState> = {}): WorkspaceState {
  return { ...EMPTY_WORKSPACE, ...over };
}

/** One output of a modelled activity, synthetic round numbers. */
export const activityCase = (over: Partial<ActivityCase> = {}): ActivityCase => ({
  estimator: "mass_balance",
  airflow_m3_per_s: 1,
  mixing_factor: 0.5,
  room_m3: null,
  air_exchange_per_h: null,
  generation_g_per_s: 0.25,
  concentration_mg_m3: 4,
  capped: false,
  twa_mg_m3: 2,
  ...over,
});

/** A modelled activity, synthetic round numbers. */
export const activity = (over: Partial<WorkerActivity> = {}): WorkerActivity => ({
  key: "drum_loading",
  label: "Drum loading",
  model: "ap42_loading",
  setting: "indoor",
  hours: 2,
  typical: activityCase(),
  worst_case: activityCase({ estimator: "two_zone", twa_mg_m3: 6 }),
  warnings: ["an activity warning"],
  statement: null,
  ...over,
});

/** One case (baseline or worst) of a worker result, synthetic round numbers. */
export const workerCase = (over: Partial<WorkerCase> = {}): WorkerCase => ({
  setting: "indoor",
  estimator: "mass_balance",
  airflow_m3_per_s: 1,
  mixing_factor: 0.5,
  room_m3: null,
  air_exchange_per_h: null,
  generation_g_per_s: 0.25,
  workplace_concentration_mg_m3: 4,
  capped: false,
  twa_mg_m3: 2,
  oel_ratio: 0.4,
  hq: 0.2,
  cancer_risk: 3e-6,
  risk_tier: "moderate",
  ...over,
});

/** A worker screening on the activity model, synthetic round numbers. */
export function worker(over: Partial<NonNullable<Facility["occupational_exposure"]>> = {}): NonNullable<Facility["occupational_exposure"]> {
  const drum = activity();
  return {
    evidence: "activity_model",
    molecular_weight: 100,
    molecular_weight_source: "a synthetic source",
    vapor_pressure_mmhg: 10,
    vapor_pressure_source: "a synthetic pressure source",
    volatility: "within",
    fugitive_release_kg_per_year: 1000,
    fugitive_reporting_year: 2020,
    fugitive_statement: "context only; no worker value uses it",
    operating_days_per_year: 250,
    hours_per_day: 16,
    oel_twa_mg_m3: 5,
    oel_source: "OSHA PEL-TWA (PubChem)",
    rfc: 1,
    iur: 1e-6,
    driving_activity: {
      key: drum.key,
      label: drum.label,
      model: drum.model,
      setting: drum.setting,
      hours: drum.hours,
      statement: null,
      estimator: "two_zone",
    },
    activities: [drum, activity({ key: "sampling", label: "Sampling", hours: 1, worst_case: activityCase({ twa_mg_m3: 3 }) })],
    activity_reason: null,
    routes: [
      {
        stage: "Processing",
        generic_operation: ["drum_loading"],
        scenarios: [
          { title: "A synthetic scenario", category: "published ESD", pages: "pp. 1-2", source: "a synthetic citation", activities: ["drum_loading"] },
        ],
        note: null,
      },
    ],
    monitoring: null,
    monitoring_reason: "no samples for the industry",
    baseline: workerCase(),
    worst_case: workerCase({ estimator: "two_zone", twa_mg_m3: 6, oel_ratio: 1.2, risk_tier: "high" }),
    risk_tier: "moderate",
    assumptions: ["a well-mixed zone"],
    warnings: ["no IUR"],
    ...over,
  };
}

/** OSHA's measured samples for an industry, synthetic round numbers. */
export const monitoring = (over: Partial<MonitoringSummary> = {}): MonitoringSummary => ({
  imis_code: "1234",
  naics_level: "4-digit NAICS",
  n_values: 40,
  n_nondetect: 5,
  median_mg_m3: 1.5,
  p95_mg_m3: 6,
  first_year: 2005,
  last_year: 2020,
  reason: null,
  source: "OSHA CEHD (synthetic)",
  statements: ["a monitoring statement"],
  level_note: null,
  unit_note: null,
  original_unit: null,
  ...over,
});

/** A worker screening on OSHA monitoring, with no modelled activity. */
export const monitoredWorker = (over: Partial<NonNullable<Facility["occupational_exposure"]>> = {}) =>
  worker({
    evidence: "monitoring",
    driving_activity: null,
    activity_reason: null,
    monitoring: monitoring(),
    monitoring_reason: null,
    baseline: workerCase({
      estimator: "monitoring",
      setting: null,
      generation_g_per_s: null,
      twa_mg_m3: 1.5,
      oel_ratio: 0.3,
    }),
    worst_case: workerCase({ estimator: "monitoring", setting: null, twa_mg_m3: 6, oel_ratio: 1.2, risk_tier: "high" }),
    ...over,
  });

/** A facility with a fugitive release and no stack release: a worker result and no community value. */
export const workerOnly = (over: Partial<Facility> = {}): Facility =>
  facility({
    frs_id: "W1",
    name: "Plant W1",
    worker_only: true,
    community_reason: "The facility reports no stack release, so no community result applies.",
    medium: null,
    total_release: null,
    release_unit: null,
    emission_rate_g_s: null,
    occupational_exposure: worker(),
    ...over,
  });

/** An operational profile with synthetic round numbers. */
export function profile(over: Partial<NonNullable<Facility["operational_profile"]>> = {}) {
  return {
    naics_code: "325199",
    life_cycle_stage: ["Processing"],
    cou_category: ["Processing as a reactant"],
    cdr_sector: {
      code: "IS21",
      name: "All Other Basic Organic Chemical Manufacturing",
      matched_naics_prefix: "32519",
      naics_edition: "2007",
    },
    days_per_week: 5,
    operating_days_per_year: 250,
    hours_per_day: 16,
    annual_operating_hours: 4240,
    schedule_source: "Census QPC test",
    warnings: [],
    ...over,
  };
}

/** A worst-case scenario with synthetic round numbers. */
export const scenario = (over: Partial<WorstCaseScenario> = {}): WorstCaseScenario => ({
  pathway_key: "community_inhalation",
  pathway: "Outdoor Air → Inhalation → General Population",
  quantity: "hq",
  quantity_label: "Hazard quotient",
  value: 2,
  tier: "high",
  benchmark: 0.1,
  factors: [],
  receptors: [],
  receptors_note: null,
  notes: [],
  ...over,
});
