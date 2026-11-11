import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EMPTY_WORKSPACE } from "./hooks/useWorkspaceStore";
import { extremum, workspace } from "./test/fixtures";
import { meResponse, renderApp } from "./test/session";

function stubApi(keyConfigured: boolean) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return Promise.resolve(meResponse());
    const status = { configured: keyConfigured };
    const body = url.endsWith("/settings/client")
      ? { model: "test-model" }
      : { openai: status, services: { census: { available: false }, comptox: { available: false } } };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("renders the workspace with the rail, both analysis panels and the copilot", async () => {
    stubApi(true);
    await renderApp();
    expect(screen.getByRole("navigation", { name: "Navigation" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Copilot" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/test-model/)).toBeInTheDocument());
  });

  it("points to Settings and blocks sending while no key is stored", async () => {
    stubApi(false);
    await renderApp();
    expect(await screen.findByText(/Add your OpenAI API key to start/)).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeDisabled();
  });

  it("opens the settings drawer from the rail without disturbing the workspace", async () => {
    stubApi(true);
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Assistant" }));
    expect(await screen.findByText("Key stored encrypted for your account")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Data services" }));
    expect(screen.getAllByText("Not available on this installation")).toHaveLength(2); // Census and CompTox
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the drawer from the composer's link while no key is stored", async () => {
    stubApi(false);
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: "Open Settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assistant" })).toHaveAttribute("aria-expanded", "true");
  });
});

const ANSWER_WITH_A_TOOL = [
  { type: "turn_started", seq: 0 },
  { type: "tool_status", seq: 1, phase: "started", call_id: "c1", tool_name: "t", label: "Queried EPA TRI releases", status: null },
  { type: "tool_status", seq: 2, phase: "finished", call_id: "c1", tool_name: "t", label: "Queried EPA TRI releases", status: "ok" },
  { type: "token", seq: 3, text: "All done." },
  {
    type: "usage",
    seq: 4,
    turn: { calls: 2, input_tokens: 1500, cached_input_tokens: 0, output_tokens: 250, complete: true, cost_usd: 0.005, cost_status: "estimate", priced_on: "2026-10-20" },
    session: { calls: 2, input_tokens: 1500, cached_input_tokens: 0, output_tokens: 250, complete: true, cost_usd: 0.005, cost_status: "estimate", priced_on: "2026-10-20" },
  },
  { type: "turn_finished", seq: 5 },
];

describe("onboarding and clearing the workspace", () => {
  function stubWithChips(events: object[] = ANSWER_WITH_A_TOOL) {
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
    if (url.endsWith("/auth/me")) return Promise.resolve(meResponse());
        calls.push({ url, method: init?.method ?? "GET" });
        const stored = { configured: true };
        let body: object = { openai: stored, services: { census: { available: false }, comptox: { available: false } } };
        if (url.endsWith("/settings/client")) body = { model: "m", suggestions: ["Assess benzene"] };
        if (url.endsWith("/chat/stream")) {
          const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
          return Promise.resolve(new Response(text, { status: 200 }));
        }
        if (init?.method === "DELETE" && url.includes("/chat/threads/")) {
          return Promise.resolve(new Response(null, { status: 204 }));
        }
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
      }),
    );
    return calls;
  }

  it("shows an off-topic redirect as a normal assistant message", async () => {
    const events = [
      { type: "turn_started", seq: 0 },
      { type: "scope", seq: 1, in_scope: false },
      { type: "guardrail_pivot", seq: 2, text: "I can't help with that, but I can map releases." },
      { type: "turn_finished", seq: 3 },
    ];
    stubWithChips(events);
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: "Assess benzene" }));
    expect(await screen.findByText(/I can't help with that, but I can map releases/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  async function clearWorkspace(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Clear workspace" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Clear" }));
  }

  it("runs a chip, shows its tool pill and answer, then clears the workspace", async () => {
    const calls = stubWithChips();
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: "Assess benzene" }));
    expect(await screen.findByText("All done.")).toBeInTheDocument();
    expect(screen.getByLabelText("Queried EPA TRI releases, done")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usage: 1.8K tokens, ~$0.0050" })).toBeInTheDocument();
    await clearWorkspace(user);
    const chat = within(screen.getByRole("region", { name: "Copilot" }));
    expect(await chat.findByRole("button", { name: "Assess benzene" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usage:/ })).toBeNull();
    expect(screen.queryByText("All done.")).toBeNull();
    // The cleared thread is discarded on the server too.
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("fills the summary from a workspace update and empties it when the workspace is cleared", async () => {
    const state = workspace({
      risk: { ...EMPTY_WORKSPACE.risk, hq_worst: extremum(2.5, "above"), reason: null },
    });
    stubWithChips([
      { type: "turn_started", seq: 0 },
      { type: "workspace_update", seq: 1, state },
      { type: "turn_finished", seq: 2 },
    ]);
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: "Assess benzene" }));
    expect(await screen.findByText("Above concern")).toBeInTheDocument();
    await clearWorkspace(user);
    await waitFor(() => expect(screen.queryByText("Above concern")).toBeNull());
  });
});
