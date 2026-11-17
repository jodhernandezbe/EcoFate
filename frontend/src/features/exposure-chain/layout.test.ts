import { describe, expect, it } from "vitest";

import { FULL_GRAPH } from "../../test/graphs";
import { NODE_H, NODE_W, type ExposureGraph } from "./graph";
import { BAND_W, COLUMNS, LABEL_H, layoutSankey, MIN_WIDTH } from "./layout";

const at = (layout: ReturnType<typeof layoutSankey>, id: string) => layout.nodes.find((n) => n.node.id === id) ?? expect.fail(id);

describe("layoutSankey", () => {
  it("puts every node in the column of its kind, so the lanes line up", () => {
    const layout = layoutSankey(FULL_GRAPH, 1800);
    expect(layout.nodes).toHaveLength(FULL_GRAPH.nodes.length);
    for (const { node, column } of layout.nodes) expect(column).toBe(COLUMNS.indexOf(node.kind));
    const xs = new Map<number, number>();
    for (const { column, x } of layout.nodes) expect(xs.set(column, xs.get(column) ?? x).get(column)).toBe(x);
    expect(at(layout, "community:air").x).toBe(at(layout, "worker:air").x);
    expect(at(layout, "source").x).toBeLessThan(at(layout, "community:stack:2").x);
    expect(at(layout, "community:endpoint").x).toBe(at(layout, "worker:endpoint").x);
  });

  it("draws every band at one width", () => {
    const layout = layoutSankey(FULL_GRAPH, 1800);
    expect(layout.bands).toHaveLength(FULL_GRAPH.edges.length);
    expect(new Set(layout.bands.map((b) => b.width))).toEqual(new Set([BAND_W]));
  });

  it("leaves no two cards overlapping", () => {
    const { nodes } = layoutSankey(FULL_GRAPH, 1800);
    const overlaps = nodes.some((a, i) =>
      nodes.slice(i + 1).some((b) => Math.abs(a.x - b.x) < NODE_W && Math.abs(a.y - b.y) < NODE_H),
    );
    expect(overlaps).toBe(false);
  });

  it("fits all six columns in about 1100 px", () => {
    expect(MIN_WIDTH).toBeLessThanOrEqual(1140);
    expect(layoutSankey(FULL_GRAPH, 0).width).toBe(MIN_WIDTH);
  });

  it("hangs every label clear of every card and of the other labels", () => {
    for (const width of [MIN_WIDTH, 1800]) {
      const { bands, nodes } = layoutSankey(FULL_GRAPH, width);
      const boxes = bands.flatMap((b) => (b.label ? [{ l: b.label.x - b.label.maxWidth / 2, r: b.label.x + b.label.maxWidth / 2, t: b.label.top, b: b.label.top + LABEL_H }] : []));
      expect(boxes).toHaveLength(FULL_GRAPH.edges.filter((e) => e.quantity).length);
      for (const box of boxes) {
        const hit = nodes.some((n) => n.x < box.r && n.x + NODE_W > box.l && n.y < box.b && n.y + NODE_H > box.t);
        expect(hit).toBe(false);
      }
      boxes.forEach((a, i) => boxes.slice(i + 1).forEach((c) => expect(a.l < c.r && a.r > c.l && a.t < c.b && a.b > c.t).toBe(false)));
    }
  });

  it("keeps the lanes in the order sent, one above the other", () => {
    const layout = layoutSankey(FULL_GRAPH, 1800);
    expect(at(layout, "community:endpoint").y).toBeLessThan(at(layout, "worker:endpoint").y);
    expect(layout.headers.map((h) => h.lane)).toEqual(["community", "worker"]);
  });

  it("never draws narrower than the minimum width", () => {
    expect(layoutSankey(FULL_GRAPH, 300).width).toBe(MIN_WIDTH);
    expect(layoutSankey(FULL_GRAPH, MIN_WIDTH + 400).width).toBe(MIN_WIDTH + 400);
  });

  it("lays out a lane it has never seen, with a branch, without overlap", () => {
    const base = FULL_GRAPH.nodes.find((n) => n.id === "community:band:0-4") ?? expect.fail("node");
    const graph: ExposureGraph = {
      ...FULL_GRAPH,
      lanes: [...FULL_GRAPH.lanes, { id: "dermal", label: "Dermal", available: true, reason: null, status: null, status_label: null }],
      nodes: [
        ...FULL_GRAPH.nodes,
        { ...base, id: "dermal:a", lane: "dermal" },
        { ...base, id: "dermal:b", lane: "dermal" },
      ],
      edges: [
        ...FULL_GRAPH.edges,
        { id: "x1", source: "source", target: "dermal:a", lane: "dermal", quantity: null },
        { id: "x2", source: "source", target: "dermal:b", lane: "dermal", quantity: null },
      ],
    };
    const { nodes, headers } = layoutSankey(graph, 1800);
    expect(headers.map((h) => h.lane)).toContain("dermal");
    const sameColumn = nodes.filter((n) => n.column === COLUMNS.indexOf("receptor"));
    expect(sameColumn).toHaveLength(4);
    const ys = sameColumn.map((n) => n.y).sort((a, b) => a - b);
    ys.slice(1).forEach((y, i) => expect(y - (ys[i] ?? 0)).toBeGreaterThanOrEqual(NODE_H));
  });

  it("ignores a band whose end is not in the graph", () => {
    const graph = { ...FULL_GRAPH, edges: [...FULL_GRAPH.edges, { id: "x", source: "source", target: "nowhere", lane: "community", quantity: null }] };
    expect(layoutSankey(graph, 1800).bands).toHaveLength(FULL_GRAPH.edges.length);
  });
});
