import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LeftNavRail } from "./LeftNavRail";

const ENTRIES = ["Workspace", "Clear workspace", "Generate report", "Monitoring", "Account", "Settings"];

function setup(over: Partial<Parameters<typeof LeftNavRail>[0]> = {}) {
  const props = {
    collapsed: false,
    onToggle: vi.fn(),
    view: "workspace" as const,
    onWorkspace: vi.fn(),
    onMonitoring: vi.fn(),
    onClear: vi.fn(),
    clearBlocked: null,
    onReport: vi.fn(),
    reportBlocked: null,
    reporting: false,
    reportError: null,
    onOpenSettings: vi.fn(),
    email: "ana@example.com",
    admin: true,
    onAccount: vi.fn(),
    ...over,
  };
  render(<LeftNavRail {...props} />);
  return props;
}

const names = () =>
  screen
    .getAllByRole("button")
    .map((button) => button.getAttribute("aria-label") ?? button.textContent ?? "")
    .filter((name) => !name.includes("navigation"));

describe("LeftNavRail expanded", () => {
  it("shows no toggle where the rail cannot expand", () => {
    setup({ onToggle: undefined });
    expect(screen.queryByRole("button", { name: /navigation/ })).toBeNull();
  });

  it("shows the brand and the entries in order, with no run list or New analysis", () => {
    setup();
    expect(screen.getByText("EcoFate")).toBeInTheDocument();
    expect(names()).toEqual(ENTRIES);
    expect(screen.getByRole("button", { name: "Workspace" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("list", { name: "Runs" })).toBeNull();
    expect(screen.queryByRole("button", { name: /New analysis/ })).toBeNull();
  });

  it("reports each action", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(screen.getByRole("button", { name: "Collapse navigation" }));
    await user.click(screen.getByRole("button", { name: "Workspace" }));
    await user.click(screen.getByRole("button", { name: "Monitoring" }));
    await user.click(screen.getByRole("button", { name: "Clear workspace" }));
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(props.onToggle).toHaveBeenCalledTimes(1);
    expect(props.onWorkspace).toHaveBeenCalledTimes(1);
    expect(props.onMonitoring).toHaveBeenCalledTimes(1);
    expect(props.onClear).toHaveBeenCalledTimes(1);
    expect(props.onReport).toHaveBeenCalledTimes(1);
    expect(props.onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("shows the signed-in email under the Account entry and opens the account sheet from it", async () => {
    const user = userEvent.setup();
    const props = setup();
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(props.onAccount).toHaveBeenCalledTimes(1);
  });

  it("shows a regular user every entry but Monitoring, Account and Settings last", () => {
    setup({ admin: false });
    expect(names()).toEqual(["Workspace", "Clear workspace", "Generate report", "Account", "Settings"]);
    expect(screen.queryByRole("button", { name: "Monitoring" })).toBeNull();
  });

  it("disables blocked entries and says why in their tooltip", async () => {
    const user = userEvent.setup();
    const props = setup({ clearBlocked: "a reply is in progress", reportBlocked: "there are no findings yet" });
    const clear = screen.getByRole("button", { name: "Clear workspace" });
    const report = screen.getByRole("button", { name: "Generate report" });
    expect(clear).toBeDisabled();
    expect(clear).toHaveAttribute("title", "Clear workspace: a reply is in progress");
    expect(report).toBeDisabled();
    expect(report).toHaveAttribute("title", "Generate report: there are no findings yet");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(props.onOpenSettings).toHaveBeenCalled();
  });

  it("describes why an entry is disabled for assistive technology too", () => {
    setup({ clearBlocked: "a reply is in progress", reportBlocked: null });
    expect(screen.getByRole("button", { name: "Clear workspace" })).toHaveAttribute("aria-description", "a reply is in progress");
    expect(screen.getByRole("button", { name: "Generate report" })).not.toHaveAttribute("aria-description");
  });

  it("marks the entry of the view on screen as the current page, and only that one", () => {
    setup({ view: "monitoring" });
    expect(screen.getByRole("button", { name: "Monitoring" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Workspace" })).not.toHaveAttribute("aria-current");
  });

  it("offers Monitoring as an enabled entry with no 'coming soon' note", () => {
    setup();
    const monitoring = screen.getByRole("button", { name: "Monitoring" });
    expect(monitoring).toBeEnabled();
    expect(monitoring).not.toHaveAttribute("title");
    expect(screen.queryByText(/Coming soon/i)).toBeNull();
  });

  it("shows a busy report entry that cannot start a second request", () => {
    setup({ reporting: true });
    const report = screen.getByRole("button", { name: "Generating report…" });
    expect(report).toBeDisabled();
    expect(report).toHaveAttribute("aria-busy", "true");
  });

  it("announces a failed report", () => {
    setup({ reportError: "The report could not be generated." });
    expect(screen.getByRole("alert")).toHaveTextContent("The report could not be generated.");
  });
});

describe("LeftNavRail collapsed", () => {
  it("shows icons only, each named and titled", () => {
    setup({ collapsed: true });
    expect(screen.queryByText("EcoFate")).toBeNull();
    expect(screen.getByRole("img", { name: "EcoFate" })).toHaveAttribute("title", "EcoFate");
    for (const name of [...ENTRIES, "Expand navigation"]) {
      const button = screen.getByRole("button", { name });
      expect(button.textContent).toBe("");
    }
    expect(screen.getByRole("button", { name: "Settings" })).toHaveAttribute("title", "Settings");
    expect(screen.getByRole("button", { name: "Monitoring" })).toHaveAttribute("title", "Monitoring");
  });

  it("opens Settings from its icon", async () => {
    const user = userEvent.setup();
    const props = setup({ collapsed: true });
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(props.onOpenSettings).toHaveBeenCalled();
  });

  it("keeps a failed report visible as a titled alert", () => {
    setup({ collapsed: true, reportError: "The report could not be generated." });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("title", "The report could not be generated.");
    expect(alert).toHaveTextContent("The report could not be generated.");
  });
});
