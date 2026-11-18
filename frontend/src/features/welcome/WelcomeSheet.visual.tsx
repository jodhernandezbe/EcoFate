import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, it } from "vitest";
import { page } from "vitest/browser";

import { WelcomeSheet } from "./WelcomeSheet";

afterEach(cleanup);

const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;
const noop = () => undefined;
const EXAMPLES = [
  "Map hexane (CAS 110-54-3) releases and compute exposure metrics",
  "How does the screening dispersion model pick the worst case?",
];

function sheet(hasKey: boolean) {
  render(
    <WelcomeSheet open hasKey={hasKey} suggestions={EXAMPLES} busy={false} onPick={noop} onOpenSettings={noop} onClose={noop} />,
  );
  return page.getByRole("dialog", { name: "Welcome to EcoFate" });
}

describe("welcome sheet, in a real browser", () => {
  it("first visit without a key: examples disabled and say why", async () => {
    await expectShot(sheet(false), "welcome-no-key");
  });

  it("key stored: the examples can be sent", async () => {
    await expectShot(sheet(true), "welcome-stored");
  });
});

async function expectShot(target: ReturnType<typeof page.getByRole>, name: string) {
  const { expect } = await import("vitest");
  await expect.element(target).toBeVisible();
  await expect.element(target).toMatchScreenshot(shot(name));
}
