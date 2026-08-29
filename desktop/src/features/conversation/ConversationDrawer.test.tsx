import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ConversationData, ConversationTurn, FeatureResult, QuestionActionState, QuestionQueueData, TurnView } from "../../surface/types";
import { ConversationDrawer } from "./ConversationDrawer";

const questions: QuestionQueueData = { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } };
const turn = (more: Partial<ConversationTurn> = {}): ConversationTurn => ({ id: "turn-1", kind: "ask", occurredAt: "2026-08-29", prompt: "What changed?", said: "", questionId: "", outcome: "completed", message: "", reason: "", answer: null, proposal: null, ...more });
const ready = (data: ConversationData): FeatureResult<ConversationData> => ({ state: "ready", data });
const controls = { state: { state: "idle" } as const, onAnswer: vi.fn(), onConfirm: vi.fn(), onDecline: vi.fn() };
const openFigure = vi.fn();

describe("durable Viva conversation", () => {
  it("renders the persisted timeline and the deterministic question queue together", () => {
    const data: ConversationData = { turns: [turn({ message: "The records changed." })], questions: { ...questions, queue: [{ id: "q-1", label: "What was this payment?", detail: "It is not classified.", status: "", action: "", type: "nature", evidence: "", state: "needs_input", outcome: null, disposition: null }] } };
    const view = render(<ConversationDrawer result={ready(data)} selectedQueue="q-1" onSelectQueue={vi.fn()} onOpenFigure={openFigure} ask={null} controls={controls} />);
    expect(view.getByText("Conversation")).toBeInTheDocument();
    expect(view.getByText("What changed?")).toBeInTheDocument();
    expect(view.getAllByText("What was this payment?").length).toBeGreaterThan(0);
  });

  it("keeps each durable outcome distinct and preserves the reviewed receipt detail", () => {
    const answer: TurnView = {
      question: "What changed?",
      text: "Your balance changed.",
      answered: true,
      refusal: "",
      grade: "verified",
      gradeSentence: "The source records verify this figure.",
      figures: [{ id: "figure-opaque", evidenceId: "conversation:turn-1:figure-opaque", written: "USD 20.00", grade: "verified", what: "The balance change", recordIds: ["record-secret-1"], evidenceLinks: [{ targetDocumentId: "doc-1", label: "Checking statement", relation: "attests", page: "" }] }],
      spoken: { maySpeak: true, withheld: "", parts: [], text: "", gradeSentence: "", citationSentence: "One local record supports this figure.", localOnly: "" },
    };
    const turns = [
      turn({ id: "completed", answer }),
      turn({ id: "refused", outcome: "refused", message: "I could not answer from these records." }),
      turn({ id: "waiting", outcome: "waiting", message: "A statement settles this." }),
      turn({ id: "stale", outcome: "stale", message: "The question changed before confirmation." }),
      turn({ id: "set-aside", outcome: "set_aside", message: "Set aside until the subject changes." }),
    ];
    const onOpenFigure = vi.fn();
    const view = render(<ConversationDrawer result={ready({ turns, questions })} selectedQueue="" onSelectQueue={vi.fn()} onOpenFigure={onOpenFigure} ask={null} controls={controls} />);

    for (const label of ["Completed", "Not completed", "Waiting", "Out of date", "Set aside"]) expect(view.getByText(label)).toBeInTheDocument();
    expect(view.getByText("The source records verify this figure.")).toBeInTheDocument();
    expect(view.getByText("One local record supports this figure.")).toBeInTheDocument();
    expect(view.getByText(/1 cited record/)).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("record-secret-1");
    const receipt = view.getByRole("button", { name: "USD 20.00 The balance change", description: "View evidence for The balance change" });
    expect(receipt).toHaveAttribute("aria-haspopup", "dialog");
    expect(receipt).toHaveAttribute("aria-controls", "figure-evidence-drawer");
    fireEvent.click(receipt);
    expect(onOpenFigure).toHaveBeenCalledWith("conversation:turn-1:figure-opaque");
  });

  it("confirms a persisted proposal by its opaque identity", () => {
    const proposed = turn({ kind: "answer", questionId: "q-1", proposal: { id: "p-1", summary: "Record the account as Home loan.", status: "open", outcome: "proposal", message: "", reason: "" } });
    const onConfirm = vi.fn();
    const view = render(<ConversationDrawer result={ready({ turns: [proposed], questions })} selectedQueue="" onSelectQueue={vi.fn()} onOpenFigure={openFigure} ask={null} controls={{ ...controls, onConfirm }} />);
    fireEvent.change(view.getByLabelText("Confirm or decline in your own words"), { target: { value: "yes, that is right" } });
    fireEvent.click(view.getByRole("button", { name: "Reply" }));
    expect(onConfirm).toHaveBeenCalledWith("q-1", "p-1", "yes, that is right", "Record the account as Home loan.");
  });

  it("renders one confirmation path and one action receipt when a proposal is restored", () => {
    const proposed = turn({ kind: "answer", questionId: "q-1", outcome: "proposal", proposal: { id: "p-1", summary: "Record the account as Home loan.", status: "open", outcome: "proposal", message: "", reason: "" } });
    const state: QuestionActionState = { state: "settled", questionId: "q-1", verb: "answer", result: { state: "settled", outcome: { kind: "proposal", message: "Nothing was recorded.", reason: "", proposalId: "p-1", proposalSummary: "Record the account as Home loan." } } };
    const view = render(<ConversationDrawer result={ready({ turns: [proposed], questions })} selectedQueue="" onSelectQueue={vi.fn()} onOpenFigure={openFigure} ask={null} controls={{ ...controls, state }} />);

    expect(view.getByLabelText("Confirm or decline in your own words")).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Confirm this proposal" })).not.toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Decline this proposal" })).not.toBeInTheDocument();
    expect(view.getAllByText("Held for your confirmation")).toHaveLength(1);
  });

  it("keeps a settled action receipt when the conversation reread fails", () => {
    const state: QuestionActionState = { state: "settled", questionId: "q-1", verb: "decline", result: { state: "settled", outcome: { kind: "set_aside", message: "Set aside until the subject changes.", reason: "" } } };
    const view = render(<ConversationDrawer result={{ state: "failed", reason: "read_failed" }} selectedQueue="" onSelectQueue={vi.fn()} onOpenFigure={openFigure} ask={null} controls={{ ...controls, state }} />);

    expect(view.getByText("Conversation could not be read")).toBeInTheDocument();
    expect(view.getAllByText("Question set aside")).toHaveLength(1);
    expect(view.getByText("Set aside until the subject changes.")).toBeInTheDocument();
  });

  it("shows an empty durable history without inventing a transcript", () => {
    const view = render(<ConversationDrawer result={ready({ turns: [], questions })} selectedQueue="" onSelectQueue={vi.fn()} onOpenFigure={openFigure} ask={null} controls={controls} />);
    expect(view.getByText("No conversation yet")).toBeInTheDocument();
    expect(view.queryByText(/supplied conversation/i)).not.toBeInTheDocument();
  });
});
