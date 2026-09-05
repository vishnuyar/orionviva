import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionOutcomeView, FeatureResult, QuestionSlot, QuestionActionState, QuestionQueueData, QuestionView } from "../../surface/types";
import { Questions } from "./Questions";
import moments from "../../../../product/viva/persona/pack-v31/moments.json";

const question = (id: string, overrides: Partial<QuestionView> = {}): QuestionView => ({ id, label: "Returned question", detail: "Returned reason", status: "Read only", action: "", type: "identity", evidence: "", state: "needs_input", outcome: null, disposition: null, scope: "account", count: 7, amount: "101.25", currency: "USD", ...overrides });
const data = (queue: QuestionView[], meta: Partial<QuestionQueueData["meta"]> = {}): QuestionQueueData => ({ queue, count: 999, meta: { total: 42, tail: null, pending: null, invite: "", answeredByDocument: "", ...meta } });
const ready = (review: QuestionQueueData): FeatureResult<QuestionQueueData> => ({ state: "ready", data: review });
const noAction = () => {};
// Every source a screen can be given carries the verbs, so there is no state
// with nothing behind the controls. Tests that are not about a verb use the
// state a screen opens in.
const noAnswer = (_questionId: string, _said: string) => {};
const inert = { state: { state: "idle" } as const, onAnswer: noAnswer, onDecline: noAction };
// A screen with the verb in whatever state the last one left it.
const acted = (state: QuestionActionState) => ({ state, onAnswer: noAnswer, onDecline: noAction });

describe("Questions inside the conversation", () => {
  it("renders live fields exactly and never combines supplied amount and currency", () => {
    const live = question("live-question");
    const { container, getByRole, getByText, queryByText, queryByRole } = render(<Questions result={ready(data([live]))} selectedQueue="live-question" onSelectQueue={noAction} actions={inert} />);
    expect(getByText("Current conversation")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Questions for you" })).toBeInTheDocument();
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
    expect(getByText("Setting a question aside, answering in your own words, and confirming or declining a resulting proposal are connected. Correcting a document is not.")).toBeInTheDocument();
    expect(getByText("Source document unavailable")).toBeInTheDocument();
    // This question declares no slots, so nothing said in words settles it and
    // there is no box to write in.
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /answer|decline|proposal|confirm|document review/i })).not.toBeInTheDocument();
    expect(queryByText("Static fictional anatomy")).not.toBeInTheDocument();
  });

  it("renders every missing live field explicitly", () => {
    const missing = question("missing-fields", { label: "", detail: "", type: "", scope: "", count: undefined, amount: "", currency: "" });
    const { getAllByText, getByText } = render(<Questions result={ready(data([missing]))} selectedQueue="missing-fields" onSelectQueue={noAction} actions={inert} />);
    expect(getAllByText("Question text was not supplied by this conversation.").length).toBeGreaterThan(0);
    for (const copy of ["Why this question was asked was not supplied by this conversation.", "Question kind was not supplied by this conversation.", "Question scope was not supplied by this conversation.", "Question count was not supplied by this conversation.", "Question amount was not supplied by this conversation.", "Question currency was not supplied by this conversation."]) expect(getByText(copy)).toBeInTheDocument();
  });



  it("keeps blank, duplicate, missing, and no-selectable identities bounded", () => {
    const duplicate = [question("duplicate"), question("duplicate")];
    const { container, getAllByText, getByRole, getByText, queryByRole, rerender } = render(<Questions result={ready(data(duplicate))} selectedQueue="duplicate" onSelectQueue={noAction} actions={inert} />);
    expect(getByRole("heading", { name: "Question selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("More than one question in this conversation has the same identity, so the interface will not choose between them.")).toBeInTheDocument();
    rerender(<Questions result={ready(data([question("present")]))} selectedQueue="missing-question-id" onSelectQueue={noAction} actions={inert} />);
    expect(getByRole("heading", { name: "Selected question unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("The selected question is no longer present in the current conversation.")).toBeInTheDocument();
    rerender(<Questions result={ready(data([question(""), question(" ")]))} selectedQueue="" onSelectQueue={noAction} actions={inert} />);
    expect(getByRole("heading", { name: "Question selection unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(container.querySelectorAll("#selected-question-title")).toHaveLength(1);
    expect(getByText("The current conversation contains questions, but none has a unique stable identity. No question was selected.")).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/question ID/i);
    expect(getAllByText("This question has no stable identity, so it cannot be selected.")).toHaveLength(2);
    expect(queryByRole("alert")).not.toBeInTheDocument();
    expect(getByRole("heading", { name: "Question selection unavailable" })).not.toHaveFocus();
  });

  it("keeps ordinary list selection on the pressed button", () => {
    const select = vi.fn();
    const queue = [question("first", { label: "First" }), question("second", { label: "Second" })];
    const { getByRole } = render(<Questions result={ready(data(queue))} selectedQueue="first" onSelectQueue={select} actions={inert} />);
    const second = getByRole("button", { name: /Second.*View question/i });
    second.focus();
    fireEvent.click(second);
    expect(select).toHaveBeenCalledWith("second");
    expect(second).toHaveFocus();
  });

  it("keeps all six FeatureResult states honest", () => {
    const props = { selectedQueue: "", onSelectQueue: noAction, actions: inert };
    const { getByText, queryByText, rerender } = render(<Questions {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Questions for you")).not.toBeInTheDocument();
    rerender(<Questions {...props} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByText("Questions are not available in this build.")).toBeInTheDocument();
    rerender(<Questions {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("The conversation could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Questions {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some conversation details are unavailable. Available questions are shown below.")).toBeInTheDocument();
    rerender(<Questions {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some questions need your input. Available questions are shown below.")).toBeInTheDocument();
    rerender(<Questions {...props} result={ready(data([]))} />);
    expect(getByText("Nothing needs you right now")).toBeInTheDocument();
  });

  it("renders pending, tail, and guidance independently without association", () => {
    const review = data([], { total: 1, tail: { count: 3, amount: "tail-amount-exact" }, pending: { count: 1 }, invite: "General invitation", answeredByDocument: "General document guidance" });
    const { getByText, queryByRole, queryByText, rerender } = render(<Questions result={ready(review)} selectedQueue="" onSelectQueue={noAction} actions={inert} />);
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
    expect(getByText("This guidance is general and is not attached to a particular question. Add a statement from Statements when a document is the answer.")).toBeInTheDocument();
    rerender(<Questions result={ready(data([], { tail: { count: 0, amount: "" }, pending: { count: 4 } }))} selectedQueue="" onSelectQueue={noAction} actions={inert} />);
    expect(getByText("4 set-aside items are reported. Each returns on its own when what it is about changes. Opening their detail is not available in this preview.")).toBeInTheDocument();
    expect(getByText("0", { selector: ".review-more-grid strong" })).toBeInTheDocument();
    expect(getByText("Tail amount was not supplied by this conversation.")).toBeInTheDocument();
    rerender(<Questions result={ready(data([], { tail: null, pending: { count: 0 } }))} selectedQueue="" onSelectQueue={noAction} actions={inert} />);
    expect(getByText("Tail summary was not supplied by this conversation.")).toBeInTheDocument();
    expect(getByText("Set-aside items reported: 0.")).toBeInTheDocument();
    rerender(<Questions result={ready(data([], { tail: null, pending: null }))} selectedQueue="" onSelectQueue={noAction} actions={inert} />);
    expect(getByText("Set-aside summary was not supplied by this conversation.")).toBeInTheDocument();
  });

  it("offers both reasons a question may be set aside, and both say it is set aside", () => {
    const decline = vi.fn();
    const actions = { state: { state: "idle" } as const, onAnswer: noAnswer, onDecline: decline };
    const { getAllByRole, getByRole, getByText, queryByRole } = render(<Questions result={ready(data([question("live-question")]))} selectedQueue="live-question" onSelectQueue={noAction} actions={actions} />);

    expect(getByText("Setting a question aside does not delete it. It comes back on its own when the amount behind it, or the number of movements it covers, changes.")).toBeInTheDocument();
    // This question declares no slots, so no answer control offers a sentence
    // that the engine has said cannot settle it.
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
    const props = { selectedQueue: "set-aside-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = acted({ state: "settled", questionId: "set-aside-question", verb: "decline", result: { state: "settled", outcome: { kind: "set_aside", message: "Set aside until something changes.", reason: "" } } });
    const { getByRole, getByText, rerender } = render(<Questions {...props} result={ready(data([question("set-aside-question")]))} actions={settled} />);

    // The question leaves the queue and the selection moves on. What became of
    // it must not leave with it.
    rerender(<Questions {...props} result={ready(data([question("next-question")]))} selectedQueue="next-question" actions={settled} />);
    expect(getByRole("status")).toHaveTextContent("Set aside");
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();

    // And the read that followed the write is a separate channel from the write
    // itself: a read that failed leaves the write's own account standing, or a
    // person sets the same question aside twice.
    rerender(<Questions {...props} result={{ state: "failed", reason: "read_failed" }} actions={settled} />);
    expect(getByText("Questions could not be read")).toBeInTheDocument();
    expect(getByText("Question set aside")).toBeInTheDocument();
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();
  });

  it("titles a settled verb in the words of the verb, and never in a machine's", () => {
    const live = question("live-question");
    const props = { result: ready(data([live])), selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = (kind: ActionOutcomeView["kind"], message: string, reason = "") =>
      acted({ state: "settled", questionId: "live-question", verb: "decline", result: { state: "settled", outcome: { kind, message, reason } } });

    const { getByRole, getByText, queryByText, rerender } = render(<Questions {...props} actions={acted({ state: "working", questionId: "live-question", verb: "decline" })} />);
    expect(getByRole("status")).toHaveTextContent("Setting this question aside");

    // A title saying "Recorded" over a sentence about a question being set
    // aside would describe an act the person did not perform.
    rerender(<Questions {...props} actions={settled("set_aside", "Set aside until something changes.")} />);
    expect(getByText("Question set aside")).toBeInTheDocument();
    expect(queryByText("Recorded")).not.toBeInTheDocument();
    expect(getByText("Set aside until something changes.")).toBeInTheDocument();

    rerender(<Questions {...props} actions={acted({ state: "settled", questionId: "live-question", verb: "answer", result: { state: "settled", outcome: { kind: "proposal", message: "Nothing was recorded.", reason: "" } } })} />);
    expect(getByText("Held for your confirmation")).toBeInTheDocument();
    expect(getByText("Nothing was recorded.")).toBeInTheDocument();
    expect(queryByText("Answered")).not.toBeInTheDocument();

    rerender(<Questions {...props} actions={settled("refused", "That question is no longer open.", "not_open")} />);
    expect(getByText("Not set aside")).toBeInTheDocument();
    expect(getByText("That question is no longer open.")).toBeInTheDocument();
    // The reason is written for a log. A person is shown the sentence.
    expect(queryByText(/not_open/)).not.toBeInTheDocument();

    rerender(<Questions {...props} actions={settled("waiting", "The document itself settles this one.")} />);
    expect(getByText("Nothing set aside yet")).toBeInTheDocument();

    rerender(<Questions {...props} actions={settled("stale", "This read has moved on.")} />);
    expect(getByText("Out of date")).toBeInTheDocument();
  });

  it("shows an inspectable proposal and sends explicit confirm or decline decisions", () => {
    const onConfirm = vi.fn();
    const proposal: QuestionActionState = { state: "settled", questionId: "live-question", verb: "answer",
      result: { state: "settled", outcome: { kind: "proposal", message: "Nothing was recorded.", reason: "",
        proposalId: "proposal-1", proposalSummary: "Open Sample Loan." } } };
    const { getByRole, getByText } = render(<Questions result={ready(data([question("live-question")]))}
      selectedQueue="live-question" onSelectQueue={noAction}
      actions={{ state: proposal, onAnswer: noAnswer, onConfirm, onDecline: noAction }} />);

    expect(getByText("Open Sample Loan.")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Confirm this proposal" }));
    fireEvent.click(getByRole("button", { name: "Decline this proposal" }));
    expect(onConfirm).toHaveBeenNthCalledWith(1, "live-question", "proposal-1", "yes", "Open Sample Loan.");
    expect(onConfirm).toHaveBeenNthCalledWith(2, "live-question", "proposal-1", "no", "Open Sample Loan.");
  });

  it("names each way a verb can fail to answer without calling any of them a refusal", () => {
    const live = question("live-question");
    const props = { result: ready(data([live])), selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const failed = (state: "unserved" | "unanswered" | "unreadable") =>
      acted({ state: "settled", questionId: "live-question", verb: "decline", result: { state } });

    // The sidecar read the request and would not take it. That is the one
    // failure this screen may title as a refusal, and it says so in its own
    // words rather than in the sidecar's, which name payload fields.
    // It is titled as the request not being taken and never as the question not
    // being set aside: the same code carries a handler that raised, and a
    // handler can raise after it has written.
    const { getByText, queryByText, rerender } = render(<Questions {...props} actions={failed("unserved")} />);
    expect(getByText("Your vault would not take this request")).toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();
    expect(getByText("Your vault refused the request as this screen sent it. Whether anything was recorded is not something this screen can tell you.")).toBeInTheDocument();

    rerender(<Questions {...props} actions={failed("unanswered")} />);
    expect(getByText("Your vault did not answer")).toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();

    // A handler that raised may have raised after writing, so nothing here may
    // say the vault is as it was.
    rerender(<Questions {...props} actions={failed("unreadable")} />);
    expect(getByText("The reply could not be read")).toBeInTheDocument();
    expect(queryByText(/was not changed/)).not.toBeInTheDocument();
    expect(queryByText("Not set aside")).not.toBeInTheDocument();
  });


  it("gives the empty state something focus can land on when a write empties the queue", () => {
    const { getByText } = render(<Questions result={ready(data([]))} selectedQueue="" onSelectQueue={noAction} actions={inert} />);

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
    const props = { result: ready(data([question("live-question")])), selectedQueue: "live-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const states: QuestionActionState[] = [
      { state: "idle" },
      { state: "working", questionId: "live-question", verb: "decline" },
      { state: "settled", questionId: "live-question", verb: "decline", result: { state: "settled", outcome: { kind: "refused", message: "That question is no longer open.", reason: "not_open" } } },
    ];
    const { container, getByRole, rerender } = render(<Questions {...props} actions={acted(states[0])} />);
    const pressed = getByRole("button", { name: "Set aside for now" });
    pressed.focus();

    for (const state of states) {
      rerender(<Questions {...props} actions={acted(state)} />);
      expect(container.querySelectorAll(".review-set-aside button[disabled]")).toHaveLength(0);
      for (const control of container.querySelectorAll(".review-set-aside button")) expect(control).not.toHaveAttribute("disabled");
    }

    // While the vault is answering, a second press does nothing and the control
    // says why to a screen reader rather than going silent.
    const declined = vi.fn();
    rerender(<Questions {...props} actions={{ state: states[1], onAnswer: noAnswer, onDecline: declined }} />);
    expect(pressed).toHaveAttribute("aria-disabled", "true");
    expect(pressed).toHaveAccessibleDescription("Your vault is answering the last request. Pressing again does nothing until it has.");
    fireEvent.click(pressed);
    expect(declined).not.toHaveBeenCalled();
  });

  it("says the queue could not be read again beside the write that took", () => {
    const props = { selectedQueue: "set-aside-question", onSelectQueue: noAction, onOpenEvidence: noAction };
    const settled = acted({ state: "settled", questionId: "set-aside-question", verb: "decline", result: { state: "settled", outcome: { kind: "set_aside", message: "Set aside until something changes.", reason: "" } } });
    const unread = "This screen could not read the queue afterwards, so it no longer knows what is still open.";

    const { getByRole, getByText, queryByText, rerender } = render(<Questions {...props} result={ready(data([question("next-question")]))} actions={settled} />);
    expect(queryByText(unread)).not.toBeInTheDocument();

    // A person told only that the write took would believe the list under it,
    // and after a failed re-read there is no list this screen can stand on.
    rerender(<Questions {...props} result={{ state: "failed", reason: "read_failed" }} actions={settled} />);
    expect(getByText("Question set aside")).toBeInTheDocument();
    expect(getByText(unread)).toBeInTheDocument();
    expect(getByRole("status")).toHaveTextContent(unread);

    // And what focus lands on when neither a question nor the empty state is
    // left on the screen.
    expect(getByText("Question set aside")).toHaveAttribute("id", "review-outcome-title");
    expect(getByText("Question set aside")).toHaveAttribute("tabindex", "-1");
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
    const { queryByRole } = render(<Questions {...props} result={answerable([])} actions={inert} />);
    expect(queryByRole("button", { name: "Send this answer" })).not.toBeInTheDocument();
  });

  it("says what each slot needs back in the queue's own words", () => {
    const { getByText } = render(<Questions {...props} result={answerable([slot])} actions={inert} />);
    expect(getByText(moments.wants_yes_no)).toBeInTheDocument();
  });

  it("shows the closed vocabulary an answer has to land in", () => {
    const { getByText } = render(<Questions {...props} result={answerable([choiceSlot])} actions={inert} />);
    expect(getByText(moments.wants_choice.replace("{alternatives}", "food, rent"))).toBeInTheDocument();
  });

  it("invites a person in the read's own sentence rather than one of its own", () => {
    const { getByLabelText } = render(<Questions {...props} result={answerable([slot])} actions={inert} />);
    expect(getByLabelText("Say it however you like.")).toBeInTheDocument();
  });

  it("sends the question and the sentence, and nothing else", () => {
    const sent: Array<[string, string]> = [];
    const actions = { state: { state: "idle" } as const, onAnswer: (id: string, said: string) => { sent.push([id, said]); }, onDecline: noAction };
    const { getByLabelText, getByRole } = render(<Questions {...props} result={answerable([slot])} actions={actions} />);
    fireEvent.change(getByLabelText("Say it however you like."), { target: { value: "  yes, that is the same account  " } });
    fireEvent.click(getByRole("button", { name: "Send this answer" }));
    expect(sent).toEqual([["q-1", "yes, that is the same account"]]);
  });

  it("sends nothing at all for an empty sentence", () => {
    const sent: string[] = [];
    const actions = { state: { state: "idle" } as const, onAnswer: (id: string) => { sent.push(id); }, onDecline: noAction };
    const { getByRole } = render(<Questions {...props} result={answerable([slot])} actions={actions} />);
    fireEvent.click(getByRole("button", { name: "Send this answer" }));
    expect(sent).toEqual([]);
  });

  it("keeps the control in the tab order while the vault is answering", () => {
    const actions = { state: { state: "working", questionId: "q-1", verb: "answer" } as const, onAnswer: noAnswer, onDecline: noAction };
    const { getByRole } = render(<Questions {...props} result={answerable([slot])} actions={actions} />);
    expect(getByRole("button", { name: "Send this answer" })).toHaveAttribute("aria-disabled", "true");
  });

  it("keeps an answer draft until its own authoritative completed reread", () => {
    const onAnswer = vi.fn();
    const idle = { state: { state: "idle" } as const, onAnswer, onDecline: noAction };
    const working = { ...idle, state: { state: "working", questionId: "q-1", verb: "answer" } as const };
    const refused = { ...idle, state: { state: "settled", questionId: "q-1", verb: "answer", authoritative: false,
      result: { state: "settled", outcome: { kind: "refused", message: "Not recorded.", reason: "not_open" } } } as const };
    const unreadable = { ...idle, state: { state: "settled", questionId: "q-1", verb: "answer", authoritative: false,
      result: { state: "unreadable" } } as const };
    const completedWithoutReread = { ...idle, state: { state: "settled", questionId: "q-1", verb: "answer", authoritative: false,
      result: { state: "settled", outcome: { kind: "completed", message: "Recorded.", reason: "" } } } as const };
    const completed = { ...idle, state: { state: "settled", questionId: "q-1", verb: "answer", authoritative: true,
      result: { state: "settled", outcome: { kind: "completed", message: "Recorded.", reason: "" } } } as const };
    const view = render(<Questions {...props} result={answerable([slot])} actions={idle} />);
    const box = () => view.getByLabelText("Say it however you like.");

    fireEvent.change(box(), { target: { value: "same account" } });
    fireEvent.click(view.getByRole("button", { name: "Send this answer" }));
    expect(box()).toHaveValue("same account");
    view.rerender(<Questions {...props} result={answerable([slot])} actions={working} />);
    expect(box()).toHaveValue("same account");
    view.rerender(<Questions {...props} result={answerable([slot])} actions={refused} />);
    expect(box()).toHaveValue("same account");
    view.rerender(<Questions {...props} result={answerable([slot])} actions={unreadable} />);
    expect(box()).toHaveValue("same account");
    view.rerender(<Questions {...props} result={answerable([slot])} actions={completedWithoutReread} />);
    expect(box()).toHaveValue("same account");

    // A late completion for the submitted words may not erase words typed since.
    fireEvent.change(box(), { target: { value: "new answer" } });
    view.rerender(<Questions {...props} result={answerable([slot])} actions={completed} />);
    expect(box()).toHaveValue("new answer");

    view.rerender(<Questions {...props} result={answerable([slot])} actions={idle} />);
    fireEvent.click(view.getByRole("button", { name: "Send this answer" }));
    view.rerender(<Questions {...props} result={answerable([slot])} actions={working} />);
    view.rerender(<Questions {...props} result={answerable([slot])} actions={completed} />);
    expect(box()).toHaveValue("");
  });
});
