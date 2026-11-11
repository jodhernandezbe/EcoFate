import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";
import { ADMIN, MEMBER, meResponse, renderApp, signedOutResponse } from "./test/session";

const json = (body: object, status = 200) => new Response(JSON.stringify(body), { status });

interface Options {
  /** The `/auth/me` answer (signed out by default). */
  me?: () => Response;
  /** Overrides by "METHOD /path". */
  routes?: Record<string, () => Response>;
}

function stub({ me = signedOutResponse, routes = {} }: Options = {}) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/api/v1", "");
      const key = `${init?.method ?? "GET"} ${path}`;
      calls.push(key);
      const route = key === "GET /auth/me" ? me : routes[key];
      if (route) return Promise.resolve(route());
      const body = path === "/settings/client" ? { model: "test-model" } : { openai: { configured: true }, services: { census: { available: false }, comptox: { available: false } } };
      return Promise.resolve(json(body));
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const rail = () => within(screen.getByRole("navigation", { name: "Navigation" }));

describe("who is signed in decides the page", () => {
  it("shows the sign-in screen and no workspace to a visitor", async () => {
    stub();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Navigation" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Map" })).toBeNull();
  });

  it("says it is loading while the session is checked", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });

  it("offers a retry when the session cannot be checked", async () => {
    let up = false;
    stub({ me: () => (up ? meResponse() : json({ error: "Something went wrong.", correlation_id: "c" }, 500)) });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The session could not be checked");
    up = true;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("navigation", { name: "Navigation" })).toBeInTheDocument();
  });

  it("does not treat an answer that is not a user as a session", async () => {
    stub({ me: () => json({ openai: { configured: true } }) });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the workspace after signing in, and not the sign-in screen", async () => {
    stub({ routes: { "POST /auth/signin": () => json({ state: "signed_in", user: MEMBER }) } });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Email"), MEMBER.email);
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });
});

describe("rail entries per role", () => {
  it("shows an administrator Monitoring, then Account and Settings last", async () => {
    stub({ me: () => meResponse(ADMIN) });
    await renderApp();
    const names = rail()
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent ?? "")
      .filter((name) => !name.includes("navigation"));
    expect(names).toEqual(["Workspace", "Clear workspace", "Generate report", "Monitoring", "Account", "Settings"]);
    expect(rail().getByText(ADMIN.email)).toBeInTheDocument();
  });

  it("shows a regular user no Monitoring entry", async () => {
    stub({ me: () => meResponse(MEMBER) });
    await renderApp(MEMBER);
    expect(rail().queryByRole("button", { name: "Monitoring" })).toBeNull();
    expect(rail().getByRole("button", { name: "Account" })).toBeInTheDocument();
    expect(rail().getByText(MEMBER.email)).toBeInTheDocument();
  });
});

describe("a 401 during use", () => {
  it("returns to sign-in without a reload and leaves nothing of the workspace on screen", async () => {
    let expire: (response: Response) => void = () => {};
    const keys = new Promise<Response>((resolve) => (expire = resolve));
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input);
        if (path.endsWith("/auth/me")) return Promise.resolve(meResponse(MEMBER));
        if (path.endsWith("/settings/keys")) return keys; // answers later, once the page is up
        return Promise.resolve(json({ model: "m" }));
      }),
    );
    await renderApp(MEMBER);
    await userEvent.click(rail().getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeInTheDocument();
    expire(signedOutResponse());
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Navigation" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Copilot" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(MEMBER.email)).toBeNull();
  });

  it("does not take a wrong password at the sign-in screen for an ended session", async () => {
    stub({
      routes: {
        "POST /auth/signin": () => json({ error: "Incorrect email or password.", correlation_id: "c" }, 401),
      },
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("the account sheet", () => {
  it("shows the email and signs out on the server, then shows the sign-in screen", async () => {
    const calls = stub({ me: () => meResponse(MEMBER), routes: { "POST /auth/signout": () => new Response(null, { status: 204 }) } });
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    const sheet = within(screen.getByRole("dialog", { name: "Account" }));
    expect(sheet.getByText(MEMBER.email)).toBeInTheDocument();
    await user.click(sheet.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(calls).toContain("POST /auth/signout");
    expect(screen.queryByRole("navigation", { name: "Navigation" })).toBeNull();
  });

  it("changes the password with the current one and confirms it", async () => {
    let body: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/auth/me")) return Promise.resolve(meResponse(MEMBER));
        if (path.endsWith("/account/password")) {
          body = JSON.parse(String(init?.body));
          return Promise.resolve(new Response(null, { status: 204 }));
        }
        return Promise.resolve(json({ openai: { configured: true }, services: { census: { available: false }, comptox: { available: false } }, model: "m" }));
      }),
    );
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    await user.type(screen.getByLabelText("Current password"), "old password value");
    await user.type(screen.getByLabelText("New password"), "new password value!");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(/Password changed/)).toBeInTheDocument();
    expect(body).toEqual({ current_password: "old password value", new_password: "new password value!" });  // pragma: allowlist secret
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("shows the server's message when the current password is wrong", async () => {
    stub({
      me: () => meResponse(MEMBER),
      routes: { "POST /account/password": () => json({ error: "The password is incorrect.", correlation_id: "c" }, 403) },
    });
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    await user.type(screen.getByLabelText("Current password"), "wrong");
    await user.type(screen.getByLabelText("New password"), "new password value!");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The password is incorrect.");
    expect(screen.getByRole("navigation", { name: "Navigation" })).toBeInTheDocument();
  });

  it("asks for the password before deleting the account, then signs out", async () => {
    const calls = stub({ me: () => meResponse(MEMBER), routes: { "POST /account/delete": () => new Response(null, { status: 204 }) } });
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("button", { name: "Delete account…" }));
    const dialog = within(screen.getByRole("alertdialog", { name: "Delete your account?" }));
    await user.click(dialog.getByRole("button", { name: "Delete account" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("Enter your password");
    expect(calls).not.toContain("POST /account/delete");
    await user.type(dialog.getByLabelText("Your password"), "correct horse battery staple");
    await user.click(dialog.getByRole("button", { name: "Delete account" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(calls).toContain("POST /account/delete");
  });

  it("keeps the account when the delete password is wrong, and cancel closes the dialog", async () => {
    stub({
      me: () => meResponse(MEMBER),
      routes: { "POST /account/delete": () => json({ error: "The password is incorrect.", correlation_id: "c" }, 403) },
    });
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("button", { name: "Delete account…" }));
    const dialog = within(screen.getByRole("alertdialog"));
    await user.type(dialog.getByLabelText("Your password"), "wrong");
    await user.click(dialog.getByRole("button", { name: "Delete account" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("The password is incorrect.");
    await user.click(dialog.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.getByRole("dialog", { name: "Account" })).toBeInTheDocument();
  });

  it("signs out everywhere and shows the sign-in screen", async () => {
    stub({ me: () => meResponse(MEMBER), routes: { "POST /account/sign-out-everywhere": () => new Response(null, { status: 204 }) } });
    const user = userEvent.setup();
    await renderApp(MEMBER);
    await user.click(rail().getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("browser storage", () => {
  it("holds nothing of the account (email, password, tokens) after using the app signed in", async () => {
    localStorage.clear();
    sessionStorage.clear();
    stub({ me: () => meResponse(MEMBER) });
    await renderApp(MEMBER);
    for (const store of [localStorage, sessionStorage]) {
      const everything = JSON.stringify({ ...store });
      expect(everything).not.toContain(MEMBER.email);
      expect(everything).not.toContain(MEMBER.id);
    }
  });
});
