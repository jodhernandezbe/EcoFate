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

describe("ChatComposer daily limit", () => {
  const reason = "Daily limit reached. It resets at 7:00 PM.";

  it("disables the input and sending, and says why", () => {
    render(
      <ChatComposer busy={false} hasKey limitReason={reason} onSend={() => undefined} onOpenSettings={() => undefined} />,
    );
    expect(screen.getByText(reason)).toHaveAttribute("role", "status");
    const field = screen.getByRole("textbox", { name: "Message" });
    expect(field).toBeDisabled();
    expect(field).toHaveAttribute("aria-description", reason);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("puts a refused message back in the input", () => {
    const { rerender } = render(
      <ChatComposer busy={false} hasKey onSend={() => undefined} onOpenSettings={() => undefined} />,
    );
    rerender(
      <ChatComposer busy={false} hasKey restore="Assess benzene" onSend={() => undefined} onOpenSettings={() => undefined} />,
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Assess benzene");
  });
});
