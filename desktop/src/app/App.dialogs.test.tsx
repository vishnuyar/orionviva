import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("dialogs", () => {
  it("opens the Viva conversation drawer with cited turns and refusal states", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    // Viva is not connected to a vault read, so the drawer says so rather than
    // showing turns from somewhere else. What it does carry is the box that
    // takes a question, which is not a read and does not wait for one.
    expect(getByText("Conversation isn’t connected yet")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("picture is complete");
    expect(document.body).not.toHaveTextContent("Brokerage statement, page 4");
    // The box that takes a question is outside the read's gate, so a person
    // can ask even where nothing has been answered yet.
    expect(getByRole("button", { name: /^Ask$/i })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /close viva conversation/i }));
    expect(getByRole("button", { name: /ask viva/i })).toBeInTheDocument();
  });

  it("moves keyboard focus into the Viva dialog when it opens", async () => {
    const user = userEvent.setup();
    const { getByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toContainElement(document.activeElement as HTMLElement | null);
  });

  it("lets a keyboard user dismiss the Viva dialog with Escape", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));
    await user.keyboard("{Escape}");

    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
  });

  it("locks and inerts the shell while Viva is open, then Close restores its opener and exact overflow", async () => {
    const user = userEvent.setup();
    const priorRoot = document.documentElement.style.overflow;
    const priorBody = document.body.style.overflow;
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "visible";
    try {
      const { getByRole } = await openSample();
      const opener = getByRole("button", { name: "Ask Viva" });
      await user.click(opener);
      expect(getByRole("button", { name: "Close Viva conversation" })).toHaveFocus();
      expect(document.querySelector("main")).toHaveAttribute("inert");
      expect(document.getElementById("primary-navigation-drawer")).toHaveAttribute("inert");
      expect(document.documentElement.style.overflow).toBe("hidden");
      expect(document.body.style.overflow).toBe("hidden");
      await user.click(getByRole("button", { name: "Close Viva conversation" }));
      await waitFor(() => expect(opener).toHaveFocus());
      expect(document.documentElement.style.overflow).toBe("clip");
      expect(document.body.style.overflow).toBe("visible");
    } finally {
      document.documentElement.style.overflow = priorRoot;
      document.body.style.overflow = priorBody;
    }
  });

  it("traps both Viva tab boundaries, recaptures outside focus, and restores from the backdrop", async () => {
    const user = userEvent.setup();
    const { container, getByRole } = await openSample();
    const opener = getByRole("button", { name: "Ask Viva" });
    await user.click(opener);
    const dialog = getByRole("dialog", { name: "Viva conversation" });
    const close = getByRole("button", { name: "Close Viva conversation" });
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(close).not.toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();
    fireEvent.focus(getByRole("heading", { name: "Your financial picture" }));
    expect(close).toHaveFocus();
    fireEvent.click(container.querySelector(".conversation-backdrop") as HTMLElement);
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("closes a stale conversation scope without restoring its opener", async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole, queryByRole } = await openSample();
    const opener = getByRole("button", { name: "Ask Viva" });
    await user.click(opener);
    fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave, hidden: true })[0]);
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    expect(document.querySelector("main")).not.toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("inert");
  });

  it("keeps the Viva shell dismissible when its body throws and recovers on reset", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const dismiss = vi.fn();
    const drawer = createRef<HTMLElement>();
    const close = createRef<HTMLButtonElement>();
    try {
      const view = render(<ConversationDialogShell resetKey="request-1-demo" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><ThrowingConversationBody /></ConversationDialogShell>);
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      expect(view.getByText("This surface could not be shown")).toBeInTheDocument();
      fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      expect(dismiss).toHaveBeenCalledTimes(1);
      view.rerender(<ConversationDialogShell resetKey="request-2-live" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><div>Recovered supplied body</div></ConversationDialogShell>);
      expect(view.getByText("Recovered supplied body")).toBeInTheDocument();
      expect(view.getByText("This drawer shows the turns this vault recorded, and takes a question of your own.")).toBeInTheDocument();
    } finally {
      error.mockRestore();
    }
  });

  it("keeps the overview selected account spotlight in sync with selection", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    expect(getByText("Abroad Current", { selector: ".coverage-account-title" })).toBeInTheDocument();

    await user.click(container.querySelectorAll(".account-card-button")[4] as HTMLElement);

    expect(getByText("Household Card", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
  });

  it("shows the selected document detail inside documents", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "What this read can show" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
    // The read supplies identity, filename, kind, resolution and what the
    // document put on the books. Pages, source regions and provenance are not
    // supplied by any vault read, and this screen says so rather than showing
    // a field it filled in itself.
    expect(getAllByText("Page details are not supplied by this vault read.").length).toBeGreaterThan(0);
    expect(getByText("Related evidence is not supplied by this vault read.")).toBeInTheDocument();
  });



  it("opens Activity on the vault own movements, with no second implementation", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = await openSample();
    await user.click(getByRole("button", { name: /activity.*what moved/i }));
    expect(getByRole("heading", { name: "What moved" })).toBeInTheDocument();
    // One implementation, and no search box: the facet explorer this screen
    // used to carry existed only for rows composed in the shell.
    expect(queryByRole("searchbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /go to review queue/i })).not.toBeInTheDocument();
  });

  it("discards a pending document-heading focus when the source request changes", async () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    const cancelAnimationFrame = vi.fn((id: number) => pendingFrames.delete(id));
    globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
      frameId += 1;
      pendingFrames.set(frameId, callback);
      return frameId;
    });
    globalThis.cancelAnimationFrame = cancelAnimationFrame;

    try {
      const { queryByRole, getAllByRole, container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      expect(document.querySelector("#selected-document-title")).not.toHaveFocus();

      fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      expect(cancelAnimationFrame).toHaveBeenCalled();
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();

      fireEvent.click(getAllByRole("button", { name: "DocumentsWhat supports it" })[0]);
      expect(document.querySelector("#selected-document-title")).toBeNull();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("discards pending capture focus when the source request changes", async () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { frameId += 1; pendingFrames.set(frameId, callback); return frameId; });
    globalThis.cancelAnimationFrame = vi.fn((id: number) => pendingFrames.delete(id));

    try {
      const { queryByRole, getAllByRole, getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      expect(document.getElementById("document-capture-status")).not.toHaveFocus();
      fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();
      fireEvent.click(getAllByRole("button", { name: "DocumentsWhat supports it" })[0]);
      expect(document.getElementById("document-capture-status")).toBeNull();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("does not resurrect document-title focus after leaving and returning to Documents", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "bank_statement" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect document-title focus after selection diverges and returns", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
      fireEvent.click(getByRole("button", { name: /everyday-checking-2026-06\.pdf/i }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "bank_statement" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("opens fresh figure evidence and routes its exact source to the selected document heading", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    const trigger = getByRole("button", { description: "View the evidence for net worth in USD." });

    await user.click(trigger);
    expect(getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
    expect(getByRole("button", { name: "Close evidence" })).toHaveFocus();
    expect(document.querySelector("main")).toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).toHaveAttribute("inert");
    await user.click(getByRole("button", { name: "Open everyday-checking-2026-06.pdf" }));

    expect(queryByRole("dialog", { name: "Net worth in USD" })).not.toBeInTheDocument();
    await waitFor(() => expect(getByRole("heading", { name: "bank_statement" })).toHaveFocus());
  });

  it("keeps Evidence, Viva, and narrow navigation mutually exclusive", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { description: "View the evidence for net worth in USD." }));
    expect(getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Ask Viva", hidden: true }));
    expect(queryByRole("dialog", { name: "Net worth in USD" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();

    fireEvent.click(getByRole("button", { name: "Open navigation" }));
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    installResponsiveMatchMedia(1440);
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    await user.click(getByRole("button", { name: /May I ask what annual fee is/i }));
    expect(getByRole("heading", { name: /May I ask what/ })).toBeInTheDocument();
    expect(getByText("Set this question aside")).toBeInTheDocument();
    expect(getAllByText("160.00").length).toBeGreaterThan(0);
  });

  it("opens and focuses an exact review question from Overview", async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole, queryByRole } = await openSample();
    await user.click(getAllByRole("button", { name: "View question" })[1]);
    await waitFor(() => expect(getByRole("heading", { name: /May I ask what/ })).toHaveFocus());
    expect(queryByRole("button", { name: /^Answer$/i })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /^Confirm$/i })).not.toBeInTheDocument();
  });

  it("does not resurrect Overview review focus after leaving Review", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = await openSample();
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /trust.*how it works/i }));
      fireEvent.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: /May I ask what/ })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the selected identity changes", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = await openSample();
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /Your acct:everyday-checking statement/i }));
      fireEvent.click(getByRole("button", { name: /May I ask what annual fee is/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: /May I ask what/ })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the vault is closed", async () => {
    const frames = installCapturedAnimationFrames();
    const restore = installSampleBridge();
    try {
      const user = userEvent.setup();
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument());
      // A question opened from Overview asks for focus one frame later. The
      // vault is closed before that frame runs, so the focus it captured names
      // a question on a screen nobody is looking at any more.
      fireEvent.click(getAllByRole("button", { name: "View question" })[0]);
      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(document.querySelector("#selected-question-title")).toBeNull();
      expect(getByRole("heading", { name: "Review" })).toHaveFocus();
    } finally {
      restore();
      frames.restore();
    }
  });

  it("keeps the selected document when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    await user.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
    expect(getByRole("heading", { name: "brokerage_statement" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    expect(getByRole("heading", { name: "brokerage_statement" })).toBeInTheDocument();
    expect(queryByRole("button", { name: /open page review/i })).not.toBeInTheDocument();
    expect(getByText("Page and source-region review are not connected.")).toBeInTheDocument();
  });

  it("keeps the selected account when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    await user.click(container.querySelectorAll(".account-card-button")[1] as HTMLElement);
    await user.click(getByRole("button", { name: /open accounts/i }));
    expect(getByRole("heading", { name: "Accounts in this read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Dormant Savings" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    expect(getByText("Dormant Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
  });

  it("keeps the selected review question when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText } = await openSample();

    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    await user.click(getByRole("button", { name: /May I ask what annual fee is/i }));
    expect(getAllByText("160.00").length).toBeGreaterThan(0);

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    expect(getAllByText("160.00").length).toBeGreaterThan(0);
  });

  it("keeps the accounts detail panel focused on the selected account", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
    expect(getByRole("heading", { name: "Accounts in this read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Abroad Current" })).toBeInTheDocument();
    expect(getByText("Grade")).toBeInTheDocument();

    await user.click(container.querySelectorAll(".detail-row-button")[4] as HTMLElement);

    expect(getByRole("heading", { name: "Household Card" })).toBeInTheDocument();
  });

  it("lets the local capture notice be dismissed", async () => {
    const { getAllByRole, getByRole, queryByRole } = await openSample();

    fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    expect(getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");

    fireEvent.click(getByRole("button", { name: /dismiss notice/i }));
    expect(queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the Trust destination from what the vault read said", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    expect(getByRole("heading", { name: "Trust" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Trust and limitations" })).toBeInTheDocument();
    // The outbound record, and what nothing on this machine can establish.
    // Both are the read's; neither is a row this screen authored.
    expect(getAllByText(moments.trust_no_anchoring).length).toBeGreaterThan(0);
    expect(getByText("Local source", { selector: ".privacy-lock span" })).toBeInTheDocument();
    expect(getByText("Every vault this app opens, the sample one included, is opened through the local desktop host on this machine.")).toBeInTheDocument();
    expect(queryByRole("button", { name: "Go to documents" })).not.toBeInTheDocument();
    const source = getByRole("complementary", { name: "Vault source" });
    const trustHeader = getByRole("heading", { name: "Trust and limitations" });
    expect(source.compareDocumentPosition(trustHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("states the fictional sample boundary", async () => {
    const { getByRole, getByText } = await openSample();
    expect(getByRole("complementary", { name: "Vault source" })).toBeInTheDocument();
    expect(getByText(moments.sample_frame_detail)).toBeInTheDocument();
  });

  it("says a vault cannot be opened here when no host bridge is injected", async () => {
    const { getByText, queryByPlaceholderText } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByPlaceholderText("/path/to/vault")).not.toBeInTheDocument();
  });

  it("keeps manual directory entry as the browser fallback", async () => {
    const { getByText, queryByLabelText, queryByRole } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByRole("button", { name: /choose folder/i })).not.toBeInTheDocument();
    expect(queryByLabelText("Vault directory")).not.toBeInTheDocument();
  });

  it("exposes the collapsed and expanded state of narrow navigation", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));
    const openNavigation = getByRole("button", { name: "Open navigation" });
    const drawer = document.getElementById("primary-navigation-drawer");

    expect(openNavigation).toHaveAttribute("aria-expanded", "false");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(drawer).toHaveAttribute("inert");
    await user.click(openNavigation);
    expect(openNavigation).toHaveAttribute("aria-expanded", "true");
    expect(getByRole("dialog", { name: "Main navigation" })).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector("main")).toHaveAttribute("inert");
    expect(getByRole("button", { name: "Close navigation" })).toHaveFocus();
    const backdrop = document.querySelector<HTMLElement>(".navigation-backdrop");
    expect(backdrop).toHaveAttribute("aria-hidden", "true");
    expect(backdrop?.tabIndex).toBe(-1);
    expect(queryByRole("button", { name: /dismiss navigation/i })).not.toBeInTheDocument();
    fireEvent.click(backdrop as HTMLElement);
    await waitFor(() => expect(openNavigation).toHaveFocus());
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it("traps focus in narrow navigation and restores the trigger after Escape", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    document.body.style.overflow = "clip";
    document.documentElement.style.overflow = "scroll";
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");
    const close = getByRole("button", { name: "Close navigation" });
    const navButtons = document.querySelectorAll<HTMLElement>("#primary-navigation button");
    const last = navButtons[navButtons.length - 1];
    close.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(last).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("clip");
    expect(document.documentElement.style.overflow).toBe("scroll");
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  });

  it("moves outside focus into the open narrow dialog in either Tab direction", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    const dialog = getByRole("dialog", { name: "Main navigation" });
    const close = getByRole("button", { name: "Close navigation" });
    const currentPage = getByRole("button", { name: "OverviewYour picture" });
    expect(document.querySelector("main")).toHaveAttribute("inert");

    trigger.focus();
    const forward = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(close).toHaveFocus();

    document.getElementById("page-title")?.focus();
    const backward = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
    document.dispatchEvent(backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(getByRole("button", { name: "TrustHow it works" })).toHaveFocus();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(currentPage).toHaveAttribute("aria-current", "page");
  });

  it("skips disabled controls and falls back to the drawer when none remain", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getAllByRole, getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    const dialog = getByRole("dialog", { name: "Main navigation" });
    const close = getByRole("button", { name: "Close navigation" });
    close.setAttribute("disabled", "");
    trigger.focus();
    const skipDisabled = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(skipDisabled);
    expect(skipDisabled.defaultPrevented).toBe(true);
    expect(getAllByRole("button", { name: moments.sample_frame_leave }).some((control) => control === document.activeElement)).toBe(true);

    dialog.querySelectorAll("button, input, select, textarea").forEach((element) => element.setAttribute("disabled", ""));
    trigger.focus();
    const empty = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(empty);
    expect(empty.defaultPrevented).toBe(true);
    expect(dialog).toHaveFocus();
  });

  it("closes narrow navigation for the current destination and focuses the page title", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    await user.click(getByRole("button", { name: "OverviewYour picture" }));

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes an open Viva drawer before opening narrow navigation", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: /ask viva/i }));
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: "Open navigation" }));

    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("keeps desktop navigation persistent and cleans up an open mobile modal at the breakpoint", async () => {
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "auto";
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("hidden");
    responsive.resize(761);

    await waitFor(() => expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("role"));
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("aria-hidden");
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("inert");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(getByRole("button", { name: "OverviewYour picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Close navigation" })).not.toHaveFocus();
    expect(trigger).not.toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.style.overflow).toBe("auto");
    document.documentElement.style.overflow = "";
  });

  it("focuses the page title after desktop resize when no current navigation item is available", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    getByRole("button", { name: "OverviewYour picture" }).removeAttribute("aria-current");
    responsive.resize(761);

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Close navigation" })).not.toHaveFocus();
    expect(getByRole("button", { name: "Open navigation" })).not.toHaveFocus();
  });

  it("restores exact root and body overflow values when an open narrow drawer unmounts", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "visible";
    const user = userEvent.setup();
    const { getByRole, unmount } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.documentElement.style.overflow).toBe("clip");
    expect(document.body.style.overflow).toBe("visible");
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    installResponsiveMatchMedia(1440);
  });
});
