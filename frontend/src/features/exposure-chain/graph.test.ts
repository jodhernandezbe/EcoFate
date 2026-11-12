import { describe, expect, it } from "vitest";

import { FULL_GRAPH } from "../../test/graphs";
import { drawnLanes, formatQuantity, headline, shapeKey, statusColor, visibleGraph } from "./graph";

const q = (value: number | null, unit = "") => ({ key: "k", label: "K", value, unit, source: null, reason: null });

describe("graph helpers", () => {
  it("formats a quantity with its unit, unitless without one, absent as not reported", () => {
    expect(formatQuantity(q(4, "µg/m³"), 2)).toBe("4 µg/m³");
    expect(formatQuantity(q(0.000003), 2)).toBe("3 × 10⁻⁶");
    expect(formatQuantity(q(null, "mg/m³"), 2)).toBe("not reported");
  });

  it("reads the headline quantity the API named", () => {
    const air = FULL_GRAPH.nodes.find((n) => n.id === "community:air");
    expect(air && headline(air)?.key).toBe("peak_concentration");
  });

  it("keeps the source and one lane when a lane is isolated", () => {
    const worker = visibleGraph(FULL_GRAPH, "worker");
    expect(worker.nodes.every((n) => n.lane === null || n.lane === "worker")).toBe(true);
    expect(worker.nodes.some((n) => n.id === "source")).toBe(true);
    expect(worker.edges.every((e) => e.lane === "worker")).toBe(true);
    expect(visibleGraph(FULL_GRAPH, "all")).toBe(FULL_GRAPH);
  });

  it("changes the shape key only when nodes or edges change", () => {
    expect(shapeKey(FULL_GRAPH)).toBe(shapeKey({ ...FULL_GRAPH, lanes: [] }));
    expect(shapeKey(FULL_GRAPH)).not.toBe(shapeKey(visibleGraph(FULL_GRAPH, "worker")));
  });

  it("lists only available lanes and colours by status token", () => {
    expect(drawnLanes(FULL_GRAPH).map((l) => l.id)).toEqual(["community", "worker"]);
    expect(statusColor("high")).toBe("var(--bad)");
    expect(statusColor("above" as never)).toBe("var(--fg-2)");
    expect(statusColor(null)).toBe("var(--fg-2)");
  });
});
