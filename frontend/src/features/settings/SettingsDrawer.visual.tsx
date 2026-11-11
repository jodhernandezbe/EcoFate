import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, it } from "vitest";
import { page } from "vitest/browser";

import type { KeysStatusResponse } from "../../types/workspace";
import { SettingsDrawer } from "./SettingsDrawer";

afterEach(cleanup);

const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;
const none = () => Promise.resolve(true);

const NO_KEY: KeysStatusResponse = {
  openai: { configured: false },
  services: { census: { available: false }, comptox: { available: true } },
};
const STORED: KeysStatusResponse = { ...NO_KEY, openai: { configured: true } };

function drawer(statuses: KeysStatusResponse, outcome?: { kind: "success" | "error"; message: string }) {
  render(
    <SettingsDrawer open statuses={statuses} busy={false} outcome={outcome} loadError={null} onSave={none} onClear={none} onClose={() => undefined} />,
  );
  return page.getByRole("dialog", { name: "Settings" });
}

describe("settings drawer, in a real browser", () => {
  it("no key stored: the Assistant section is open and says so", async () => {
    await expectShot(drawer(NO_KEY), "settings-no-key");
  });

  it("key stored, with the data services open: availability in words and no input", async () => {
    const view = drawer(STORED, { kind: "success", message: "Key saved." });
    await userEvent.click(page.getByRole("button", { name: "Assistant" }).element());
    await userEvent.click(page.getByRole("button", { name: "Data services" }).element());
    await expectShot(view, "settings-stored-services");
  });

  it("a rejected key shows the error in the Assistant section", async () => {
    await expectShot(drawer(NO_KEY, { kind: "error", message: "The API key is empty." }), "settings-error");
  });
});

async function expectShot(target: ReturnType<typeof page.getByRole>, name: string) {
  const { expect } = await import("vitest");
  await expect.element(target).toBeVisible();
  await expect.element(target).toMatchScreenshot(shot(name));
}
