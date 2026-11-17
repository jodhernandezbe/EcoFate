import { useCallback, useState } from "react";

import type { Facility, WorkspaceState } from "../types/workspace";

/** What the server sends before any tool has run (nothing placed, nothing computed). */
export const EMPTY_WORKSPACE: WorkspaceState = {
  framing_version: 0,
  bounds: null,
  facilities: [],
  selected_frs_id: null,
  chemical: {
    cas_number: null,
    name: null,
    molecular_weight_g_mol: null,
    vapor_pressure_mmhg: null,
    density_g_cm3: null,
    oel_twa_mg_m3: null,
    rfc_mg_m3: null,
    iur_per_ug_m3: null,
    sources: {},
    read_across: {
      kind: "not_evaluated",
      surrogate_cas: null,
      surrogate_name: null,
      hybrid_score: null,
      cosine_similarity: null,
      tanimoto_similarity: null,
      within_applicability_domain: null,
      warnings: [],
    },
    warnings: [],
  },
  risk: {
    hq_worst: null,
    cancer_risk_worst: null,
    hq_representative: null,
    cancer_risk_representative: null,
    reason: "not yet computed",
  },
  worker_risk: {
    baseline: { oel_ratio: null, hq: null, cancer_risk: null },
    worst_case: { oel_ratio: null, hq: null, cancer_risk: null },
    reason: "not yet computed",
  },
  scenario_drivers: [],
  worst_case_chain: { lanes: [], nodes: [], edges: [], caption: null },
  receptors: null,
  meteorology: null,
  unattributed: [],
  warnings: [],
};

/** The fields added after the first contract; a server that predates them does not send them. */
const FACILITY_DEFAULTS: Pick<
  Facility,
  | "fugitive_release_kg_per_year"
  | "fugitive_reporting_year"
  | "occupational_exposure"
  | "operational_profile"
  | "scenarios"
> = {
  fugitive_release_kg_per_year: null,
  fugitive_reporting_year: null,
  occupational_exposure: null,
  operational_profile: null,
  scenarios: [],
};

/**
 * The state with every field filled: what the server sent wins, and a field an older server (or a
 * snapshot saved by one) does not send is absent, not undefined, so no view reads past it.
 */
export function withDefaults(state: WorkspaceState): WorkspaceState {
  return {
    ...EMPTY_WORKSPACE,
    ...state,
    facilities: state.facilities.map((f) => ({ ...FACILITY_DEFAULTS, ...f })),
  };
}

/**
 * The workspace the analysis area shows: the latest `workspace_update`, empty before any.
 * `epoch` rises when the whole workspace is replaced (a new or restored run), so the map
 * reframes even if the replacement carries the same framing version as the one it replaces.
 */
export function useWorkspaceStore() {
  const [workspace, setWorkspace] = useState<WorkspaceState>(EMPTY_WORKSPACE);
  const [epoch, setEpoch] = useState(0);
  const apply = useCallback((state: WorkspaceState) => setWorkspace(withDefaults(state)), []);
  const replace = useCallback((state: WorkspaceState) => {
    setWorkspace(withDefaults(state));
    setEpoch((now) => now + 1);
  }, []);
  const clear = useCallback(() => replace(EMPTY_WORKSPACE), [replace]);
  return { workspace, epoch, apply, replace, clear };
}
