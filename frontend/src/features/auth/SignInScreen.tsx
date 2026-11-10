import { useState } from "react";

import { signIn } from "../../services/apiClient";
import type { UserInfo } from "../../types/workspace";
import { AuthCard, AuthForm, LinkButton } from "./AuthCard";
import { TextField } from "./TextField";
import { useSubmit } from "./useSubmit";

interface SignInScreenProps {
  onSignedIn: (user: UserInfo) => void;
  /** The password was right but the address is not verified yet. */
  onUnverified: (email: string) => void;
  onSignUp: () => void;
  onForgot: () => void;
  /** Shown above the form, e.g. after a password reset. */
  notice?: string | undefined;
}

export function SignInScreen({ onSignedIn, onUnverified, onSignUp, onForgot, notice }: SignInScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();

  const submit = async () => {
    const answer = await run(() => signIn(email, password));
    setPassword("");
    if (!answer) return;
    if (answer.state === "signed_in" && answer.user) onSignedIn(answer.user);
    else onUnverified(email);
  };

  return (
    <AuthCard
      title="Sign in"
      lead={notice ?? "Sign in to your EcoFate account."}
      footer={
        <>
          <LinkButton onClick={onForgot}>Forgot password?</LinkButton>
          <span>
            No account yet? <LinkButton onClick={onSignUp}>Create an account</LinkButton>
          </span>
        </>
      }
    >
      <AuthForm onSubmit={() => void submit()} busy={busy} progress="Signing in…" error={error} submitLabel="Sign in">
        <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </AuthForm>
    </AuthCard>
  );
}
