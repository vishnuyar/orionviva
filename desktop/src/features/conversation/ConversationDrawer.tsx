import { useState, type FormEvent } from "react";
import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import { conversationEvidenceFigure } from "../../surface/evidence";
import { Questions } from "./Questions";
import { outcomePresentation } from "./questionPresentation";
import type { ActionOutcome, AskActionState, ConversationData, ConversationGoalDraft, ConversationTurn, DeclineReason, FeatureResult, QuestionActionState, TurnView } from "../../surface/types";

export type AskControls = { state: AskActionState; onAsk: (question: string, mirrored: boolean, planRequest?: boolean) => void };
export type ConversationControls = {
  state: QuestionActionState;
  onAnswer: (questionId: string, said: string) => void;
  onConfirm: (questionId: string, proposalId: string, said: string, asked: string) => void;
  onDecline: (questionId: string, reason: DeclineReason) => void;
};

function AskBox({ ask }: { ask: AskControls }) {
  const [question, setQuestion] = useState("");
  const working = ask.state.state === "working";
  const settled = ask.state.state === "settled" ? ask.state : null;
  const channel = settled && settled.result.state !== "settled" ? channelPresentation(settled.result) : null;
  const said = channel ? `${channel.title}. ${channel.detail}` : settled && !settled.turn && settled.result.state === "settled" ? settled.result.outcome.message.trim() || UNSPOKEN_REPLY : "";
  function send(planRequest = false) {
    if (working || !question.trim()) return;
    ask.onAsk(question.trim(), true, planRequest);
    setQuestion("");
  }
  return <section className="conversation-ask" aria-labelledby="conversation-ask-title">
    <h3 id="conversation-ask-title">Ask about your money</h3>
    <form onSubmit={(event) => { event.preventDefault(); send(); }}>
      <label htmlFor="conversation-ask-question">Your question</label>
      <textarea id="conversation-ask-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} />
      <button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined}>Ask</button>
      <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined} onClick={() => send(true)}>Draft a save-up plan</button>
    </form>
    {working ? <span className="action-explanation" id="conversation-ask-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{said}</div>
    {said ? <p className="conversation-answer-text">{said}</p> : null}
  </section>;
}

function ProposalReply({ turn, controls }: { turn: ConversationTurn; controls: ConversationControls }) {
  const [said, setSaid] = useState("");
  const proposal = turn.proposal;
  if (!proposal || proposal.status !== "open") return null;
  const openProposal = proposal;
  const working = controls.state.state === "working";
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!said.trim() || working) return;
    controls.onConfirm(turn.questionId, openProposal.id, said.trim(), openProposal.summary || turn.prompt);
    setSaid("");
  }
  return <form className="conversation-proposal" onSubmit={submit}>
    <strong>{openProposal.summary}</strong>
    <label htmlFor={`proposal-${openProposal.id}`}>Confirm or decline in your own words</label>
    <div className="review-reply-row"><input id={`proposal-${openProposal.id}`} value={said} onChange={(event) => setSaid(event.target.value)} /><button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? `proposal-${openProposal.id}-waiting` : undefined}>Reply</button></div>
    {working ? <span className="action-explanation" id={`proposal-${openProposal.id}-waiting`}>Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
  </form>;
}

const outcomeLabels: Record<ActionOutcome, string> = {
  completed: "Completed",
  refused: "Not completed",
  proposal: "Awaiting confirmation",
  waiting: "Waiting",
  stale: "Out of date",
  set_aside: "Set aside",
};

function AnswerDetail({ answer, onOpenFigure, onReviewPlan }: { answer: TurnView; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void }) {
  return <div className="conversation-answer">
    <p className="conversation-answer-text">{answer.text || answer.refusal}</p>
    {answer.gradeSentence ? <p className="conversation-answer-grade">{answer.gradeSentence}</p> : null}
    {answer.figures.length ? <dl className="conversation-answer-figures">{answer.figures.map((figure) => <div key={figure.id}>
      <dt>{figure.evidenceId && figure.evidenceLinks.length ? <Figure figure={conversationEvidenceFigure(figure)} onOpenEvidence={onOpenFigure} className="conversation-figure-trigger" /> : figure.written || figure.what}</dt>
      <dd>{figure.what}{figure.recordIds.length ? ` · ${figure.recordIds.length === 1 ? "1 cited record" : `${figure.recordIds.length} cited records`}` : ""}</dd>
    </div>)}</dl> : null}
    {answer.options.length ? <ul className="conversation-answer-options">{answer.options.map((option) => <li key={option.id}>{option.label}</li>)}</ul> : null}
    {answer.missing.length ? <ul className="conversation-answer-missing">{answer.missing.map((item, index) => <li key={`${item.tag}:${item.label}:${index}`}>{item.question || item.label || item.tag}</li>)}</ul> : null}
    {answer.spoken.withheld ? <p className="conversation-answer-withheld">{answer.spoken.withheld}</p> : null}
    {answer.spoken.citationSentence ? <p className="conversation-answer-citation">{answer.spoken.citationSentence}</p> : null}
    {answer.goalDraft?.reviewInPlans && onReviewPlan ? <button className="secondary-button" type="button" onClick={() => onReviewPlan(answer.goalDraft!)}>Review in Plans</button> : null}
  </div>;
}

function Timeline({ data, controls, onOpenFigure, onReviewPlan }: { data: ConversationData; controls: ConversationControls; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void }) {
  if (!data.turns.length) return <section className="conversation-thread"><div className="empty-state"><strong>No conversation yet</strong><span>Ask Viva, or answer one of the questions below. New turns will remain with this vault.</span></div></section>;
  return <section className="conversation-thread" aria-labelledby="conversation-turns-title">
    <h3 id="conversation-turns-title">Conversation</h3>
    <ol>{data.turns.map((turn) => <li className={`conversation-turn ${turn.outcome}`} key={turn.id}>
      <div className="conversation-turn-meta"><strong>{turn.kind === "ask" ? "You asked" : turn.kind === "answer" ? "You answered" : turn.kind === "decline" ? "You set aside" : "You confirmed"}</strong><span>{outcomeLabels[turn.outcome]}</span>{turn.occurredAt ? <time dateTime={turn.occurredAt}>{turn.occurredAt}</time> : null}</div>
      <p>{turn.prompt}</p>
      {turn.said ? <blockquote>{turn.said}</blockquote> : null}
      {turn.answer ? <AnswerDetail answer={turn.answer} onOpenFigure={onOpenFigure} onReviewPlan={onReviewPlan} /> : turn.message ? <p className="conversation-answer-text">{turn.message}</p> : null}
      {turn.proposal && turn.proposal.status !== "open" && turn.proposal.message ? <p>{turn.proposal.message}</p> : null}
      <ProposalReply turn={turn} controls={controls} />
    </li>)}</ol>
  </section>;
}

export function ConversationDrawer({ result, selectedQueue, onSelectQueue, onOpenFigure, onReviewPlan, ask, controls }: { result: FeatureResult<ConversationData>; selectedQueue: string; onSelectQueue: (id: string) => void; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void; ask: AskControls | null; controls: ConversationControls }) {
  const actionSaid = controls.state.state === "settled" ? outcomePresentation(controls.state.verb, controls.state.result) : null;
  const conversationReadable = result.state === "ready" || result.state === "partial" || result.state === "needs_input";
  return <>
    {ask ? <AskBox ask={ask} /> : null}
    <PanelStateView result={result} copy={{ partial: "Some conversation details are unavailable.", needsInput: "This conversation needs input.", unavailable: { title: "Conversation unavailable", detail: "This build cannot read the conversation for this vault." }, failed: { title: "Conversation could not be read", detail: "The durable conversation read did not complete." } }}>
      {(data) => {
        const proposalIsRestored = data.turns.some((turn) => turn.proposal?.status === "open");
        const questionControls = proposalIsRestored ? { ...controls, onConfirm: undefined } : controls;
        return <div className="conversation-body"><Timeline data={data} controls={controls} onOpenFigure={onOpenFigure} onReviewPlan={onReviewPlan} /><Questions result={{ state: "ready", data: data.questions }} selectedQueue={selectedQueue} onSelectQueue={onSelectQueue} actions={questionControls} /></div>;
      }}
    </PanelStateView>
    {actionSaid && !conversationReadable ? <section className="conversation-action-outcome" role="status" aria-live="polite"><h3 id="conversation-action-outcome" tabIndex={-1}>{actionSaid.title}</h3><p>{actionSaid.detail}</p></section> : null}
  </>;
}
