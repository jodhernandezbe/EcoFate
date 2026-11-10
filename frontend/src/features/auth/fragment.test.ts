import { clearFragment, readLinkAction } from "./fragment";

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789_-ABC";  // pragma: allowlist secret

describe("readLinkAction", () => {
  it("reads a verification and a reset token from the fragment", () => {
    expect(readLinkAction(`#verify=${TOKEN}`)).toEqual({ kind: "verify", token: TOKEN });
    expect(readLinkAction(`#reset=${TOKEN}`)).toEqual({ kind: "reset", token: TOKEN });
  });

  it.each(["", "#", "#other=" + TOKEN, "#verify=", "#verify=short", "#reset=has space in it 0123456789", "#verify=" + "x".repeat(300), `?verify=${TOKEN}`])(
    "reads nothing from %j",
    (hash) => {
      expect(readLinkAction(hash)).toBeNull();
    },
  );
});

describe("clearFragment", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("removes the fragment from the address bar and keeps the path and query", () => {
    window.history.replaceState(null, "", `/app?x=1#reset=${TOKEN}`);
    clearFragment();
    expect(window.location.href).toBe("http://localhost:3000/app?x=1");
  });
});
