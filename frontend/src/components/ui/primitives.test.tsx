import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { AccordionSection } from "./Accordion";
import { Banner } from "./Banner";
import { BottomDrawer } from "./BottomDrawer";
import { InfoTooltip } from "./InfoTooltip";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <AccordionSection title="Assistant" open={open} onToggle={() => setOpen(!open)}>
      <p>inside</p>
    </AccordionSection>
  );
}

describe("AccordionSection", () => {
  it("toggles its content and reports it with aria-expanded", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const button = screen.getByRole("button", { name: "Assistant" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("inside")).not.toBeVisible();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("inside")).toBeVisible();
  });
});

describe("AccordionSection summary", () => {
  it("shows the summary beside the heading without changing the button's name", () => {
    render(
      <AccordionSection title="Assistant" open={false} onToggle={() => {}} summary="Key saved">
        <p>inside</p>
      </AccordionSection>,
    );
    expect(screen.getByRole("button", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByText("Key saved")).toBeInTheDocument();
  });
});

describe("InfoTooltip", () => {
  it("describes its button with the tooltip text", () => {
    render(<InfoTooltip label="About the key" text="Runs the assistant." />);
    const button = screen.getByRole("button", { name: "About the key" });
    expect(button).toHaveAccessibleDescription("Runs the assistant.");
  });
});

describe("Banner", () => {
  it("announces an error as an alert and a success as a status", () => {
    render(
      <>
        <Banner kind="error">Broke</Banner>
        <Banner kind="success">Saved</Banner>
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Broke");
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });
});

describe("BottomDrawer", () => {
  it("renders nothing while closed", () => {
    render(
      <BottomDrawer open={false} title="Settings" onClose={() => undefined}>
        body
      </BottomDrawer>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes with Escape and with the close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <BottomDrawer open title="Settings" onClose={onClose}>
        body
      </BottomDrawer>,
    );
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Close settings" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("is modal, and closes when the scrim behind it is pressed", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <BottomDrawer open title="Settings" onClose={onClose}>
        body
      </BottomDrawer>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await user.pointer({ keys: "[MouseLeft>]", target: dialog.parentElement as HTMLElement });
    await user.pointer({ keys: "[MouseLeft>]", target: dialog });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("takes the height of its content when asked, and a fixed height otherwise", () => {
    const { rerender } = render(
      <BottomDrawer open title="Settings" onClose={() => undefined} fitContent>
        body
      </BottomDrawer>,
    );
    expect(screen.getByRole("dialog").style.height).toBe("");
    rerender(
      <BottomDrawer open title="Settings" onClose={() => undefined}>
        body
      </BottomDrawer>,
    );
    expect(screen.getByRole("dialog").style.height).not.toBe("");
  });

  it("maximizes and restores", async () => {
    const user = userEvent.setup();
    render(
      <BottomDrawer open title="Settings" onClose={() => undefined}>
        body
      </BottomDrawer>,
    );
    const before = screen.getByRole("dialog").style.height;
    await user.click(screen.getByRole("button", { name: "Maximize settings" }));
    expect(screen.getByRole("dialog").style.height).not.toBe(before);
    await user.click(screen.getByRole("button", { name: "Restore settings size" }));
    expect(screen.getByRole("dialog").style.height).toBe(before);
  });

  it("resizes with the arrow keys, within limits", async () => {
    const user = userEvent.setup();
    render(
      <BottomDrawer open title="Settings" onClose={() => undefined} minPx={240}>
        body
      </BottomDrawer>,
    );
    const handle = screen.getByRole("separator", { name: "Resize settings" });
    const start = Number(handle.getAttribute("aria-valuenow"));
    handle.focus();
    await user.keyboard("{ArrowUp}");
    expect(Number(handle.getAttribute("aria-valuenow"))).toBeGreaterThan(start);
    for (let i = 0; i < 100; i += 1) await user.keyboard("{ArrowDown}");
    expect(Number(handle.getAttribute("aria-valuenow"))).toBe(240);
  });
});
