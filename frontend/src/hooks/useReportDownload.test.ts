import { act, renderHook } from "@testing-library/react";

import { useReportDownload } from "./useReportDownload";

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function report(): Response {
  // Raw bytes, not a jsdom Blob: jsdom's Blob has no stream(), which Response.blob() needs.
  return new Response(new TextEncoder().encode("docx"), {
    status: 200,
    headers: {
      "content-type": DOCX,
      "content-disposition": 'attachment; filename="exposure-screening-11-11-1-2026-01-02.docx"',
    },
  });
}

describe("useReportDownload", () => {
  let clicked: string[];

  beforeEach(() => {
    clicked = [];
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:report"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("saves the file under the server's name and revokes the URL", async () => {
    const fetch = vi.fn((input: RequestInfo | URL) => Promise.resolve(input && report()));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useReportDownload());
    await act(() => result.current.download("t 1"));
    expect(String(fetch.mock.calls[0]?.[0])).toBe("/api/v1/chat/threads/t%201/report");
    expect(clicked).toEqual(["exposure-screening-11-11-1-2026-01-02.docx"]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:report");
    expect(result.current.error).toBeNull();
    expect(result.current.busy).toBe(false);
  });

  it("keeps the server's generic message and saves nothing on failure", async () => {
    const body = JSON.stringify({ error: "There are no findings to report yet.", correlation_id: "c" });
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(body, { status: 409 }))));
    const { result } = renderHook(() => useReportDownload());
    await act(() => result.current.download("t1"));
    expect(result.current.error).toBe("The report could not be generated. There are no findings to report yet.");
    expect(clicked).toEqual([]);
    act(() => result.current.dismiss());
    expect(result.current.error).toBeNull();
  });

  it("does not start a second request while one runs", async () => {
    let finish: (value: Response) => void = () => undefined;
    const fetch = vi.fn(() => new Promise<Response>((resolve) => (finish = resolve)));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useReportDownload());
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.download("t1");
    });
    expect(result.current.busy).toBe(true);
    await act(() => result.current.download("t1"));
    expect(fetch).toHaveBeenCalledTimes(1);
    finish(report());
    await act(() => first);
    expect(result.current.busy).toBe(false);
  });
});
