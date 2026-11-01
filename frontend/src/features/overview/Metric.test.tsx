import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Metric } from "./Metric";

describe("Metric", () => {
  it("shows a large value at the headline size in the primary colour", () => {
    render(<dl><Metric label="Worst case" large>2.5</Metric></dl>);
    expect(screen.getByText("2.5")).toHaveClass("text-xl", "text-fg");
  });

  it("keeps an absent value at body size in the secondary colour, even when large", () => {
    render(<dl><Metric label="Worst case" large>not reported</Metric></dl>);
    const value = screen.getByText("not reported");
    expect(value).toHaveClass("text-sm", "text-fg2");
    expect(value).not.toHaveClass("text-xl");
  });
});
