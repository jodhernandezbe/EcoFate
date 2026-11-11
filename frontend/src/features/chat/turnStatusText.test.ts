import { STOPPING, turnStatusText } from "./turnStatusText";

describe("turnStatusText", () => {
  it("says how many turns are ahead while queued", () => {
    expect(turnStatusText({ phase: "queued", label: null, position: 2 })).toBe(
      "Waiting for a worker (about 2 ahead)",
    );
  });

  it("does not count when nothing is ahead or the position is unknown", () => {
    expect(turnStatusText({ phase: "queued", label: null, position: 0 })).toBe("Waiting for a worker");
    expect(turnStatusText({ phase: "queued", label: null, position: null })).toBe("Waiting for a worker");
  });

  it("names the running step", () => {
    expect(turnStatusText({ phase: "running_tool", label: "Fetching chemical properties", position: null })).toBe(
      "Running: Fetching chemical properties",
    );
  });

  it("says thinking otherwise", () => {
    expect(turnStatusText(null)).toBe("Thinking");
    expect(turnStatusText({ phase: "running", label: null, position: null })).toBe("Thinking");
    expect(turnStatusText({ phase: "thinking", label: null, position: null })).toBe("Thinking");
    expect(turnStatusText({ phase: "running_tool", label: null, position: null })).toBe("Thinking");
  });

  it("has a fixed text while stopping", () => {
    expect(STOPPING).toBe("Stopping after the current step");
  });
});
