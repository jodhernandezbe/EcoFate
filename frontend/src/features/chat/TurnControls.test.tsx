import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { TurnInterruption } from "../../types/workspace";
import { TurnControls, type TurnControlsProps } from "./TurnControls";

type Reason = TurnInterruption["reason"];
const stop = (reason: Reason, resumable = true): TurnInterruption => ({
  reason,
  resumable,
  message: `Stopped: ${reason}.`,
});
const idle: TurnControlsProps = {
  busy: false,
  status: null,
  stopping: false,
  interrupted: null,
};
const draw = (props: Partial<TurnControlsProps>) =>
  render(<TurnControls {...idle} {...props} />);

describe("TurnControls after an interruption", () => {
  it.each<Reason>([
    "out_of_credits",
    "rate_limited",
    "provider_down",
    "step_limit",
    "worker_lost",
  ])(
    "shows the fixed text and a Resume button for %s, without Settings",
    (reason) => {
      const onResume = vi.fn();
      draw({ interrupted: stop(reason), onResume, onOpenSettings: vi.fn() });
      expect(screen.getByRole("status")).toHaveTextContent(
        `Stopped: ${reason}.`,
      );
      screen.getByRole("button", { name: "Resume" }).click();
      expect(onResume).toHaveBeenCalledOnce();
      expect(
        screen.queryByRole("button", { name: "Open Settings" }),
      ).toBeNull();
    },
  );

  it("offers Resume and Open Settings for a rejected key", () => {
    const onOpenSettings = vi.fn();
    draw({ interrupted: stop("bad_key"), onResume: vi.fn(), onOpenSettings });
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    screen.getByRole("button", { name: "Open Settings" }).click();
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });

  it("shows the message without a Resume button when it can no longer be resumed", () => {
    draw({ interrupted: stop("out_of_credits", false), onResume: vi.fn() });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Stopped: out_of_credits.",
    );
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });

  it("shows nothing when the conversation is idle", () => {
    const { container } = draw({});
    expect(container).toBeEmptyDOMElement();
  });
});

describe("TurnControls while a turn runs", () => {
  it("shows the turn's status", () => {
    draw({
      busy: true,
      status: {
        phase: "running_tool",
        label: "Fetching chemical properties",
        position: null,
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Running: Fetching chemical properties…",
    );
  });

  it("says how many turns are ahead while it waits for a worker", () => {
    draw({ busy: true, status: { phase: "queued", label: null, position: 2 } });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waiting for a worker (about 2 ahead)…",
    );
  });

  it("offers Stop, which asks the turn to stop", async () => {
    const onStop = vi.fn();
    draw({ busy: true, onStop });
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("disables Stop with its reason once a stop was asked for", () => {
    draw({ busy: true, stopping: true, onStop: () => {} });
    const button = screen.getByRole("button", { name: "Stop" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      "aria-description",
      "Stopping after the current step",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Stopping after the current step…",
    );
  });

  it("does not offer Resume of an earlier stop while a turn runs", () => {
    draw({ busy: true, interrupted: stop("rate_limited"), onResume: vi.fn() });
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });
});
