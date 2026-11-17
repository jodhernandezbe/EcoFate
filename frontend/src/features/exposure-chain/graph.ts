import { BAND_LOOK, isBand } from "../../lib/band";
import { NOT_REPORTED, formatNumber, formatWithUnit } from "../../lib/format";
import type { ExposureGraph, GraphEdge, GraphLane, GraphNode, GraphQuantity } from "../../types/api";

export type { ExposureGraph, GraphEdge, GraphLane, GraphNode, GraphQuantity };

/** Size every node card is laid out and drawn at, px. */
export const NODE_W = 140;
export const NODE_H = 132;

/** The quantity a node puts on its face, when it names one. */
export const headline = (node: GraphNode): GraphQuantity | null =>
  node.quantities.find((q) => q.key === node.headline) ?? null;

/** A quantity as the API sent it, with its unit; absent reads "not reported" (never 0). */
export function formatQuantity(quantity: GraphQuantity, digits: number): string {
  if (quantity.value === null) return NOT_REPORTED;
  return quantity.unit ? formatWithUnit(quantity.value, quantity.unit, digits) : formatNumber(quantity.value, digits);
}

/** CSS colour of a status (design tokens), neutral when there is none. */
export const statusColor = (status: GraphLane["status"]): string =>
  isBand(status) ? BAND_LOOK[status].color : "var(--fg-2)";

/** The chain with nothing in it: before any assessment, or from a server that sends no chain. */
export const EMPTY_CHAIN: ExposureGraph = { lanes: [], nodes: [], edges: [], caption: null };
