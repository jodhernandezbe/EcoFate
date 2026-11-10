import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ToolStep } from "../../hooks/chatState";
import { ToolExecutionPills } from "./ToolExecutionPill";

const steps: ToolStep[] = [
  { callId: "1", label: "Queried EPA TRI releases", state: "done" },
  { callId: "2", label: "Retrieved meteorology", state: "done" },
  { callId: "3", label: "Counted Census receptors", state: "running" },
  { callId: "4", label: "Computed screening dispersion and risk", state: "error" },
];

describe("ToolExecutionPills", () => {
  it("renders nothing without steps", () => {
    const { container } = render(<ToolExecutionPills steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every step on its own row, open by default", () => {
    render(<ToolExecutionPills steps={steps} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    const toggle = screen.getByRole("button", { name: /1 running/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("list")).toBeVisible();
  });

  it("is always a vertical stack, never a row that wraps or clips", () => {
    render(<ToolExecutionPills steps={steps} />);
    const list = screen.getByRole("list");
    expect(list).toHaveClass("flex-col");
    expect(list.className).not.toMatch(/flex-wrap|flex-nowrap|overflow-hidden/);
  });

  it("hides and shows the steps from the header, still vertical when shown again", async () => {
    const user = userEvent.setup();
    render(<ToolExecutionPills steps={steps} />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list")).toBeNull();
    await user.click(screen.getByRole("button"));
    expect(screen.getByRole("list")).toHaveClass("flex-col");
  });

  it("names each pill's label and state for assistive technology", () => {
    render(<ToolExecutionPills steps={steps} />);
    expect(screen.getByLabelText("Queried EPA TRI releases, done")).toBeInTheDocument();
    expect(screen.getByLabelText("Counted Census receptors, running")).toBeInTheDocument();
    expect(screen.getByLabelText("Computed screening dispersion and risk, failed")).toBeInTheDocument();
  });

  it("summarises a finished turn by its step count", () => {
    render(<ToolExecutionPills steps={steps.map((s) => ({ ...s, state: "done" as const }))} />);
    expect(screen.getByRole("button", { name: "4 steps" })).toBeInTheDocument();
  });

  it("says one step in the singular", () => {
    render(<ToolExecutionPills steps={[{ callId: "1", label: "Queried EPA TRI releases", state: "done" }]} />);
    expect(screen.getByRole("button", { name: "1 step" })).toBeInTheDocument();
  });
});
