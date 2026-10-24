import { act, fireEvent, render, afterEach, beforeEach, describe, expect, it, vi, App,
  installResponsiveMatchMedia, reviewEmptyPayload } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; vi.useRealTimers(); });

describe("Ask history publication recovery", () => {
  it.each(["recover", "dismiss", "dismiss-during-retry"])("handles saved Ask history over Overview when publication becomes current: %s", async (action) => {
    vi.useFakeTimers();
    let priorityCalls = 0;
    let conversationCalls = 0;
    const operations: string[] = [];
    let releaseRecovery!: () => void;
    const recovering = new Promise<void>((resolve) => { releaseRecovery = resolve; });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { operation: string; payload: Record<string, unknown> }) => {
        operations.push(operation);
        if (operation === "bridge.open_vault") return { protocol: "2.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        let data: unknown = {};
        if (payload.surface === "overview_accounts") {
          priorityCalls += 1;
          data = { state: priorityCalls === 1 ? "stale" : "ready", freshness: priorityCalls === 1 ? "stale" : "current", lifecycle: priorityCalls === 1 ? "stale" : "equal", revision: priorityCalls === 1 ? "old" : "current", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" };
        } else if (payload.surface === "review") data = reviewEmptyPayload;
        else if (payload.surface === "conversation") {
          conversationCalls += 1;
          if (conversationCalls === 2 && action === "dismiss-during-retry") await recovering;
          data = conversationCalls === 1 ? { state: "failed", reason: "read_store_unavailable" }
            : { turns: [{ id: "saved-turn", kind: "ask", context_mode: "new_question", prompt: "Saved synthetic question", outcome: "completed", message: "Saved synthetic answer" }], questions: [], total: 0 };
        }
        return { protocol: "2.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "synthetic", data } as T };
      },
    };
    const view = render(<App />);
    try {
      fireEvent.click(view.getByRole("button", { name: "Open existing vault" }));
      fireEvent.change(view.getByLabelText("Vault directory"), { target: { value: "/synthetic" } });
      fireEvent.change(view.getByLabelText("Passphrase"), { target: { value: "synthetic" } });
      await act(async () => { fireEvent.click(view.getByRole("button", { name: "Open local vault" })); });
      await act(async () => { fireEvent.click(view.getByRole("button", { name: "Ask Viva" })); });
      expect(view.getByText("Conversation could not be loaded")).toBeInTheDocument();
      const draft = view.getByRole("textbox", { name: "Your question" });
      fireEvent.change(draft, { target: { value: "My draft during publication" } });
      draft.focus();
      expect(view.getByText("Starting a new conversation")).toBeInTheDocument();
      if (action === "dismiss") await act(async () => { fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" })); });
      await act(async () => { await vi.advanceTimersByTimeAsync(250); });
      if (action === "dismiss-during-retry") {
        expect(conversationCalls).toBe(2);
        await act(async () => { fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" })); });
        await act(async () => { releaseRecovery(); await recovering; });
        expect(view.queryByRole("dialog", { name: "Ask Viva" })).toBeNull();
        expect(view.queryByText("Saved synthetic answer")).toBeNull();
        expect(operations).not.toContain("viva.conversation.ask");
        return;
      }
      if (action === "dismiss") {
        expect(conversationCalls).toBe(1);
        expect(view.queryByRole("dialog", { name: "Ask Viva" })).toBeNull();
        expect(view.queryByText("Saved synthetic answer")).toBeNull();
        return;
      }
      expect(view.queryByText("Conversation could not be loaded")).toBeNull();
      expect(view.getByText("Saved synthetic question")).toBeInTheDocument();
      expect(view.getByText("Saved synthetic answer")).toBeInTheDocument();
      expect(view.container.querySelector('button[aria-current="page"]')).toHaveTextContent("Overview");
      expect(conversationCalls).toBe(2);
      expect(view.getByRole("textbox", { name: "Your question" })).toBe(draft);
      expect(draft).toHaveValue("My draft during publication");
      expect(draft).toHaveFocus();
      expect(view.getByText("Starting a new conversation")).toBeInTheDocument();
      expect(view.queryByText("Continuing this conversation")).toBeNull();
      expect(view.getByRole("button", { name: "Continue previous conversation" })).toBeInTheDocument();
      expect(operations).not.toContain("viva.conversation.ask");
    } finally { view.unmount(); }
  });
});
