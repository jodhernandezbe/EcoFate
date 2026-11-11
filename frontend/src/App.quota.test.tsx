import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FakeMap } from "./test/fakeMaplibre";
import { meResponse, renderApp } from "./test/session";

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
const RESET = "2026-03-06T00:00:00Z";
const status = (remaining: number | null) =>
  remaining === null
    ? { applies: false, limit: null, used: null, remaining: null, resets_at: null }
    : { applies: true, limit: 3, used: 3 - remaining, remaining, resets_at: RESET };

const json = (body: object, init: ResponseInit = {}) => new Response(JSON.stringify(body), init);
const frame = (event: object) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);

/** A server whose quota answers come from `quotas` (the last repeats) and whose chat answers `chat`. */
function stub(quotas: (number | null | "down")[], chat: () => Response) {
  const remaining = [...quotas];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return Promise.resolve(meResponse());
      if (url.endsWith("/settings/client")) return Promise.resolve(json(CONFIG));
      if (url.endsWith("/settings/keys")) {
        const body = { openai: { configured: true }, services: { census: { available: false }, comptox: { available: false } } };
        return Promise.resolve(json(body));
      }
      if (url.endsWith("/usage/quota")) {
        const next = remaining.length > 1 ? remaining.shift() : remaining[0];
        if (next === "down") return Promise.resolve(json({ error: "down" }, { status: 503 }));
        return Promise.resolve(json(status(next ?? null)));
      }
      return Promise.resolve(chat());
    }),
  );
}

const answered = () =>
  new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(frame({ type: "token", seq: 0, text: "Hi" }));
        controller.enqueue(frame({ type: "turn_finished", seq: 1 }));
        controller.close();
      },
    }),
    { status: 200 },
  );
const refused = () =>
  json(
    { detail: "You have used all of today's assessments.", limit: 3, resets_at: RESET, correlation_id: "c1" },
    { status: 429, headers: { "retry-after": "3600" } },
  );

const dock = () => within(screen.getByRole("region", { name: "Copilot" }));

beforeEach(() => FakeMap.reset());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("daily quota in the chat dock", () => {
  it("shows the turns left in the header", async () => {
    stub([3], answered);
    await renderApp();
    expect(await dock().findByText("3 turns left today")).toBeInTheDocument();
    expect(dock().getByLabelText("Message")).toBeEnabled();
  });

  it("refreshes after a finished turn and disables the input when none are left", async () => {
    stub([1, 0], answered);
    const user = userEvent.setup();
    await renderApp();
    expect(await dock().findByText("1 turn left today")).toBeInTheDocument();
    await user.click(await dock().findByRole("button", { name: "Assess benzene" }));
    expect(await dock().findByText("No turns left today")).toBeInTheDocument();
    const field = dock().getByLabelText("Message");
    await waitFor(() => expect(field).toBeDisabled());
    expect(dock().getByText(/^Daily limit reached\. It resets at /)).toBeInTheDocument();
    expect(dock().getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("keeps the typed message and shows the limit when the server answers 429", async () => {
    stub([3, "down"], refused); // the refresh after the refusal fails: the 429 alone sets the state
    const user = userEvent.setup();
    await renderApp();
    await dock().findByText("3 turns left today");
    // Keyboard only: without layout, jsdom puts every element at (0, 0) and the panel splitters
    // take the focus of any pointer press.
    dock().getByLabelText("Message").focus();
    await user.keyboard("Assess toluene{Enter}");
    await dock().findByText("No turns left today");
    expect(dock().getByLabelText("Message")).toHaveValue("Assess toluene");
    expect(dock().getByLabelText("Message")).toBeDisabled();
    expect(dock().getByText(/^Daily limit reached\. It resets at /)).toBeInTheDocument();
    expect(dock().queryByText("Assess toluene", { selector: "p, div" })).not.toBeInTheDocument();
  });

  it("shows no quota figure to a user it does not apply to", async () => {
    stub([null], answered);
    await renderApp();
    await dock().findByLabelText("Message");
    await waitFor(() => expect(dock().queryByText(/turns? left today/)).not.toBeInTheDocument());
    expect(dock().queryByText(/Daily limit reached/)).not.toBeInTheDocument();
    expect(dock().getByLabelText("Message")).toBeEnabled();
  });
});
