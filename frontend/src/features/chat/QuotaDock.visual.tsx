import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import type { QuotaStatus } from "../../types/workspace";
import { ChatDock } from "./ChatDock";

afterEach(cleanup);

const frame = () => page.getByTestId("frame");
const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;
const noop = () => undefined;
// No reset time: its text is the viewer's local time, which would differ between machines
// (quotaText.test.ts covers it).
const quota = (remaining: number): QuotaStatus => ({
  applies: true,
  limit: 3,
  used: 3 - remaining,
  remaining,
  resets_at: null,
});

function Dock({ remaining }: { remaining: number }) {
  return (
    <div data-testid="frame" style={{ width: 420, height: 300, background: "var(--bg)", color: "var(--fg)" }}>
      <ChatDock
        messages={[]}
        busy={false}
        hasKey
        model="gpt-4.1"
        usage={null}
        quota={quota(remaining)}
        onSend={noop}
        onClear={noop}
        onOpenSettings={noop}
        onCollapse={noop}
      />
    </div>
  );
}

describe("daily quota in the chat dock, in a real browser", () => {
  it("shows the turns left beside the header controls", async () => {
    render(<Dock remaining={2} />);
    await expect.element(frame()).toMatchScreenshot(shot("quota-left"));
  });

  it("disables the input and says when it resets", async () => {
    render(<Dock remaining={0} />);
    await expect.element(frame()).toMatchScreenshot(shot("quota-none"));
  });
});
