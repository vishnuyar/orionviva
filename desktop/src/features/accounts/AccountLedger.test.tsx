import { createRef } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AccountLedgerData, AccountLedgerMovement, ActivityData, ConversationData, FeatureResult, MovementView, ReviewTransactionTarget } from "../../surface/types";
import { AccountLedger, type LedgerCorrectionControls } from "./AccountLedger";
import { activity, ledger } from "./accountLedgerData.testSupport";

const ready = <T,>(data: T): FeatureResult<T> => ({ state: "ready", data });
const conversation: ConversationData = { turns: [], questions: { queue: [{ id: "question-one", label: "Is this a transfer?", detail: "The vault needs your decision.", status: "open", action: "answer", type: "classification", evidence: "", state: "needs_input", outcome: null, disposition: "answer", refs: { movement: ledger.groups[0].movements[0].id } }], count: 1, meta: { total: 1, tail: null, pending: null, invite: "", answeredByDocument: "" } } };
const completed = { result: { state: "settled" as const, outcome: { kind: "completed" as const, message: "Recorded exactly.", reason: "" } }, refresh: "refreshed" as const };
function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason?: unknown) => void = () => undefined;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function accountCopy(id: string, name: string): AccountLedgerData {
  return { ...ledger, scope: { kind: "account", accountId: id }, account: { ...ledger.account, id, name }, groups: ledger.groups.map((group) => ({ ...group, movements: group.movements.map((row) => ({ ...row, account: id, accountId: id, accountName: name })) })) };
}
function controls(overrides: Partial<LedgerCorrectionControls> = {}): LedgerCorrectionControls {
  return { state: { state: "idle" }, onAssignClassification: vi.fn(async () => completed), onAddTags: vi.fn(async () => completed), onRemoveTags: vi.fn(async () => completed), ...overrides };
}
function props(overrides: Record<string, unknown> = {}) {
  return { accountId: ledger.account.id, read: vi.fn(async () => ready(ledger)), activityResult: ready(activity), conversationResult: ready(conversation), correction: controls(), onBack: vi.fn(), onOpenEvidence: vi.fn(), onOpenQuestion: vi.fn(), pageTitleRef: createRef<HTMLElement>(), ...overrides };
}
function reviewTarget(row: AccountLedgerMovement, overrides: Partial<ReviewTransactionTarget> = {}): ReviewTransactionTarget {
  return { kind: "transaction", questionId: "target-question", accountId: row.accountId, requestedMovementId: row.id, canonicalMovementId: row.deduplication.canonicalMovementId, memberMovementIds: row.deduplication.memberMovementIds, ...overrides };
}
function targetConversation(target: ReviewTransactionTarget, questionId = target.questionId): ConversationData {
  return { ...conversation, questions: { ...conversation.questions, queue: [{ ...conversation.questions.queue[0], id: questionId, refs: { movement: target.requestedMovementId, movements: [...target.memberMovementIds], account: target.accountId } }] } };
}

afterEach(() => vi.unstubAllGlobals());

describe("account transaction ledger", () => {
  it("renders backend groups and disclosures, filters text, and selects exactly visible loaded rows", async () => {
    const user = userEvent.setup();
    const view = render(<AccountLedger {...props()} />);
    expect(screen.getByText("Reading account ledger")).toBeInTheDocument();
    await screen.findByRole("heading", { name: ledger.account.name });
    expect(screen.getByRole("heading", { name: ledger.groups[0].label })).toBeInTheDocument();
    expect(screen.getByText("Running balance is omitted because it is not authoritatively available.")).toBeInTheDocument();
    expect(screen.getByLabelText("Viva needs an answer")).toBeInTheDocument();
    expect(screen.getByLabelText("Possible transfer needs a decision")).toBeInTheDocument();
    expect(screen.queryByLabelText("Classification needs review")).not.toBeInTheDocument();
    const query = screen.getByRole("searchbox", { name: "Search" });
    await user.type(query, ledger.groups[0].movements[0].description);
    expect(screen.getByText(/1 visible of 3 loaded transactions/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Select visible loaded transactions only"));
    expect(view.container.querySelectorAll('.account-ledger-row input[type="checkbox"]:checked')).toHaveLength(1);
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText(/3 visible of 3 loaded transactions/)).toBeInTheDocument();
  });

  it("keeps long authored descriptions, tags, categories, and amounts in the responsive row structure without truncating them", async () => {
    const seed = ledger.groups[0].movements[1];
    const description = "A deliberately long merchant description that must wrap instead of extending beyond the available ledger content width";
    const amount = "USD 123,456,789,012,345,678.90";
    const tags = [{ id: "long-tag", label: "A long authored travel and household tag that remains readable" }];
    const row = { ...seed, description, display: amount, category: { ...seed.category, label: "A very long authored category label" }, subcategory: { ...seed.subcategory, label: "A very long authored subcategory label" }, tags };
    const longLedger: AccountLedgerData = { ...ledger, groups: [{ month: "2026-04", label: "April 2026", movements: [row] }], page: { limit: 50, returned: 1, remaining: 0, nextCursor: null } };
    render(<AccountLedger {...props({ read: vi.fn(async () => ready(longLedger)), conversationResult: ready({ ...conversation, questions: { ...conversation.questions, queue: [], count: 0 } }) })} />);
    const descriptionNode = await screen.findByText(description);
    const descriptionCell = descriptionNode.closest(".account-ledger-description");
    expect(descriptionCell).not.toBeNull();
    expect(screen.getByText(amount).closest(".account-ledger-amount")).not.toBeNull();
    expect(within(descriptionCell as HTMLElement).getByText(/A very long authored category label/)).toHaveTextContent(tags[0].label);
    expect(screen.getByRole("button", { name: new RegExp(description, "i") })).not.toHaveAttribute("title");
  });

  it("removes hidden selections and submits only the exact visible canonical IDs", async () => {
    const user = userEvent.setup();
    const assign = vi.fn(async () => completed);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Possible transfer to savings" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Corner market");
    await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument());
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Category for 1 selected transaction" }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Subcategory for 1 selected transaction" }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(["movement:b"], "dining", "restaurant"));
  });

  it("opens a focus-managed drawer with question and source context, then restores focus on Escape", async () => {
    const user = userEvent.setup();
    const onQuestion = vi.fn(); const onEvidence = vi.fn();
    render(<AccountLedger {...props({ onOpenQuestion: onQuestion, onOpenEvidence: onEvidence })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    const row = screen.getByRole("button", { name: new RegExp(ledger.groups[0].movements[0].description, "i") });
    await user.click(row);
    const drawer = screen.getByRole("dialog", { name: /possible transfer to savings/i });
    expect(within(drawer).getByRole("heading", { name: "Required decision" })).toBeInTheDocument();
    const source = within(drawer).getAllByRole("button").find((button) => button.classList.contains("proof-link"));
    if (source) await user.click(source);
    if (ledger.groups[0].movements[0].evidenceLinks.length) expect(onEvidence).toHaveBeenCalledWith(ledger.groups[0].movements[0].evidenceLinks[0]);
    await user.click(row);
    await user.click(within(screen.getByRole("dialog", { name: /possible transfer to savings/i })).getByRole("button", { name: "Answer this question" }));
    expect(onQuestion).toHaveBeenCalledWith("question-one", ledger.groups[0].movements[0].id);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    row.focus();
    await user.click(row);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("sends the exact checked batch and waits for the authoritative ledger reread before clearing selection", async () => {
    const user = userEvent.setup();
    let release: (() => void) | undefined;
    const reread = new Promise<FeatureResult<AccountLedgerData>>((resolve) => { release = () => resolve(ready(ledger)); });
    const read = vi.fn().mockResolvedValueOnce(ready(ledger)).mockReturnValueOnce(reread);
    const assign = vi.fn(async () => completed);
    render(<AccountLedger {...props({ read, correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    const checkboxes = screen.getAllByRole("checkbox", { name: /^Select / }).filter((box) => box.getAttribute("aria-label")?.startsWith("Select "));
    await user.click(checkboxes[0]); await user.click(checkboxes[1]);
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Category for 2 selected transactions" }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Subcategory for 2 selected transactions" }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    expect(assign).toHaveBeenCalledWith([ledger.groups[0].movements[0].id, ledger.groups[0].movements[1].id], "dining", "restaurant");
    expect(screen.getByText("Saving changes")).toBeInTheDocument();
    expect(checkboxes[0]).toBeChecked();
    release?.();
    await waitFor(() => expect(screen.getByText("Correction recorded")).toBeInTheDocument());
    expect(screen.queryByText("2 selected")).not.toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("does not clear an expanded live selection when an earlier filtered batch completes", async () => {
    const user = userEvent.setup();
    const action = deferred<typeof completed>();
    const assign = vi.fn(() => action.promise);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Corner");
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    let batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    expect(assign).toHaveBeenCalledWith(["movement:b"], "dining", "restaurant");

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Possible transfer to savings" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByText("Another change is being saved")).toBeInTheDocument();
    action.resolve(completed);
    await waitFor(() => expect(screen.queryByText("Another change is being saved")).not.toBeInTheDocument());
    batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    expect(within(batch).getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Corner market" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Possible transfer to savings" })).toBeChecked();
  });

  it("does not clear a contracted live selection when an earlier wider batch completes", async () => {
    const user = userEvent.setup();
    const action = deferred<typeof completed>();
    const assign = vi.fn(() => action.promise);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Possible transfer to savings" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 2/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 2/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Corner");
    await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument());
    expect(screen.getByText("Another change is being saved")).toBeInTheDocument();

    action.resolve(completed);
    await waitFor(() => expect(screen.queryByText("Another change is being saved")).not.toBeInTheDocument());
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Corner market" })).toBeChecked();
  });

  it("retains selection and old ledger when a correction is refused", async () => {
    const user = userEvent.setup();
    const refused = { result: { state: "settled" as const, outcome: { kind: "refused" as const, message: "That pair was refused.", reason: "invalid_pair" } }, refresh: "refreshed" as const };
    const assign = vi.fn(async () => refused);
    const read = vi.fn(async () => ready(ledger));
    render(<AccountLedger {...props({ read, correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getAllByRole("checkbox", { name: /^Select / }).find((box) => box.getAttribute("aria-label")?.startsWith("Select "))!);
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Category for 1 selected transaction" }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: "Subcategory for 1 selected transaction" }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    await screen.findByText("Correction refused");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("merges a valid cross-month page and focuses the first newly loaded row", async () => {
    const user = userEvent.setup();
    const first: AccountLedgerData = { ...ledger, groups: [ledger.groups[0]], page: { limit: 2, returned: 2, remaining: 1, nextCursor: "next-page" } };
    const second: AccountLedgerData = { ...ledger, groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 0, nextCursor: null } };
    const read = vi.fn().mockResolvedValueOnce(ready(first)).mockResolvedValueOnce(ready(second));
    render(<AccountLedger {...props({ read })} />);
    await screen.findByText("Corner market");
    await user.click(screen.getByRole("button", { name: "Load more (1 remaining)" }));
    await screen.findByText("Neighborhood cafe");
    await waitFor(() => expect(document.getElementById("ledger-row-movement:a")).toHaveFocus());
    expect(read).toHaveBeenLastCalledWith(ledger.account.id, "next-page", 2);
  });

  it("locates an exact requested canonical row across bounded pages and opens only that drawer", async () => {
    const first: AccountLedgerData = { ...ledger, groups: [ledger.groups[0]], page: { limit: 2, returned: 2, remaining: 1, nextCursor: "next-page" } };
    const second: AccountLedgerData = { ...ledger, groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 0, nextCursor: null } };
    const read = vi.fn().mockResolvedValueOnce(ready(first)).mockResolvedValueOnce(ready(second));
    const target = reviewTarget(ledger.groups[1].movements[0]);
    render(<AccountLedger {...props({ read, requestedReviewTarget: target, conversationResult: ready(targetConversation(target)), backLabel: "Back to Review" })} />);
    expect(await screen.findByRole("dialog", { name: "Neighborhood cafe" })).toBeInTheDocument();
    expect(read).toHaveBeenNthCalledWith(2, ledger.account.id, "next-page", 2);
    expect(screen.getByRole("button", { name: "Back to Review" })).toBeInTheDocument();
  });

  it("refuses a requested movement whose canonical binding does not match", async () => {
    const row = ledger.groups[0].movements[0];
    const target = reviewTarget(row, { canonicalMovementId: "another-canonical", memberMovementIds: ["another-canonical", row.id] });
    render(<AccountLedger {...props({ requestedReviewTarget: target, conversationResult: ready(targetConversation(target)) })} />);
    expect(await screen.findByText("Referenced transaction is not in this account ledger")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([
    ["ghost member", (target: ReviewTransactionTarget) => ({ ...target, memberMovementIds: [...target.memberMovementIds, "movement:ghost"] })],
    ["missing member", (target: ReviewTransactionTarget) => ({ ...target, memberMovementIds: [] })],
    ["wrong account", (target: ReviewTransactionTarget) => ({ ...target, accountId: "acct:other" })],
  ])("falls back to the exact conversation for a %s target", async (_label, change) => {
    const row = ledger.groups[0].movements[0];
    const target = change(reviewTarget(row));
    render(<AccountLedger {...props({ accountId: target.accountId, requestedReviewTarget: target, conversationResult: ready(targetConversation(target)) })} />);
    expect(await screen.findByRole("button", { name: "Answer in conversation" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("rejects reordered and extra collapsed members", async () => {
    const row = ledger.groups[0].movements[0];
    const collapsedRow = { ...row, deduplication: { state: "exact_duplicate" as const, canonicalMovementId: row.id, memberMovementIds: [row.id, "movement:z"] } };
    const collapsed = { ...ledger, groups: [{ ...ledger.groups[0], movements: [collapsedRow, ledger.groups[0].movements[1]] }, ledger.groups[1]] };
    for (const members of [["movement:z", row.id], [row.id, "movement:z", "movement:extra"]]) {
      const target = reviewTarget(collapsedRow, { memberMovementIds: members });
      const view = render(<AccountLedger {...props({ read: vi.fn(async () => ready(collapsed)), requestedReviewTarget: target, conversationResult: ready(targetConversation(target)) })} />);
      expect(await screen.findByRole("button", { name: "Answer in conversation" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("does not substitute another question that shares the requested movement", async () => {
    const row = ledger.groups[0].movements[0];
    const target = reviewTarget(row);
    render(<AccountLedger {...props({ requestedReviewTarget: target, conversationResult: ready(targetConversation(target, "another-question")) })} />);
    expect(await screen.findByRole("button", { name: "Answer in conversation" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the exact requested question marker after handing off from the drawer until the authoritative question disappears", async () => {
    const user = userEvent.setup();
    const row = ledger.groups[0].movements[0];
    const target = reviewTarget(row);
    const onQuestion = vi.fn();
    const exactConversation = targetConversation(target);
    const view = render(<AccountLedger {...props({ requestedReviewTarget: target, conversationResult: ready(exactConversation), onOpenQuestion: onQuestion })} />);
    const drawer = await screen.findByRole("dialog", { name: row.description });
    expect(screen.getAllByLabelText("Viva needs an answer")).toHaveLength(1);
    await user.click(within(drawer).getByRole("button", { name: "Answer this question" }));
    expect(onQuestion).toHaveBeenCalledWith(target.questionId, row.id);
    expect(screen.queryByRole("dialog", { name: row.description })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("Viva needs an answer")).toHaveLength(1);

    view.rerender(<AccountLedger {...props({ requestedReviewTarget: target, conversationResult: ready(exactConversation), onOpenQuestion: onQuestion })} />);
    expect(await screen.findAllByLabelText("Viva needs an answer")).toHaveLength(1);
    view.rerender(<AccountLedger {...props({ requestedReviewTarget: target, conversationResult: ready({ ...exactConversation, questions: { ...exactConversation.questions, queue: [], count: 0 } }), onOpenQuestion: onQuestion })} />);
    await waitFor(() => expect(screen.queryByLabelText("Viva needs an answer")).not.toBeInTheDocument());
  });

  it("shows only the authored transfer counterpart and offers Transactions only when its exact Activity row authors an action", async () => {
    const user = userEvent.setup();
    const row = ledger.groups[0].movements[0];
    const authored: MovementView = {
      id: row.id, date: row.date, description: row.description, account: row.account, accountId: row.accountId, accountName: row.accountName,
      direction: row.direction, exactValue: row.exactValue, currency: row.currency, display: row.display, nature: row.nature,
      treatment: row.treatment, loanRepaymentChoices: row.loanRepaymentChoices, sentence: row.sentence, decidedBy: row.decidedBy,
      provisional: row.provisional, linked: row.linked, category: row.category, subcategory: row.subcategory, classification: row.classification,
      classificationValid: row.classificationValid, tags: row.tags, tagsValid: row.tagsValid, evidenceLinks: row.evidenceLinks,
      evidenceLinksValid: row.evidenceLinksValid, transfer: row.transfer, actions: ["confirm_transfer", "reject_transfer"],
    };
    const onReviewTransfer = vi.fn();
    const activityWithAction: ActivityData = { ...activity, movements: [authored] };
    const view = render(<AccountLedger {...props({ activityResult: ready(activityWithAction), onReviewTransfer })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: new RegExp(row.description, "i") }));
    let drawer = screen.getByRole("dialog", { name: row.description });
    const transfer = within(drawer).getByRole("region", { name: "Possible transfer" });
    expect(transfer).toHaveTextContent("Rainy Day Savings");
    expect(transfer).toHaveTextContent("$12.00");
    expect(transfer).toHaveTextContent("The vault found the corresponding movement in Rainy Day Savings.");
    await user.click(within(transfer).getByRole("button", { name: "Review transfer controls in Transactions" }));
    expect(onReviewTransfer).toHaveBeenCalledWith(row.id);

    view.rerender(<AccountLedger {...props({ activityResult: ready({ ...activity, movements: [{ ...authored, actions: [] }] }), onReviewTransfer })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: new RegExp(row.description, "i") }));
    drawer = screen.getByRole("dialog", { name: row.description });
    expect(within(drawer).getByRole("region", { name: "Possible transfer" })).toHaveTextContent("Rainy Day Savings");
    expect(within(drawer).queryByRole("button", { name: "Review transfer controls in Transactions" })).not.toBeInTheDocument();
  });

  it.each([
    [4, true],
    [5, false],
  ])("searches at most four total pages when the target is on page %i", async (pageNumber, opens) => {
    const seed = ledger.groups[0].movements[0];
    const rows = Array.from({ length: pageNumber }, (_unused, index) => {
      const id = `movement:page-${index + 1}`;
      return { ...seed, id, date: `2026-04-${String(20 - index).padStart(2, "0")}`, description: `Page ${index + 1}`, deduplication: { state: "single" as const, canonicalMovementId: id, memberMovementIds: [id] } };
    });
    const pages = rows.map((row, index): AccountLedgerData => ({ ...ledger,
      groups: [{ month: "2026-04", label: "April 2026", movements: [row] }],
      page: { limit: 1, returned: 1, remaining: rows.length - index - 1, nextCursor: index + 1 < rows.length ? `cursor-${index + 2}` : null },
    }));
    const target = reviewTarget(rows[pageNumber - 1]);
    const read = vi.fn();
    pages.forEach((page) => read.mockResolvedValueOnce(ready(page)));
    render(<AccountLedger {...props({ read, requestedReviewTarget: target, conversationResult: ready(targetConversation(target)) })} />);
    if (opens) expect(await screen.findByRole("dialog", { name: `Page ${pageNumber}` })).toBeInTheDocument();
    else {
      expect(await screen.findByText("Referenced transaction is beyond the bounded search")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Load more (1 remaining)" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
    expect(read).toHaveBeenCalledTimes(4);
  });

  it("keeps loaded rows visible and reports a pagination failure", async () => {
    const user = userEvent.setup();
    const first: AccountLedgerData = { ...ledger, groups: [ledger.groups[0]], page: { limit: 2, returned: 2, remaining: 1, nextCursor: "next-page" } };
    const read = vi.fn().mockResolvedValueOnce(ready(first)).mockResolvedValueOnce({ state: "failed", reason: "read_failed" });
    render(<AccountLedger {...props({ read })} />);
    await screen.findByText("Corner market");
    await user.click(screen.getByRole("button", { name: "Load more (1 remaining)" }));
    expect(await screen.findByText("Ledger continuation could not be verified")).toBeInTheDocument();
    expect(screen.getByText("Corner market")).toBeInTheDocument();
  });

  it.each([
    ["repeat-only page", (first: AccountLedgerData) => ({ ...ledger, groups: [{ ...first.groups[0], movements: [first.groups[0].movements[1]] }], page: { limit: 2, returned: 1, remaining: 0, nextCursor: null } })],
    ["cursor loop", () => ({ ...ledger, groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 0, nextCursor: "next-page" } })],
    ["inconsistent remaining count", () => ({ ...ledger, groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 1, nextCursor: "third-page" } })],
    ["repeated source filename drift", () => ({ ...ledger, sources: ledger.sources.map((source) => ({ ...source, filename: `${source.filename}.changed` })), groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 0, nextCursor: null } })],
  ])("preserves the prior ledger and cursor for a %s", async (_label, page) => {
    const user = userEvent.setup();
    const first: AccountLedgerData = { ...ledger, groups: [ledger.groups[0]], page: { limit: 2, returned: 2, remaining: 1, nextCursor: "next-page" } };
    const read = vi.fn().mockResolvedValueOnce(ready(first)).mockResolvedValueOnce(ready(page(first)));
    render(<AccountLedger {...props({ read })} />);
    await screen.findByText("Corner market");
    await user.click(screen.getByRole("button", { name: "Load more (1 remaining)" }));
    expect(await screen.findByText("Ledger continuation could not be verified")).toBeInTheDocument();
    expect(screen.queryByText("Neighborhood cafe")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load more (1 remaining)" })).toBeInTheDocument();
  });

  it("discloses empty and failed ledger reads without stale transaction rows", async () => {
    const empty: AccountLedgerData = { ...ledger, groups: [], page: { limit: 50, returned: 0, remaining: 0, nextCursor: null } };
    const view = render(<AccountLedger {...props({ read: vi.fn(async () => ready(empty)) })} />);
    expect(await screen.findByText("No transactions in this account ledger")).toBeInTheDocument();
    view.rerender(<AccountLedger {...props({ accountId: "another", loadingAccountName: "Another account", read: vi.fn(async () => ({ state: "failed", reason: "read_failed" })) })} />);
    expect(await screen.findByText("Account ledger could not be read")).toBeInTheDocument();
    expect(screen.queryByText("Corner market")).not.toBeInTheDocument();
  });

  it("sends exact single-row compound classification and additive tag payloads from the drawer", async () => {
    const user = userEvent.setup();
    const assign = vi.fn(async () => completed);
    const add = vi.fn(async () => completed);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign, onAddTags: add }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    const drawer = screen.getByRole("dialog", { name: /Possible transfer to savings/i });
    await user.selectOptions(within(drawer).getByRole("combobox", { name: "Category for 1 selected transaction" }), "groceries");
    await user.selectOptions(within(drawer).getByRole("combobox", { name: "Subcategory for 1 selected transaction" }), "supermarket");
    await user.click(within(drawer).getByRole("button", { name: "Save category and subcategory" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(["movement:c"], "groceries", "supermarket"));
    await user.click(within(drawer).getByRole("checkbox", { name: "Travel" }));
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith(["movement:c"], ["travel"]));
  });

  it("matches a question to a collapsed member ID exactly and attaches it once", async () => {
    const user = userEvent.setup();
    const canonical = ledger.groups[0].movements[0];
    const collapsed: AccountLedgerData = { ...ledger, groups: [{ ...ledger.groups[0], movements: [{ ...canonical, deduplication: { state: "exact_duplicate", canonicalMovementId: canonical.id, memberMovementIds: [canonical.id, "movement:z"] } }, ledger.groups[0].movements[1]] }, ledger.groups[1]] };
    const memberConversation: ConversationData = { ...conversation, questions: { ...conversation.questions, queue: [{ ...conversation.questions.queue[0], refs: { movement: "movement:z", movements: [canonical.id, "movement:z"] } }] } };
    render(<AccountLedger {...props({ read: vi.fn(async () => ready(collapsed)), conversationResult: ready(memberConversation) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    expect(screen.getAllByLabelText("Viva needs an answer")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    expect(within(screen.getByRole("dialog")).getAllByRole("button", { name: "Answer this question" })).toHaveLength(1);
  });

  it("keeps drawer-local refusal feedback and staged edits, then clears staged tags only after a successful reread", async () => {
    const user = userEvent.setup();
    const refused = { result: { state: "settled" as const, outcome: { kind: "refused" as const, message: "No change was recorded.", reason: "policy" } }, refresh: "refreshed" as const };
    const pendingRefusal = deferred<typeof refused>();
    const add = vi.fn().mockReturnValueOnce(pendingRefusal.promise).mockResolvedValueOnce(completed);
    const read = vi.fn(async () => ready(ledger));
    render(<AccountLedger {...props({ read, correction: controls({ onAddTags: add }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    const drawer = screen.getByRole("dialog");
    const tag = within(drawer).getByRole("checkbox", { name: "Travel" });
    await user.click(tag);
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    expect(within(drawer).getByText("Saving changes")).toBeInTheDocument();
    expect(document.querySelector(".account-ledger-page")).toHaveAttribute("inert");
    pendingRefusal.resolve(refused);
    expect(await within(drawer).findByText("Correction refused")).toBeInTheDocument();
    expect(tag).toBeChecked();
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    expect(await within(drawer).findByText("Correction recorded")).toBeInTheDocument();
    await waitFor(() => expect(tag).not.toBeChecked());
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("keeps drawer context and staged tags when the authoritative ledger reread fails", async () => {
    const user = userEvent.setup();
    const read = vi.fn().mockResolvedValueOnce(ready(ledger)).mockRejectedValueOnce(new Error("offline"));
    render(<AccountLedger {...props({ read })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    const drawer = screen.getByRole("dialog");
    const tag = within(drawer).getByRole("checkbox", { name: "Travel" });
    await user.click(tag);
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    expect(await within(drawer).findByText("Correction recorded; ledger refresh failed")).toBeInTheDocument();
    expect(tag).toBeChecked();
    expect(within(drawer).getByRole("heading", { name: "Possible transfer to savings" })).toBeInTheDocument();
  });

  it.each(["refusal", "failure", "success"] as const)("isolates row B from row A's pending and %s feedback, then permits a row B action", async (outcome) => {
    const user = userEvent.setup();
    const first = deferred<Awaited<ReturnType<LedgerCorrectionControls["onAddTags"]>>>();
    const refused = { result: { state: "settled" as const, outcome: { kind: "refused" as const, message: "A was refused.", reason: "policy" } }, refresh: "refreshed" as const };
    const add = vi.fn().mockImplementationOnce(() => first.promise).mockResolvedValueOnce(completed);
    render(<AccountLedger {...props({ correction: controls({ onAddTags: add }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    let drawer = screen.getByRole("dialog", { name: /Possible transfer to savings/i });
    await user.click(within(drawer).getByRole("checkbox", { name: "Travel" }));
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    expect(within(drawer).getByText("Saving changes")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Close transaction details" }));
    await user.click(screen.getByRole("button", { name: /Corner market/i }));
    drawer = screen.getByRole("dialog", { name: /Corner market/i });
    expect(within(drawer).queryByText("Saving changes")).not.toBeInTheDocument();
    expect(within(drawer).getByText("Another change is being saved")).toBeInTheDocument();
    const rowBTag = within(drawer).getByRole("checkbox", { name: "Travel" });
    await user.click(rowBTag);
    expect(rowBTag).toBeChecked();
    expect(within(drawer).getByRole("button", { name: "Add selected tags" })).toHaveAttribute("aria-disabled", "true");
    if (outcome === "failure") first.reject(new Error("A failed"));
    else first.resolve(outcome === "refusal" ? refused : completed);
    await waitFor(() => expect(within(drawer).queryByText("Another change is being saved")).not.toBeInTheDocument());
    expect(within(drawer).queryByText(/Correction refused|Correction recorded|Your vault did not answer/)).not.toBeInTheDocument();
    expect(rowBTag).toBeChecked();
    expect(within(drawer).getByRole("button", { name: "Add selected tags" })).toHaveAttribute("aria-disabled", "false");
    await user.click(within(drawer).getByRole("button", { name: "Add selected tags" }));
    await waitFor(() => expect(add).toHaveBeenNthCalledWith(2, ["movement:b"], ["travel"]));
    expect(await within(drawer).findByText("Correction recorded")).toBeInTheDocument();
    await waitFor(() => expect(rowBTag).not.toBeChecked());
  });

  it("keeps batch feedback out of an unrelated transaction drawer and restores it after the drawer closes", async () => {
    const user = userEvent.setup();
    const action = deferred<typeof completed>();
    const assign = vi.fn(() => action.promise);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    expect(screen.getByText("Saving changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Possible transfer to savings/i }));
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).queryByText("Saving changes")).not.toBeInTheDocument();
    expect(within(drawer).getByText("Another change is being saved")).toBeInTheDocument();
    action.resolve(completed);
    await waitFor(() => expect(within(drawer).queryByText("Another change is being saved")).not.toBeInTheDocument());
    expect(within(drawer).queryByText("Correction recorded")).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "Close transaction details" }));
    expect(await screen.findByText("Correction recorded")).toBeInTheDocument();
  });

  it("guards a double submit synchronously", async () => {
    const user = userEvent.setup();
    const pending = deferred<typeof completed>();
    const assign = vi.fn(() => pending.promise);
    render(<AccountLedger {...props({ correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    const save = within(batch).getByRole("button", { name: "Save category and subcategory" });
    await user.dblClick(save);
    expect(assign).toHaveBeenCalledTimes(1);
    pending.resolve(completed);
  });

  it("discards a late pagination page after the account changes", async () => {
    const user = userEvent.setup();
    const page = deferred<FeatureResult<AccountLedgerData>>();
    const first: AccountLedgerData = { ...ledger, groups: [ledger.groups[0]], page: { limit: 2, returned: 2, remaining: 1, nextCursor: "next-page" } };
    const other = accountCopy("acct:other", "Other account");
    const read = vi.fn((id: string, cursor?: string) => cursor ? page.promise : Promise.resolve(ready(id === other.account.id ? other : first)));
    const view = render(<AccountLedger {...props({ read })} />);
    await screen.findByText("Corner market");
    await user.click(screen.getByRole("button", { name: "Load more (1 remaining)" }));
    view.rerender(<AccountLedger {...props({ accountId: other.account.id, read })} />);
    await screen.findByRole("heading", { name: "Other account" });
    page.resolve(ready({ ...ledger, groups: [ledger.groups[1]], page: { limit: 2, returned: 1, remaining: 0, nextCursor: null } }));
    await Promise.resolve();
    expect(screen.getByRole("heading", { name: "Other account" })).toBeInTheDocument();
  });

  it("discards a late action and its result after the account changes", async () => {
    const user = userEvent.setup();
    const action = deferred<typeof completed>();
    const assign = vi.fn(() => action.promise);
    const other = accountCopy("acct:other", "Other account");
    const read = vi.fn((id: string) => Promise.resolve(ready(id === other.account.id ? other : ledger)));
    const view = render(<AccountLedger {...props({ read, correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    view.rerender(<AccountLedger {...props({ accountId: other.account.id, read, correction: controls({ onAssignClassification: assign }) })} />);
    await screen.findByRole("heading", { name: "Other account" });
    action.resolve(completed);
    await Promise.resolve();
    expect(screen.queryByText("Correction recorded")).not.toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("does not start a reread for an action that settles after unmount", async () => {
    const user = userEvent.setup();
    const action = deferred<typeof completed>();
    const read = vi.fn(async () => ready(ledger));
    const view = render(<AccountLedger {...props({ read, correction: controls({ onAssignClassification: vi.fn(() => action.promise) }) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    view.unmount();
    action.resolve(completed);
    await Promise.resolve();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("discards a completed action's late authoritative reread after the account changes", async () => {
    const user = userEvent.setup();
    const reread = deferred<FeatureResult<AccountLedgerData>>();
    const other = accountCopy("acct:other", "Other account");
    let suppliedInitial = false;
    const read = vi.fn((id: string) => {
      if (id === other.account.id) return Promise.resolve(ready(other));
      if (!suppliedInitial) { suppliedInitial = true; return Promise.resolve(ready(ledger)); }
      return reread.promise;
    });
    const view = render(<AccountLedger {...props({ read })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    await user.click(screen.getByRole("checkbox", { name: "Select Corner market" }));
    const batch = screen.getByRole("region", { name: "Batch edit selected transactions" });
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Category for 1/ }), "dining");
    await user.selectOptions(within(batch).getByRole("combobox", { name: /Subcategory for 1/ }), "restaurant");
    await user.click(within(batch).getByRole("button", { name: "Save category and subcategory" }));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    view.rerender(<AccountLedger {...props({ accountId: other.account.id, read })} />);
    await screen.findByRole("heading", { name: "Other account" });
    reread.resolve(ready(ledger));
    await Promise.resolve();
    expect(screen.getByRole("heading", { name: "Other account" })).toBeInTheDocument();
    expect(screen.queryByText("Correction recorded")).not.toBeInTheDocument();
  });

  it("renders backend direction and honest balance and coverage states", async () => {
    const rows: AccountLedgerMovement[] = ledger.groups[0].movements.map((row, index) => ({ ...row, directionDisplay: index ? "Credit" : "Direction unavailable" }));
    const truth: AccountLedgerData = { ...ledger, account: { ...ledger.account, balance: { state: "available", kind: "current_balance", exactValue: "300", display: "$300.00", asOf: "2026-04-30", grade: "conflicted" } }, coverage: { state: "discontinuous", runs: ledger.coverage.runs, gaps: [] }, reconciliation: { ...ledger.reconciliation, balance: "conflicted" }, groups: [{ ...ledger.groups[0], movements: rows }, ledger.groups[1]] };
    const view = render(<AccountLedger {...props({ read: vi.fn(async () => ready(truth)) })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    expect(screen.getByText(/Evidence conflicted/)).toBeInTheDocument();
    expect(screen.getByText("Balance evidence conflicts")).toBeInTheDocument();
    expect(screen.getByText("Coverage is discontinuous across 2 supplied runs.")).toBeInTheDocument();
    expect(screen.getByText(/Direction unavailable · Spending/)).toBeInTheDocument();
    expect(screen.getByText(/Credit · Spending/)).toBeInTheDocument();
    expect(screen.getByText(/Debit · Spending/)).toBeInTheDocument();
    view.unmount();
    const absent: AccountLedgerData = { ...ledger, account: { ...ledger.account, balance: { state: "absent", reason: "no_authoritative_balance_observation" } }, reconciliation: { ...ledger.reconciliation, balance: "not_established" } };
    render(<AccountLedger {...props({ read: vi.fn(async () => ready(absent)) })} />);
    expect(await screen.findByText(/Balance unavailable: this ledger has no authoritative balance observation/)).toBeInTheDocument();
    expect(screen.getByText("Balance reconciliation unavailable")).toBeInTheDocument();
  });

  it("keeps narrow filter controls behind a semantic disclosure without losing state", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, media: "(max-width: 620px)", onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    render(<AccountLedger {...props()} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    const summary = screen.getByText("Filters", { selector: "summary" });
    const disclosure = summary.closest("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    await user.click(summary);
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Corner");
    expect(summary).toHaveTextContent("1 active");
    await user.click(summary);
    expect(disclosure).not.toHaveAttribute("open");
    await user.click(summary);
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("Corner");
  });

  it("never renders a late wrong-account response after the account changes", async () => {
    let resolveOld: ((value: FeatureResult<AccountLedgerData>) => void) | undefined;
    const old = new Promise<FeatureResult<AccountLedgerData>>((resolve) => { resolveOld = resolve; });
    const read = vi.fn((id: string) => id === "old" ? old : Promise.resolve(ready(ledger)));
    const view = render(<AccountLedger {...props({ accountId: "old", read })} />);
    view.rerender(<AccountLedger {...props({ accountId: ledger.account.id, read })} />);
    await screen.findByRole("heading", { name: ledger.account.name });
    resolveOld?.(ready({ ...ledger, scope: { kind: "account", accountId: "old" }, account: { ...ledger.account, id: "old", name: "Wrong old account" } }));
    await Promise.resolve();
    expect(screen.queryByText("Wrong old account")).not.toBeInTheDocument();
  });
});
