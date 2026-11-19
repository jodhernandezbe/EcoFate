import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WelcomeSheet } from "./WelcomeSheet";

function setup(over: Partial<Parameters<typeof WelcomeSheet>[0]> = {}) {
  const props = {
    open: true,
    hasKey: true,
    suggestions: ["Assess benzene", "Find facilities near me"] as string[] | undefined,
    busy: false,
    onPick: vi.fn(),
    onOpenSettings: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  render(<WelcomeSheet {...props} />);
  return props;
}

const example = () => screen.getByRole("button", { name: /Try “Assess benzene”/ });

describe("WelcomeSheet", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has the title, the intro and the three features in order", () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "Welcome to EcoFate" });
    expect(dialog).toHaveTextContent("Screening-level chemical exposure and risk, from public inventories");
    const titles = within(dialog).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(["Bring your OpenAI key", "Ask in plain words", "See the risk at a glance"]);
  });

  it("opens with focus on Continue", () => {
    setup();
    expect(screen.getByRole("button", { name: "Continue" })).toHaveFocus();
  });

  it("says no key yet and offers Settings", async () => {
    const props = setup({ hasKey: false });
    expect(screen.getByRole("status")).toHaveTextContent("No key yet.");
    await userEvent.click(screen.getByRole("button", { name: "Add your key in Settings" }));
    expect(props.onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("says key stored and no longer offers Settings", () => {
    setup();
    expect(screen.getByRole("status")).toHaveTextContent("Key stored.");
    expect(screen.queryByRole("button", { name: "Add your key in Settings" })).toBeNull();
  });

  it("the example sends the first configured prompt", async () => {
    const props = setup();
    await userEvent.click(example());
    expect(props.onPick).toHaveBeenCalledWith("Assess benzene");
  });

  it("disables the example and says a key is needed first when there is no key", async () => {
    const props = setup({ hasKey: false });
    expect(example()).toBeDisabled();
    expect(example()).toHaveAttribute("title", "Add your OpenAI key first.");
    expect(example()).toHaveAttribute("aria-description", "Add your OpenAI key first.");
    await userEvent.click(example());
    expect(props.onPick).not.toHaveBeenCalled();
  });

  it("disables the example with a reason while a reply is running", () => {
    setup({ busy: true });
    expect(example()).toBeDisabled();
    expect(example()).toHaveAttribute("title", "A reply is in progress.");
  });

  it("offers no example when none is configured", () => {
    setup({ suggestions: [] });
    expect(screen.queryByRole("button", { name: /Try/ })).toBeNull();
  });

  it("names the overview, the map and the report and says results are screening level", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("The overview, the map and a downloadable report");
    expect(dialog).toHaveTextContent("screening level, not a regulatory determination");
  });

  it("dismisses with Continue and Escape", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("never contains a key input", () => {
    setup({ hasKey: false });
    expect(document.querySelectorAll("input, textarea")).toHaveLength(0);
  });
});
