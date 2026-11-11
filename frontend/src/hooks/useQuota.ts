import { useEffect, useState } from "react";

import { getQuota } from "../services/apiClient";
import type { QuotaStatus } from "../types/workspace";
import type { QuotaRefusal } from "./useAgentStream";

/** The quota once the server has refused a turn: none left until the reset. */
function exhausted(now: QuotaStatus | null, resetsAt: string): QuotaStatus {
  return {
    applies: true,
    limit: now?.limit ?? null,
    used: now?.limit ?? null,
    remaining: 0,
    resets_at: resetsAt,
  };
}

/**
 * The signed-in user's daily turn quota: loaded with the page, read again whenever a turn
 * ends, and set to "none left" when the server refuses a turn (429). The server enforces the
 * limit; a failed read keeps the last figures and never blocks the user.
 */
export function useQuota(busy: boolean, refusal: QuotaRefusal | null): QuotaStatus | null {
  const [quota, setQuota] = useState<QuotaStatus | null>(null);
  const [seen, setSeen] = useState<QuotaRefusal | null>(null);

  if (refusal !== seen) {
    setSeen(refusal);
    if (refusal?.resetsAt) setQuota(exhausted(quota, refusal.resetsAt));
  }

  useEffect(() => {
    if (busy) return;
    let live = true;
    getQuota()
      .then((value) => {
        if (live) setQuota(value);
      })
      .catch(() => undefined); // keep what is shown; the next finished turn tries again
    return () => {
      live = false;
    };
  }, [busy]);

  return quota;
}
