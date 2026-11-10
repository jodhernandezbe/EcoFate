import { useState } from "react";

import { signUp } from "../../services/apiClient";
import { AuthCard, AuthForm, LinkButton } from "./AuthCard";
import { TextField } from "./TextField";
import { useSubmit } from "./useSubmit";

interface SignUpScreenProps {
  /** The request was accepted; the answer is the same whether or not the address had an account. */
  onSent: (email: string) => void;
  onSignIn: () => void;
}

export function SignUpScreen({ onSent, onSignIn }: SignUpScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();

  const submit = async () => {
    const done = await run(async () => {
      await signUp(email, password);
      return true;
    });
    setPassword("");
    if (done) onSent(email);
  };

  return (
    <AuthCard
      title="Create an account"
      lead="You will get an email to verify your address."
      footer={
        <span>
          Already have an account? <LinkButton onClick={onSignIn}>Sign in</LinkButton>
        </span>
      }
    >
      <AuthForm onSubmit={() => void submit()} busy={busy} progress="Creating your account…" error={error} submitLabel="Create account">
        <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          hint="Use a long password you do not use anywhere else."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </AuthForm>
    </AuthCard>
  );
}
