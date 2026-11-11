import { render, screen } from "@testing-library/react";

import type { ChatMessage, LiveStatus } from "../../hooks/chatState";
import { ChatDock } from "./ChatDock";

const streaming: ChatMessage = {
  id: "a",
  role: "assistant",
  text: "",
  error: null,
  streaming: true,
  tools: [],
  interrupted: null,
};

function dock(status: LiveStatus | null, busy = true) {
  render(
    <ChatDock
      messages={[streaming]}
      busy={busy}
      hasKey
      usage={null}
      status={status}
      onSend={() => {}}
      onClear={() => {}}
      onOpenSettings={() => {}}
      onCollapse={() => {}}
    />,
  );
}

describe("ChatDock header status", () => {
  it("says the turn is queued while it waits for a worker", () => {
    dock({ phase: "queued", label: null, position: 1 });
    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("says thinking once a worker runs it", () => {
    dock({ phase: "running_tool", label: "Read toxicity", position: null });
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.queryByText("Queued")).toBeNull();
  });

  it("says ready when nothing runs", () => {
    dock(null, false);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });
});
