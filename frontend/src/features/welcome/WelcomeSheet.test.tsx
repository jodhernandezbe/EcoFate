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

describe("WelcomeSheet", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has the title, the intro and the three steps in order", () => {
    setup();
    const dialog = screen.getByRole("dialog", { name: "Welcome to EcoFate" });
    expect(dialog).toHaveTextContent("screening-level chemical exposure and risk assessments from public inventories");
    const steps = within(dialog).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(steps).toEqual(["Add your OpenAI key", "Ask a question", "Read the results"]);
  });

  it("says no key yet, or key stored", () => {
    setup({ hasKey: false });
    expect(screen.getByRole("status")).toHaveTextContent("No key yet");
  });

  it("says key stored", () => {
    setup();
    expect(screen.getByRole("status")).toHaveTextContent("Key stored");
  });

  it("opens Settings from step 1", async () => {
    const props = setup({ hasKey: false });
    await userEvent.click(screen.getByRole("button", { name: "Open Settings" }));
    expect(props.onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("picking an example sends that prompt", async () => {
    const props = setup();
    await userEvent.click(screen.getByRole("button", { name: "Assess benzene" }));
    expect(props.onPick).toHaveBeenCalledWith("Assess benzene");
  });

  it("disables the examples and says a key is needed first when there is no key", async () => {
    const props = setup({ hasKey: false });
    const chip = screen.getByRole("button", { name: "Assess benzene" });
    expect(chip).toBeDisabled();
    expect(screen.getByText(/Add your OpenAI key first/)).toBeInTheDocument();
    expect(document.querySelector("[aria-description]")).toHaveAttribute("title", "Add your OpenAI key first (step 1).");
    await userEvent.click(chip);
    expect(props.onPick).not.toHaveBeenCalled();
  });

  it("disables the examples with a reason while a reply is running", () => {
    setup({ busy: true });
    expect(screen.getByRole("button", { name: "Assess benzene" })).toBeDisabled();
    expect(screen.getByText("A reply is in progress.")).toBeInTheDocument();
  });

  it("asks to type a question when there are no suggestions", () => {
    setup({ suggestions: [] });
    expect(screen.getByText("Type a question in the chat.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Suggestions" })).toBeNull();
  });

  it("names the Overview, Map, Chat and report and says results are screening level", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    for (const name of ["Overview", "Map", "Chat", "Report"]) expect(within(dialog).getByText(name)).toBeInTheDocument();
    expect(dialog).toHaveTextContent("screening level, not a regulatory determination");
  });

  it("dismisses with Get started, the close control and Escape", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(screen.getByRole("button", { name: "Get started" }));
    await user.click(screen.getByRole("button", { name: "Close Welcome to EcoFate panel" }));
    await user.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalledTimes(3);
  });

  it("never contains a key input", () => {
    setup({ hasKey: false });
    expect(document.querySelectorAll("input, textarea")).toHaveLength(0);
  });
});
