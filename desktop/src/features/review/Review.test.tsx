import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionOutcomeView, FeatureResult, QuestionSlot, ReviewActionState, ReviewData, ReviewView } from "../../surface/types";
import { Review } from "./Review";
import moments from "../../../../product/viva/persona/pack-v25/moments.json";

const question = (id: string, overrides: Partial<ReviewView> = {}): ReviewView => ({ id, label: "Returned question", detail: "Returned reason", status: "Read only", action: "", type: "identity", evidence: "", state: "needs_input", outcome: null, disposition: null, scope: "account", count: 7, amount: "101.25", currency: "USD", ...overrides });
const data = (queue: ReviewView[], meta: Partial<ReviewData["meta"]> = {}): ReviewData => ({ queue, count: 999, meta: { total: 42, tail: null, pending: null, invite: "", answeredByDocument: "", ...meta } });
const ready = (review: ReviewData): FeatureResult<ReviewData> => ({ state: "ready", data: review });
const noAction = () => {};
// Every source a screen can be given carries the verbs, so there is no state
// with nothing behind the controls. Tests that are not about a verb use the
// state a screen opens in.
const noAnswer = (_questionId: string, _said: string) => {};
const inert = { state: { state: "idle" } as const, onAnswer: noAnswer, onDecline: noAction };
// A screen with the verb in whatever state the last one left it.
const acted = (state: ReviewActionState) => ({ state, onAnswer: noAnswer, onDecline: noAction });

describe("Review inspection surface", () => {
  it("renders live fields exactly and never combines supplied amount and currency", () => {
    const live = question("live-question");
    const { container, getByRole, getByText, queryByText, queryByRole } = render(<Review result={ready(data([live]))} mode="live" selectedQueue="live-question" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Current review read")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(getByText("42", { selector: ".review-summary > strong" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Returned question" })).toHaveAttribute("id", "selected-question-title");
    expect(getByRole("heading", { name: "Returned question" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    for (const value of ["Returned reason", "identity", "account", "7", "101.25", "USD"]) expect(getByText(value, { selector: ".review-detail-grid strong" })).toBeInTheDocument();
    expect(queryByText("101.25 USD")).not.toBeInTheDocument();
    expect(queryByText("What this screen cannot do")).not.toBeInTheDocument();
    // A live row is a row a person can act on, so nothing on it says otherwise.
    expect(queryByText("Read only")).not.toBeInTheDocument();
    // Said once, in the panel holding the controls it is about, rather than
    // three times over one screen.
    expect(container.querySelectorAll(".review-set-aside p")).toHaveLength(2);
    expect(getByText("Setting a question aside is connected, and so is answering one in your own words. Proposing a change, confirming one, and correcting a document are not.")).toBeInTheDocument();
    expect(getByText("Source document unavailable")).toBeInTheDocument();
    // This question declares no slots, so nothing said in words settles it and
    // there is no box to write in.
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /answer|decline|proposal|confirm|document review/i })).not.toBeInTheDocument();
    expect(queryByText("Static fictional anatomy")).not.toBeInTheDocument();
  });

  it("renders every missing live field explicitly", () => {
    const missing = question("missing-fields", { label: "", detail: "", type: "", scope: "", count: undefined, amount: "", currency: "" });
    const { getAllByText, getByText } = render(<Review result={ready(data([missing]))} mode="live" selectedQueue="missing-fields" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
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
    const { getByRole, getByText, queryByRole, rerender } = render(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="answer" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Answer boundary")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="decline" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Set-aside boundary")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="proposal" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Proposal — not applied")).toBeInTheDocument();
    expect(getByText("Fictional proposed value")).toBeInTheDocument();
    rerender(<Review result={ready(data(anatomy))} mode="demo" selectedQueue="confirmation" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
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
    const { getByRole, queryByText, rerender } = render(<Review result={ready(data([sample]))} mode="demo" selectedQueue="sample" onSelectQueue={noAction} onOpenEvidence={open} actions={inert} />);
    fireEvent.click(getByRole("button", { name: "Fictional statement · page 2" }));
    expect(open).toHaveBeenCalledWith(link);
    rerender(<Review result={ready(data([sample]))} mode="live" selectedQueue="sample" onSelectQueue={noAction} onOpenEvidence={open} actions={inert} />);
    expect(queryByText("Fictional statement")).not.toBeInTheDocument();
  });

  it("keeps blank, duplicate, missing, and no-selectable identities bounded", () => {
    const duplicate = [question("duplicate"), question("duplicate")];
    const { container, getAllByText, getByRole, getByText, queryByRole, rerender } = render(<Review result={ready(data(duplicate))} mode="live" selectedQueue="duplicate" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByRole("heading", { name: "Question selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("More than one question in this read uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    expect(getByText("Requested question ID: duplicate")).toBeInTheDocument();
    rerender(<Review result={ready(data([question("present")]))} mode="live" selectedQueue="missing-question-id" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByRole("heading", { name: "Selected question unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("The selected question is no longer present in the current review read.")).toBeInTheDocument();
    expect(getByText("Requested question ID: missing-question-id")).toBeInTheDocument();
    rerender(<Review result={ready(data([question(""), question(" ")]))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
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
    const { getByRole } = render(<Review result={ready(data(queue))} mode="live" selectedQueue="first" onSelectQueue={select} onOpenEvidence={noAction} actions={inert} />);
    const second = getByRole("button", { name: /Second.*View question/i });
    second.focus();
    fireEvent.click(second);
    expect(select).toHaveBeenCalledWith("second");
    expect(second).toHaveFocus();
  });

  it("keeps all six FeatureResult states and both empty modes honest", () => {
    const props = { mode: "live" as const, selectedQueue: "", onSelectQueue: noAction, onOpenEvidence: noAction, actions: inert };
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
    rerender(<Review {...props} result={ready(data([]))} />);
    expect(getByText("Nothing needs you right now")).toBeInTheDocument();
    rerender(<Review {...props} mode="demo" result={ready(data([]))} />);
    expect(getByText("No sample review questions")).toBeInTheDocument();
  });

  it("renders pending, tail, and guidance independently without association", () => {
    const review = data([], { total: 1, tail: { count: 3, amount: "tail-amount-exact" }, pending: { count: 1 }, invite: "General invitation", answeredByDocument: "General document guidance" });
    const { getByText, queryByRole, queryByText, rerender } = render(<Review result={ready(review)} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("These summaries are shown separately. The interface does not add them together or create question rows from them.")).toBeInTheDocument();
    expect(getByText("1 set-aside item is reported. It returns on its own when what it is about changes. Opening its detail is not available in this preview.")).toBeInTheDocument();
    expect(getByText("3", { selector: ".review-more-grid strong" })).toBeInTheDocument();
    expect(getByText("tail-amount-exact")).toBeInTheDocument();
    expect(getByText("Tail amount supplied")).toBeInTheDocument();
    expect(getByText("No question rows are created from this summary.")).toBeInTheDocument();
    // The read supplies an invitation to answer in a sentence and nothing in
    // this build can take one, so the words are not repeated at a person under
    // a heading that reads as an ask. The boundary is stated instead.
    expect(queryByText("General invitation")).not.toBeInTheDocument();
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    expect(queryByText(/invites an answer in a sentence/)).not.toBeInTheDocument();
    expect(getByText("General document guidance")).toBeInTheDocument();
    expect(getByText("The contract supplies no mapping from this guidance to a specific question. This preview cannot accept an answer or document.")).toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: { count: 0, amount: "" }, pending: { count: 4 } }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("4 set-aside items are reported. Each returns on its own when what it is about changes. Opening their detail is not available in this preview.")).toBeInTheDocument();
    expect(getByText("0", { selector: ".review-more-grid strong" })).toBeInTheDocument();
    expect(getByText("Tail amount was not supplied by this read.")).toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: null, pending: { count: 0 } }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Tail summary was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Set-aside items reported: 0.")).toBeInTheDocument();
    rerender(<Review result={ready(data([], { tail: null, pending: null }))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);
    expect(getByText("Set-aside summary was not supplied by this read.")).toBeInTheDocument();
  });

  it("offers both reasons a question may be set aside, and both say it is set aside", () => {
    const decline = vi.fn();
    const actions = { state: { state: "idle" } as const, onAnswer: noAnswer, onDecline: decline };
    const { getAllByRole, getByRole, getByText, queryByRole } = render(<Review result={ready(data([question("live-question")]))} mode="live" selectedQueue="live-question" onSelectQueue={noAction} onOpenEvidence={noAction} actions={actions} />);

    expect(getByText("Setting a question aside does not delete it. It comes back on its own when the amount behind it, or the number of movements it covers, changes.")).toBeInTheDocument();
    // Answering is not connected in this version, so no control offers it and
    // nothing on this screen invites a sentence it would then refuse.
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /record this answer/i })).not.toBeInTheDocument();
    // Neither control may read as an answer: declining is setting aside, and a
    // person who thinks they destroyed a question will not decline again.
    for (const control of getAllByRole("button", { name: /^Set aside/ })) expect(control).toBeEnabled();
    fireEvent.click(getByRole("button", { name: "Set aside for now" }));
    fireEvent.click(getByRole("button", { name: "Set aside: I do not know" }));

    expect(decline.mock.calls).toEqual([["live-question", "not_now"], ["live-question", "dont_know"]]);
  });

  it("keeps what happened on the screen after the question it happened to has gone", () => {
    const props = { mode: "live" as const, selectedQueue: "set-aside-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = acted({ state: "settled", questionId: "set-aside-question", verb: "decline", result: { state: "settled", outcome: { kind: "completed", message: "Set aside until something changes.", reason: "" } } });
    const { getByRole, getByText, rerender } = render(<Review {...props} result={ready(data([question("set-aside-question")]))} actions={settled} />);

    // The question leaves the queue and the selection moves on. What became of
    // it must not leave with it.
    rerender(<Review {...props} result={ready(data([question("next-question")]))} selectedQueue="next-question" actions={settled} />);
    expect(getByRole("status")).toHaveTextContent("Set aside");
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();

    // And the read that followed the write is a separate channel from the write
    // itself: a read that failed leaves the write's own account standing, or a
    // person sets the same question aside twice.
    rerender(<Review {...props} result={{ state: "failed", reason: "read_failed" }} actions={settled} />);
    expect(getByText("Review could not be read")).toBeInTheDocument();
    expect(getByText("Set aside")).toBeInTheDocument();
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();
  });

  it("titles a settled verb in the words of the verb, and never in a machine's", () => {
    const live = question("live-question");
    const props = { result: ready(data([live])), mode: "live" as const, selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = (kind: ActionOutcomeView["kind"], message: string, reason = "") =>
      acted({ state: "settled", questionId: "live-question", verb: "decline", result: { state: "settled", outcome: { kind, message, reason } } });

    const { getByRole, getByText, queryByText, rerender } = render(<Review {...props} actions={acted({ state: "working", questionId: "live-question", verb: "decline" })} />);
    expect(getByRole("status")).toHaveTextContent("Setting this question aside");

    // A title saying "Recorded" over a sentence about a question being set
    // aside would describe an act the person did not perform.
    rerender(<Review {...props} actions={settled("completed", "Set aside until something changes.")} />);
    expect(getByText("Set aside")).toBeInTheDocument();
    expect(queryByText("Recorded")).not.toBeInTheDocument();
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();

    rerender(<Review {...props} actions={settled("refused", "That question is no longer open.", "not_open")} />);
    expect(getByText("Not set aside")).toBeInTheDocument();
    expect(getByText("That question is no longer open.")).toBeInTheDocument();
    // The reason is written for a log. A person is shown the sentence.
    expect(queryByText(/not_open/)).not.toBeInTheDocument();

    rerender(<Review {...props} actions={settled("waiting", "The document itself settles this one.")} />);
    expect(getByText("Nothing set aside yet")).toBeInTheDocument();

    rerender(<Review {...props} actions={settled("stale", "This read has moved on.")} />);
    expect(getByText("Out of date")).toBeInTheDocument();
  });

  it("names each way a verb can fail to answer without calling any of them a refusal", () => {
    const live = question("live-question");
    const props = { result: ready(data([live])), mode: "live" as const, selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const failed = (state: "unserved" | "unanswered" | "unreadable") =>
      acted({ state: "settled", questionId: "live-question", verb: "decline", result: { state } });

    // The sidecar read the request and would not take it. That is the one
    // failure this screen may title as a refusal, and it says so in its own
    // words rather than in the sidecar's, which name payload fields.
    // It is titled as the request not being taken and never as the question not
    // being set aside: the same code carries a handler that raised, and a
    // handler can raise after it has written.
    const { getByText, queryByText, rerender } = render(<Review {...props} actions={failed("unserved")} />);
    expect(getByText("Your vault would not take this request")).toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();
    expect(getByText("Your vault refused the request as this screen sent it. Whether anything was recorded is not something this screen can tell you.")).toBeInTheDocument();

    rerender(<Review {...props} actions={failed("unanswered")} />);
    expect(getByText("Your vault did not answer")).toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();

    // A handler that raised may have raised after writing, so nothing here may
    // say the vault is as it was.
    rerender(<Review {...props} actions={failed("unreadable")} />);
    expect(getByText("The reply could not be read")).toBeInTheDocument();
    expect(queryByText(/was not changed/)).not.toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();
  });

  it("says a sample refusal in the sample vault, where nothing is recorded", () => {
    const decline = vi.fn();
    const sample = question("sample-question", { sample: { anatomy: "answer", evidenceLinks: [] } });
    const actions = { state: { state: "settled", questionId: "sample-question", verb: "decline", result: { state: "settled", outcome: { kind: "refused", message: "This is the sample vault, and nothing in it is recorded.", reason: "sample_vault" } } } as const, onAnswer: noAnswer, onDecline: decline };
    const { getByRole, getByText } = render(<Review result={ready(data([sample]))} mode="demo" selectedQueue="sample-question" onSelectQueue={noAction} onOpenEvidence={noAction} actions={actions} />);

    fireEvent.click(getByRole("button", { name: "Set aside for now" }));

    expect(decline).toHaveBeenCalledWith("sample-question", "not_now");
    expect(getByText("Not set aside")).toBeInTheDocument();
    expect(getByText("This is the sample vault, and nothing in it is recorded.")).toBeInTheDocument();
  });

  it("gives the empty state something focus can land on when a write empties the queue", () => {
    const { getByText } = render(<Review result={ready(data([]))} mode="live" selectedQueue="" onSelectQueue={noAction} onOpenEvidence={noAction} actions={inert} />);

    // The best moment this screen has is also the one where the question that
    // was operated on has gone, so focus has nowhere to fall back to.
    expect(getByText("Nothing needs you right now")).toHaveAttribute("tabindex", "-1");
    expect(getByText("Nothing needs you right now")).toHaveAttribute("id", "review-empty-title");
  });

  it("never disables a set-aside control, in any state a verb can leave it", () => {
    // A focused element that becomes disabled loses focus, and the browser this
    // ships in drops it to the document body. Asserting that focus survived
    // would pass in a test environment that does not implement the blur and say
    // nothing about the shipped product, so the mechanism is what is asserted:
    // the control the person pressed is never disabled while they hold it.
    const props = { result: ready(data([question("live-question")])), mode: "live" as const, selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const states: ReviewActionState[] = [
      { state: "idle" },
      { state: "working", questionId: "live-question", verb: "decline" },
      { state: "settled", questionId: "live-question", verb: "decline", result: { state: "settled", outcome: { kind: "refused", message: "That question is no longer open.", reason: "not_open" } } },
    ];
    const { container, getByRole, rerender } = render(<Review {...props} actions={acted(states[0])} />);
    const pressed = getByRole("button", { name: "Set aside for now" });
    pressed.focus();

    for (const state of states) {
      rerender(<Review {...props} actions={acted(state)} />);
      expect(container.querySelectorAll(".review-set-aside button[disabled]")).toHaveLength(0);
      for (const control of container.querySelectorAll(".review-set-aside button")) expect(control).not.toHaveAttribute("disabled");
    }

    // While the vault is answering, a second press does nothing and the control
    // says why to a screen reader rather than going silent.
    const declined = vi.fn();
    rerender(<Review {...props} actions={{ state: states[1], onAnswer: noAnswer, onDecline: declined }} />);
    expect(pressed).toHaveAttribute("aria-disabled", "true");
    expect(pressed).toHaveAccessibleDescription("Your vault is answering the last request. Pressing again does nothing until it has.");
    fireEvent.click(pressed);
    expect(declined).not.toHaveBeenCalled();
  });

  it("says the queue could not be read again beside the write that took", () => {
    const props = { mode: "live" as const, selectedQueue: "set-aside-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = acted({ state: "settled", questionId: "set-aside-question", verb: "decline", result: { state: "settled", outcome: { kind: "completed", message: "Set aside until something changes.", reason: "" } } });
    const unread = "This screen could not read the queue afterwards, so it no longer knows what is still open.";

    const { getByRole, getByText, queryByText, rerender } = render(<Review {...props} result={ready(data([question("next-question")]))} actions={settled} />);
    expect(queryByText(unread)).not.toBeInTheDocument();

    // A person told only that the write took would believe the list under it,
    // and after a failed re-read there is no list this screen can stand on.
    rerender(<Review {...props} result={{ state: "failed", reason: "read_failed" }} actions={settled} />);
    expect(getByText("Set aside")).toBeInTheDocument();
    expect(getByText(unread)).toBeInTheDocument();
    expect(getByRole("status")).toHaveTextContent(unread);

    // And what focus lands on when neither a question nor the empty state is
    // left on the screen.
    expect(getByText("Set aside")).toHaveAttribute("id", "review-outcome-title");
    expect(getByText("Set aside")).toHaveAttribute("tabindex", "-1");
  });
});

describe("answering in a person's own words", () => {
  const props = { selectedQueue: "q-1", onSelectQueue: noAction, onOpenEvidence: noAction };
  const slot = { name: "same_account", type: "yes_no", required: true, wants: moments.wants_yes_no, choices: [] as string[] };
  const choiceSlot = { name: "category", type: "choice", required: true, wants: moments.wants_choice.replace("{alternatives}", "food, rent"), choices: ["food", "rent"] };
  const answerable = (slots: readonly QuestionSlot[]) => ready(data([{ ...question("q-1"), slots }], { invite: "Say it however you like." }));

  it("renders no form for a question nothing said in words settles", () => {
    // A document settles it. The form is absent rather than present and
    // refusing.
    const { queryByRole } = render(<Review {...props} result={answerable([])} mode="live" actions={inert} />);
    expect(queryByRole("button", { name: "Send this answer" })).not.toBeInTheDocument();
  });

  it("says what each slot needs back in the queue's own words", () => {
    const { getByText } = render(<Review {...props} result={answerable([slot])} mode="live" actions={inert} />);
    expect(getByText(moments.wants_yes_no)).toBeInTheDocument();
  });

  it("shows the closed vocabulary an answer has to land in", () => {
    const { getByText } = render(<Review {...props} result={answerable([choiceSlot])} mode="live" actions={inert} />);
    expect(getByText(moments.wants_choice.replace("{alternatives}", "food, rent"))).toBeInTheDocument();
  });

  it("invites a person in the read's own sentence rather than one of its own", () => {
    const { getByLabelText } = render(<Review {...props} result={answerable([slot])} mode="live" actions={inert} />);
    expect(getByLabelText("Say it however you like.")).toBeInTheDocument();
  });

  it("sends the question and the sentence, and nothing else", () => {
    const sent: Array<[string, string]> = [];
    const actions = { state: { state: "idle" } as const, onAnswer: (id: string, said: string) => { sent.push([id, said]); }, onDecline: noAction };
    const { getByLabelText, getByRole } = render(<Review {...props} result={answerable([slot])} mode="live" actions={actions} />);
    fireEvent.change(getByLabelText("Say it however you like."), { target: { value: "  yes, that is the same account  " } });
    fireEvent.click(getByRole("button", { name: "Send this answer" }));
    expect(sent).toEqual([["q-1", "yes, that is the same account"]]);
  });

  it("sends nothing at all for an empty sentence", () => {
    const sent: string[] = [];
    const actions = { state: { state: "idle" } as const, onAnswer: (id: string) => { sent.push(id); }, onDecline: noAction };
    const { getByRole } = render(<Review {...props} result={answerable([slot])} mode="live" actions={actions} />);
    fireEvent.click(getByRole("button", { name: "Send this answer" }));
    expect(sent).toEqual([]);
  });

  it("keeps the control in the tab order while the vault is answering", () => {
    const actions = { state: { state: "working", questionId: "q-1", verb: "answer" } as const, onAnswer: noAnswer, onDecline: noAction };
    const { getByRole } = render(<Review {...props} result={answerable([slot])} mode="live" actions={actions} />);
    expect(getByRole("button", { name: "Send this answer" })).toHaveAttribute("aria-disabled", "true");
  });
});
