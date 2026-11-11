import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { KeyOutcome } from "../../hooks/useKeyStatus";
import type { KeysStatusResponse } from "../../types/workspace";
import { SettingsDrawer } from "./SettingsDrawer";

const KEY = "sk-test-0123456789abcdef"; // pragma: allowlist secret
const NO_SERVICES = { census: { available: false }, comptox: { available: false } };
const BOTH_SERVICES = { census: { available: true }, comptox: { available: true } };
const NO_KEY: KeysStatusResponse = { openai: { configured: false }, services: NO_SERVICES };
const STORED: KeysStatusResponse = { openai: { configured: true }, services: BOTH_SERVICES };

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
const service = (label: string) => screen.getByRole("region", { name: `${label} service`, hidden: true });
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

  it("says the state of each section in words while collapsed", () => {
    setup({ statuses: { openai: { configured: true }, services: { ...NO_SERVICES, census: { available: true } } } });
    expect(screen.getByText("Key saved")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 available")).toBeInTheDocument();
  });

  it("says a key is missing, and nothing before the statuses are known", () => {
    const { unmount } = render(
      <SettingsDrawer open statuses={null} busy={false} outcome={undefined} loadError={null} onSave={vi.fn()} onClear={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.queryByText(/Key (saved|missing)/)).toBeNull();
    unmount();
    setup();
    expect(screen.getByText("Key missing")).toBeInTheDocument();
    expect(screen.getByText("0 of 2 available")).toBeInTheDocument();
  });

  it("has an Assistant section for the OpenAI key and a read-only Data services section", async () => {
    setup();
    await open("Data services");
    const assistant = screen.getByRole("region", { name: "Assistant" });
    const data = screen.getByRole("region", { name: "Data services" });
    expect(within(assistant).getByRole("region", { name: "OpenAI API key" })).toBeInTheDocument();
    expect(within(data).getByRole("region", { name: "Census service" })).toBeInTheDocument();
    expect(within(data).getByRole("region", { name: "CompTox service" })).toBeInTheDocument();
  });

  it("opens the Assistant section by itself while the key is missing, and not otherwise", () => {
    setup();
    expect(screen.getByRole("button", { name: "Assistant" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Data services" })).toHaveAttribute("aria-expanded", "false");
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

  it("renders no input for the Census or CompTox keys", async () => {
    setup();
    await open("Data services");
    expect(document.querySelectorAll("input")).toHaveLength(1); // the OpenAI key only
    expect(screen.queryByLabelText("Census API key")).toBeNull();
    expect(screen.queryByLabelText("CompTox API key")).toBeNull();
    for (const label of ["Census", "CompTox"]) {
      expect(within(service(label)).queryByRole("textbox")).toBeNull();
      expect(within(service(label)).queryByRole("button", { name: /save|clear|reset/i })).toBeNull();
    }
  });

  it("says whether each data service is provided by this installation", async () => {
    setup({ statuses: { openai: { configured: true }, services: { census: { available: false }, comptox: { available: true } } } });
    await open("Data services");
    expect(within(service("CompTox")).getByRole("status")).toHaveTextContent("Provided by this installation");
    expect(within(service("Census")).getByRole("status")).toHaveTextContent("Not available on this installation");
  });

  it("says which lookups are missing for an unavailable service only", async () => {
    setup({ statuses: { openai: { configured: true }, services: { census: { available: false }, comptox: { available: true } } } });
    await open("Data services");
    expect(service("Census")).toHaveTextContent("population counts fall back");
    expect(service("CompTox")).not.toHaveTextContent("cannot be looked up");
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
