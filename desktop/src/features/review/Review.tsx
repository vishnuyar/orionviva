import { useState, type FormEvent } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import type { DeclineReason, EvidenceLink, FeatureResult, ReviewActionState, ReviewData, ReviewView } from "../../surface/types";
import { outcomePresentation, resolveReviewSelection, workingPresentation } from "./reviewPresentation";

// What a screen needs to use the review verb this build serves. Every source a
// screen can be given carries the verb, so there is no state in which the
// controls are absent.
export type ReviewActionControls = { state: ReviewActionState; onAnswer: (questionId: string, said: string) => void; onConfirm?: (questionId: string, proposalId: string, said: string, asked: string) => void; onDecline: (questionId: string, reason: DeclineReason) => void };
type ReviewProps = { result: FeatureResult<ReviewData>; selectedQueue: string; onSelectQueue: (id: string) => void; actions: ReviewActionControls };

// Whether this read can say what is still open. Only the read's own states
// carry a queue; in any other state the screen has no list to stand on, and
// says so beside what it last did to the vault.
function queueUnread(result: FeatureResult<ReviewData>): boolean {
  return result.state !== "ready" && result.state !== "partial" && result.state !== "needs_input";
}

function ReviewHeader({ total }: { total: number }) {
  return <><header className="review-surface-header"><div className="detail-panel-label">Current review read</div><h2>Review queue</h2><p>This read shows the questions that are open. You can answer one in your own words, or set it aside until something about it changes.</p></header><section className="review-summary" aria-labelledby="review-summary-title"><h3 id="review-summary-title">Open-question total from this read</h3><strong>{total}</strong><p>This total is shown as supplied. The interface does not count or rank questions.</p></section></>;
}

function ReviewQueue({ queue, selectedId, onSelectQueue }: { queue: readonly ReviewView[]; selectedId: string; onSelectQueue: (id: string) => void }) {
  return <section className="review-queue" aria-labelledby="review-queue-title"><h3 id="review-queue-title">Questions in this read</h3><p>Questions are shown in the order returned by the review read. The interface does not calculate priority.</p><ul>{queue.map((question, occurrence) => {
    const identityCount = question.id.trim() ? queue.filter((candidate) => candidate.id === question.id).length : 0;
    const selectable = Boolean(question.id.trim()) && identityCount === 1;
    return <li key={`${question.id || "blank-question"}-${occurrence}`}>{selectable ? <button className={selectedId === question.id ? "review-question-row active" : "review-question-row"} aria-pressed={selectedId === question.id} onClick={() => onSelectQueue(question.id)}><span><strong>{question.label || "Question text was not supplied by this read."}</strong><small>{question.id}</small></span><span className="review-question-action">View question</span></button> : <div className="review-question-row review-question-unavailable"><span><strong>{question.id.trim() ? "Question identity conflicted" : "Question identity unavailable"}</strong><small>{question.id.trim() ? "More than one row uses this question ID. No row with this identity can be selected." : "This row has no stable question ID, so it cannot be selected."}</small></span></div>}</li>;
  })}</ul></section>;
}

// What became of the last verb a person used. It sits outside the review
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
function ActionOutcomeNotice({ state, unread, actions }: { state: ReviewActionState; unread: boolean; actions: ReviewActionControls }) {
  const notice = state.state === "idle" ? null
    : state.state === "working" ? workingPresentation(state.verb)
      : outcomePresentation(state.verb, state.result);
  const unreadable = notice && state.state === "settled" && unread ? "This screen could not read the queue afterwards, so it no longer knows what is still open." : "";
  const proposal = state.state === "settled" && state.result.state === "settled" && state.result.outcome.kind === "proposal" ? state.result.outcome : null;
  const deciding = actions.state.state === "working";
  const decide = (said: "yes" | "no") => {
    if (!proposal?.proposalId || deciding || state.state !== "settled") return;
    actions.onConfirm?.(state.questionId, proposal.proposalId, said, proposal.proposalSummary || proposal.message);
  };
  return <><div className="visually-hidden" role="status" aria-live="polite">{notice ? `${notice.title}. ${notice.detail}${unreadable ? ` ${unreadable}` : ""}` : ""}</div>{notice ? <div className="review-outcome"><strong id="review-outcome-title" tabIndex={-1}>{notice.title}</strong><p>{notice.detail}</p>{proposal?.proposalId && actions.onConfirm ? <div className="review-set-aside-controls"><button className="primary-button" type="button" aria-disabled={deciding} onClick={() => decide("yes")}>Confirm this proposal</button><button className="secondary-button" type="button" aria-disabled={deciding} onClick={() => decide("no")}>Decline this proposal</button></div> : null}{unreadable ? <p>{unreadable}</p> : null}</div> : null}</>;
}

// The control a person pressed stays focusable for as long as the vault is
// answering: a focused element that becomes `disabled` is blurred to the
// document body. A second press is refused in the handler and said in words
// through `aria-disabled` instead.
function SetAsideControls({ question, actions }: { question: ReviewView; actions: ReviewActionControls }) {
  const working = actions.state.state === "working";
  const setAside = (reason: DeclineReason) => { if (!working) actions.onDecline(question.id, reason); };
  return <section className="review-set-aside" aria-labelledby="review-set-aside-title">
    <h4 id="review-set-aside-title">Set this question aside</h4>
    <p>Setting a question aside does not delete it. It comes back on its own when the amount behind it, or the number of movements it covers, changes.</p>
    <p>Setting a question aside, answering in your own words, and confirming or declining a resulting proposal are connected. Correcting a document is not.</p>
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
function AnswerControls({ question, invite, actions }: { question: ReviewView; invite: string; actions: ReviewActionControls }) {
  const [said, setSaid] = useState("");
  const working = actions.state.state === "working";
  const slots = question.slots ?? [];
  function answer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || !said.trim()) return;
    actions.onAnswer(question.id, said.trim());
    setSaid("");
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
      <textarea id="review-answer-said" value={said} onChange={(event) => setSaid(event.target.value)} rows={3} />
      <button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? "review-answer-waiting" : undefined}>Send this answer</button>
    </form>
    {working ? <span className="action-explanation" id="review-answer-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
  </section>;
}

function QuestionDetail({ question, actions, invite }: { question: ReviewView; actions: ReviewActionControls; invite: string }) {
  return <><div className="review-detail-grid"><div><span>Question ID</span><strong>{question.id}</strong><small>A question ID is the stable identity used for selection. It is not a queue position or document ID.</small></div><div><span>Question text</span><strong>{question.label || "Question text was not supplied by this read."}</strong></div><div><span>Why this question was asked</span><strong>{question.detail || "Why this question was asked was not supplied by this read."}</strong></div><div><span>Question kind</span><strong>{question.type || "Question kind was not supplied by this read."}</strong></div><div><span>Question scope</span><strong>{question.scope || "Question scope was not supplied by this read."}</strong></div><div><span>Question count</span><strong>{question.count === undefined ? "Question count was not supplied by this read." : question.count}</strong></div><div><span>Question amount</span><strong>{question.amount || "Question amount was not supplied by this read."}</strong></div><div><span>Question currency</span><strong>{question.currency || "Question currency was not supplied by this read."}</strong></div></div><p className="review-value-helper">These values are shown as supplied. The interface does not calculate consequence or change question order.</p><div className="review-live-omissions"><p>A separate consequence description was not supplied by this read.</p><p>Proposal state was not supplied by this read.</p></div><section className="review-source-state"><h4>Source document unavailable</h4><p>A source document target was not supplied for this question.</p></section><AnswerControls question={question} invite={invite} actions={actions} /><SetAsideControls question={question} actions={actions} /></>;
}

function SelectionState({ state }: { state: ReturnType<typeof resolveReviewSelection> }) {
  if (state.state === "missing") return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Selected question unavailable</h3><div className="empty-state"><span>The selected question is no longer present in the current review read.</span><span>Requested question ID: {state.requestedId}</span></div></aside>;
  if (state.state === "conflicted_identity") return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Question selection unavailable</h3><div className="empty-state"><span>More than one question in this read uses the selected identity, so the interface will not choose between them.</span><span>Requested question ID: {state.requestedId}</span></div></aside>;
  return <aside className="review-selected" aria-labelledby="selected-question-title"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>Question selection unavailable</h3><div className="empty-state"><span>The current review read contains rows, but none has a unique nonblank question ID. No question was selected.</span></div></aside>;
}

function MoreFromRead({ data }: { data: ReviewData }) {
  const pending = data.meta.pending;
  const pendingCopy = pending === null ? "Set-aside summary was not supplied by this read." : pending.count === 0 ? "Set-aside items reported: 0." : pending.count === 1 ? "1 set-aside item is reported. It returns on its own when what it is about changes. Opening its detail is not available in this preview." : `${pending.count} set-aside items are reported. Each returns on its own when what it is about changes. Opening their detail is not available in this preview.`;
  // The invitation the read supplies is shown where a person writes, beside
  // the box it invites them into, rather than here.
  return <section className="review-more" aria-labelledby="review-more-title"><h3 id="review-more-title">More from this read</h3><p>These summaries are shown separately. The interface does not add them together or create question rows from them.</p><div className="review-more-grid">{data.meta.tail === null ? <div><span>Open questions outside this list</span><strong>Tail summary was not supplied by this read.</strong><small>No question rows are created from this summary.</small></div> : <><div><span>Open questions outside this list</span><strong>{data.meta.tail.count}</strong><small>No question rows are created from this summary.</small></div><div><span>Tail amount supplied</span><strong>{data.meta.tail.amount || "Tail amount was not supplied by this read."}</strong></div></>}<div><span>Set-aside summary</span><strong>{pendingCopy}</strong></div></div><div className="review-guidance"><div><h4>Document-answer guidance</h4><p>{data.meta.answeredByDocument || "Document-answer guidance was not supplied by this read."}</p></div></div><p>The contract supplies no mapping from this guidance to a specific question. This preview cannot accept an answer or document.</p></section>;
}

export function Review({ result, selectedQueue, onSelectQueue, actions }: ReviewProps) {
  return <div className="review-screen"><PanelStateView result={result} copy={{ partial: "Some review details are unavailable. Available questions are shown below.", needsInput: "Some review questions need your input. Available questions are shown below.", unavailable: { title: "Review unavailable", detail: "Review details are not available in this build." }, failed: { title: "Review could not be read", detail: "The review section could not be read. The private vault is still open." } }}>{(data) => {
    const selection = resolveReviewSelection(data.queue, selectedQueue);
    const activeId = selection.state === "ready" ? selection.question.id : selectedQueue;
    const pending = data.meta.pending;
    const pendingAddendum = pending === null || pending.count === 0 ? "" : pending.count === 1 ? " 1 set-aside item remains. Opening it is not available in this preview." : ` ${pending.count} set-aside items remain. Opening them is not available in this preview.`;
    return <section className="feature-panel review-inspection"><ReviewHeader total={data.meta.total} />{!data.queue.length ? <div className="empty-state"><strong id="review-empty-title" tabIndex={-1}>Nothing needs you right now</strong><span>{`There are no open questions in the current review read.${pendingAddendum}`}</span></div> : <div className="review-inspection-layout"><ReviewQueue queue={data.queue} selectedId={activeId} onSelectQueue={onSelectQueue} />{selection.state === "ready" ? <aside className="review-selected"><div className="detail-panel-label">Selected question</div><h3 id="selected-question-title" tabIndex={-1}>{selection.question.label || "Question text was not supplied by this read."}</h3><QuestionDetail question={selection.question} actions={actions} invite={data.meta.invite} /></aside> : <SelectionState state={selection} />}</div>}<MoreFromRead data={data} /></section>;
  }}</PanelStateView><ActionOutcomeNotice state={actions.state} unread={queueUnread(result)} actions={actions} /></div>;
}
