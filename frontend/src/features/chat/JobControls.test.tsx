import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { JobInfo } from "../../types/workspace";
import { JobControls } from "./JobControls";

const job = (change: Partial<JobInfo>): JobInfo => ({
  job_id: "a".repeat(32),
  tool: "assess_facilities",
  status: "queued",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: null,
  ended_at: null,
  position: 2,
  ...change,
});

afterEach(() => vi.useRealTimers());

describe("JobControls", () => {
  it("shows nothing without a job", () => {
    const { container } = render(<JobControls jobs={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says a queued job waits, and Cancel asks for that job", async () => {
    const onCancel = vi.fn();
    render(<JobControls jobs={[job({})]} onCancel={onCancel} />);
    expect(screen.getByRole("status")).toHaveTextContent("Assessment queued (2 ahead)");
    await userEvent.click(screen.getByRole("button", { name: "Cancel assessment" }));
    expect(onCancel).toHaveBeenCalledWith("a".repeat(32));
  });

  it("counts the running time up every second", () => {
    vi.useFakeTimers({ now: Date.parse("2026-01-01T00:01:20Z") });
    render(<JobControls jobs={[job({ status: "running", started_at: "2026-01-01T00:00:00Z", position: null })]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Assessment running, 1 min 20 s");
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Assessment running, 1 min 25 s");
  });

  it("disables Cancel with its reason once asked", () => {
    render(<JobControls jobs={[job({ status: "running" })]} cancelling={new Set(["a".repeat(32)])} onCancel={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Cancel assessment" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Stopping after the current step");
    expect(screen.getByRole("status")).toHaveTextContent("stopping after the current step");
  });

  it("shows a failed cancel as an alert", () => {
    render(<JobControls jobs={[job({})]} error="The assessment could not be cancelled. Try again." />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be cancelled");
  });

  it("offers no Cancel when the page gave no handler", () => {
    render(<JobControls jobs={[job({})]} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
