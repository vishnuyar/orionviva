import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("vault", () => {
  it("asks the native host to choose a vault directory and copies the selection into the manual field", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => "/chosen/local-vault");
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/chosen/local-vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("treats a cancelled native picker as a no-op and keeps the manual path", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => null);
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
      expect(queryByRole("status")).toBeNull();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps picker failures bounded and leaves manual entry available", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const hostFailure = "dialog failed while reading /private/vault";
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory: async () => { throw new Error(hostFailure); },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(getAllByRole("status")[0]).toHaveTextContent(/folder picker could not be opened/i);
      expect(getAllByRole("status")[0]).not.toHaveTextContent(hostFailure);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("opens a local vault through the injected host bridge", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => ({
        protocol: "1.0",
        request_id: "req",
        ok: true,
        result: (operation === "bridge.open_vault"
          ? { state: "opened" }
          : { surface: payload.surface, job_id: "job-1", data: payload.surface === "overview" ? { accounts: [], as_of: "August 1, 2026" } : payload.surface === "documents" ? { documents: [] } : payload.surface === "trust" ? trustPayload : payload.surface === "activity" ? activityPayload : { questions: [], total: 0 } }) as T,
      }),
    };

    try {
      const { getAllByText, getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByText("Private vault")).toBeInTheDocument());
      expect(getByText("Opened on this device")).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("hides the sample surface as soon as a private vault opens, while live reads are still pending", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let releaseReads: () => void = () => {};
    const readsCanFinish = new Promise<void>((resolve) => {
      releaseReads = resolve;
    });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        await readsCanFinish;
        const data = payload.surface === "overview"
          ? { accounts: [] }
          : payload.surface === "documents"
            ? { documents: [] }
            : payload.surface === "trust"
              ? trustPayload
              : payload.surface === "activity"
                ? activityPayload
              : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Private vault")).toBeInTheDocument();
      expect(getByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).toBeInTheDocument();
      expect(queryByText("USD 17,486.45")).not.toBeInTheDocument();
      expect(queryByText("Everyday Checking")).not.toBeInTheDocument();
      releaseReads();
      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(queryByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps a closed vault closed even when its read resolves later", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let releaseReads: () => void = () => {};
    const readsCanFinish = new Promise<void>((resolve) => {
      releaseReads = resolve;
    });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        await readsCanFinish;
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "late-private", name: "Late private account", balance: { amount: "999.99", grade: "verified" } }] }
          : payload.surface === "documents"
            ? { documents: [{ id: "late-private-document", doc_type: "statement" }] }
            : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByText, getAllByRole, getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      expect(getByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).toBeInTheDocument();

      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
      expect(queryByText("Late private account")).not.toBeInTheDocument();

      // The read that was still in flight when the vault was closed lands on a
      // session that has moved on. It changes nothing: a row from a vault
      // nobody has open any more is a row about somebody's money on a screen
      // that says no vault is open.
      releaseReads();
      await waitFor(() => expect(getAllByText("No vault open")[0]).toBeInTheDocument());
      expect(queryByText("Late private account")).not.toBeInTheDocument();
      expect(queryByText("late-private-document")).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders combined live surfaces, and closing takes every one of them away", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview"
          ? { as_of: "2026-08-18", accounts: [{ account: "live-account", name: "Private checking", kind: "deposit", currency: "USD", balance: { amount: "101.25", grade: "conflicted", dated: "2026-08-18" } }] }
          : surface === "documents"
            ? { documents: [{ id: "live-document", doc_type: "statement", resolved: false, raw_available: true }] }
            : surface === "conversation"
              ? { turns: [], questions: [{ id: "live-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, tail: { count: 0, amount: "0" }, pending: { count: 0 }, invite: "Write an answer", answered_by_document: "A document answers this" }
              : surface === "trust" ? trustPayload : activityPayload;
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText, getAllByText, queryByRole, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      // Twice on the screen: the account card and the selected-account panel. A
      // figure carries its subject in text a reader hears and a screen does not
      // show, and this counts what is shown.
      await waitFor(() => expect(getAllByText("Private checking", { ignore: "script, style, .figure-invitation" })).toHaveLength(2));
      expect(getByText("Private vault")).toBeInTheDocument();
      expect(getByText("Opened on this device")).toBeInTheDocument();
      expect(getByText("Private vault · Opened on this device")).toBeInTheDocument();
      expect(getByRole("complementary", { name: "Vault source" })).toHaveTextContent("The surfaces below are read from this vault. Features that are not connected stay hidden or say so.");
      expect(getAllByText("Conflicting evidence").length).toBeGreaterThan(0);
      expect(queryByText("101.25")).not.toBeInTheDocument();
      expect(getAllByText("Amount unavailable from this preview read.").length).toBeGreaterThan(0);
      expect(queryByText("USD 17,486.45")).not.toBeInTheDocument();
      expect(queryByText(/silverline-checking/i)).not.toBeInTheDocument();
      expect(queryByText("Every figure carries its date, scope, and evidence. Uncertainty stays visible.")).not.toBeInTheDocument();
      expect(queryByText("Document capture is not connected for this vault.")).not.toBeInTheDocument();
      expect(queryByRole("button", { name: /add document/i })).not.toBeInTheDocument();

      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(queryByText("101.25")).not.toBeInTheDocument();
      expect(getAllByText("Amount unavailable from this preview read.").length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /overview.*your picture/i }));

      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByRole("button", { name: /^Ask$/i })).toBeInTheDocument();
      expect(document.body).not.toHaveTextContent("Recorded conversation is unavailable");
      expect(queryByText("What changed this month?")).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /close viva conversation/i }));

      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByRole("heading", { name: "statement" })).toBeInTheDocument();
      expect(getAllByText(/live-document/).length).toBeGreaterThan(0);
      expect(queryByText("Capture queue")).not.toBeInTheDocument();
      expect(queryByRole("button", { name: /choose a/i })).not.toBeInTheDocument();
      expect(queryByText("Document capture unavailable")).not.toBeInTheDocument();

      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByRole("heading", { name: "Is this your account?" })).toBeInTheDocument();
      expect(queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
      expect(getByRole("button", { name: "Set aside for now" })).toBeInTheDocument();
      expect(getByText("Setting a question aside, answering in your own words, and confirming or declining a resulting proposal are connected. Correcting a document is not.")).toBeInTheDocument();
      // The read supplies an invitation to answer in a sentence. Nothing here
      // can take one, so a real vault's invitation is never put to a person.
      expect(queryByText("Write an answer")).not.toBeInTheDocument();
      expect(queryByText(/invites an answer in a sentence/)).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /close viva conversation/i }));

      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
      expect(queryByText("Private checking")).not.toBeInTheDocument();
      expect(queryByText("live-document")).not.toBeInTheDocument();
      expect(queryByText("Is this your account?")).not.toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders a complete backend canonical account display byte-for-byte", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const canonicalDisplay = "Canonical backend display — USD 202.50";
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "complete-account", name: "Complete account", balance: { amount: "202.50", display: canonicalDisplay, measure: "balance", currency: "USD", dated: "2026-08-18", coverage: "Statement period ending 2026-08-18", provenance: "document live-doc, page 7", grade: "verified" } }] }
          : payload.surface === "documents" ? { documents: [] } : payload.surface === "trust" ? trustPayload : payload.surface === "activity" ? activityPayload : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getByLabelText, getByRole, getAllByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getAllByText(canonicalDisplay).length).toBeGreaterThan(0));
      expect(queryByText("202.50")).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(getAllByText(canonicalDisplay).length).toBeGreaterThan(0);
      expect(queryByText("202.50")).not.toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders an explicit empty state for every private-vault destination", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const data = payload.surface === "overview"
          ? { accounts: [] }
          : payload.surface === "documents"
            ? { documents: [] }
            : payload.surface === "trust"
              ? trustPayload
              : payload.surface === "activity"
                ? activityPayload
              : { turns: [], questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getAllByText, getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(getByText("Local source", { selector: ".privacy-lock span" })).toBeInTheDocument();
      expect(getByText("Every vault this app opens, the sample one included, is opened through the local desktop host on this machine.")).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("No documents yet", { selector: "strong" })).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByText("Nothing needs you right now", { selector: "strong" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /close viva conversation/i }));
      await user.click(getByRole("button", { name: /activity.*what moved/i }));
      // Activity is a read. A vault that knows of nothing moving says so,
      // which is not the same as nothing having moved.
      expect(getAllByText(moments.activity_empty).length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /trust.*how it works/i }));
      // Trust is a read, and a vault that has sent nothing says so with the
      // same prominence as one that has. That emptiness is the record.
      expect(getAllByText(moments.outbound_none).length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("reports a partial private-vault read without discarding successful surfaces", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        if (payload.surface === "documents") {
          throw new Error("private path must stay bounded");
        }
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "kept-account", name: "Kept account", balance: { amount: "1", grade: "unverified" } }] }
          : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText, getAllByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getAllByRole("status")[0]).toHaveTextContent("The private vault opened, but some surfaces could not be read. Your vault was not changed."));
      expect(getAllByText("Kept account", { ignore: "script, style, .figure-invitation" })).toHaveLength(2);
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("validates the vault-open form before calling the host", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let calls = 0;
    window.orionVivaBridge = {
      request: async <T,>() => {
        calls += 1;
        return { protocol: "1.0", request_id: "req", ok: true, result: { state: "opened" } as T };
      },
    };

    try {
      const { getByRole, getByText } = render(<App />);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Enter a vault directory and passphrase to open a local vault.")).toBeInTheDocument();
      expect(calls).toBe(0);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows an opening state while the host request is pending", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let resolveRequest: (() => void) | undefined;
    window.orionVivaBridge = {
      request: <T,>() => new Promise<{ protocol: string; request_id: string; ok: boolean; result: T }>((resolve) => {
        resolveRequest = () => resolve({
          protocol: "1.0",
          request_id: "req",
          ok: true,
          result: {} as T,
        });
      }),
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      const control = getByRole("button", { name: "Opening vault..." });
      expect(control).not.toHaveAttribute("disabled");
      expect(control).toHaveAttribute("aria-disabled", "true");
      // Both sentences reach the control: what a lost passphrase costs, which
      // is what this form is for, and why pressing again does nothing.
      expect(control).toHaveAccessibleDescription("This opens the vault in the folder you name. If there is none there, nothing is made unless you say so above — a folder named by mistake would otherwise look like an empty vault. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it. Your vault is answering the last request. Pressing again does nothing until it has.");
      resolveRequest?.();
      await waitFor(() => expect(getByRole("button", { name: "Open local vault" })).not.toHaveAttribute("aria-disabled", "true"));
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows a bounded open error and clears the passphrase", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const secret = "correct horse battery staple";
    window.orionVivaBridge = {
      request: async <T,>() => ({
        protocol: "1.0",
        request_id: "req",
        ok: false,
        error: { code: "vault_open_failed", message: "internal details must not reach the UI" },
      } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T }),
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), secret);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getAllByRole("status")[0]).toHaveTextContent("The local vault could not be opened.");
      expect(getAllByRole("status")[0]).not.toHaveTextContent(secret);
      expect(getByLabelText("Passphrase")).toHaveValue("");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
