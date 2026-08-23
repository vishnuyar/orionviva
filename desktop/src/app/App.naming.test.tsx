import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("naming a folder", () => {
  it("makes no vault unless a person said to, and repeats the vault's own sentence", async () => {
    // A path typed with a letter wrong used to answer as an opened, brand-new
    // empty vault, which reads to somebody as their records having vanished.
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const sent: Array<Record<string, unknown>> = [];
    window.orionVivaBridge = {
      request: async <T,>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        sent.push(frame.payload);
        return { protocol: "2.0", request_id: frame.requestId, ok: false, error: { code: "vault_absent", message: moments.vault_absent } } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T };
      },
    };
    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/typo");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(sent[0].create).toBe(false);
      expect(getAllByRole("status")[0]).toHaveTextContent(moments.vault_absent);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("asks for a vault to be made only when the box is ticked, and says so on the control", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const sent: Array<Record<string, unknown>> = [];
    window.orionVivaBridge = {
      request: async <T,>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (frame.operation === "bridge.open_vault") sent.push(frame.payload);
        const data = frame.payload.surface === "overview" ? { accounts: [] } : frame.payload.surface === "documents" ? { documents: [] } : frame.payload.surface === "trust" ? trustPayload : frame.payload.surface === "activity" ? activityPayload : { questions: [], total: 0 };
        return { protocol: "2.0", request_id: frame.requestId, ok: true, result: (frame.operation === "bridge.open_vault" ? { state: "created" } : { surface: frame.payload.surface, job_id: "job", data }) as T };
      },
    };
    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/new");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByLabelText("Make a new vault in that folder"));
      expect(getByRole("button", { name: "Make and open vault" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: "Make and open vault" }));

      expect(sent[0].create).toBe(true);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("never repeats machine text from a code whose message is not a reviewed sentence", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "2.0", request_id: "r", ok: false, error: { code: "handler_failed", message: "Everyday Checking has 1200.00" } } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T }),
    };
    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getAllByRole("status")[0]).not.toHaveTextContent("Everyday Checking");
      expect(getAllByRole("status")[0]).toHaveTextContent("The local vault could not be opened.");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
