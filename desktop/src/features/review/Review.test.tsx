import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FeatureResult, ReviewData, ReviewView } from "../../surface/types";
import { Review } from "./Review";

const question = (id: string, overrides: Partial<ReviewView> = {}): ReviewView => ({ id, label: "Returned question", detail: "Returned reason", status: "Read only", action: "", type: "identity", evidence: "", state: "needs_input", outcome: null, disposition: null, scope: "account", count: 7, amount: "101.25", currency: "USD", ...overrides });
const data = (queue: ReviewView[], meta: Partial<ReviewData["meta"]> = {}): ReviewData => ({ queue, count: 999, meta: { total: 42, tail: null, pending: null, invite: "", answeredByDocument: "", ...meta } });
const ready = (review: ReviewData): FeatureResult<ReviewData> => ({ state: "ready", data: review });
const noAction = () => {};

describe("Review inspection surface", () => {
  it("renders live fields exactly and never combines supplied amount and currency", () => {
    const live = question("live-question");
    const { container, getByRole, getByText, queryByText, queryByRole } = render(<Review result={ready(data([live]))} mode="live" selectedQueue="live-question" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Current review read")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(getByText("42", { selector: ".review-summary > strong" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Returned question" })).toHaveAttribute("id", "selected-question-title");
    expect(getByRole("heading", { name: "Returned question" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    for (const value of ["Returned reason", "identity", "account", "7", "101.25", "USD"]) expect(getByText(value, { selector: ".review-detail-grid strong" })).toBeInTheDocument();
    expect(queryByText("101.25 USD")).not.toBeInTheDocument();
    expect(getByText("Actions are not connected")).toBeInTheDocument();
    expect(getByText("Source document unavailable")).toBeInTheDocument();
    expect(queryByRole("form")).not.toBeInTheDocument();
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /answer|decline|proposal|confirm|document review/i })).not.toBeInTheDocument();
    expect(queryByText("Static fictional anatomy")).not.toBeInTheDocument();
  });

  it("renders every missing live field explicitly", () => {
    const missing = question("missing-fields", { label: "", detail: "", type: "", scope: "", count: undefined, amount: "", currency: "" });
    const { getAllByText, getByText } = render(<Review result={ready(data([missing]))} mode="live" selectedQueue="missing-fields" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getAllByText("Question text was not supplied by this read.").length).toBeGreaterThan(0);
    for (const copy of ["Why this question was asked was not supplied by this read.", "Question kind was not supplied by this read.", "Question scope was not supplied by this read.", "Question count was not supplied by this read.", "Question amount was not supplied by this read.", "Question currency was not supplied by this read."]) expect(getByText(copy)).toBeInTheDocument();
  });

  it("renders all four fictional anatomy types without action controls", () => {
    const anatomy = [
      question("answer", { label: "Answer sample", sample: { anatomy: "answer", evidenceLinks: [] } }),
      question("decline", { label: "Decline sample", sample: { anatomy: "decline", evidenceLinks: [] } }),
      question("proposal", { label: "Proposal sample", sample: { anatomy: "proposal", proposedValue: "Fictional proposed value", evidenceLinks: [] } }),
      question("confirmation", { label: "Confirmation sample", sample: { anatomy: "confirmation", proposedValue: "Fictional confirmation value", confirmationPrompt: "Confirm fictional value?", evidenceLinks: [] } }),
    ];
    const { getByRole, getByText, queryByRole, rerender } = render(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="answer" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Answer boundary")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="decline" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Decline / set aside boundary")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="proposal" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Proposal — not applied")).toBeInTheDocument();
    expect(getByText("Fictional proposed value")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="confirmation" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Confirmation required")).toBeInTheDocument();
    expect(getByText("Fictional confirmation value")).toBeInTheDocument();
    expect(getByText("Confirm fictional value?")).toBeInTheDocument();
    expect(queryByRole("button", { name: /^(Answer|Decline|Proposal|Confirm)$/i })).not.toBeInTheDocument();
    expect(getByRole("heading", { name: "Confirmation sample" })).toBeInTheDocument();
  });

  it("routes only demo evidence by exact document target", () => {
    const open = vi.fn();
    const link = { targetDocumentId: "demo-document", label: "Fictional statement", relation: "settles_question" as const, page: "page 2" };
    const sample = question("sample", { sample: { anatomy: "answer", evidenceLinks: [link] } });
    const { getByRole, queryByText, rerender } = render(<Review result={ready(data([sample]))} mode="demo" selectedQueue="sample" onSelectQueue={noAction} onOpenEvidence={open} />);
    fireEvent.click(getByRole("button", { name: "Fictional statement · page 2" }));
    expect(open).toHaveBeenCalledWith(link);
    rerender(<Review result={ready(data([sample]))} mode="live" selectedQueue="sample" onSelectQueue={noAction} onOpenEvidence={open} />);
    expect(queryByText("Fictional statement")).not.toBeInTheDocument();
  });

  it("keeps blank, duplicate, missing, and no-selectable identities bounded", () => {
    const duplicate = [question("duplicate"), question("duplicate")];
    const { container, getAllByText, getByRole, getByText, queryByRole, rerender } = render(<Review result={ready(data(duplicate))} mode="live" selectedQueue="duplicate" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByRole("heading", { name: "Question selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("More than one question in this read uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    expect(getByText("Requested question ID: duplicate")).toBeInTheDocument();
    rerender(<Review result={ready(data([question("present")]))} mode="live" selectedQueue="missing-question-id" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByRole("heading", { name: "Selected question unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("The selected question is no longer present in the current review read.")).toBeInTheDocument();
    expect(getByText("Requested question ID: missing-question-id")).toBeInTheDocument();
    rerender(<Review result={ready(data([question(""), question(" ")]))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByRole("heading", { name: "Question selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("The current review read contains rows, but none has a unique nonblank question ID. No question was selected.")).toBeInTheDocument();
    expect(getAllByText("This row has no stable question ID, so it cannot be selected.")).toHaveLength(2);
    expect(queryByRole("alert")).not.toBeInTheDocument();
    expect(getByRole("heading", { name: "Question selection unavailable" })).not.toHaveFocus();
  });

  it("keeps ordinary list selection on the pressed button", () => {
    const select = vi.fn();
    const queue = [question("first", { label: "First" }), question("second", { label: "Second" })];
    const { getByRole } = render(<Review result={ready(data(queue))} mode="live" selectedQueue="first" onSelectQueue={select} onOpenEvidence={noAction} />);
    const second = getByRole("button", { name: /Second.*View question/i });
    second.focus();
    fireEvent.click(second);
    expect(select).toHaveBeenCalledWith("second");
    expect(second).toHaveFocus();
  });

  it("keeps all six FeatureResult states and both empty modes honest", () => {
    const props = { mode: "live" as const, selectedQueue: "", onSelectQueue: noAction, onOpenEvidence: noAction };
    const { getByText, queryByText, rerender } = render(<Review {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Review queue")).not.toBeInTheDocument();
    rerender(<Review {...props} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByText("Review details are not available in this build.")).toBeInTheDocument();
    rerender(<Review {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("The review section could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Review {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some review details are unavailable. Available questions are shown below.")).toBeInTheDocument();
    rerender(<Review {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some review questions need your input. Available questions are shown below.")).toBeInTheDocument();
    expect(getByText("This preview does not connect a way to answer them.")).toBeInTheDocument();
    rerender(<Review {...props} result={ready(data([]))} />);
    expect(getByText("Nothing needs you right now")).toBeInTheDocument();
    rerender(<Review {...props} mode="demo" result={ready(data([]))} />);
    expect(getByText("No sample review questions")).toBeInTheDocument();
  });

  it("renders pending, tail, and guidance independently without association", () => {
    const review = data([], { total: 1, tail: { count: 3, amount: "tail-amount-exact" }, pending: { count: 1 }, invite: "General invitation", answeredByDocument: "General document guidance" });
    const { getByText, queryByText, rerender } = render(<Review result={ready(review)} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("These summaries are shown separately. The interface does not add them together or create question rows from them.")).toBeInTheDocument();
    expect(getByText("1 set-aside item is reported. Opening its detail is not available in this preview.")).toBeInTheDocument();
    expect(getByText("3", { selector: ".review-more-grid strong" })).toBeInTheDocument();
    expect(getByText("tail-amount-exact")).toBeInTheDocument();
    expect(getByText("Tail amount supplied")).toBeInTheDocument();
    expect(getByText("No question rows are created from this summary.")).toBeInTheDocument();
    expect(getByText("General invitation")).toBeInTheDocument();
    expect(getByText("General document guidance")).toBeInTheDocument();
    expect(getByText("The contract supplies no mapping from this guidance to a specific question. This preview cannot accept an answer or document.")).toBeInTheDocument();
    expect(queryByText(/Returned question.*General invitation/)).not.toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: { count: 0, amount: "" }, pending: { count: 4 } }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("4 set-aside items are reported. Opening their detail is not available in this preview.")).toBeInTheDocument();
    expect(getByText("0", { selector: ".review-more-grid strong" })).toBeInTheDocument();
    expect(getByText("Tail amount was not supplied by this read.")).toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: null, pending: { count: 0 } }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Tail summary was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Set-aside items reported: 0.")).toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: null, pending: null }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} />);
    expect(getByText("Set-aside summary was not supplied by this read.")).toBeInTheDocument();
  });
});
