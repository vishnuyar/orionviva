import { act, fireEvent, render, waitFor, createRef, userEvent,
  afterEach, beforeEach, describe, expect, it, vi, App,
  ConversationDialogShell, moments, sampleVault, SAVED_NO_READER,
  queryByRoleIn, ThrowingConversationBody, installResponsiveMatchMedia,
  installCapturedAnimationFrames, activityPayload, trustPayload, sampleReads,
  sampleFrame, installSampleBridge, openSample } from "./App.testSupport";
import { restoreAccountIndexFocus } from "./App";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("shell", () => {
  it("returns focus to the Accounts heading when the originating account disappeared", () => {
    const host = document.createElement("section");
    host.innerHTML = '<h2 id="accounts-index-heading" tabindex="-1">Accounts in this read</h2>';
    document.body.append(host);
    restoreAccountIndexFocus("account-that-is-no-longer-present", null);
    expect(host.querySelector("h2")).toHaveFocus();
    host.remove();
  });
  it("opens on the financial picture", async () => {
    const { getByRole, getByText, getAllByText } = await openSample();
    const heading = getByRole("heading", { name: "Your financial picture" });
    expect(heading).toBeInTheDocument();
    await waitFor(() => expect(heading).toHaveFocus());
    expect(getByText("USD 17,486.45")).toBeInTheDocument();
    expect(getAllByText("Sample vault")[0]).toBeInTheDocument();
    expect(getByText(moments.sample_frame)).toBeInTheDocument();
    const disclosure = getByRole("complementary", { name: "Vault source" });
    const hero = document.querySelector(".hero-grid");
    expect(disclosure.compareDocumentPosition(hero as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("opens an exact Overview account in its ledger and returns focus to the originating card", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = await openSample();

    const origin = getAllByText("Rainy Day Savings").find((node) => node.closest("button")?.classList.contains("account-card-button"))!.closest("button")!;
    origin.focus();
    await user.keyboard("{Enter}");

    expect(getByRole("heading", { name: "Rainy Day Savings" })).toBeInTheDocument();
    expect(getByRole("button", { name: "Accounts" })).toHaveAttribute("aria-current", "page");
    expect(getByRole("button", { name: "Back to Overview" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: "Back to Overview" }));
    await waitFor(() => expect(document.querySelector('[data-overview-account-id="acct:rainy-day-savings"]')).toHaveFocus());
    expect(getByText("Rainy Day Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
  });

  it("pairs every overview account amount with a distinct stable-id source control", async () => {
    const { container, getAllByText } = await openSample();
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".account-card"));

    expect(cards).toHaveLength(8);
    expect(getAllByText("USD 3,081.45")).toHaveLength(1);
    cards.forEach((card) => {
      const amount = card.querySelector(".account-amount");
      const selection = card.querySelector(".account-card-button");
      // The displayed amount is outside the account-selection control.
      expect(amount).not.toBeNull();
      expect(selection).not.toBeNull();
      expect(selection?.contains(amount)).toBe(false);
    });

    const savingsCard = cards.find((card) => card.textContent?.includes("Rainy Day Savings")) as HTMLElement;
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

    await user.click(view.getByRole("button", { name: "Accounts" }));
    const row = [...view.container.querySelectorAll<HTMLElement>(".detail-row")].find((entry) => entry.textContent?.includes("Rainy Day Savings"))!;
    expect(row.textContent).toContain(qualification);
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "Statements" }));
    expect(getByRole("heading", { name: "Statements & documents" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Add a statement" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
  });

  it("runs an advertised Activity correction through the installed shell and focuses the reread row", async () => {
    const user = userEvent.setup();
    const activity = {
      state: "ready", sentence: moments.activity_scope, beyond: { count: 0 },
      vocabularies: { categories: { items: [{ id: "food", label: "Food" }, { id: "housing", label: "Housing" }], complete: true, limit: 40 }, tags: { items: [{ id: "trip", label: "Trip" }], complete: true, limit: 40, max_selected: 40, max_label_length: 80 } },
      items: [{ id: "movement:key", date: "2026-06-01", description: "Corner shop", account: "acct:one", account_id: "acct:one", account_name: "Everyday account", direction: "out", exact_value: "12.00", currency: "USD", display: "USD 12.00", nature: "spending", treatment: { kind: "spending", name: "" }, sentence: "", decided_by: "default", provisional: false, linked: false, category: { id: "food", label: "Food" }, subcategory: { id: null, label: "" }, classification: { grade: "verified", provenance: "human" }, tags: [{ id: "trip", label: "Trip" }], evidence_links: [], transfer: { state: "none" }, actions: ["assign_category", "assign_meaning", "replace_tags"] }],
    };
    const view = await openSample({ activity });
    await user.click(view.getByRole("button", { name: "Transactions" }));
    await user.click(view.getByText(/Correct category, treatment, or tags/));
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
    await user.click(view.getByRole("button", { name: "Transactions" }));
    const suggestionSummary = view.getAllByText("Correct category, treatment, tags, or transfer", { exact: true }).find((summary) => summary.getAttribute("aria-label")?.includes("possible transfer to savings"));
    if (!suggestionSummary) throw new Error("installed suggested row correction is missing");
    await user.click(suggestionSummary);
    expect(view.getByText(suggested.explanation)).toBeInTheDocument();
    expect(view.getByText(suggested.candidates[0].relationship)).toBeInTheDocument();
    expect(view.getByRole("button", { name: /Confirm transfer for/ })).toBeInTheDocument();
    expect(view.getByRole("button", { name: /Reject transfer suggestion for/ })).toBeInTheDocument();
    const linkSummary = view.getAllByText("Correct category, tags, or transfer", { exact: true }).find((summary) => summary.getAttribute("aria-label")?.includes("transfer from checking"));
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
      ["Overview", ".hero-grid"],
      ["Accounts", ".feature-panel"],
      ["Transactions", ".activity-panel"],
      ["Statements", ".documents-surface"],
      ["Trust & settings", ".trust-panel"],
    ] as const;
    for (const [name, selector] of destinations) {
      await user.click(view.getByRole("button", { name }));
      const source = view.getByRole("complementary", { name: "Vault source" });
      const facts = view.container.querySelector(selector);
      expect(facts).not.toBeNull();
      expect(source.compareDocumentPosition(facts as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(view.container.querySelectorAll("h1")).toHaveLength(1);
      expect(view.container.querySelectorAll('.sidebar [aria-current="page"]')).toHaveLength(1);
    }
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    const { getAllByRole, container, getByRole } = await openSample();
    await user.click(getByRole("button", { name: "Add statement" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a statement" })).toHaveFocus());
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("focuses the static capture explanation when already on Documents", async () => {
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    await user.click(getByRole("button", { name: "Statements" }));
    await user.click(getByRole("button", { name: "Add statement" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a statement" })).toHaveFocus());
  });

  it("does not resurrect capture focus after navigating away and back from another destination", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Add statement" }));
      fireEvent.click(getByRole("button", { name: "Accounts" }));
      fireEvent.click(getByRole("button", { name: "Statements" }));
      getByRole("heading", { name: "Statements & documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a statement" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect capture focus after navigating away and back from Documents", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Statements" }));
      fireEvent.click(getByRole("button", { name: "Add statement" }));
      fireEvent.click(getByRole("button", { name: "Accounts" }));
      fireEvent.click(getByRole("button", { name: "Statements" }));
      getByRole("heading", { name: "Statements & documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a statement" })).not.toHaveFocus();
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
    ["Overview", "Overview"],
    ["Accounts", "Accounts"],
    ["Transactions", "Transactions"],
    ["Statements", "Statements"],
    ["Trust & settings", "Trust & settings"],
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
    if (destination === "Statements") fireEvent.click(view.container.querySelectorAll(".document-list .detail-row-button")[1]);

    await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);

    expect(view.queryByText(moments.sample_frame)).not.toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.container.querySelectorAll("h1")).toHaveLength(1);
    expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    expect(view.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
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
      expect(view.getByRole("dialog", { name: "Ask Viva" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close Ask Viva" }));
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
        fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" }));
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

  it("keeps Ask Viva separate and shows the authored total on Review navigation", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    await user.click(getByRole("button", { name: "Ask Viva" }));
    expect(queryByRole("heading", { name: "Questions for you" })).not.toBeInTheDocument();
    await user.click(getByRole("button", { name: "Close Ask Viva" }));
    const reviewTotal = (sampleReads.review.result.data as { actionable_count: number }).actionable_count;
    expect(getByRole("button", { name: new RegExp(`Review, ${reviewTotal} actionable items`, "i") })).toBeInTheDocument();
  });
});
