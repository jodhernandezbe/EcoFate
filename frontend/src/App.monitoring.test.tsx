import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { meResponse, renderApp } from "./test/session";


function stubApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return Promise.resolve(meResponse());
    const none = { configured: false };
    let body: object = { openai: { configured: true }, census: none, comptox: none };
    if (url.endsWith("/settings/client")) body = { model: "test-model" };
    if (url.endsWith("/monitoring/sessions")) body = { state: "ok", message: null, sessions: [] };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

const rail = () => screen.getByRole("navigation", { name: "Navigation" });
const entry = (name: string) => within(rail()).getByRole("button", { name });

describe("App Monitoring view", () => {
  it("opens Monitoring over the analysis area and marks it as the current page", async () => {
    stubApi();
    const user = userEvent.setup();
    await renderApp();
    expect(screen.queryByRole("region", { name: "Monitoring" })).toBeNull();
    await user.click(entry("Monitoring"));
    expect(await screen.findByRole("region", { name: "Monitoring" })).toBeInTheDocument();
    expect(entry("Monitoring")).toHaveAttribute("aria-current", "page");
    expect(entry("Workspace")).not.toHaveAttribute("aria-current");
  });

  it("keeps the overview, the map and the copilot mounted, the first two inert underneath", async () => {
    stubApi();
    const user = userEvent.setup();
    await renderApp();
    await user.click(entry("Monitoring"));
    await screen.findByRole("region", { name: "Monitoring" });
    for (const name of ["Overview", "Map"]) {
      const panel = document.querySelector(`section[aria-label="${name}"]`);
      expect(panel).not.toBeNull();
      expect(panel?.closest("[inert]")).not.toBeNull();
    }
    const copilot = screen.getByRole("region", { name: "Copilot" });
    expect(copilot.closest("[inert]")).toBeNull();
  });

  it("returns to the workspace exactly as it was left", async () => {
    stubApi();
    const user = userEvent.setup();
    await renderApp();
    await user.click(entry("Monitoring"));
    await screen.findByRole("region", { name: "Monitoring" });
    await user.click(entry("Workspace"));
    expect(screen.queryByRole("region", { name: "Monitoring" })).toBeNull();
    expect(entry("Workspace")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("region", { name: "Overview" }).closest("[inert]")).toBeNull();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
  });

  it("closes the settings drawer when Monitoring is opened", async () => {
    stubApi();
    const user = userEvent.setup();
    await renderApp();
    await user.click(entry("Settings"));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    await user.click(entry("Monitoring"));
    expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    expect(await screen.findByRole("region", { name: "Monitoring" })).toBeInTheDocument();
  });

  it("reads the sessions each time the view is opened", async () => {
    const fetchMock = stubApi();
    const user = userEvent.setup();
    await renderApp();
    const reads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/monitoring/sessions")).length;
    await user.click(entry("Monitoring"));
    await screen.findByText(/No sessions were recorded/);
    await user.click(entry("Workspace"));
    await user.click(entry("Monitoring"));
    await screen.findByText(/No sessions were recorded/);
    expect(reads()).toBe(2);
  });

  it("asks nothing of the user for a token", async () => {
    stubApi();
    const user = userEvent.setup();
    await renderApp();
    await user.click(entry("Monitoring"));
    await screen.findByRole("region", { name: "Monitoring" });
    expect(within(screen.getByRole("region", { name: "Monitoring" })).queryByRole("textbox")).toBeNull();
  });
});
