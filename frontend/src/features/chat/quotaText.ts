import type { QuotaStatus } from "../../types/workspace";

/** "3 turns left today", "1 turn left today" or "No turns left today"; null when no quota applies. */
export function turnsLeftText(quota: QuotaStatus | null): string | null {
  if (!quota?.applies || quota.remaining === null) return null;
  if (quota.remaining === 0) return "No turns left today";
  return `${quota.remaining} ${quota.remaining === 1 ? "turn" : "turns"} left today`;
}

/** The reset in the user's local time: the clock time, with the weekday when it is not today. */
export function localReset(resetsAt: string, now: Date = new Date()): string {
  const at = new Date(resetsAt);
  const sameDay = at.toDateString() === now.toDateString();
  const options: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" };
  if (!sameDay) options.weekday = "short";
  return at.toLocaleString(undefined, options);
}

/** Why the chat input is disabled, or null while turns are left (or no quota applies). */
export function limitReachedReason(quota: QuotaStatus | null, now: Date = new Date()): string | null {
  if (!quota?.applies || quota.remaining !== 0) return null;
  const when = quota.resets_at ? ` It resets at ${localReset(quota.resets_at, now)}.` : "";
  return `Daily limit reached.${when}`;
}
