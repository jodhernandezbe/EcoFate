import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";

import { AccountScreens } from "./AccountScreens";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const root = () => page.getByRole("main");
const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

describe("account screens, in a real browser", () => {
  it("sign in", async () => {
    render(<AccountScreens onSignedIn={() => undefined} />);
    await expect.element(root()).toMatchScreenshot(shot("sign-in"));
  });

  it("sign in with the server's message after a wrong password", async () => {
    const wrong = { error: "Incorrect email or password.", correlation_id: "c" };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(wrong), { status: 401 }))));
    render(<AccountScreens onSignedIn={() => undefined} />);
    await userEvent.type(page.getByLabelText("Email").element(), "ana@example.com");
    await userEvent.type(page.getByLabelText("Password").element(), "not the password");
    await userEvent.click(page.getByRole("button", { name: "Sign in" }).element());
    await expect.element(page.getByRole("alert")).toBeVisible();
    await expect.element(root()).toMatchScreenshot(shot("sign-in-error"));
  });

  it("sign up", async () => {
    render(<AccountScreens onSignedIn={() => undefined} />);
    await userEvent.click(page.getByRole("button", { name: "Create an account" }).element());
    await expect.element(root()).toMatchScreenshot(shot("sign-up"));
  });

  it("check your email", async () => {
    const accepted = new Response(JSON.stringify({ status: "accepted" }), { status: 202 });
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(accepted)));
    render(<AccountScreens onSignedIn={() => undefined} />);
    await userEvent.click(page.getByRole("button", { name: "Create an account" }).element());
    await userEvent.type(page.getByLabelText("Email").element(), "ana@example.com");
    await userEvent.type(page.getByLabelText("Password").element(), "a long enough password");
    await userEvent.click(page.getByRole("button", { name: "Create account" }).element());
    await expect.element(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
    await expect.element(root()).toMatchScreenshot(shot("check-email"));
  });

  it("forgot password", async () => {
    render(<AccountScreens onSignedIn={() => undefined} />);
    await userEvent.click(page.getByRole("button", { name: "Forgot password?" }).element());
    await expect.element(root()).toMatchScreenshot(shot("forgot"));
  });
});
