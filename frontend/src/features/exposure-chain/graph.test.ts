import { describe, expect, it } from "vitest";

import { FULL_GRAPH } from "../../test/graphs";
import { formatQuantity, headline, statusColor } from "./graph";

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

  it("colours by status token", () => {
    expect(statusColor("high")).toBe("var(--bad)");
    expect(statusColor("above" as never)).toBe("var(--fg-2)");
    expect(statusColor(null)).toBe("var(--fg-2)");
  });
});
