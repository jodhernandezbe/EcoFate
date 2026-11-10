import { render, screen } from "@testing-library/react";

import { App } from "../App";
import type { UserInfo } from "../types/workspace";

export const ADMIN: UserInfo = { id: "u-admin", email: "ana@example.com", role: "admin", verified: true };
export const MEMBER: UserInfo = { id: "u-member", email: "ben@example.com", role: "user", verified: true };

/** The `GET /auth/me` answer for a signed-in user. */
export const meResponse = (user: UserInfo = ADMIN): Response =>
  new Response(JSON.stringify(user), { status: 200 });

/** The answer of a signed-out server. */
export const signedOutResponse = (): Response =>
  new Response(JSON.stringify({ error: "Sign in to continue.", correlation_id: "c1" }), { status: 401 });

/** Render the app for a signed-in user and wait until the workspace (its rail) is on screen. */
export async function renderApp(user: UserInfo = ADMIN) {
  void user; // the stub of `/auth/me` decides who is signed in; this only documents the intent
  const view = render(<App />);
  await screen.findByRole("navigation", { name: "Navigation" });
  return view;
}
