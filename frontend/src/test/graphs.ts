import type { ExposureGraph } from "../types/api";
import generated from "./exposureGraphs.json";

/** Graphs produced by the real backend builder from synthetic round numbers (see the JSON's note). */
export const FULL_GRAPH = generated.full as ExposureGraph;
export const COMMUNITY_ONLY_GRAPH = generated.communityOnly as ExposureGraph;
export const MONITORING_GRAPH = generated.monitoring as ExposureGraph;
