import { render, screen } from "@testing-library/react";

import { App } from "../App";
import type { UserInfo } from "../types/workspace";

export const ADMIN: UserInfo = { id: "u-admin", email: "ana@example.com", role: "admin", verified: true };
export const MEMBER: UserInfo = { id: "u-member", email: "ben@example.com", role: "user", verified: true };

/** The `GET /auth/me` answer for a signed-in user. */
export const meResponse = (user: UserInfo = ADMIN): Response =>
  new Response(JSON.stringify(user), { status: 200 });

/** The answer of a signed-out server. */
/** A user with no thread yet: the page opens on a fresh one. */
export const noCurrentThread = (): Response =>
  new Response(JSON.stringify({ error: "That run is no longer available." }), { status: 404 });

export const signedOutResponse = (): Response =>
  new Response(JSON.stringify({ error: "Sign in to continue.", correlation_id: "c1" }), { status: 401 });

/** Render the app for a signed-in user and wait until the workspace (its rail) is on screen. */
export async function renderApp(user: UserInfo = ADMIN, options: { welcome?: boolean } = {}) {
  void user; // the stub of `/auth/me` decides who is signed in; this only documents the intent
  // The welcome sheet opens on a first visit; other tests start as a returning user.
  if (!options.welcome) for (const known of [ADMIN, MEMBER]) localStorage.setItem(`ecofate.welcome.seen.${known.id}`, "1");
  const view = render(<App />);
  await screen.findByRole("navigation", { name: "Navigation" });
  return view;
}
