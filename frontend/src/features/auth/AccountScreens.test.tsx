import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MEMBER } from "../../test/session";
import { AccountScreens } from "./AccountScreens";

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789_-ABC";  // pragma: allowlist secret
const PASSWORD = "correct horse battery staple"; // pragma: allowlist secret

interface Call {
  method: string;
  path: string;
  body: Record<string, unknown> | null;
}

type Answer = Response | (() => Response);

/** Stubs fetch with an answer per "METHOD /path"; every call is recorded. */
function stub(answers: Record<string, Answer>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/api/v1", "");
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      calls.push({ method, path, body });
      const answer = answers[`${method} ${path}`];
      const response = typeof answer === "function" ? answer() : answer;
      return Promise.resolve(response ?? new Response(null, { status: 404 }));
    }),
  );
  return calls;
}

const json = (body: object, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });
const accepted = () => json({ status: "accepted" }, 202);
const none = () => new Response(null, { status: 204 });
const failure = (error: string, status: number, extra: object = {}, headers = {}) =>
  json({ error, correlation_id: "c1", ...extra }, status, headers);

const typeInto = async (label: string, text: string) =>
  userEvent.type(screen.getByLabelText(label), text);

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("sign in", () => {
  it("is the first screen, with labelled fields and links to the other screens", () => {
    render(<AccountScreens onSignedIn={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeRequired();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Forgot password?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create an account" })).toBeInTheDocument();
  });

  it("shows progress while signing in, then hands over the user and clears the password", async () => {
    let finish: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => (finish = resolve));
    vi.stubGlobal("fetch", vi.fn(() => pending));
    const onSignedIn = vi.fn();
    render(<AccountScreens onSignedIn={onSignedIn} />);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("status")).toHaveTextContent("Signing in…");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    finish(json({ state: "signed_in", user: MEMBER }));
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(MEMBER));
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("sends the credentials in the body of the sign-in request", async () => {
    const calls = stub({ "POST /auth/signin": () => json({ state: "signed_in", user: MEMBER }) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({ method: "POST", path: "/auth/signin", body: { email: "ben@example.com", password: PASSWORD } });
  });

  it("shows the server's message on a wrong password and stays on the screen", async () => {
    stub({ "POST /auth/signin": () => failure("Incorrect email or password.", 401) });
    const onSignedIn = vi.fn();
    render(<AccountScreens onSignedIn={onSignedIn} />);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("says how long to wait when the server limits the attempts", async () => {
    stub({ "POST /auth/signin": () => failure("Too many attempts. Try again later.", 429, {}, { "Retry-After": "42" }) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 42 seconds.");
  });

  it("asks to check the email when the address is not verified yet", async () => {
    stub({
      "POST /auth/signin": () => json({ state: "verification_required", user: null }),
      "POST /auth/resend": accepted,
    });
    const onSignedIn = vi.fn();
    render(<AccountScreens onSignedIn={onSignedIn} />);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/not verified yet/)).toBeInTheDocument();
    expect(onSignedIn).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Send the link again" }));
    expect(await screen.findByRole("status")).toHaveTextContent("a new link was sent");
  });
});

describe("sign up", () => {
  it("creates the account and moves to the check-your-email screen", async () => {
    const calls = stub({ "POST /auth/signup": accepted });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    await typeInto("Email", "new@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/new@example.com/)).toBeInTheDocument();
    expect(calls[0]?.body).toEqual({ email: "new@example.com", password: PASSWORD });
  });

  it("names the field the server rejected", async () => {
    stub({
      "POST /auth/signup": () =>
        failure("Invalid request.", 422, { fields: [{ loc: ["body", "password"], msg: "Use at least 12 characters." }] }),
    });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
    await typeInto("Email", "new@example.com");
    await typeInto("Password", "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Use at least 12 characters.");
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();
  });

  it("shows the sign-up-closed message", async () => {
    stub({ "POST /auth/signup": () => failure("Sign-up is closed on this server.", 403) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
    await typeInto("Email", "new@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-up is closed");
  });

  it("links back to sign in", async () => {
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("verify email", () => {
  it("uses the token from the link once, sends it in the body, and removes it from the address", async () => {
    window.history.replaceState(null, "", `/#verify=${TOKEN}`);
    const calls = stub({ "POST /auth/verify": none });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    expect(await screen.findByText("Your email is verified. You can sign in now.")).toBeInTheDocument();
    expect(calls).toEqual([{ method: "POST", path: "/auth/verify", body: { token: TOKEN } }]);
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
  });

  it("says when the link is invalid or expired and points to sign in for a new one", async () => {
    window.history.replaceState(null, "", `/#verify=${TOKEN}`);
    stub({ "POST /auth/verify": () => failure("This link is invalid or has expired.", 400) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or has expired");
    await userEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows progress while the token is being used", () => {
    window.history.replaceState(null, "", `/#verify=${TOKEN}`);
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<AccountScreens onSignedIn={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Verifying your email…");
  });
});

describe("forgot and reset password", () => {
  it("asks for the email and says the same thing whatever the answer", async () => {
    const calls = stub({ "POST /auth/forgot": accepted });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await typeInto("Email", "ben@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If an account uses this address");
    expect(calls[0]?.body).toEqual({ email: "ben@example.com" });
  });

  it("shows an error when the request is limited", async () => {
    stub({ "POST /auth/forgot": () => failure("Too many attempts. Try again later.", 429) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Forgot password?" }));
    await typeInto("Email", "ben@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
  });

  it("opens the reset screen from the link, removes the token from the address and sends it in the body", async () => {
    window.history.replaceState(null, "", `/#reset=${TOKEN}`);
    const calls = stub({ "POST /auth/reset": none });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Choose a new password" })).toBeInTheDocument();
    expect(window.location.href).not.toContain(TOKEN);
    await typeInto("New password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByText("Your password was changed. Sign in with the new one.")).toBeInTheDocument();
    expect(calls).toEqual([{ method: "POST", path: "/auth/reset", body: { token: TOKEN, password: PASSWORD } }]);
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("keeps the reset screen and shows the server's message when the link has expired", async () => {
    window.history.replaceState(null, "", `/#reset=${TOKEN}`);
    stub({ "POST /auth/reset": () => failure("This link is invalid or has expired.", 400) });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await typeInto("New password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or has expired");
    await userEvent.click(screen.getByRole("button", { name: "Ask for a new one" }));
    expect(screen.getByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
  });

  it("opens the reset screen when a link is followed while the page is already open", async () => {
    render(<AccountScreens onSignedIn={vi.fn()} />);
    window.history.replaceState(null, "", `/#reset=${TOKEN}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await screen.findByRole("heading", { name: "Choose a new password" })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });
});

describe("browser storage", () => {
  it("holds no password and no token after signing up, verifying, resetting and signing in", async () => {
    window.history.replaceState(null, "", `/#reset=${TOKEN}`);
    stub({
      "POST /auth/reset": none,
      "POST /auth/signin": () => json({ state: "signed_in", user: MEMBER }),
    });
    render(<AccountScreens onSignedIn={vi.fn()} />);
    await typeInto("New password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Save password" }));
    await screen.findByText(/Your password was changed/);
    await typeInto("Email", "ben@example.com");
    await typeInto("Password", PASSWORD);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByLabelText("Password")).toHaveValue(""));
    for (const store of [localStorage, sessionStorage]) {
      expect(store.length).toBe(0);
      expect(JSON.stringify({ ...store })).not.toContain(PASSWORD);
    }
  });
});
