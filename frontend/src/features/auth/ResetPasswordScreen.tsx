import { useState } from "react";

import { resetPassword } from "../../services/apiClient";
import { AuthCard, AuthForm, LinkButton } from "./AuthCard";
import { TextField } from "./TextField";
import { useSubmit } from "./useSubmit";

interface ResetPasswordScreenProps {
  token: string;
  /** The password was changed; every session of the account has ended. */
  onDone: () => void;
  onForgot: () => void;
}

export function ResetPasswordScreen({ token, onDone, onForgot }: ResetPasswordScreenProps) {
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();

  const submit = async () => {
    const done = await run(async () => {
      await resetPassword(token, password);
      return true;
    });
    setPassword("");
    if (done) onDone();
  };

  return (
    <AuthCard
      title="Choose a new password"
      footer={
        <span>
          Link not working? <LinkButton onClick={onForgot}>Ask for a new one</LinkButton>
        </span>
      }
    >
      <AuthForm onSubmit={() => void submit()} busy={busy} progress="Saving your password…" error={error} submitLabel="Save password">
        <TextField
          label="New password"
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
