import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReviewData } from "../../surface/types";
import { Review } from "./Review";

const target = { kind: "transaction" as const, questionId: "q-1", accountId: "acct-1", requestedMovementId: "member-2", canonicalMovementId: "member-1", memberMovementIds: ["member-1", "member-2"] };
const binding = { itemId: "question:q-1", questionId: "q-1", questionKind: "transfer", label: "Was this a transfer?", reason: "A matching movement was supplied.", refs: { movement: "member-2", movements: ["member-1", "member-2"], candidates: [], document: "", documentId: "", account: "acct-1" }, target, status: "open" as const, primaryAction: "open_transaction" as const, allowedActions: ["open_transaction" as const] };
const data: ReviewData = { contract: "ReviewSummary.v1", title: "Review", summary: "1 item is waiting for your answer.", actionableCount: 1, shownCount: 1, remainingCount: 0, types: [{ id: "questions", label: "Questions", count: 1 }], groups: [{ id: "questions", label: "Questions", count: 1, items: [{ id: "question:q-1", type: "question", typeLabel: "Question", marker: "?", markerLabel: "Viva needs an answer", label: binding.label, reason: binding.reason, status: "open", context: { date: "2026-06-22", amount: "USD 275.00", account: "Everyday account", merchant: "Transfer" }, target, primaryAction: "open_transaction", actionLabel: "Review transaction", allowedActions: ["open_transaction"], binding }] }] };

describe("Review center", () => {
  it("renders only supplied kinds/count/context and opens its exact target", () => {
    const open = vi.fn();
    const view = render(<Review result={{ state: "ready", data }} onOpenQuestion={vi.fn()} onOpenTransaction={open} />);
    expect(view.getByLabelText("1 actionable review item")).toHaveTextContent("1");
    expect(view.getByLabelText("Viva needs an answer").querySelector("svg")).not.toBeNull();
    expect(view.getByLabelText("Viva needs an answer")).not.toHaveTextContent("?");
    fireEvent.click(view.getByRole("button", { name: /review transaction/i }));
    expect(open).toHaveBeenCalledWith(data.groups[0].items[0].target, "question:q-1");
  });

  it("offers the supplied next item without changing its exact target or backend order", () => {
    const open = vi.fn();
    const view = render(<Review result={{ state: "ready", data }} nextItemId="question:q-1" onOpenQuestion={vi.fn()} onOpenTransaction={open} />);
    expect(view.getByText("Why this needs review")).toBeInTheDocument();
    expect(view.getByText("Amount").nextElementSibling).toHaveTextContent("USD 275.00");
    fireEvent.click(view.getByRole("button", { name: "Next item: Review transaction" }));
    expect(open).toHaveBeenCalledWith(target, "question:q-1");
  });

  it("does not call an incomplete or bounded empty queue complete", () => {
    const empty = { ...data, shownCount: 0, groups: [], remainingCount: 1 };
    const view = render(<Review result={{ state: "partial", data: empty, issues: [{ code: "partial", message: "Some items unavailable." }] }} onOpenQuestion={vi.fn()} onOpenTransaction={vi.fn()} />);
    expect(view.getByText("No review items loaded")).toBeInTheDocument();
    expect(view.queryByText("Nothing to review")).not.toBeInTheDocument();
    expect(view.getByText("1 more review item is not shown here.")).toBeInTheDocument();
  });

  it("keeps locked/error reads honest and caps only the visual badge", () => {
    const unavailable = render(<Review result={{ state: "unavailable", reason: "locked" }} onOpenQuestion={vi.fn()} onOpenTransaction={vi.fn()} />);
    expect(unavailable.getByText("Review unavailable")).toBeInTheDocument();
    unavailable.unmount();
    const large = render(<Review result={{ state: "ready", data: { ...data, actionableCount: 1250, remainingCount: 1249 } }} onOpenQuestion={vi.fn()} onOpenTransaction={vi.fn()} />);
    expect(large.getByLabelText("1250 actionable review items")).toHaveTextContent("999+");
  });
});

it("shows truthful source attention totals without inventing Question actions", () => {
  const id = "a".repeat(64); const open = vi.fn(); const question = vi.fn();
  const result: ReviewData = { ...data, actionableCount: 0, shownCount: 0, remainingCount: 0, groups: [], types: [], documentAttention: { state: "ready", totalDocuments: 51, shownCount: 1, remainingCount: 50, unavailableReason: null, documents: [{ documentId: id, filename: "partial.pdf", components: [{ component: "payment:PAY-X", kind: "payment", label: "Payment PAY-X", disposition: "held", reasonCode: "unmatched_counterpart", reason: "A unique counterpart is unresolved.", sourcePages: [{ documentId: id, page: 2, label: "Source page 2" }] }] }] } };
  const view = render(<Review result={{ state: "ready", data: result }} onOpenQuestion={question} onOpenTransaction={vi.fn()} onOpenSourceDocument={open} />);
  expect(view.getByText("No questions waiting")).toBeInTheDocument();
  expect(view.getByText("Showing 1 of 51 documents with unresolved source sections.")).toBeInTheDocument();
  expect(view.getByText("50 more documents have unresolved source sections. Select a document in Documents to inspect its current sections.")).toBeInTheDocument();
  fireEvent.click(view.getByRole("button", { name: "Source page 2" }));
  expect(open).toHaveBeenCalledWith(id, 2); expect(question).not.toHaveBeenCalled();
});
