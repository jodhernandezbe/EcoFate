import { render, screen } from "@testing-library/react";

import { StatusPill } from "./StatusPill";
import { TierPill } from "./TierPill";

describe("StatusPill", () => {
  it.each([
    ["low", "Low"],
    ["moderate", "Moderate"],
    ["high", "High"],
    [null, "Not computed"],
  ] as const)("says %s in words", (status, label) => {
    render(<StatusPill status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders a band it does not know as not reported", () => {
    render(<StatusPill status={"above" as never} />);
    expect(screen.getByText("not reported")).toHaveAttribute("data-status", "none");
  });
});

describe("StatusPill label", () => {
  it("replaces the default words but keeps the status", () => {
    render(<StatusPill status="high" label="High, screening priority" />);
    expect(screen.getByText("High, screening priority")).toHaveAttribute("data-status", "high");
  });
});

describe("TierPill", () => {
  it.each([
    ["low", "Low"],
    ["moderate", "Moderate"],
    ["high", "High"],
    [null, "Not computed"],
  ] as const)("says %s in words", (tier, label) => {
    render(<TierPill tier={tier} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders an old saved tier as not reported without crashing", () => {
    render(<TierPill tier={"exceedance" as never} prefix="Worker" />);
    expect(screen.getByText("Worker not reported")).toHaveAttribute("data-tier", "none");
  });
});
