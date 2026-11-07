import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import type { ChatMessage } from "../../hooks/chatState";
import type { TurnInterruption } from "../../types/workspace";
import { MessageStream } from "./MessageStream";

afterEach(cleanup);

/** The chat dock's column: its width and background, as `ChatDock` provides. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="frame"
      style={{
        width: 420,
        height: 360,
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        color: "var(--fg)",
      }}
    >
      {children}
    </div>
  );
}

const frame = () => page.getByTestId("frame");
const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

const message = (interrupted: TurnInterruption): ChatMessage[] => [
  {
    id: "u",
    role: "user",
    text: "Assess testane",
    error: null,
    streaming: false,
    tools: [],
    interrupted: null,
  },
  {
    id: "a",
    role: "assistant",
    text: "I found the facilities and started the dispersion screening.",
    error: null,
    streaming: false,
    tools: [{ callId: "c0", label: "Found facilities", state: "done" }],
    interrupted,
  },
];

const noop = () => undefined;

describe("interrupted turn notice, in a real browser", () => {
  it("offers Resume under the partial answer", async () => {
    const stop = {
      reason: "out_of_credits" as const,
      resumable: true,
      message:
        "Your account has no credits left. Add credits, then press Resume.",
    };
    render(
      <Frame>
        <MessageStream
          messages={message(stop)}
          onResume={noop}
          onOpenSettings={noop}
        />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("stop-resumable"));
  });

  it("dims Resume while a turn runs", async () => {
    const stop = {
      reason: "rate_limited" as const,
      resumable: true,
      message:
        "Requests are limited right now. Wait a moment, then press Resume.",
    };
    render(
      <Frame>
        <MessageStream
          messages={message(stop)}
          busy
          onResume={noop}
          onOpenSettings={noop}
        />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("stop-busy"));
  });

  it("adds Open Settings for a rejected key", async () => {
    const stop = {
      reason: "bad_key" as const,
      resumable: true,
      message:
        "The API key was rejected. Replace it in Settings, then press Resume.",
    };
    render(
      <Frame>
        <MessageStream
          messages={message(stop)}
          onResume={noop}
          onOpenSettings={noop}
        />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("stop-bad-key"));
  });

  it("shows only the message when it can no longer be resumed", async () => {
    const stop = {
      reason: "step_limit" as const,
      resumable: false,
      message:
        "This turn stopped and cannot be resumed again. Send a new message.",
    };
    render(
      <Frame>
        <MessageStream messages={message(stop)} onResume={noop} />
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("stop-final"));
  });
});
