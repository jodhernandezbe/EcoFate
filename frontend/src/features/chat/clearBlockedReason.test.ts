import { clearBlockedReason } from "./clearBlockedReason";

describe("clearBlockedReason", () => {
  it("is null when there are messages and no reply is streaming", () => {
    expect(clearBlockedReason(false, 2)).toBeNull();
  });

  it("says a reply is streaming, even when there are messages", () => {
    expect(clearBlockedReason(true, 2)).toBe("a reply is still streaming");
  });

  it("says there is nothing to clear for an empty chat", () => {
    expect(clearBlockedReason(false, 0)).toBe("nothing to clear yet");
  });
});
