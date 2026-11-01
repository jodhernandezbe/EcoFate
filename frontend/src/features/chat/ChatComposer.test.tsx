import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChatComposer } from "./ChatComposer";

describe("ChatComposer focus", () => {
  it("draws the focus ring on the pill, not on the inner field", () => {
    render(<ChatComposer busy={false} hasKey onSend={() => undefined} onOpenSettings={() => undefined} />);
    const field = screen.getByRole("textbox", { name: "Message" });
    expect(field).toHaveAttribute("data-ring-on-parent");
    expect(field.parentElement).toHaveClass("focus-within:outline-2", "focus-within:outline-accent");
  });

  it("keeps the global focus ring for other controls", () => {
    render(<ChatComposer busy={false} hasKey onSend={() => undefined} onOpenSettings={() => undefined} />);
    expect(screen.getByRole("button", { name: "Send" })).not.toHaveAttribute("data-ring-on-parent");
  });
});
