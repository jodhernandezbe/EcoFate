import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { KeyOutcome } from "../../hooks/useKeyStatus";
import type { KeysStatusResponse } from "../../types/workspace";
import { SettingsDrawer } from "./SettingsDrawer";

const KEY = "sk-test-0123456789abcdef"; // pragma: allowlist secret
const SERVICES = { census: { available: false }, comptox: { available: false } }; // still sent by the API, not shown
const NO_KEY: KeysStatusResponse = { openai: { configured: false }, services: SERVICES };
const STORED: KeysStatusResponse = { openai: { configured: true }, services: SERVICES };

function setup(overrides: Partial<Parameters<typeof SettingsDrawer>[0]> = {}) {
  const props = {
    open: true,
    statuses: NO_KEY as KeysStatusResponse | null,
    busy: false,
    outcome: undefined as KeyOutcome | undefined,
    loadError: null,
    onSave: vi.fn().mockResolvedValue(true),
    onClear: vi.fn().mockResolvedValue(true),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<SettingsDrawer {...props} />);
  return props;
}

const openai = () => screen.getByRole("region", { name: "OpenAI API key", hidden: true });
const open = async (title: string) => {
  const button = screen.getByRole("button", { name: title });
  if (button.getAttribute("aria-expanded") === "false") await userEvent.click(button);
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("SettingsDrawer", () => {
  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says the state of the Assistant section in words while collapsed", () => {
    setup({ statuses: STORED });
    expect(screen.getByText("Key saved")).toBeInTheDocument();
  });

  it("says a key is missing, and nothing before the statuses are known", () => {
    const { unmount } = render(
      <SettingsDrawer open statuses={null} busy={false} outcome={undefined} loadError={null} onSave={vi.fn()} onClear={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.queryByText(/Key (saved|missing)/)).toBeNull();
    unmount();
    setup();
    expect(screen.getByText("Key missing")).toBeInTheDocument();
  });

  it("has only an Assistant section, for the OpenAI key", () => {
    setup();
    const assistant = screen.getByRole("region", { name: "Assistant" });
    expect(within(assistant).getByRole("region", { name: "OpenAI API key" })).toBeInTheDocument();
    expect(screen.getAllByRole("region", { hidden: true }).filter((r) => r.getAttribute("aria-label") !== "OpenAI API key")).toHaveLength(1);
  });

  it("shows no Census or CompTox entry and no Data services section", () => {
    setup({ statuses: STORED });
    expect(screen.queryByRole("button", { name: "Data services" })).toBeNull();
    expect(screen.queryByText(/Census|CompTox|Data services/)).toBeNull();
    expect(document.querySelectorAll("input")).toHaveLength(1); // the OpenAI key only
  });

  it("opens the Assistant section by itself while the key is missing, and not otherwise", () => {
    setup();
    expect(screen.getByRole("button", { name: "Assistant" })).toHaveAttribute("aria-expanded", "true");
  });

  it("starts collapsed when the key is stored", () => {
    setup({ statuses: STORED });
    expect(screen.getByRole("button", { name: "Assistant" })).toHaveAttribute("aria-expanded", "false");
  });

  it("explains the key as billed to the user's own account and masks the input", () => {
    setup();
    expect(screen.getByRole("button", { name: "About the OpenAI key" })).toHaveAccessibleDescription(
      /billed to your own OpenAI account/,
    );
    expect(within(openai()).getByLabelText("OpenAI API key")).toHaveAttribute("type", "password");
  });

  it("says the key is stored encrypted for the account, with no part of it, or that none is set", () => {
    const { unmount } = render(
      <SettingsDrawer open statuses={STORED} busy={false} outcome={undefined} loadError={null} onSave={vi.fn()} onClear={vi.fn()} onClose={vi.fn()} />,
    );
    return userEvent.click(screen.getByRole("button", { name: "Assistant" })).then(() => {
      expect(within(openai()).getByRole("status")).toHaveTextContent("Key stored encrypted for your account");
      expect(openai()).not.toHaveTextContent("Keychain");
      unmount();
      setup();
      expect(within(openai()).getByRole("status")).toHaveTextContent("No key configured");
    });
  });

  it("saves the typed key, empties the input and never uses browser storage", async () => {
    const user = userEvent.setup();
    const props = setup();
    const input = within(openai()).getByLabelText("OpenAI API key");
    expect(within(openai()).getByRole("button", { name: "Save OpenAI key" })).toBeDisabled();
    await user.type(input, KEY);
    await user.click(within(openai()).getByRole("button", { name: "Save OpenAI key" }));
    expect(props.onSave).toHaveBeenCalledWith(KEY);
    expect(input).toHaveValue("");
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(document.body.innerHTML).not.toContain(KEY);
  });

  it("Reset and the input's clear control empty the draft without saving", async () => {
    const user = userEvent.setup();
    const props = setup();
    const input = within(openai()).getByLabelText("OpenAI API key");
    await user.type(input, KEY);
    await user.click(within(openai()).getByRole("button", { name: "Reset OpenAI key input" }));
    expect(input).toHaveValue("");
    await user.type(input, KEY);
    await user.click(within(openai()).getByRole("button", { name: "Clear OpenAI key input" }));
    expect(input).toHaveValue("");
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("clears a stored key through the clear action only", async () => {
    const user = userEvent.setup();
    const props = setup({ statuses: STORED });
    await open("Assistant");
    await user.click(within(openai()).getByRole("button", { name: "Clear OpenAI key" }));
    expect(props.onClear).toHaveBeenCalledTimes(1);
  });

  it("shows the outcome of a save as a success or an error", () => {
    const { unmount } = render(
      <SettingsDrawer open statuses={NO_KEY} busy={false} outcome={{ kind: "success", message: "Key saved." }} loadError={null} onSave={vi.fn()} onClear={vi.fn()} onClose={vi.fn()} />,
    );
    expect(within(openai()).getByText("Key saved.")).toBeInTheDocument();
    unmount();
    setup({ outcome: { kind: "error", message: "The key was not accepted." } });
    expect(within(openai()).getByRole("alert")).toHaveTextContent("The key was not accepted.");
  });

  it("disables the actions while a request runs", () => {
    setup({ busy: true });
    expect(within(openai()).getByRole("button", { name: "Save OpenAI key" })).toBeDisabled();
  });

  it("shows a load error and closes with Escape", async () => {
    const user = userEvent.setup();
    const props = setup({ loadError: "Could not reach the server." });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the server.");
    await user.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalled();
  });
});
