import { render, screen } from "@testing-library/react";

import type { SessionSummary } from "../../types/workspace";
import { SessionsTable } from "./SessionsTable";

/** Synthetic round numbers, never real measurements. */
const SESSION: SessionSummary = {
  session_id: "s1",
  started_at: "2026-10-28T20:00:00Z",
  question: "Map hexane releases",
  model: "gpt-4.1",
  turns: 2,
  model_calls: 6,
  tool_calls: 4,
  input_tokens: 1000,
  output_tokens: 200,
  cached_input_tokens: null,
  cost_usd: 0.01,
  cost_status: "estimate",
  duration_ms: 12000,
  outcome: "ok",
};

const header = (name: string) => screen.getByRole("columnheader", { name });

describe("SessionsTable", () => {
  beforeEach(() => {
    render(<SessionsTable sessions={[SESSION]} selectedId={null} onSelect={() => {}} />);
  });

  it("can never outgrow its pane: fixed layout inside a container", () => {
    expect(screen.getByRole("table")).toHaveClass("w-full", "table-fixed");
    expect(screen.getByRole("table").parentElement?.parentElement).toHaveClass("@container");
  });

  it("always shows started, question, cost and status", () => {
    for (const name of ["Started", "Question", "Estimated cost", "Status"]) {
      expect(header(name)).not.toHaveClass("hidden");
    }
  });

  it("adds model and turns on a medium pane, and the counts, tokens and duration on a wide one", () => {
    for (const name of ["Model", "Turns"]) expect(header(name)).toHaveClass("hidden", "@3xl:table-cell");
    for (const name of ["Model calls", "Tool calls", "Tokens", "Duration"]) {
      expect(header(name)).toHaveClass("hidden", "@7xl:table-cell");
    }
  });

  it("truncates the question and keeps it whole in its tooltip", () => {
    const question = screen.getByText("Map hexane releases");
    expect(question).toHaveClass("truncate");
    expect(question).toHaveAttribute("title", "Map hexane releases");
  });

  it("names every column distinctly", () => {
    const names = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("SessionsTable failed rows", () => {
  it("says where to find the reason for a failed session, and only for failed ones", () => {
    render(
      <SessionsTable
        sessions={[
          { ...SESSION, session_id: "bad", outcome: "error" },
          { ...SESSION, session_id: "good", outcome: "ok" },
        ]}
        selectedId={null}
        onSelect={() => {}}
      />,
    );
    const failed = screen.getByText("Failed").closest("td");
    expect(failed).toHaveAttribute("title", expect.stringContaining("which step failed"));
    expect(screen.getByText("Completed").closest("td")).not.toHaveAttribute("title");
  });
});
