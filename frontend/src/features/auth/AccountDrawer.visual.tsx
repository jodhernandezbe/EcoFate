import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import { MEMBER } from "../../test/session";
import { AccountDrawer } from "./AccountDrawer";

afterEach(cleanup);

const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

describe("account drawer, in a real browser", () => {
  it("opens named as itself, focused on its content, with a readable form width", async () => {
    render(
      <AccountDrawer open user={MEMBER} onClose={() => undefined} onSignOut={() => undefined} onGone={() => undefined} />,
    );
    const drawer = page.getByRole("dialog", { name: "Account" });
    await expect.element(page.getByRole("button", { name: "Close Account panel" })).toBeVisible();
    await expect.element(page.getByRole("button", { name: "Sign out", exact: true })).toHaveFocus();
    await expect.element(drawer).toMatchScreenshot(shot("account-drawer"));
  });
});
