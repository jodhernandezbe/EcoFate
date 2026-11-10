import { useState } from "react";

import { Banner } from "../../components/ui/Banner";
import { BottomDrawer } from "../../components/ui/BottomDrawer";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { changePassword, deleteAccount, signOutEverywhere } from "../../services/apiClient";
import type { UserInfo } from "../../types/workspace";
import { TextField } from "./TextField";
import { describe, useSubmit } from "./useSubmit";

const BUTTON = "spring rounded-full px-4 py-1.5 text-sm transition disabled:opacity-30";
const PASSWORD_NEEDED = "Enter your password to confirm.";  // pragma: allowlist secret

interface AccountDrawerProps {
  open: boolean;
  user: UserInfo;
  onClose: () => void;
  onSignOut: () => void;
  /** The session ended on the server (everywhere, or the account was deleted). */
  onGone: () => void;
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useSubmit();

  const submit = async () => {
    setSaved(false);
    const done = await run(async () => {
      await changePassword(current, next);
      return true;
    });
    setCurrent("");
    setNext("");
    setSaved(done === true);
  };

  return (
    <form
      aria-label="Change password"
      aria-busy={busy}
      onSubmit={(event) => {
        event.preventDefault();
        if (!busy) void submit();
      }}
      className="flex flex-col gap-3"
    >
      <h4 className="text-sm font-semibold">Change password</h4>
      <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      <TextField label="New password" type="password" autoComplete="new-password" required value={next} onChange={(e) => setNext(e.target.value)} />
      {error ? <Banner kind="error">{error}</Banner> : null}
      {saved ? <Banner kind="success">Password changed. Your other sessions were signed out.</Banner> : null}
      {busy ? <p role="status" className="text-xs text-fg2">Saving…</p> : null}
      <button type="submit" disabled={busy} className={`${BUTTON} w-fit bg-accent font-medium text-accent-fg`}>
        Change password
      </button>
    </form>
  );
}

function DeleteDialog({ open, onCancel, onGone }: { open: boolean; onCancel: () => void; onGone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (!password) return setError(PASSWORD_NEEDED);
    try {
      await deleteAccount(password);
      setPassword("");
      onGone();
    } catch (failure) {
      setError(describe(failure));
    }
  };
  const cancel = () => {
    setPassword("");
    setError(null);
    onCancel();
  };

  return (
    <ConfirmDialog open={open} title="Delete your account?" confirmLabel="Delete account" destructive onConfirm={() => void confirm()} onCancel={cancel}>
      <p>This deletes your account and every conversation, workspace and report stored for it. It cannot be recovered.</p>
      <TextField label="Your password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      {error ? <p role="alert" className="text-bad">{error}</p> : null}
    </ConfirmDialog>
  );
}

/** The signed-in account: its email, sign out, a new password, and deleting it. */
export function AccountDrawer({ open, user, onClose, onSignOut, onGone }: AccountDrawerProps) {
  const [deleting, setDeleting] = useState(false);
  const everywhere = useSubmit();

  return (
    <>
      <BottomDrawer open={open && !deleting} title="Account" onClose={onClose} fitContent>
        <div className="flex w-full max-w-md flex-col gap-6">
          <section aria-label="Signed in as" className="flex flex-wrap items-center justify-between gap-3">
            <p className="min-w-0 truncate text-sm">
              <span className="text-fg2">Signed in as </span>
              <span className="font-medium">{user.email}</span>
            </p>
            <button type="button" onClick={onSignOut} className={`${BUTTON} bg-hairline font-medium`}>
              Sign out
            </button>
          </section>
          <ChangePassword />
          <section aria-label="Sessions" className="flex flex-col gap-2">
            <h4 className="text-sm font-semibold">Other devices</h4>
            <p className="text-xs text-fg2">Sign out of every browser where you are signed in, this one included.</p>
            {everywhere.error ? <Banner kind="error">{everywhere.error}</Banner> : null}
            <button
              type="button"
              disabled={everywhere.busy}
              onClick={() => void everywhere.run(async () => { await signOutEverywhere(); onGone(); })}
              className={`${BUTTON} w-fit bg-hairline font-medium`}
            >
              Sign out everywhere
            </button>
          </section>
          <section aria-label="Delete account" className="flex flex-col gap-2">
            <h4 className="text-sm font-semibold">Delete account</h4>
            <p className="text-xs text-fg2">Removes your account and everything stored for it.</p>
            <button type="button" onClick={() => setDeleting(true)} className={`${BUTTON} w-fit border border-bad font-medium text-bad`}>
              Delete account…
            </button>
          </section>
        </div>
      </BottomDrawer>
      <DeleteDialog open={deleting} onCancel={() => setDeleting(false)} onGone={onGone} />
    </>
  );
}
