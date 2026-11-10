import { useEffect, useRef, useState } from "react";

import { Banner } from "../../components/ui/Banner";
import { verifyEmail } from "../../services/apiClient";
import { AuthCard, LinkButton } from "./AuthCard";
import { describe } from "./useSubmit";

interface VerifyEmailScreenProps {
  token: string;
  onSignIn: () => void;
}

type Outcome = { status: "working" } | { status: "done" } | { status: "failed"; message: string };

/** Uses the emailed token once, on arrival, and says how it went. */
export function VerifyEmailScreen({ token, onSignIn }: VerifyEmailScreenProps) {
  const [outcome, setOutcome] = useState<Outcome>({ status: "working" });
  const started = useRef(false); // a token works once: never send it twice

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    verifyEmail(token).then(
      () => setOutcome({ status: "done" }),
      (failure: unknown) => setOutcome({ status: "failed", message: describe(failure) }),
    );
  }, [token]);

  return (
    <AuthCard title="Verify your email" footer={<LinkButton onClick={onSignIn}>Back to sign in</LinkButton>}>
      {outcome.status === "working" ? (
        <p role="status" className="text-sm text-fg2">
          Verifying your email…
        </p>
      ) : null}
      {outcome.status === "done" ? <Banner kind="success">Your email is verified. You can sign in now.</Banner> : null}
      {outcome.status === "failed" ? (
        <>
          <Banner kind="error">{outcome.message}</Banner>
          <p className="text-sm text-fg2">Sign in with your password to get a new link.</p>
        </>
      ) : null}
    </AuthCard>
  );
}
