import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClearChatButton } from "./ClearChatButton";

describe("ClearChatButton", () => {
  it("clears the chat when clicked", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(<ClearChatButton blocked={null} onClear={onClear} />);
    await user.click(screen.getByRole("button", { name: "Clear chat" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("does nothing while blocked, and says why", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(<ClearChatButton blocked="nothing to clear yet" onClear={onClear} />);
    const button = screen.getByRole("button", { name: "Clear chat" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Clear chat: nothing to clear yet");
    expect(button).toHaveAttribute("aria-description", "nothing to clear yet");
    await user.click(button);
    expect(onClear).not.toHaveBeenCalled();
  });
});
