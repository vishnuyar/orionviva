import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, reviewEmptyPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("documents", () => {
  it("sends one document per gesture, reads the vault again, and says only what the vault said", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: Array<{ operation: string; payload: Record<string, unknown> }> = [];
    let captured = false;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        operations.push({ operation, payload });
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") {
          captured = true;
          return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? (captured
            ? { documents: [{ id: "captured-identity", doc_type: "statement", filename: "quarter-close.pdf", resolved: false, raw_available: true, reading: "never_read" }], reading_sentence: SAVED_NO_READER }
            : { documents: [], reading_sentence: "" })
            : surface === "conversation" ? { turns: [], questions: [], total: 0, invite: "", answered_by_document: "" }
              : surface === "review" ? reviewEmptyPayload
                : surface === "trust" ? trustPayload
                : surface === "plans" ? { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] }
                  : activityPayload;
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      pickDocumentPaths: async () => ["/chosen/first.pdf"],
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { container, getAllByText, getByLabelText, getByRole, getByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Statements" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Statements" }));
      expect(getByText("Add a statement to begin, or open the sample vault to see a populated document index.")).toBeInTheDocument();

      operations.length = 0;
      await user.click(getByRole("button", { name: "Choose statement file" }));

      // Capture sends one path, then rereads every destination and the job registry.
      await waitFor(() => expect(container.querySelector(".document-library")).toHaveTextContent("quarter-close.pdf"));
      expect(operations.map((frame) => frame.operation)).toEqual(["viva.documents.upload", ...Array(8).fill("viva.surface.read")]);
      expect(operations[0].payload).toEqual({ path: "/chosen/first.pdf" });
      expect(operations.slice(1).map((frame) => frame.payload.surface).sort()).toEqual(["activity", "conversation", "documents", "jobs", "overview", "plans", "review", "trust"]);
      expect(getAllByText(SAVED_NO_READER).length).toBeGreaterThan(0);

      // A dropped path is the same request from the same screen: a path
      // crosses, and nothing about the file's contents does.
      operations.length = 0;
      expect(listen).not.toBeNull();
      await act(async () => { listen?.(["/dropped/second.pdf"]); });
      await waitFor(() => expect(operations.map((frame) => frame.operation)).toEqual(["viva.documents.upload", ...Array(8).fill("viva.surface.read")]));
      expect(operations[0].payload).toEqual({ path: "/dropped/second.pdf" });

      // More than one document in one gesture is refused in this window,
      // before anything is sealed, and nothing is sent.
      operations.length = 0;
      await act(async () => { listen?.(["/dropped/third.pdf", "/dropped/fourth.pdf"]); });
      expect(operations).toEqual([]);
      const refusal = container.querySelector(".notice");
      expect(refusal).toHaveTextContent("This takes one document at a time. Nothing was added.");
      expect(refusal).toHaveAttribute("data-kind", "refused");
      expect(refusal).toHaveClass("notice-refused");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("names what a lost passphrase costs to the field and the control beside it", async () => {
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = { request: async <T,>(frame: { requestId: string }) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) };
    const consequence = "This opens the vault in the folder you name. If there is none there, nothing is made unless you say so above — a folder named by mistake would otherwise look like an empty vault. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it.";
    try {
      const { container, getByLabelText, getByRole, getByText } = render(<App />);
      expect(getByText(consequence)).toBeInTheDocument();
      expect(getByLabelText("Passphrase")).toHaveAccessibleDescription(consequence);
      expect(getByRole("button", { name: "Open local vault" })).toHaveAccessibleDescription(consequence);
      // The nesting the capture stylesheet is written against.
      expect(container.querySelector(".vault-open-form .vault-passphrase-consequence")).not.toBeNull();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("says so when the file picker could not be opened, and stays quiet when it was closed with nothing chosen", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let picker: () => Promise<readonly string[]> = async () => [];
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      pickDocumentPaths: () => picker(),
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Statements" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Statements" }));

      // Closed with nothing chosen is a person changing their mind.
      await user.click(getByRole("button", { name: "Choose statement file" }));
      expect(queryByText("The file picker could not be opened, so nothing was chosen and nothing was added to this vault.")).not.toBeInTheDocument();

      // A picker that could not be opened is a control that did not work.
      picker = async () => { throw new Error("the dialog never opened"); };
      await user.click(getByRole("button", { name: "Choose statement file" }));
      await waitFor(() => expect(getByText("The file picker could not be opened, so nothing was chosen and nothing was added to this vault.")).toBeInTheDocument());
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("takes a person to the receipt when a file is dropped on another screen, and keeps it there afterwards", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { getAllByText, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Overview" })).toBeInTheDocument());
      expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();

      // The drop lands while another screen is open. Something durable happens,
      // so the screen that can say what became of it is what the person sees.
      await act(async () => { listen?.(["/dropped/first.pdf"]); });
      await waitFor(() => expect(getByRole("heading", { name: "Statements & documents" })).toBeInTheDocument());
      await waitFor(() => expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1));

      // What was written is the session's, not the panel's: leaving the screen
      // and returning does not discard the receipt for it.
      await user.click(getByRole("button", { name: "Overview" }));
      await user.click(getByRole("button", { name: "Statements" }));
      expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("refuses a picker that hands back more than one document, and seals none of them", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: string[] = [];
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        operations.push(operation);
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      // A shim that lost its cap. The refusal is at the door both gestures
      // pass through, so nothing is sealed here either.
      pickDocumentPaths: async () => ["/chosen/first.pdf", "/chosen/second.pdf"],
    };

    try {
      const { container, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Statements" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Statements" }));

      operations.length = 0;
      await user.click(getByRole("button", { name: "Choose statement file" }));

      await waitFor(() => expect(container.querySelector(".notice")).toHaveTextContent("This takes one document at a time. Nothing was added."));
      expect(operations).toEqual([]);
      expect(container.querySelector(".notice")).toHaveAttribute("data-kind", "refused");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("sends one vault-open request however many times the control is pressed", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: string[] = [];
    let release: (() => void) | undefined;
    window.orionVivaBridge = {
      request: <T,>({ operation }: { requestId: string; operation: string }) => {
        operations.push(operation);
        return new Promise<{ protocol: string; request_id: string; ok: boolean; result: T }>((resolve) => {
          release = () => resolve({ protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T });
        });
      },
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");

      // The form that creates a vault, on a transport that answers one request
      // before it reads the next. Pressing again while it waits sends nothing.
      await user.click(getByRole("button", { name: "Open local vault" }));
      const waiting = getByRole("button", { name: "Opening vault..." });
      await user.click(waiting);
      await user.click(waiting);
      expect(operations).toEqual(["bridge.open_vault"]);

      release?.();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("announces the move when a dropped file changes the screen from under a person", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { container, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: "Overview" })).toBeInTheDocument());

      // A drawer is open, so the screen under it is inert and anything landing
      // there would be announced to nobody and painted behind the drawer.
      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByRole("dialog", { name: "Ask Viva" })).toBeInTheDocument();

      await act(async () => { listen?.(["/dropped/first.pdf"]); });

      await waitFor(() => expect(container.querySelector("main")).not.toHaveAttribute("inert"));
      expect(queryByRoleIn(container, "dialog")).toBeNull();
      await waitFor(() => expect(document.getElementById("page-title")).toHaveTextContent("Statements & documents"));
      await waitFor(() => expect(document.getElementById("page-title")).toHaveFocus());
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
