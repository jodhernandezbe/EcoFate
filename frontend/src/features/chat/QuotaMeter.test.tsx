import { render, screen } from "@testing-library/react";

import { QuotaMeter } from "./QuotaMeter";

describe("QuotaMeter", () => {
  it("shows the turns left today", () => {
    const quota = { applies: true, limit: 5, used: 2, remaining: 3, resets_at: "2026-03-06T00:00:00Z" };
    render(<QuotaMeter quota={quota} />);
    expect(screen.getByText("3 turns left today")).toBeInTheDocument();
  });

  it("shows nothing for an exempt user or before it loads", () => {
    const exempt = { applies: false, limit: null, used: null, remaining: null, resets_at: null };
    expect(render(<QuotaMeter quota={exempt} />).container).toBeEmptyDOMElement();
    expect(render(<QuotaMeter quota={null} />).container).toBeEmptyDOMElement();
  });
});
