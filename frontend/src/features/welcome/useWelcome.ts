import { useCallback, useState } from "react";

import { safeStorage } from "../../lib/safeStorage";

const SEEN_PREFIX = "ecofate.welcome.seen.";
const SEEN = "1";

/**
 * Whether the welcome sheet is open. It opens by itself on a user's first visit in this browser
 * (decided once, on mount); dismissing it is remembered per user as a convenience only, so when
 * storage is unavailable it simply shows again. Nothing sensitive is stored.
 */
export function useWelcome(userId: string) {
  const storageKey = `${SEEN_PREFIX}${userId}`;
  const [open, setOpen] = useState(() => safeStorage.getItem(storageKey) !== SEEN);
  const show = useCallback(() => setOpen(true), []);
  const dismiss = useCallback(() => {
    safeStorage.setItem(storageKey, SEEN);
    setOpen(false);
  }, [storageKey]);
  return { open, show, dismiss };
}
