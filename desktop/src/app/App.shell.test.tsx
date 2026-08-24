import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("shell", () => {
  it("opens on the financial picture", async () => {
    const { getByRole, getByText, getAllByText } = await openSample();
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("USD 17,486.45")).toBeInTheDocument();
    expect(getAllByText("Sample vault")[0]).toBeInTheDocument();
    expect(getByText(moments.sample_frame)).toBeInTheDocument();
    const disclosure = getByRole("complementary", { name: "Vault source" });
    const hero = document.querySelector(".hero-grid");
    expect(disclosure.compareDocumentPosition(hero as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lets the overview spotlight select an account and open its detail", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = await openSample();

    await user.click(getAllByText("Rainy Day Savings").find((node) => node.closest("button")?.classList.contains("account-card-button"))!.closest("button")!);

    expect(getByText("Selected account")).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
    expect(getByText("Rainy Day Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getAllByText("This figure is over Rainy Day Savings alone. It is good as of 2026-06-01.")).toHaveLength(2);
  });

  it("pairs every overview account amount with a distinct stable-id source control", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText, getAllByText } = await openSample();
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".account-card"));

    expect(cards).toHaveLength(8);
    expect(getAllByText("USD 3,081.45")).toHaveLength(1);
    cards.forEach((card) => {
      const amount = card.querySelector(".account-amount");
      const selection = card.querySelector(".account-card-button");
      // The amount a card shows and the control that selects it are separate
      // elements, so pressing the row never reads as pressing the figure. The
      // proof link that used to sit beside them was a field only the fixture
      // filled; the vault read supplies none, and this no longer looks for one.
      expect(amount).not.toBeNull();
      expect(selection).not.toBeNull();
      expect(selection?.contains(amount)).toBe(false);
    });

    const savingsCard = cards.find((card) => card.textContent?.includes("Rainy Day Savings")) as HTMLElement;
    await user.click(savingsCard.querySelector(".account-card-button") as HTMLElement);
    expect(getByText("Rainy Day Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();

    // The proof link beside a figure is the read's own citation, and it is a
    // separate control from the one that selects the row: pressing the row
    // never reads as pressing the figure.
    const proof = savingsCard.querySelector(".proof-link");
    expect(proof).not.toBeNull();
    expect(savingsCard.querySelector(".account-card-button")?.contains(proof as Node)).toBe(false);
  });

  it("keeps the live incomplete-coverage qualification in spotlight cards and account rows with details off", async () => {
    const user = userEvent.setup();
    const overview = sampleVault.reads.overview.result.data as { accounts: Array<{ account: string; balance: { coverage: string; proof_presentation: { qualifications: string[] } } }> };
    const live = overview.accounts.find((account) => account.account === "acct:rainy-day-savings")!;
    const qualification = live.balance.coverage;
    expect(live.balance.proof_presentation.qualifications).toContain(qualification);

    const view = await openSample();
    const spotlight = [...view.container.querySelectorAll<HTMLElement>(".account-card")].find((card) => card.textContent?.includes("Rainy Day Savings"))!;
    expect(spotlight.textContent).toContain(qualification);

    await user.click(view.getByRole("button", { name: "AccountsWhere money sits" }));
    const row = [...view.container.querySelectorAll<HTMLElement>(".detail-row")].find((entry) => entry.textContent?.includes("Rainy Day Savings"))!;
    expect(row.textContent).toContain(qualification);
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
  });

  it("runs an advertised Activity correction through the installed shell and focuses the reread row", async () => {
    const user = userEvent.setup();
    const activity = {
      state: "ready", sentence: moments.activity_scope, beyond: { count: 0 },
      vocabularies: { categories: { items: [{ id: "food", label: "Food" }, { id: "housing", label: "Housing" }], complete: true, limit: 40 }, tags: { items: [{ id: "trip", label: "Trip" }], complete: true, limit: 40, max_selected: 40, max_label_length: 80 } },
      items: [{ id: "movement:key", date: "2026-06-01", description: "Corner shop", account: "acct:one", direction: "out", exact_value: "12.00", currency: "USD", display: "USD 12.00", nature: "spending", sentence: "", decided_by: "default", provisional: false, linked: false, category: { id: "food", label: "Food" }, tags: [{ id: "trip", label: "Trip" }], transfer: { state: "none" }, actions: ["assign_category", "replace_tags"] }],
    };
    const view = await openSample({ activity });
    await user.click(view.getByRole("button", { name: "ActivityWhat moved" }));
    await user.click(view.getByText(/Correct category or tags/));
    await user.selectOptions(view.getByRole("combobox", { name: /Category for/ }), "housing");
    await user.click(view.getByRole("button", { name: /Save category for/ }));

    await waitFor(() => expect(view.getByText("Correction recorded")).toBeInTheDocument());
    expect(view.getByText("The full picture was read again.")).toBeInTheDocument();
    expect(view.getByText("Corner shop").closest("li")).toHaveFocus();
    // The action receipt never patches financial data. This stub's full read
    // still says Food, so the screen still says Food after a completed reply.
    expect(view.getAllByText("Food").length).toBeGreaterThan(0);
  });

  it("renders the installed v3 parity suggestion and link only from their reviewed transfer fields", async () => {
    const user = userEvent.setup();
    const raw = sampleReads.activity.result.data as { items: Array<{ transfer: { state: string; explanation?: string; relationship?: string; candidates?: Array<{ relationship: string }> } }> };
    const suggested = raw.items.find((row) => row.transfer.state === "suggested")?.transfer;
    const linked = raw.items.find((row) => row.transfer.state === "linked")?.transfer;
    if (!suggested?.explanation || !suggested.candidates?.[0] || !linked?.explanation || !linked.relationship) throw new Error("live v3 parity fixture is missing transfer authority");
    const view = await openSample();
    await user.click(view.getByRole("button", { name: "ActivityWhat moved" }));
    const suggestionSummary = view.getAllByText("Correct category or transfer", { exact: true }).find((summary) => summary.getAttribute("aria-label")?.includes("possible transfer to savings"));
    if (!suggestionSummary) throw new Error("installed suggested row correction is missing");
    await user.click(suggestionSummary);
    expect(view.getByText(suggested.explanation)).toBeInTheDocument();
    expect(view.getByText(suggested.candidates[0].relationship)).toBeInTheDocument();
    expect(view.getByRole("button", { name: /Confirm transfer for/ })).toBeInTheDocument();
    expect(view.getByRole("button", { name: /Reject transfer suggestion for/ })).toBeInTheDocument();
    const linkSummary = view.getAllByText("Correct category or transfer", { exact: true }).find((summary) => summary.getAttribute("aria-label")?.includes("transfer from checking"));
    if (!linkSummary) throw new Error("installed linked row correction is missing");
    await user.click(linkSummary);
    expect(view.getAllByText(linked.explanation).length).toBeGreaterThan(0);
    expect(view.getAllByText(linked.relationship).length).toBeGreaterThan(0);
    expect(view.getAllByRole("button", { name: /Unlink transfer for/ }).some((button) => button.getAttribute("aria-label")?.startsWith("Unlink transfer for 2026-06-18, transfer from checking,"))).toBe(true);
  });

  it("keeps the sample source before facts with one page heading and one current destination", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    const destinations = [
      ["OverviewYour picture", ".hero-grid"],
      ["AccountsWhere money sits", ".feature-panel"],
      ["ActivityWhat moved", ".activity-panel"],
      ["DocumentsWhat supports it", ".documents-surface"],
      ["ReviewWhat needs you", ".review-inspection"],
      ["TrustHow it works", ".trust-panel"],
    ] as const;
    for (const [name, selector] of destinations) {
      await user.click(view.getByRole("button", { name }));
      const source = view.getByRole("complementary", { name: "Vault source" });
      const facts = view.container.querySelector(selector);
      expect(facts).not.toBeNull();
      expect(source.compareDocumentPosition(facts as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(view.container.querySelectorAll("h1")).toHaveLength(1);
      expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    }
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    const { getAllByRole, container, getByRole } = await openSample();
    await user.click(getByRole("button", { name: "Go to documents" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a document" })).toHaveFocus());
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("focuses the static capture explanation when already on Documents", async () => {
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: "Go to documents" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a document" })).toHaveFocus());
  });

  it("does not resurrect capture focus after navigating away and back from another destination", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a document" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect capture focus after navigating away and back from Documents", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a document" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("puts one frame around the sample vault, and leaves it in one action", async () => {
    const user = userEvent.setup();
    const { queryByText, getAllByRole, getByRole, getByText, getAllByText } = await openSample();

    expect(getAllByText("Sample vault")[0]).toBeInTheDocument();
    // One frame, said once, in the pack's own words — not a qualifier repeated
    // beside every figure inside it.
    expect(getAllByText(moments.sample_frame)).toHaveLength(1);
    expect(getByText(moments.sample_frame_detail)).toBeInTheDocument();

    await user.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    expect(getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(queryByText(moments.sample_frame)).not.toBeInTheDocument();
  });

  it.each([
    ["Overview", "OverviewYour picture"],
    ["Accounts", "AccountsWhere money sits"],
    ["Activity", "ActivityWhat moved"],
    ["Documents", "DocumentsWhat supports it"],
    ["Review", "ReviewWhat needs you"],
    ["Trust", "TrustHow it works"],
  ] as const)("leaves the sample vault from %s and takes the whole session with it", async (destination, navigationName) => {
    // Leaving is one action, and nothing from the vault survives it: not the
    // screen a person was on, not what they had selected there, not an open
    // overlay, and not the vault itself. The session is rebuilt from nothing
    // rather than cleared field by field, so a field added later cannot be the
    // one that survives.
    const user = userEvent.setup();
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    const view = await openSample();
    await user.click(view.getByRole("button", { name: navigationName }));

    if (destination === "Overview") fireEvent.click(view.container.querySelectorAll(".account-card-button")[1]);
    if (destination === "Accounts") fireEvent.click(view.container.querySelectorAll(".detail-row-button")[1]);
    if (destination === "Documents") fireEvent.click(view.container.querySelectorAll(".document-list .detail-row-button")[1]);
    if (destination === "Review") fireEvent.click(view.container.querySelectorAll(".review-question-row")[1]);

    await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);

    expect(view.queryByText(moments.sample_frame)).not.toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.container.querySelectorAll("h1")).toHaveLength(1);
    expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    expect(view.getByRole("button", { name: "OverviewYour picture" })).toHaveAttribute("aria-current", "page");
    expect(view.queryByText("USD 17,486.45")).not.toBeInTheDocument();
    expect(view.getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(view.queryAllByRole("dialog")).toHaveLength(0);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(view.getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
  });

  it.each(["Evidence", "Viva"] as const)("does not resurrect explicitly closed %s after a sample reset", async (overlay) => {
    const user = userEvent.setup();
    const view = await openSample();
    if (overlay === "Evidence") {
      await user.click(view.getByRole("button", { description: "View the evidence for net worth in USD." }));
      expect(view.getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close evidence" }));
    } else {
      await user.click(view.getByRole("button", { name: "Ask Viva" }));
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close Viva conversation" }));
    }
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it.each(["Evidence", "Viva"] as const)("cancels captured stale %s restoration before a reset transition", async (overlay) => {
    const frames = installCapturedAnimationFrames();
    try {
      const view = await openSample();
      if (overlay === "Evidence") {
        const opener = view.getByRole("button", { description: "View the evidence for net worth in USD." });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      } else {
        const opener = view.getByRole("button", { name: "Ask Viva" });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      }
      const reset = view.getAllByRole("button", { name: moments.sample_frame_leave })[0];
      reset.focus();
      fireEvent.click(reset);
      frames.runCaptured();
      expect(view.queryByRole("dialog")).not.toBeInTheDocument();
      expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
      expect(view.queryByText(moments.sample_frame)).not.toBeInTheDocument();
      expect(view.getByRole("button", { name: "Ask Viva" })).not.toHaveFocus();
      expect(document.documentElement.style.overflow).toBe("");
      expect(document.body.style.overflow).toBe("");
    } finally {
      frames.restore();
    }
  });

  it("shows the supplied review total without adding a navigation count", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    expect(getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(getByText("Open-question total from this read")).toBeInTheDocument();
    const reviewTotal = (sampleReads.review.result.data as { total: number }).total;
    expect(getByText(String(reviewTotal), { selector: ".review-summary > strong" })).toBeInTheDocument();
    expect(container.querySelector(".nav-count")).toBeNull();
  });
});
