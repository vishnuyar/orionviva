import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("conversation questions and corrections", () => {
  it("says what became of a question set aside and moves focus once the write has settled", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let setAside = false;
    const questions = () => (setAside
      ? [{ id: "second-question", kind: "merchant", text: "What is this payment for?", why: "The merchant is unknown." }]
      : [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." },
         { id: "second-question", kind: "merchant", text: "What is this payment for?", why: "The merchant is unknown." }]);
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.conversation.decline") {
          setAside = true;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "completed", message: "Set aside until something changes.", state: null, reason: null } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : surface === "conversation" ? { turns: [], questions: questions(), total: setAside ? 1 : 2, invite: "Write an answer", answered_by_document: "A document answers this" }
              : surface === "trust" ? trustPayload : activityPayload;
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Ask Viva" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Ask Viva" }));

      await user.click(getByRole("button", { name: "Set aside for now" }));

      // The question leaves the queue and the control that was pressed goes
      // with it, so what happened is said where it can still be read and focus
      // lands on the question the queue moved to.
      await waitFor(() => expect(getByRole("heading", { name: "What is this payment for?" })).toBeInTheDocument());
      await waitFor(() => expect(document.getElementById("selected-question-title")).toHaveFocus());
      expect(getAllByRole("status").some((status) => status.textContent?.includes("Set aside until something changes."))).toBe(true);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("never disables the pressed control, so a refusal leaves it under the person's hands", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let answerDecline: () => void = () => {};
    const declineAnswered = new Promise<void>((resolve) => { answerDecline = resolve; });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.conversation.decline") {
          await declineAnswered;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "refused", message: "That question is no longer open.", state: null, reason: "not_open" } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : surface === "conversation" ? { turns: [], questions: [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, invite: "Write an answer", answered_by_document: "A document answers this" }
              : surface === "trust" ? trustPayload : activityPayload;
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Ask Viva" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Ask Viva" }));

      const control = getByRole("button", { name: "Set aside for now" });
      await user.click(control);

      // The vault has not answered yet. A focused element that becomes disabled
      // is blurred to the document body by the browser this ships in, and this
      // test environment does not implement that blur — so what is asserted
      // through the whole in-flight window is that the control was never
      // disabled, which is observable in both.
      await waitFor(() => expect(getAllByRole("status").some((status) => status.textContent?.includes("Setting this question aside"))).toBe(true));
      expect(control).not.toBeDisabled();
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveFocus();

      answerDecline();

      // Nothing moved, so the control the person must use again is still under
      // their hands and the screen does not take focus off it.
      await waitFor(() => expect(getAllByRole("status").some((status) => status.textContent?.includes("That question is no longer open."))).toBe(true));
      expect(control).not.toBeDisabled();
      expect(control).toHaveFocus();
    } finally {
      answerDecline();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("gives focus somewhere to land when the read after a write fails, and says the queue is unread", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let setAside = false;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.conversation.decline") {
          setAside = true;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "completed", message: "Set aside until something changes.", state: null, reason: null } as T };
        }
        const surface = payload.surface;
        if (surface === "conversation" && setAside) throw new Error("bounded read failure");
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : surface === "conversation" ? { turns: [], questions: [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, invite: "Write an answer", answered_by_document: "A document answers this" }
              : surface === "trust" ? trustPayload : activityPayload;
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Ask Viva" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Ask Viva" }));

      await user.click(getByRole("button", { name: "Set aside for now" }));

      // The write took and the read that followed did not, so the panel and the
      // control are both gone. What happened is still said, it says the queue
      // was not read again, and focus lands on it rather than on the body.
      await waitFor(() => expect(getByText("Conversation could not be read")).toBeInTheDocument());
      expect(getAllByRole("status").some((status) => status.textContent?.includes("Set aside until something changes."))).toBe(true);
      await waitFor(() => expect(document.getElementById("conversation-action-outcome")).toHaveFocus());
      expect(document.activeElement).not.toBe(document.body);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
