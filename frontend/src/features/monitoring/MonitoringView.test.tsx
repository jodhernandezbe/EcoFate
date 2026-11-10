import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type {
  SessionDetailResponse,
  SessionsResponse,
  SessionSummary,
  SessionTurn,
} from "../../types/workspace";
import { MonitoringView } from "./MonitoringView";

const SESSION: SessionSummary = {
  session_id: "s1",
  started_at: "2026-01-02T03:04:05+00:00",
  question: "Assess benzene",
  model: "model-x",
  turns: 1,
  model_calls: 3,
  tool_calls: 1,
  input_tokens: 23425,
  cached_input_tokens: 11136,
  output_tokens: 88,
  cost_usd: 0.030850000000000002,
  cost_status: "estimate",
  duration_ms: 8707,
  outcome: "ok",
  account: "ana@example.com",
};

const TURN: SessionTurn = {
  trace_id: "a".repeat(32),
  started_at: "2026-01-02T03:04:05+00:00",
  question: "Assess benzene",
  duration_ms: 8707,
  outcome: "ok",
  trace_url: "https://logfire.example/acme/assessor?q=trace",
  steps: [
    {
      kind: "model",
      name: "model-x-resolved",
      offset_ms: 30,
      duration_ms: 2249,
      outcome: "ok",
      input_tokens: 11196,
      output_tokens: 21,
    },
    {
      kind: "tool",
      name: "Fetching properties",
      offset_ms: 2297,
      duration_ms: 4290,
      outcome: "ok",
      input_tokens: null,
      output_tokens: null,
    },
    {
      kind: "model",
      name: "model-x-resolved",
      offset_ms: 6580,
      duration_ms: 1098,
      outcome: "error",
      input_tokens: null,
      output_tokens: null,
    },
  ],
};

/** The item at `index`, failing the test (not the types) when there is none. */
function nth<T>(items: T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`expected an item at ${index}`);
  return item;
}

const listing = (over: Partial<SessionsResponse> = {}): SessionsResponse => ({
  state: "ok",
  message: null,
  sessions: [SESSION],
  ...over,
});

const detail = (over: Partial<SessionDetailResponse> = {}): SessionDetailResponse => ({
  state: "ok",
  message: null,
  session: SESSION,
  turns: [TURN],
  ...over,
});

type Reply = object | (() => Promise<Response>) | number;

/** Routes `/api/v1/monitoring/*` to canned replies; a number is an error status. */
function stub(routes: Record<string, Reply>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input).replace("/api/v1/monitoring", "");
    const reply = routes[path];
    if (typeof reply === "function") return reply();
    if (typeof reply === "number") {
      return Promise.resolve(
        new Response(JSON.stringify({ error: "No such session was recorded." }), { status: reply }),
      );
    }
    return Promise.resolve(new Response(JSON.stringify(reply), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("MonitoringView sessions", () => {
  it("shows progress, then each session with its usage, cost, duration and status", async () => {
    stub({ "/sessions": listing() });
    render(<MonitoringView />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading sessions…");
    const table = await screen.findByRole("table", { name: /Recorded sessions/ });
    const row = nth(within(table).getAllByRole("row"), 1);
    for (const text of [
      "Assess benzene",
      "model-x",
      "23,425 in / 88 out",
      "~$0.0309",
      "8.7 s",
      "Completed",
    ]) {
      expect(row).toHaveTextContent(text);
    }
    expect(within(row).getAllByRole("cell")[4]).toHaveTextContent("3"); // model calls
  });

  it("says 'not reported' for a figure the server did not send, never 0 or a dash", async () => {
    const bare = {
      ...SESSION,
      model_calls: null,
      input_tokens: null,
      output_tokens: null,
      cost_usd: null,
      cost_status: "unknown" as const,
      duration_ms: null,
      question: null,
    };
    stub({ "/sessions": listing({ sessions: [bare] }) });
    render(<MonitoringView />);
    const row = nth(await screen.findAllByRole("row"), 1);
    expect(within(row).getAllByText("not reported").length).toBeGreaterThanOrEqual(5);
    expect(row).not.toHaveTextContent("$0");
  });

  it("explains the empty window and how to record a session", async () => {
    stub({ "/sessions": listing({ sessions: [] }) });
    render(<MonitoringView />);
    expect(await screen.findByText(/No sessions were recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("explains that monitoring is not set up, without asking for a token or offering a retry", async () => {
    const message = "Monitoring is not set up on this server: there is no Logfire read token.";
    stub({ "/sessions": listing({ state: "not_configured", message, sessions: [] }) });
    render(<MonitoringView />);
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByLabelText(/token/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it.each(["unavailable", "unauthorized"] as const)(
    "shows the %s message with a retry that reads again",
    async (state) => {
      const user = userEvent.setup();
      const responses = [
        listing({ state, message: "Logfire could not be reached.", sessions: [] }),
        listing(),
      ];
      const fetchMock = stub({
        "/sessions": () => Promise.resolve(new Response(JSON.stringify(responses.shift()))),
      });
      render(<MonitoringView />);
      expect(await screen.findByRole("alert")).toHaveTextContent("Logfire could not be reached.");
      expect(screen.queryByRole("table")).toBeNull();
      await user.click(screen.getByRole("button", { name: "Retry" }));
      expect(await screen.findByRole("table")).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(2);
    },
  );

  it("shows a failed request as an error with a retry", async () => {
    stub({ "/sessions": 500 });
    render(<MonitoringView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The sessions could not be loaded.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("reads the sessions again on Refresh", async () => {
    const user = userEvent.setup();
    const fetchMock = stub({ "/sessions": listing() });
    render(<MonitoringView />);
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("table");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("MonitoringView timeline", () => {
  it("opens a session with its calls in order, tokens, a failed call and a link to Logfire", async () => {
    const user = userEvent.setup();
    stub({ "/sessions": listing(), "/sessions/s1": detail() });
    render(<MonitoringView />);
    await user.click(await screen.findByRole("button", { name: /Jan 2, 2026|2026/ }));
    const turn = await screen.findByRole("region", { name: "Turn 1" });
    const steps = within(turn).getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent("Model call: model-x-resolved");
    expect(steps[0]).toHaveTextContent("11,196 in / 21 out");
    expect(steps[1]).toHaveTextContent("Tool call: Fetching properties");
    expect(steps[1]).toHaveTextContent("4.3 s");
    expect(steps[2]).toHaveTextContent("Failed");
    expect(steps[2]).toHaveTextContent("not reported");
    const link = within(turn).getByRole("link", { name: /Open in Logfire/ });
    expect(link).toHaveAttribute("href", TURN.trace_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("omits the link when the server could not build one", async () => {
    const user = userEvent.setup();
    stub({ "/sessions": listing(), "/sessions/s1": detail({ turns: [{ ...TURN, trace_url: null }] }) });
    render(<MonitoringView />);
    await user.click(await screen.findByRole("button", { name: /2026/ }));
    await screen.findByRole("region", { name: "Turn 1" });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("says when a turn recorded no model or tool calls", async () => {
    const user = userEvent.setup();
    stub({ "/sessions": listing(), "/sessions/s1": detail({ turns: [{ ...TURN, steps: [] }] }) });
    render(<MonitoringView />);
    await user.click(await screen.findByRole("button", { name: /2026/ }));
    expect(await screen.findByText(/No model or tool calls were recorded/)).toBeInTheDocument();
  });

  it("shows a session that cannot be loaded as an error", async () => {
    const user = userEvent.setup();
    stub({ "/sessions": listing(), "/sessions/s1": 404 });
    render(<MonitoringView />);
    await user.click(await screen.findByRole("button", { name: /2026/ }));
    expect(await screen.findByText(/The session could not be loaded\. No such session/)).toBeInTheDocument();
  });

  it("keeps the newest selection when an older reply arrives last", async () => {
    const user = userEvent.setup();
    const other = {
      ...SESSION,
      session_id: "s2",
      started_at: "2026-01-03T03:04:05+00:00",
      question: "Assess toluene",
    };
    let releaseFirst: (value: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => (releaseFirst = resolve));
    stub({
      "/sessions": listing({ sessions: [SESSION, other] }),
      "/sessions/s1": () => slow,
      "/sessions/s2": detail({ turns: [{ ...TURN, question: "Assess toluene" }] }),
    });
    render(<MonitoringView />);
    const buttons = await screen.findAllByRole("button", { name: /2026/ });
    await user.click(nth(buttons, 0));
    await user.click(nth(buttons, 1));
    await screen.findByText("Assess toluene", { selector: "p" });
    releaseFirst(
      new Response(JSON.stringify(detail({ turns: [{ ...TURN, question: "Assess benzene (late)" }] }))),
    );
    await waitFor(() => expect(screen.queryByText("Assess benzene (late)")).toBeNull());
    expect(screen.getByText("Assess toluene", { selector: "p" })).toBeInTheDocument();
  });
});
