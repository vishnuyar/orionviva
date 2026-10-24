import { useEffect, useState, type FormEvent } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import type { DeclineReason, FeatureResult, QuestionActionState, QuestionQueueData, QuestionView } from "../../surface/types";
import { outcomePresentation, resolveReviewSelection, workingPresentation } from "./questionPresentation";

// What a screen needs to use the question verb this build serves. Every source a
// screen can be given carries the verb, so there is no state in which the
// controls are absent.
export type ReviewActionControls = { state: QuestionActionState; onAnswer: (questionId: string, said: string) => void; onConfirm?: (questionId: string, proposalId: string, said: string, asked: string) => void; onDecline: (questionId: string, reason: DeclineReason) => void };
type QuestionsProps = { result: FeatureResult<QuestionQueueData>; selectedQueue: string; onSelectQueue: (id: string) => void; actions: ReviewActionControls };

// Whether this read can say what is still open. Only the read's own states
// carry a queue; in any other state the screen has no list to stand on, and
// says so beside what it last did to the vault.
function queueUnread(result: FeatureResult<QuestionQueueData>): boolean {
  return result.state !== "ready" && result.state !== "partial" && result.state !== "needs_input";
}

function ReviewHeader({ total }: { total: number }) {
  return <><header className="review-surface-header"><div className="detail-panel-label">Your input</div><h2>Questions for you</h2><p>These questions are part of this conversation. You can answer one in your own words, or set it aside until something about it changes.</p></header><section className="review-summary" aria-labelledby="review-summary-title"><h3 id="review-summary-title">Open questions</h3><strong>{total}</strong></section></>;
}

function ReviewQueue({ queue, selectedId, onSelectQueue }: { queue: readonly QuestionView[]; selectedId: string; onSelectQueue: (id: string) => void }) {
  return <section className="review-queue" aria-labelledby="review-queue-title"><h3 id="review-queue-title">Questions</h3><ul>{queue.map((question, occurrence) => {
    const identityCount = question.id.trim() ? queue.filter((candidate) => candidate.id === question.id).length : 0;
    const selectable = Boolean(question.id.trim()) && identityCount === 1;
    return <li key={`${question.id || "blank-question"}-${occurrence}`}>{selectable ? <button className={selectedId === question.id ? "review-question-row active" : "review-question-row"} aria-pressed={selectedId === question.id} onClick={() => onSelectQueue(question.id)}><span><strong>{question.label || "Question text unavailable."}</strong></span><span className="review-question-action">View question</span></button> : <div className="review-question-row review-question-unavailable"><span><strong>Question unavailable</strong><small>{question.id.trim() ? "More than one open question has the same identity, so none is selected automatically." : "This question has no stable identity, so it cannot be selected."}</small></span></div>}</li>;
  })}</ul></section>;
}

// What became of the last verb a person used. It sits outside the question
// read's state gate, so a write that succeeded and a re-read that then failed
// still says the write happened, and says in the same notice that the queue
// under it could not be read again.
//
// The region announcing it is mounted for the life of the screen and only its
// text changes, because a live region that arrives with its words is one
// several screen readers never announce. It is offscreen rather than laid out,
// so the panel beside it is an ordinary conditional child of the grid.
//
// The visible notice is the last child of the screen and takes a band of the
// layout for itself. It is never lifted out of the flow to hold the bottom of
// the viewport, where it would paint and take clicks over whatever the person
// has scrolled under it.
function ActionOutcomeNotice({ state, unread, actions }: { state: QuestionActionState; unread: boolean; actions: ReviewActionControls }) {
  const notice = state.state === "idle" ? null
    : state.state === "working" ? workingPresentation(state.verb)
      : outcomePresentation(state.verb, state.result);
  const unconfirmedQueue = state.state === "settled" && state.authoritative === false
    && state.result.state === "settled"
    && (state.result.outcome.kind === "completed" || state.result.outcome.kind === "set_aside");
  const unreadable = notice && state.state === "settled" && (unread || unconfirmedQueue) ? "This screen could not read the queue afterwards, so it no longer knows what is still open." : "";
  const proposal = state.state === "settled" && state.result.state === "settled" && state.result.outcome.kind === "proposal" ? state.result.outcome : null;
  const deciding = actions.state.state === "working";
  const decide = (said: "yes" | "no") => {
    if (!proposal?.proposalId || deciding || state.state !== "settled") return;
    actions.onConfirm?.(state.questionId, proposal.proposalId, said, proposal.proposalSummary || proposal.message);
  };
  return <><div className="visually-hidden" role="status" aria-live="polite">{notice ? `${notice.title}. ${notice.detail}${unreadable ? ` ${unreadable}` : ""}` : ""}</div>{notice ? <div className="review-outcome"><strong id="review-outcome-title" tabIndex={-1}>{notice.title}</strong><p>{notice.detail}</p>{proposal?.proposalId && actions.onConfirm ? <><div className="review-set-aside-controls"><button className="primary-button" type="button" aria-disabled={deciding} aria-describedby={deciding ? "review-proposal-waiting" : undefined} onClick={() => decide("yes")}>Confirm this proposal</button><button className="secondary-button" type="button" aria-disabled={deciding} aria-describedby={deciding ? "review-proposal-waiting" : undefined} onClick={() => decide("no")}>Decline this proposal</button></div>{deciding ? <span className="action-explanation" id="review-proposal-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}</> : null}{unreadable ? <p>{unreadable}</p> : null}</div> : null}</>;
}

// The control a person pressed stays focusable for as long as the vault is
// answering: a focused element that becomes `disabled` is blurred to the
// document body. A second press is refused in the handler and said in words
// through `aria-disabled` instead.
function SetAsideControls({ question, actions }: { question: QuestionView; actions: ReviewActionControls }) {
  const working = actions.state.state === "working";
  const setAside = (reason: DeclineReason) => { if (!working) actions.onDecline(question.id, reason); };
  return <section className="review-set-aside" aria-labelledby="review-set-aside-title">
    <h4 id="review-set-aside-title">Set this question aside</h4>
    <p>Setting a question aside does not delete it. It comes back on its own when the amount behind it, or the number of movements it covers, changes.</p>
    <div className="review-set-aside-controls">
      <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "review-set-aside-waiting" : undefined} onClick={() => setAside("not_now")}>Set aside for now</button>
      <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "review-set-aside-waiting" : undefined} onClick={() => setAside("dont_know")}>Set aside: I do not know</button>
    </div>
    {working ? <span className="action-explanation" id="review-set-aside-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
  </section>;
}

// Answering, in a person's own words. What each slot needs back and the closed
// vocabulary an answer must land in are the queue's — this renders them and
// writes neither. Nothing but the sentence crosses: the structure behind it is
// read on the other side of the bridge, where the check that stands between a
// model's structure and the ledger lives.
//
// `invite` is what the box says before anything is written, and it is the
// read's too. A screen inventing that line would be inviting a person into a
// contract it made up.
function AnswerControls({ question, invite, actions }: { question: QuestionView; invite: string; actions: ReviewActionControls }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<{ questionId: string; said: string; observedWorking: boolean } | null>(null);
  const said = drafts[question.id] ?? "";
  const working = actions.state.state === "working";
  const slots = question.slots ?? [];
  useEffect(() => {
    if (submitted && !submitted.observedWorking && actions.state.state === "working" && actions.state.questionId === submitted.questionId) {
      setSubmitted({ ...submitted, observedWorking: true });
      return;
    }
    const settled = actions.state.state === "settled" ? actions.state : null;
    if (settled?.authoritative === true && settled.result.state === "settled" && settled.result.outcome.kind === "completed"
        && submitted?.observedWorking && submitted.questionId === settled.questionId && drafts[settled.questionId] === submitted.said) {
      setDrafts((current) => ({ ...current, [settled.questionId]: "" }));
      setSubmitted(null);
    }
  }, [actions.state, drafts, submitted]);
  function answer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || !said.trim()) return;
    const exact = said.trim();
    setSubmitted({ questionId: question.id, said: exact, observedWorking: false });
    actions.onAnswer(question.id, exact);
  }
  // A question with no slots is one nothing said in words settles — a document
  // does. The form is absent rather than present and refusing, and the read's
  // own sentence about that stands in its place elsewhere on the screen.
  if (!slots.length) return null;
  return <section className="review-answer" aria-labelledby="review-answer-title">
    <h4 id="review-answer-title">Answer this</h4>
    <ul className="review-answer-wants">{slots.map((slot) => <li key={slot.name}>{slot.wants}</li>)}</ul>
    <form onSubmit={answer}>
      <label htmlFor="review-answer-said">{invite || "Write your answer here."}</label>
      <textarea id="review-answer-said" value={said} onChange={(event) => setDrafts((current) => ({ ...current, [question.id]: event.target.value }))} rows={3} />
      <button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? "review-answer-waiting" : undefined}>Send this answer</button>
    </form>
    {working ? <span className="action-explanation" id="review-answer-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
  </section>;
}

function QuestionDetail({ question, actions, invite }: { question: QuestionView; actions: ReviewActionControls; invite: string }) {
  const hasAmount = Boolean(question.amount || question.currency);
  return <><div className="review-detail-grid"><div><span>Why it matters</span><strong>{question.detail || "The reason for this question is unavailable."}</strong></div>{hasAmount ? <><div><span>Amount</span><strong>{question.amount || "Amount unavailable"}</strong></div><div><span>Currency</span><strong>{question.currency || "Currency unavailable"}</strong></div></> : null}</div>
    <section className="review-source-state"><h4>Check the source</h4><p>Open Statements for document details; source documents cannot be opened from this question.</p>{question.evidence ? <p>{question.evidence}</p> : null}</section>
    <AnswerControls question={question} invite={invite} actions={actions} /><SetAsideControls question={question} actions={actions} />
    <details className="review-more"><summary>Question details</summary><div className="review-detail-grid"><div><span>Type</span><strong>{question.type || "Type unavailable"}</strong></div><div><span>Scope</span><strong>{question.scope || "Scope unavailable"}</strong></div><div><span>Related items</span><strong>{question.count === undefined ? "Count unavailable" : question.count}</strong></div>{!hasAmount ? <div><span>Amount and currency</span><strong>Not available for this question</strong></div> : null}</div><p>Questions keep their recorded order. A separate consequence description is unavailable; proposals appear after you answer when confirmation is needed.</p></details>
  </>;
}

function SelectionState({ state }: { state: ReturnType<typeof resolveReviewSelection> }) {
  if (state.state === "missing") return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Selected question unavailable</h3><div className="empty-state"><span>The selected question is no longer present in the current conversation.</span></div></aside>;
  if (state.state === "conflicted_identity") return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Question selection unavailable</h3><div className="empty-state"><span>More than one question in this conversation has the same identity, so the interface will not choose between them.</span></div></aside>;
  return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Question selection unavailable</h3><div className="empty-state"><span>The current conversation contains questions, but none has a unique stable identity. No question was selected.</span></div></aside>;
}

function MoreFromRead({ data }: { data: QuestionQueueData }) {
  const pending = data.meta.pending;
  const pendingCopy = pending === null ? "Set-aside summary unavailable." : pending.count === 0 ? "No set-aside questions reported." : `${pending.count} set-aside ${pending.count === 1 ? "question" : "questions"}. These return when what they concern changes; their details cannot be opened here.`;
  return <details className="review-more"><summary>More about your questions</summary><p>These summaries cover questions outside the list above.</p><div className="review-more-grid"><div><span>Other open questions</span><strong>{data.meta.tail === null ? "Summary unavailable" : data.meta.tail.count}</strong></div>{data.meta.tail ? <div><span>Amount for other questions</span><strong>{data.meta.tail.amount || "Amount unavailable"}</strong></div> : null}<div><span>Set-aside questions</span><strong>{pendingCopy}</strong></div></div><div className="review-guidance"><div><h4>When a document answers the question</h4><p>{data.meta.answeredByDocument || "Document guidance unavailable."}</p></div></div><p>This guidance applies generally. Add a statement from Statements when a document is the answer.</p></details>;
}

export function Questions({ result, selectedQueue, onSelectQueue, actions }: QuestionsProps) {
  return <div className="review-screen"><PanelStateView result={result} copy={{ partial: "Some conversation details are unavailable. Available questions are shown below.", needsInput: "Some questions need your input. Available questions are shown below.", unavailable: { title: "Questions unavailable", detail: "Questions are not available in this build." }, failed: { title: "Questions could not be loaded", detail: "Your questions could not be loaded. Your vault is still open." } }}>{(data) => {
    const selection = resolveReviewSelection(data.queue, selectedQueue);
    const activeId = selection.state === "ready" ? selection.question.id : selectedQueue;
    const pending = data.meta.pending;
    const pendingAddendum = pending === null || pending.count === 0 ? "" : pending.count === 1 ? " 1 set-aside item remains. Opening it is not available in this preview." : ` ${pending.count} set-aside items remain. Opening them is not available in this preview.`;
    return <section className="feature-panel review-inspection"><ReviewHeader total={data.meta.total} />{!data.queue.length ? <div className="empty-state"><strong id="review-empty-title" tabIndex={-1}>Nothing needs you right now</strong><span>{`There are no open questions in the current conversation.${pendingAddendum}`}</span></div> : <div className="review-inspection-layout"><ReviewQueue queue={data.queue} selectedId={activeId} onSelectQueue={onSelectQueue} />{selection.state === "ready" ? <aside className="review-selected"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>{selection.question.label || "Question text unavailable."}</h3><QuestionDetail question={selection.question} actions={actions} invite={data.meta.invite} /></aside> : <SelectionState state={selection} />}</div>}<MoreFromRead data={data} /></section>;
  }}</PanelStateView><ActionOutcomeNotice state={actions.state} unread={queueUnread(result)} actions={actions} /></div>;
}
