import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MessageStream } from "./MessageStream";
import { SuggestionChips } from "./SuggestionChips";

const SUGGESTIONS = ["Map hexane releases", "Find a read-across surrogate", "Assess benzene"];

describe("SuggestionChips", () => {
  it("sends the chip's text when clicked", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<SuggestionChips suggestions={SUGGESTIONS} disabled={false} onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: "Find a read-across surrogate" }));
    expect(onPick).toHaveBeenCalledWith("Find a read-across surrogate");
  });

  it("is disabled while sending is not possible", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<SuggestionChips suggestions={SUGGESTIONS} disabled onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: "Assess benzene" }));
    expect(onPick).not.toHaveBeenCalled();
  });

  it("renders nothing without suggestions", () => {
    const { container } = render(<SuggestionChips suggestions={[]} disabled={false} onPick={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("onboarding in the message stream", () => {
  it("shows the chips on an empty conversation and submits a pick", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<MessageStream messages={[]} suggestions={SUGGESTIONS} canSend onSend={onSend} />);
    await user.click(screen.getByRole("button", { name: "Assess benzene" }));
    expect(onSend).toHaveBeenCalledWith("Assess benzene");
  });

  it("hides the onboarding once the conversation has started", () => {
    render(
      <MessageStream
        messages={[{ id: "u", role: "user", text: "hi", error: null, streaming: false, tools: [], interrupted: null }]}
        suggestions={SUGGESTIONS}
        canSend
        onSend={vi.fn()}
      />,
    );
    expect(screen.queryByRole("list", { name: "Suggestions" })).toBeNull();
  });
});
