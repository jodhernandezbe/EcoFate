import type { Facility } from "../types/workspace";
import { isBand, type Band } from "./band";

/**
 * The exposure pathway: the medium, the route and the receptors. Outdoor air reaches the general
 * population by inhalation (the stack result); indoor air reaches the workers by inhalation (the
 * fugitive release in the plant).
 */
export type Pathway = "outdoor" | "indoor";

export interface PathwayInfo {
  key: Pathway;
  label: string;
  /** The API's `pathway_key` of the scenarios and drivers of this pathway. */
  pathwayKey: string;
  /** The facility's screening band on this pathway, as the API sent it; null when it has none. */
  band: (facility: Facility) => Band | null;
}

/** Shared by Risk by group and the map, so their pathway choices cannot drift apart. */
export const PATHWAYS: readonly PathwayInfo[] = [
  {
    key: "outdoor",
    label: "Outdoor Air → Inhalation → General Population",
    pathwayKey: "community_inhalation",
    band: (facility) => (isBand(facility.status) ? facility.status : null),
  },
  {
    key: "indoor",
    label: "Indoor Air → Inhalation → Worker",
    pathwayKey: "worker_inhalation",
    band: (facility) => {
      const tier = facility.occupational_exposure?.risk_tier;
      return isBand(tier) ? tier : null;
    },
  },
];

/** The entry of a pathway (the list always holds both keys). */
export const pathwayInfo = (key: Pathway): PathwayInfo => {
  const [outdoor] = PATHWAYS;
  return PATHWAYS.find((p) => p.key === key) ?? (outdoor as PathwayInfo);
};
