/** Why "Clear chat" is unavailable, in words; null when it can be used. */
export function clearBlockedReason(busy: boolean, messageCount: number): string | null {
  if (busy) return "a reply is still streaming";
  return messageCount === 0 ? "nothing to clear yet" : null;
}
