import type { QuotaStatus } from "../../types/workspace";
import { limitReachedReason, localReset, turnsLeftText } from "./quotaText";

const status = (over: Partial<QuotaStatus> = {}): QuotaStatus => ({
  applies: true,
  limit: 5,
  used: 2,
  remaining: 3,
  resets_at: "2026-03-06T00:00:00Z",
  ...over,
});

describe("turnsLeftText", () => {
  it("counts the turns left, agreeing with the number", () => {
    expect(turnsLeftText(status())).toBe("3 turns left today");
    expect(turnsLeftText(status({ remaining: 1 }))).toBe("1 turn left today");
    expect(turnsLeftText(status({ remaining: 0 }))).toBe("No turns left today");
  });

  it("says nothing when no quota applies or none is loaded", () => {
    expect(turnsLeftText(null)).toBeNull();
    const exempt = status({ applies: false, limit: null, used: null, remaining: null, resets_at: null });
    expect(turnsLeftText(exempt)).toBeNull();
  });
});

describe("limitReachedReason", () => {
  const none = status({ remaining: 0, used: 5 });

  it("says the limit was reached and when it resets, in local time", () => {
    const now = new Date("2026-03-05T12:00:00Z");
    const reason = limitReachedReason(none, now) ?? "";
    expect(reason).toMatch(/^Daily limit reached\. It resets at .+\.$/);
    expect(reason).toContain(localReset(none.resets_at ?? "", now));
  });

  it("is null while turns are left or no quota applies", () => {
    expect(limitReachedReason(status())).toBeNull();
    expect(limitReachedReason(null)).toBeNull();
    expect(limitReachedReason(status({ applies: false, remaining: null }))).toBeNull();
  });

  it("still explains itself without a reset time", () => {
    expect(limitReachedReason(status({ remaining: 0, resets_at: null }))).toBe("Daily limit reached.");
  });
});
