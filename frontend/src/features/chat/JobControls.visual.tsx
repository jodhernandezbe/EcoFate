import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";

import type { JobInfo } from "../../types/workspace";
import { ChatDock } from "./ChatDock";

afterEach(cleanup);

const frame = () => page.getByTestId("frame");
const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;
const noop = () => undefined;
const ID = "a".repeat(32);
// The running time is read from the browser's clock: it is fixed so the picture is the same each run.
const NOW = Date.parse("2026-01-01T00:01:20Z");
const queued: JobInfo = {
  job_id: ID,
  tool: "assess_facilities",
  status: "queued",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: null,
  ended_at: null,
  position: 2,
};
const running: JobInfo = { ...queued, status: "running", started_at: "2026-01-01T00:00:00Z", position: null };

function Dock({ job, cancelling = false }: { job: JobInfo; cancelling?: boolean }) {
  return (
    <div data-testid="frame" style={{ width: 420, height: 260, background: "var(--bg)", color: "var(--fg)" }}>
      <ChatDock
        messages={[]}
        busy={false}
        hasKey
        model="gpt-4.1"
        usage={null}
        jobs={[job]}
        cancellingJobs={new Set(cancelling ? [ID] : [])}
        onCancelJob={noop}
        onSend={noop}
        onClear={noop}
        onOpenSettings={noop}
        onCollapse={noop}
      />
    </div>
  );
}

describe("background job status line in the chat dock, in a real browser", () => {
  it("shows a queued assessment and how many are ahead", async () => {
    render(<Dock job={queued} />);
    await expect.element(frame()).toMatchScreenshot(shot("job-queued"));
  });

  it("shows a running assessment with its running time", async () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    render(<Dock job={running} />);
    await expect.element(frame()).toMatchScreenshot(shot("job-running"));
    vi.useRealTimers();
  });

  it("dims Cancel once it was asked", async () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    render(<Dock job={running} cancelling />);
    await expect.element(frame()).toMatchScreenshot(shot("job-cancelling"));
    vi.useRealTimers();
  });
});
