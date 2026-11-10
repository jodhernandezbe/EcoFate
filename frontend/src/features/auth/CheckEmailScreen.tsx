import { useState } from "react";

import { Banner } from "../../components/ui/Banner";
import { resendVerification } from "../../services/apiClient";
import { AuthCard, LinkButton } from "./AuthCard";
import { useSubmit } from "./useSubmit";

interface CheckEmailScreenProps {
  email: string;
  /** `unverified`: a sign-in with the right password found the address not verified yet. */
  reason: "sent" | "unverified";
  onSignIn: () => void;
}

const LEADS = {
  sent: "If this address can be used, a message with a verification link is on its way.",
  unverified: "Your password is right, but your email address is not verified yet.",
} as const;

export function CheckEmailScreen({ email, reason, onSignIn }: CheckEmailScreenProps) {
  const [sent, setSent] = useState(false);
  const { busy, error, run } = useSubmit();

  const resend = async () => {
    const done = await run(async () => {
      await resendVerification(email);
      return true;
    });
    setSent(done === true);
  };

  return (
    <AuthCard
      title="Check your email"
      lead={`${LEADS[reason]} Open the link in the message sent to ${email}.`}
      footer={<LinkButton onClick={onSignIn}>Back to sign in</LinkButton>}
    >
      {sent ? <Banner kind="success">If this address needs one, a new link was sent.</Banner> : null}
      {error ? <Banner kind="error">{error}</Banner> : null}
      {busy ? (
        <p role="status" className="text-xs text-fg2">
          Sending…
        </p>
      ) : null}
      <button
        type="button"
        disabled={busy}
        onClick={() => void resend()}
        className="spring rounded-xl bg-hairline px-4 py-2 text-sm font-semibold transition hover:opacity-80 disabled:opacity-40"
      >
        Send the link again
      </button>
    </AuthCard>
  );
}
