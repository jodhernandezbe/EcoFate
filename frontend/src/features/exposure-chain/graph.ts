import { BAND_LOOK, isBand } from "../../lib/band";
import { NOT_REPORTED, formatNumber, formatWithUnit } from "../../lib/format";
import type { ExposureGraph, GraphEdge, GraphLane, GraphNode, GraphQuantity } from "../../types/api";

export type { ExposureGraph, GraphEdge, GraphLane, GraphNode, GraphQuantity };

/** Size every node is laid out and drawn at, px. */
export const NODE_W = 188;
export const NODE_H = 118;

/** The quantity a node puts on its face, when it names one. */
export const headline = (node: GraphNode): GraphQuantity | null =>
  node.quantities.find((q) => q.key === node.headline) ?? null;

/** A quantity as the API sent it, with its unit; absent reads "not reported" (never 0). */
export function formatQuantity(quantity: GraphQuantity, digits: number): string {
  if (quantity.value === null) return NOT_REPORTED;
  return quantity.unit ? formatWithUnit(quantity.value, quantity.unit, digits) : formatNumber(quantity.value, digits);
}

/** The lanes that can be drawn, in the order the API sent them. */
export const drawnLanes = (graph: ExposureGraph): GraphLane[] => graph.lanes.filter((lane) => lane.available);

/** The graph restricted to one lane (plus the shared source), or the whole graph for "all". */
export function visibleGraph(graph: ExposureGraph, lane: string): ExposureGraph {
  if (lane === "all") return graph;
  const keep = (id: string | null) => id === null || id === lane;
  return {
    lanes: graph.lanes.filter((l) => l.id === lane),
    nodes: graph.nodes.filter((n) => keep(n.lane)),
    edges: graph.edges.filter((e) => e.lane === lane),
  };
}

/** A stable key of the graph's shape, so layout reruns only when nodes or edges change. */
export const shapeKey = (graph: ExposureGraph): string =>
  [...graph.nodes.map((n) => n.id), "|", ...graph.edges.map((e) => e.id)].join(",");

/** CSS colour of a status (design tokens), neutral when there is none. */
export const statusColor = (status: GraphLane["status"]): string =>
  isBand(status) ? BAND_LOOK[status].color : "var(--fg-2)";
