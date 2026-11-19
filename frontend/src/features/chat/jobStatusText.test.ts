import type { JobInfo } from "../../types/workspace";
import { formatElapsed, jobStatusText } from "./jobStatusText";

const NOW = Date.parse("2026-01-01T00:10:00Z");
const job = (change: Partial<JobInfo>): JobInfo => ({
  job_id: "j".repeat(32),
  tool: "assess_facilities",
  status: "queued",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: null,
  ended_at: null,
  position: null,
  ...change,
});

describe("formatElapsed", () => {
  it.each([
    [0, "0 s"],
    [45, "45 s"],
    [80, "1 min 20 s"],
    [120, "2 min"],
    [3900, "1 h 5 min"],
    [7200, "2 h"],
    [-5, "0 s"],
  ])("%s seconds reads %s", (seconds, text) => {
    expect(formatElapsed(seconds)).toBe(text);
  });
});

describe("jobStatusText", () => {
  it("says how many jobs are ahead while queued, and nothing about a zero queue", () => {
    expect(jobStatusText(job({ position: 2 }), NOW, false)).toBe("Assessment queued (2 ahead)");
    expect(jobStatusText(job({ position: 0 }), NOW, false)).toBe("Assessment queued");
    expect(jobStatusText(job({ position: null }), NOW, false)).toBe("Assessment queued");
  });

  it("says how long it has run, from the server's start time", () => {
    const running = job({ status: "running", started_at: "2026-01-01T00:08:40Z" });
    expect(jobStatusText(running, NOW, false)).toBe("Assessment running, 1 min 20 s");
  });

  it("does not guess a running time the server did not send, or a malformed one", () => {
    expect(jobStatusText(job({ status: "running" }), NOW, false)).toBe("Assessment running");
    expect(jobStatusText(job({ status: "running", started_at: "soon" }), NOW, false)).toBe("Assessment running");
  });

  it("names a tool this build does not know as a background job", () => {
    expect(jobStatusText(job({ tool: "other", position: 1 }), NOW, false)).toBe("Background job queued (1 ahead)");
  });

  it("says it is stopping once asked", () => {
    expect(jobStatusText(job({ status: "running" }), NOW, true)).toBe("Assessment: stopping after the current step");
  });
});
