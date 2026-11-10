import { useCallback, useEffect, useState } from "react";

import { ApiError, getMe, onUnauthorized, signOut as signOutRequest } from "../services/apiClient";
import type { UserInfo } from "../types/workspace";

const PROBE_FAILED = "The session could not be checked. Try again.";

/** Whether anyone is signed in. Held in memory only: the cookie is the session, not the page. */
export type SessionState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "failed"; message: string }
  | { status: "signed-in"; user: UserInfo };

/** A reply that is not shaped like a user is treated as no session (never trusted as one). */
function isUser(value: unknown): value is UserInfo {
  if (typeof value !== "object" || value === null) return false;
  const user = value as Partial<UserInfo>;
  return typeof user.id === "string" && typeof user.email === "string" && (user.role === "user" || user.role === "admin");
}

/** Ask the server who is signed in. Never rejects: a failure is a state. */
async function readSession(): Promise<SessionState> {
  try {
    const user: unknown = await getMe();
    return isUser(user) ? { status: "signed-in", user } : { status: "signed-out" };
  } catch (error) {
    const gone = error instanceof ApiError && error.status === 401;
    return gone ? { status: "signed-out" } : { status: "failed", message: PROBE_FAILED };
  }
}

/**
 * The signed-in user (`GET /auth/me`), with the ways the session changes: `signedIn` after a
 * sign-in, `signOut` (ends it on the server), and any 401 the API answers during use, which
 * returns to signed-out so the caller can unmount the workspace.
 */
export function useSession() {
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let live = true;
    void readSession().then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => onUnauthorized(() => setState({ status: "signed-out" })), []);

  const signedIn = useCallback((user: UserInfo) => setState({ status: "signed-in", user }), []);
  const signedOut = useCallback(() => setState({ status: "signed-out" }), []);
  const signOut = useCallback(async () => {
    try {
      await signOutRequest();
    } catch {
      // The session may already be gone; either way this page leaves it.
    }
    setState({ status: "signed-out" });
  }, []);
  const retry = useCallback(async () => {
    setState({ status: "loading" });
    setState(await readSession());
  }, []);
  return { state, signedIn, signedOut, signOut, retry };
}
