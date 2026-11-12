import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EMPTY_WORKSPACE } from "./hooks/useWorkspaceStore";
import { FakeMap } from "./test/fakeMaplibre";
import { extremum, facility, workspace } from "./test/fixtures";
import { meResponse, renderApp } from "./test/session";

const ASSESSED = workspace({
  framing_version: 3,
  facilities: [facility()],
  risk: { ...EMPTY_WORKSPACE.risk, hq_worst: extremum(2.5, "high"), reason: null },
});

const CONFIG = {
  model: "m",
  suggestions: ["Assess benzene"],
  map: {
    light_style: "l",
    dark_style: "d",
    marker_min_px: 4,
    marker_max_px: 9,
    initial_view: { west: -125, south: 24.5, east: -66.9, north: 49.5 },
  },
};

interface Stub {
  calls: string[];
  reset: () => Response;
  report: () => Response;
}

const frame = (event: object) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);


function stub(options: { never?: boolean } = {}): Stub {
  const state: Stub = {
    calls: [],
    reset: () => new Response(null, { status: 204 }),
    report: () =>
      // Raw bytes, not a jsdom Blob: jsdom's Blob has no stream(), which Response.blob() needs.
      new Response(new TextEncoder().encode("docx"), {
        status: 200,
        headers: { "content-disposition": 'attachment; filename="exposure-screening-chemical-2026-01-02.docx"' },
      }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
    if (url.endsWith("/auth/me")) return Promise.resolve(meResponse());
      state.calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/settings/client")) return Promise.resolve(new Response(JSON.stringify(CONFIG)));
      if (url.endsWith("/settings/keys")) {
        const body = { openai: { configured: true }, services: { census: { available: false }, comptox: { available: false } } };
        return Promise.resolve(new Response(JSON.stringify(body)));
      }
      if (url.endsWith("/report")) return Promise.resolve(state.report());
      if (init?.method === "DELETE") return Promise.resolve(state.reset());
      const open = new ReadableStream({
        start(controller) {
          controller.enqueue(frame({ type: "token", seq: 0, text: "Hi" }));
          controller.enqueue(frame({ type: "workspace_update", seq: 1, state: ASSESSED }));
          if (!options.never) {
            controller.enqueue(frame({ type: "turn_finished", seq: 2 }));
            controller.close();
          }
        },
      });
      return Promise.resolve(new Response(open, { status: 200 }));
    }),
  );
  return state;
}

const rail = () => within(screen.getByRole("navigation", { name: "Navigation" }));
const chat = () => within(screen.getByRole("region", { name: "Copilot" }));

async function runOnce(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await chat().findByRole("button", { name: "Assess benzene" }));
  await screen.findByText("Hi");
  await waitFor(() => expect(chat().getByLabelText("Message")).toBeEnabled());
}

beforeEach(() => FakeMap.reset());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("clear workspace", () => {
  it("is disabled while the workspace is empty", async () => {
    stub();
    await renderApp();
    const clear = rail().getByRole("button", { name: "Clear workspace" });
    expect(clear).toBeDisabled();
    expect(clear).toHaveAttribute("title", "Clear workspace: the workspace is already empty");
  });

  it("asks first and Escape changes nothing", async () => {
    const api = stub();
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    const clear = rail().getByRole("button", { name: "Clear workspace" });
    // Opened from the keyboard: without layout, jsdom puts every element at (0, 0) and the
    // panel splitters take the focus of any pointer press.
    clear.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("alertdialog", { name: "Clear this workspace?" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(clear).toHaveFocus();
    expect(screen.getByText("Hi")).toBeInTheDocument();
    expect(api.calls.some((call) => call.startsWith("DELETE"))).toBe(false);
  });

  it("discards the thread, empties everything and reframes the map on the United States", async () => {
    const api = stub();
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    // The ribbon's status joins the legend's always-present "High" label.
    const shown = (await screen.findAllByText("High")).length;
    await waitFor(() => expect(FakeMap.instances.length).toBeGreaterThan(0));
    const map = FakeMap.last;
    const before = map.fits.length;
    await user.click(rail().getByRole("button", { name: "Clear workspace" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Clear" }));
    expect(await chat().findByRole("button", { name: "Assess benzene" })).toBeInTheDocument();
    expect(screen.queryByText("Hi")).toBeNull();
    await waitFor(() => expect(screen.queryAllByText("High").length).toBeLessThan(shown));
    expect(api.calls.filter((call) => call.startsWith("DELETE"))).toHaveLength(1);
    await waitFor(() => expect(map.fits.length).toBe(before + 1));
    expect(map.fits.at(-1)?.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
  });

  it("keeps the workspace and says so when the server refuses", async () => {
    const api = stub();
    api.reset = () => new Response(JSON.stringify({ error: "A turn is already running for this thread.", correlation_id: "c" }), { status: 409 });
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    await user.click(rail().getByRole("button", { name: "Clear workspace" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Clear" }));
    expect(await chat().findByText(/The workspace could not be cleared/)).toBeInTheDocument();
    expect(screen.getByText("Hi")).toBeInTheDocument();
  });

  it("is disabled while a reply streams", async () => {
    stub({ never: true });
    const user = userEvent.setup();
    await renderApp();
    await user.click(await chat().findByRole("button", { name: "Assess benzene" }));
    await screen.findByText("Hi");
    const clear = rail().getByRole("button", { name: "Clear workspace" });
    expect(clear).toBeDisabled();
    expect(clear).toHaveAttribute("title", "Clear workspace: a reply is in progress");
    expect(rail().getByRole("button", { name: "Generate report" })).toBeDisabled();
  });

  it("opens the same confirmation from the chat's clear button", async () => {
    stub();
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    await user.click(chat().getByRole("button", { name: "Clear chat" }));
    expect(screen.getByRole("alertdialog", { name: "Clear this workspace?" })).toBeInTheDocument();
  });
});

describe("generate report", () => {
  it("is disabled until there are findings", async () => {
    stub();
    await renderApp();
    const report = rail().getByRole("button", { name: "Generate report" });
    expect(report).toBeDisabled();
    expect(report).toHaveAttribute("title", "Generate report: there are no findings yet");
  });

  it("downloads the server's file and leaves the workspace unchanged", async () => {
    const api = stub();
    const saved: string[] = [];
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    await user.click(rail().getByRole("button", { name: "Generate report" }));
    await waitFor(() => expect(saved).toEqual(["exposure-screening-chemical-2026-01-02.docx"]));
    expect(api.calls.some((call) => call.startsWith("GET") && call.endsWith("/report"))).toBe(true);
    expect(screen.getByText("Hi")).toBeInTheDocument();
  });

  it("shows the server's message when the report fails", async () => {
    const api = stub();
    api.report = () => new Response(JSON.stringify({ error: "That run is no longer available.", correlation_id: "c" }), { status: 404 });
    const user = userEvent.setup();
    await renderApp();
    await runOnce(user);
    await user.click(rail().getByRole("button", { name: "Generate report" }));
    expect(await rail().findByRole("alert")).toHaveTextContent(
      "The report could not be generated. That run is no longer available.",
    );
  });
});

describe("workspace entry", () => {
  it("closes the Settings drawer", async () => {
    stub();
    const user = userEvent.setup();
    await renderApp();
    await user.click(rail().getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    await user.click(rail().getByRole("button", { name: "Workspace" }));
    expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
  });
});
