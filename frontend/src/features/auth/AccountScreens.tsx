import { useEffect, useState } from "react";

import type { UserInfo } from "../../types/workspace";
import { CheckEmailScreen } from "./CheckEmailScreen";
import { ForgotPasswordScreen } from "./ForgotPasswordScreen";
import { clearFragment, readLinkAction } from "./fragment";
import { ResetPasswordScreen } from "./ResetPasswordScreen";
import { SignInScreen } from "./SignInScreen";
import { SignUpScreen } from "./SignUpScreen";
import { VerifyEmailScreen } from "./VerifyEmailScreen";

type Screen =
  | { name: "sign-in"; notice?: string }
  | { name: "sign-up" }
  | { name: "check-email"; email: string; reason: "sent" | "unverified" }
  | { name: "forgot" }
  | { name: "verify"; token: string }
  | { name: "reset"; token: string };

const RESET_DONE = "Your password was changed. Sign in with the new one.";

/** The screen an emailed link opens, if the address carries one. Reads; clears in an effect. */
function fromAddress(): Screen {
  const action = readLinkAction(window.location.hash);
  if (action?.kind === "verify") return { name: "verify", token: action.token };
  if (action?.kind === "reset") return { name: "reset", token: action.token };
  return { name: "sign-in" };
}

/**
 * Everything shown while nobody is signed in. A token in the address (from an emailed link) is
 * read into memory and removed from the address bar at once; nothing is written to storage.
 */
export function AccountScreens({ onSignedIn }: { onSignedIn: (user: UserInfo) => void }) {
  const [screen, setScreen] = useState<Screen>(fromAddress);

  useEffect(() => {
    if (window.location.hash) clearFragment();
    const onHash = () => {
      const action = readLinkAction(window.location.hash);
      if (action?.kind === "verify") setScreen({ name: "verify", token: action.token });
      if (action?.kind === "reset") setScreen({ name: "reset", token: action.token });
      if (window.location.hash) clearFragment();
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const signIn = () => setScreen({ name: "sign-in" });
  switch (screen.name) {
    case "sign-up":
      return <SignUpScreen onSignIn={signIn} onSent={(email) => setScreen({ name: "check-email", email, reason: "sent" })} />;
    case "check-email":
      return <CheckEmailScreen email={screen.email} reason={screen.reason} onSignIn={signIn} />;
    case "forgot":
      return <ForgotPasswordScreen onSignIn={signIn} />;
    case "verify":
      return <VerifyEmailScreen token={screen.token} onSignIn={signIn} />;
    case "reset":
      return <ResetPasswordScreen token={screen.token} onForgot={() => setScreen({ name: "forgot" })} onDone={() => setScreen({ name: "sign-in", notice: RESET_DONE })} />;
    default:
      return (
        <SignInScreen
          notice={screen.notice}
          onSignedIn={onSignedIn}
          onUnverified={(email) => setScreen({ name: "check-email", email, reason: "unverified" })}
          onSignUp={() => setScreen({ name: "sign-up" })}
          onForgot={() => setScreen({ name: "forgot" })}
        />
      );
  }
}
