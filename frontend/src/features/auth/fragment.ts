/** What an emailed link asks for: the token travels in the URL fragment, which no server sees. */
export type LinkAction = { kind: "verify" | "reset"; token: string };

const KINDS = { "#verify=": "verify", "#reset=": "reset" } as const;
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{16,256}$/;

/** The action in a URL fragment (`#verify=<token>` or `#reset=<token>`), or null. */
export function readLinkAction(hash: string): LinkAction | null {
  for (const [prefix, kind] of Object.entries(KINDS)) {
    if (!hash.startsWith(prefix)) continue;
    const token = hash.slice(prefix.length);
    return TOKEN_SHAPE.test(token) ? { kind: kind as LinkAction["kind"], token } : null;
  }
  return null;
}

/** Remove the fragment from the address bar (and the history entry), so a token does not stay. */
export function clearFragment(): void {
  const { pathname, search } = window.location;
  window.history.replaceState(null, "", pathname + search);
}
