import { useState } from "react";

import { Banner } from "../../components/ui/Banner";
import { forgotPassword } from "../../services/apiClient";
import { AuthCard, AuthForm, LinkButton } from "./AuthCard";
import { TextField } from "./TextField";
import { useSubmit } from "./useSubmit";

export function ForgotPasswordScreen({ onSignIn }: { onSignIn: () => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const { busy, error, run } = useSubmit();

  const submit = async () => {
    const done = await run(async () => {
      await forgotPassword(email);
      return true;
    });
    if (done) setSent(true);
  };

  return (
    <AuthCard
      title="Reset your password"
      lead="Enter your email and we will send you a link to choose a new password."
      footer={<LinkButton onClick={onSignIn}>Back to sign in</LinkButton>}
    >
      {sent ? (
        <Banner kind="success">If an account uses this address, a reset link is on its way.</Banner>
      ) : (
        <AuthForm onSubmit={() => void submit()} busy={busy} progress="Sending…" error={error} submitLabel="Send reset link">
          <TextField label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </AuthForm>
      )}
    </AuthCard>
  );
}
