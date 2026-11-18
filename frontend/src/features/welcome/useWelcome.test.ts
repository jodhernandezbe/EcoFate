import { act, renderHook } from "@testing-library/react";

import { useWelcome } from "./useWelcome";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("useWelcome", () => {
  it("is open on a first visit", () => {
    const { result } = renderHook(() => useWelcome("u1"));
    expect(result.current.open).toBe(true);
  });

  it("dismissing closes it and it stays closed on the next visit", () => {
    const first = renderHook(() => useWelcome("u1"));
    act(() => first.result.current.dismiss());
    expect(first.result.current.open).toBe(false);
    expect(localStorage.getItem("ecofate.welcome.seen.u1")).not.toBeNull();
    first.unmount();
    expect(renderHook(() => useWelcome("u1")).result.current.open).toBe(false);
  });

  it("can be shown again after it was dismissed", () => {
    const { result } = renderHook(() => useWelcome("u1"));
    act(() => result.current.dismiss());
    act(() => result.current.show());
    expect(result.current.open).toBe(true);
  });

  it("remembers per user", () => {
    const first = renderHook(() => useWelcome("u1"));
    act(() => first.result.current.dismiss());
    expect(renderHook(() => useWelcome("u2")).result.current.open).toBe(true);
  });

  it("stores nothing but the flag under the user's key", () => {
    const { result } = renderHook(() => useWelcome("u1"));
    act(() => result.current.dismiss());
    expect(Object.keys(localStorage)).toEqual(["ecofate.welcome.seen.u1"]);
  });

  it("still works, and shows again next time, when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const first = renderHook(() => useWelcome("u1"));
    expect(first.result.current.open).toBe(true);
    act(() => first.result.current.dismiss());
    expect(first.result.current.open).toBe(false);
    first.unmount();
    expect(renderHook(() => useWelcome("u1")).result.current.open).toBe(true);
  });
});
