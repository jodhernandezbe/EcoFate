import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import type { ChatMessage, LiveStatus } from "../../hooks/chatState";
import type { TurnInterruption } from "../../types/workspace";
import { MessageStream } from "./MessageStream";
import { TurnControls, type TurnControlsProps } from "./TurnControls";

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

/** The dock's turn controls above the conversation, as `ChatDock` composes them. */
function Dock({ messages, ...controls }: Partial<TurnControlsProps> & { messages: ChatMessage[] }) {
  const last = messages[messages.length - 1];
  return (
    <Frame>
      <TurnControls
        busy={false}
        status={null}
        stopping={false}
        interrupted={last?.interrupted ?? null}
        onStop={noop}
        onResume={noop}
        onOpenSettings={noop}
        {...controls}
      />
      <MessageStream messages={messages} status={controls.status ?? null} />
    </Frame>
  );
}

describe("interrupted turn, in a real browser", () => {
  it("offers Resume above the conversation, with the reason", async () => {
    const stop = {
      reason: "out_of_credits" as const,
      resumable: true,
      message: "Your account has no credits left. Add credits, then press Resume.",
    };
    render(<Dock messages={message(stop)} />);
    await expect.element(frame()).toMatchScreenshot(shot("stop-resumable"));
  });

  it("adds Open Settings for a rejected key", async () => {
    const stop = {
      reason: "bad_key" as const,
      resumable: true,
      message: "The API key was rejected. Replace it in Settings, then press Resume.",
    };
    render(<Dock messages={message(stop)} />);
    await expect.element(frame()).toMatchScreenshot(shot("stop-bad-key"));
  });

  it("shows only the message when it can no longer be resumed", async () => {
    const stop = {
      reason: "step_limit" as const,
      resumable: false,
      message: "This turn stopped and cannot be resumed again. Send a new message.",
    };
    render(<Dock messages={message(stop)} />);
    await expect.element(frame()).toMatchScreenshot(shot("stop-final"));
  });
});

const question: ChatMessage = {
  id: "u",
  role: "user",
  text: "Assess testane",
  error: null,
  streaming: false,
  tools: [],
  interrupted: null,
};
const answering: ChatMessage = {
  id: "a",
  role: "assistant",
  text: "I found the facilities and I am reading the toxicity values.",
  error: null,
  streaming: true,
  tools: [
    { callId: "c0", label: "Found facilities", state: "done" },
    { callId: "c1", label: "Read toxicity", state: "running" },
  ],
  interrupted: null,
};
const running: ChatMessage[] = [question, answering];
const reading: LiveStatus = { phase: "running_tool", label: "Read toxicity", position: null };

describe("live turn status, in a real browser", () => {
  it("says how many turns are ahead while it waits for a worker", async () => {
    const queued: LiveStatus = { phase: "queued", label: null, position: 2 };
    render(<Dock messages={[question, { ...answering, text: "", tools: [] }]} busy status={queued} />);
    await expect.element(frame()).toMatchScreenshot(shot("live-queued"));
  });

  it("names the running step and offers Stop above the conversation", async () => {
    render(<Dock messages={running} busy status={reading} />);
    await expect.element(frame()).toMatchScreenshot(shot("live-running"));
  });

  it("dims Stop once a stop was asked for", async () => {
    render(<Dock messages={running} busy stopping status={reading} />);
    await expect.element(frame()).toMatchScreenshot(shot("live-stopping"));
  });
});
