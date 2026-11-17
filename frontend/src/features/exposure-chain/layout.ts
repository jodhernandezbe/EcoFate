import { sankey, type SankeyLink, type SankeyNode } from "d3-sankey";

import { NODE_H, NODE_W, type ExposureGraph, type GraphEdge, type GraphNode } from "./graph";
import { KINDS } from "./kinds";

/** Presentation constants of the diagram, px. Band width encodes no value: every band is this wide. */
export const BAND_W = 12;
/** Height reserved for a band's label, which hangs below the cards of its lane (never over a card). */
export const LABEL_H = 52;
/** Space between a card's bottom edge and the label under it. */
export const LABEL_DROP = 6;
/**
 * Vertical gap between two cards of a column: holds the labels of the lane above and the header of
 * the lane below.
 */
export const NODE_GAP = LABEL_DROP + LABEL_H + 26;
/** The least horizontal gap between two columns: a band and its arrowhead, the label is not in it. */
export const COLUMN_GAP_MIN = 60;
/** Room above the first card for a lane header. */
const TOP = 28;

/** Columns, left to right: one for each kind of step. */
export const COLUMNS = Object.keys(KINDS);
/** The diagram never draws narrower than this; its container scrolls instead. */
export const MIN_WIDTH = COLUMNS.length * NODE_W + (COLUMNS.length - 1) * COLUMN_GAP_MIN;

export interface LaidNode {
  node: GraphNode;
  column: number;
  x: number;
  y: number;
}

export interface LaidBand {
  edge: GraphEdge;
  /** Right edge of the source card and left edge of the target card, at their vertical centres. */
  from: { x: number; y: number };
  to: { x: number; y: number };
  width: number;
  /** Where the label hangs: centred under the gap between the cards, joined to the band by a leader. */
  label: { x: number; top: number; maxWidth: number } | null;
}

export interface LaneHeader {
  lane: string;
  x: number;
  y: number;
}

export interface SankeyLayout {
  width: number;
  height: number;
  /** In reading order: the source, then each lane in the order sent, column by column. */
  nodes: LaidNode[];
  bands: LaidBand[];
  headers: LaneHeader[];
}

interface N {
  id: string;
  rank: number;
  order: number;
  fixedValue: number;
}
type L = Record<string, never>;
type Placed = SankeyNode<N, L>;

/** Column of a kind: its place in `KINDS` (an unknown kind goes after the last). */
export const columnOf = (kind: string): number => {
  const index = COLUMNS.indexOf(kind);
  return index < 0 ? COLUMNS.length : index;
};

function reading(graph: ExposureGraph): GraphNode[] {
  const lane = (id: string | null) => (id === null ? -1 : graph.lanes.findIndex((l) => l.id === id));
  const rank = (id: string | null) => (lane(id) < 0 && id !== null ? graph.lanes.length : lane(id));
  return graph.nodes
    .map((node, index) => ({ node, index }))
    .sort((a, b) => rank(a.node.lane) - rank(b.node.lane) || columnOf(a.node.kind) - columnOf(b.node.kind) || a.index - b.index)
    .map(({ node }) => node);
}

/** The steps of a column hold as many band widths as they have links, so a branch gets room. */
function weights(ordered: GraphNode[], edges: GraphEdge[]): N[] {
  const used = [...new Set(ordered.map((n) => columnOf(n.kind)))].sort((a, b) => a - b);
  return ordered.map((node, order) => {
    const links = Math.max(edges.filter((e) => e.source === node.id).length, edges.filter((e) => e.target === node.id).length);
    return { id: node.id, rank: used.indexOf(columnOf(node.kind)), order, fixedValue: Math.max(1, links) };
  });
}

function neededHeight(items: N[], column: (item: N) => number): number {
  const byColumn = new Map<number, N[]>();
  for (const item of items) byColumn.set(column(item), [...(byColumn.get(column(item)) ?? []), item]);
  const heights = [...byColumn.values()].map((c) => c.reduce((sum, i) => sum + i.fixedValue * NODE_H, 0) + (c.length - 1) * NODE_GAP);
  return Math.max(NODE_H, ...heights);
}

function placeNodes(items: N[], links: { source: string; target: string; value: number }[], height: number, width: number): Placed[] {
  const layout = sankey<N, L>()
    .nodeId((n) => n.id)
    .nodeAlign((n) => n.rank)
    .nodeSort((a, b) => a.order - b.order)
    .nodeWidth(NODE_W)
    .nodePadding(NODE_GAP)
    .extent([
      [0, TOP],
      [width, TOP + height],
    ]);
  return layout({ nodes: items.map((i) => ({ ...i })), links: links as unknown as SankeyLink<N, L>[] }).nodes;
}

function headers(nodes: LaidNode[]): LaneHeader[] {
  const first = new Map<string, LaidNode>();
  for (const laid of nodes) {
    const lane = laid.node.lane;
    const best = lane === null ? undefined : first.get(lane);
    if (lane !== null && (!best || laid.y < best.y || (laid.y === best.y && laid.x < best.x))) first.set(lane, laid);
  }
  return [...first].map(([lane, laid]) => ({ lane, x: laid.x, y: laid.y - 24 }));
}

/**
 * Sankey layout of the chain (pure; presentation only, no value is read). A card's column is the
 * place of its kind in `KINDS`, so every lane's steps line up; `d3-sankey` orders and spaces the
 * cards within a column, every link having value 1 so every band has the same width.
 */
export function layoutSankey(graph: ExposureGraph, availableWidth: number): SankeyLayout {
  const width = Math.max(availableWidth, MIN_WIDTH);
  const ordered = reading(graph);
  const ids = new Set(ordered.map((n) => n.id));
  const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const items = weights(ordered, edges);
  const height = neededHeight(items, (i) => i.rank);
  const placed = new Map(placeNodes(items, edges.map((e) => ({ source: e.source, target: e.target, value: 1 })), height, width).map((p) => [p.id, p]));
  const columns = Math.max(COLUMNS.length, ...ordered.map((n) => columnOf(n.kind) + 1));
  const pitch = (width - NODE_W) / (columns - 1);
  const nodes: LaidNode[] = ordered.map((node) => {
    const p = placed.get(node.id);
    const center = p ? ((p.y0 ?? 0) + (p.y1 ?? 0)) / 2 : TOP;
    const column = columnOf(node.kind);
    return { node, column, x: column * pitch, y: center - NODE_H / 2 };
  });
  const at = new Map(nodes.map((n) => [n.node.id, n]));
  const bands = edges.map((edge): LaidBand => {
    const a = at.get(edge.source);
    const b = at.get(edge.target);
    const from = { x: (a?.x ?? 0) + NODE_W, y: (a?.y ?? 0) + NODE_H / 2 };
    const to = { x: b?.x ?? 0, y: (b?.y ?? 0) + NODE_H / 2 };
    const label = edge.quantity
      ? { x: (from.x + to.x) / 2, top: Math.max(from.y, to.y) + NODE_H / 2 + LABEL_DROP, maxWidth: to.x - from.x + NODE_W - 8 }
      : null;
    return { edge, from, to, width: BAND_W, label };
  });
  return { width, height: TOP + height + LABEL_H + LABEL_DROP, nodes, bands, headers: headers(nodes) };
}
