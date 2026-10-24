import { useEffect, useRef, useState, type FormEvent } from "react";
import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import { conversationEvidenceFigure } from "../../surface/evidence";
import { Questions } from "./Questions";
import { outcomePresentation } from "./questionPresentation";
import type { ActionResult, ActionOutcome, AskActionState, AskContextMode, ConversationData, ConversationGoalDraft, ConversationTurn, DeclineReason, FeatureResult, MissingAnswerInput, QuestionActionState, TurnView } from "../../surface/types";

export type AskControls = { state: AskActionState; onAsk: (question: string, mirrored: boolean, planRequest?: boolean, contextMode?: AskContextMode, movementIds?: readonly string[]) => void };
export type ConversationControls = {
  state: QuestionActionState;
  onAnswer: (questionId: string, said: string) => void;
  onConfirm: (questionId: string, proposalId: string, said: string, asked: string) => void;
  onDecline: (questionId: string, reason: DeclineReason) => void;
};

export type ConversationContextControls = { mode: AskContextMode; onNewConversation: () => void };

export type AccountingContext = { movementIds: readonly string[]; label: string };

function AskBox({ ask, accountingContext, onClearAccountingContext, context, starterQuestions }: { ask: AskControls; accountingContext?: AccountingContext | null; onClearAccountingContext?: () => void; context?: ConversationContextControls; starterQuestions: readonly string[] }) {
  const [question, setQuestion] = useState("");
  const explanationRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (accountingContext) explanationRef.current?.focus(); }, [accountingContext]);
  const [localContextMode, setContextMode] = useState<AskContextMode>("new_question");
  const contextMode = context?.mode ?? localContextMode;
  const [submitted, setSubmitted] = useState<{ question: string; observedWorking: boolean } | null>(null);
  const working = ask.state.state === "working";
  const settled = ask.state.state === "settled" ? ask.state : null;
  const channel = settled && settled.result.state !== "settled" ? channelPresentation(settled.result) : null;
  const said = channel ? `${channel.title}. ${channel.detail}` : settled && !settled.turn && settled.result.state === "settled" ? settled.result.outcome.message.trim() || UNSPOKEN_REPLY : "";
  useEffect(() => {
    if (submitted && !submitted.observedWorking && ask.state.state === "working" && ask.state.question === submitted.question) {
      setSubmitted({ ...submitted, observedWorking: true });
      return;
    }
    if (settled?.authoritative === true && settled.result.state === "settled"
        && (settled.result.outcome.kind === "completed" || settled.result.outcome.kind === "refused")
        && submitted?.observedWorking && settled.question === submitted.question && question === submitted.question) {
      if (!accountingContext) setContextMode("follow_up");
      if (settled.result.outcome.kind === "completed") {
        setQuestion("");
      }
      setSubmitted(null);
    }
  }, [ask.state, question, settled, submitted, accountingContext]);
  function send(planRequest = false) {
    if (working || !question.trim()) return;
    const exact = question.trim();
    setSubmitted({ question: exact, observedWorking: false });
    if (accountingContext) ask.onAsk(exact, true, false, "new_question", accountingContext.movementIds);
    else ask.onAsk(exact, true, planRequest, contextMode);
  }
  return <section className="conversation-ask" aria-labelledby="conversation-ask-title">
    <h3 id="conversation-ask-title">{accountingContext ? "Explain accounting treatment" : "Ask about your money"}</h3>
    {accountingContext ? <p className="conversation-context-help">Selected transaction: {accountingContext.label}. Explain its accounting treatment here; corrections update your reports.</p> : null}
    <form onSubmit={(event) => { event.preventDefault(); send(); }}>
      <label htmlFor="conversation-ask-question">{accountingContext ? "Your explanation" : "Your question"}</label>
      <textarea ref={explanationRef} id="conversation-ask-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} />
      {!accountingContext ? <div className="conversation-context-controls">
        <div className="conversation-context-status"><strong>{contextMode === "follow_up" ? "Continuing this conversation" : "Starting a new conversation"}</strong><button className="text-button" type="button" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : "conversation-context-help"} onClick={() => { if (working) return; setSubmitted(null); setContextMode("new_question"); context?.onNewConversation(); explanationRef.current?.focus(); }}>New conversation</button></div>
        <p className="conversation-context-help" id="conversation-context-help">{contextMode === "follow_up" ? "Your next question uses questions and answers since you last started a new conversation." : "Earlier messages stay saved. Your next question will not use them."}</p>
      </div> : null}
      <button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined}>{accountingContext ? "Apply explanation" : "Ask"}</button>
      {!accountingContext ? <details className="conversation-planning"><summary>Plan a savings goal</summary><p>Describe your goal above, then ask Viva to draft a plan. You can review it in Plans before recording anything.</p><button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined} onClick={() => send(true)}>Draft a save-up plan</button></details> : onClearAccountingContext ? <button className="text-button" type="button" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined} onClick={() => { if (working) return; setQuestion(""); setContextMode("new_question"); onClearAccountingContext(); }}>Ask another question</button> : null}
    </form>
    {!accountingContext && starterQuestions.length ? <div className="conversation-starters" aria-label="Question ideas"><p>Try a question</p>{starterQuestions.map((starter) => <button className="secondary-button" type="button" key={starter} aria-disabled={working} onClick={() => { if (working) return; setQuestion(starter); explanationRef.current?.focus(); }}>{starter}</button>)}</div> : null}
    {working ? <span className="action-explanation" id="conversation-ask-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{said}</div>
    {said ? <p className="conversation-answer-text">{said}</p> : null}
  </section>;
}

function ProposalReply({ turn, controls }: { turn: ConversationTurn; controls: ConversationControls }) {
  const [said, setSaid] = useState("");
  const [submitted, setSubmitted] = useState<{ said: string; observedWorking: boolean } | null>(null);
  const proposal = turn.proposal;
  const working = controls.state.state === "working";
  useEffect(() => {
    if (submitted && !submitted.observedWorking && controls.state.state === "working" && controls.state.questionId === turn.questionId) {
      setSubmitted({ ...submitted, observedWorking: true });
      return;
    }
    const settled = controls.state.state === "settled" ? controls.state : null;
    if (settled?.authoritative === true && settled.result.state === "settled" && settled.result.outcome.kind === "completed"
        && submitted?.observedWorking && settled.questionId === turn.questionId && said === submitted.said) {
      setSaid("");
      setSubmitted(null);
    }
  }, [controls.state, said, submitted, turn.questionId]);
  if (!proposal || proposal.status !== "open") return null;
  const openProposal = proposal;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!said.trim() || working) return;
    const exact = said.trim();
    setSubmitted({ said: exact, observedWorking: false });
    controls.onConfirm(turn.questionId, openProposal.id, exact, openProposal.summary || turn.prompt);
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

function CapabilityBoundary({ item }: { item: MissingAnswerInput }) {
  return <section className="conversation-capability-boundary" aria-label="Available financial answers">
    <p><strong>Requested</strong> {item.requestedLabel || "A financial answer that is not available yet"}</p>
    <p><strong>Available now</strong></p>
    <ul>{(item.supportedFamilies ?? []).map((family) => <li key={family.id}><strong>{family.label}</strong><span>{family.example}</span></li>)}</ul>
  </section>;
}

function CorrectionUndo({ id, onUndo }: { id: string; onUndo: (correctionId: string) => Promise<ActionResult> }) {
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [completed, setCompleted] = useState(false);
  async function undo() {
    if (working || completed) return;
    setWorking(true);
    try {
      const result = await onUndo(id);
      if (result.state === "settled") {
        setMessage(result.outcome.message || UNSPOKEN_REPLY);
        setCompleted(result.outcome.kind === "completed");
      } else { const copy = channelPresentation(result); setMessage(`${copy.title}. ${copy.detail}`); }
    } catch { setMessage("The correction could not be undone. Try again."); }
    finally { setWorking(false); }
  }
  return <div><button type="button" className="text-button" aria-disabled={working || completed} aria-describedby={working || completed ? `undo-status-${id}` : undefined} onClick={() => void undo()}>{working ? "Undoing correction…" : completed ? "Correction undone" : "Undo accounting correction"}</button>{working || message ? <p id={`undo-status-${id}`} role="status" aria-live="polite">{working ? "The correction is being undone. Wait for the result before trying again." : message}</p> : null}</div>;
}

function AnswerDetail({ answer, onOpenFigure, onReviewPlan, onUndoCorrection }: { answer: TurnView; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void; onUndoCorrection?: (correctionId: string) => Promise<ActionResult> }) {
  const answerText = answer.text || answer.refusal;
  const ordinaryMissing = answer.missing.filter((item) => item.tag !== "unsupported_family" && (item.question || item.label || item.tag).trim() !== answerText.trim());
  const capability = answer.missing.find((item) => item.tag === "unsupported_family");
  return <div className="conversation-answer" role={answer.status === "capability_gap" ? "status" : undefined} aria-live={answer.status === "capability_gap" ? "polite" : undefined} aria-atomic={answer.status === "capability_gap" ? "true" : undefined}>
    <p className="conversation-answer-text">{answerText}</p>
    {answer.accountingCorrection && onUndoCorrection ? <CorrectionUndo id={answer.accountingCorrection.id} onUndo={onUndoCorrection} /> : null}
    {answer.gradeSentence ? <p className="conversation-answer-grade">{answer.gradeSentence}</p> : null}
    {answer.figures.length ? <dl className="conversation-answer-figures">{answer.figures.map((figure) => <div key={figure.id}>
      <dt>{figure.evidenceId && figure.evidenceLinks.length ? <Figure figure={conversationEvidenceFigure(figure)} onOpenEvidence={onOpenFigure} className="conversation-figure-trigger" /> : figure.written || figure.what}</dt>
      <dd>{figure.what}{figure.recordIds.length ? ` · ${figure.recordIds.length === 1 ? "1 cited record" : `${figure.recordIds.length} cited records`}` : ""}</dd>
    </div>)}</dl> : null}
    {answer.options.length ? <ul className="conversation-answer-options">{answer.options.map((option) => <li key={option.id}>{option.label}</li>)}</ul> : null}
    {capability ? <CapabilityBoundary item={capability} /> : null}
    {ordinaryMissing.length ? <ul className="conversation-answer-missing">{ordinaryMissing.map((item, index) => <li key={`${item.tag}:${item.label}:${index}`}>{item.question || item.label || item.tag}</li>)}</ul> : null}
    {answer.spoken.withheld ? <p className="conversation-answer-withheld">{answer.spoken.withheld}</p> : null}
    {answer.spoken.citationSentence ? <p className="conversation-answer-citation">{answer.spoken.citationSentence}</p> : null}
    {answer.goalDraft?.reviewInPlans && onReviewPlan ? <button className="secondary-button" type="button" onClick={() => onReviewPlan(answer.goalDraft!)}>Review in Plans</button> : null}
  </div>;
}

function Timeline({ data, controls, onOpenFigure, onReviewPlan, onUndoCorrection, mode }: { mode: "ask" | "review" | "combined"; data: ConversationData; controls: ConversationControls; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void; onUndoCorrection?: (correctionId: string) => Promise<ActionResult> }) {
  if (!data.turns.length) return <section className="conversation-thread"><div className="empty-state"><strong>No conversation yet</strong><span>{mode === "ask" ? "Ask Viva about your money. Your questions and answers stay saved in this vault." : mode === "review" ? "Answer one of the questions below. Your replies stay saved in this vault." : "Ask Viva, or answer one of the questions below. Your messages stay saved in this vault."}</span></div></section>;
  return <section className="conversation-thread" aria-labelledby="conversation-turns-title">
    <h3 id="conversation-turns-title">Conversation</h3>
    <ol>{data.turns.map((turn) => <li className={`conversation-turn ${turn.outcome}`} key={turn.id}>
      <div className="conversation-turn-meta">
        {turn.kind === "ask" && turn.contextMode === "new_question" ? <span className="conversation-context-boundary">New question</span> : null}
        <div className="conversation-turn-meta-main"><strong>{turn.kind === "ask" ? "You asked" : turn.kind === "answer" ? "You answered" : turn.kind === "decline" ? "You set aside" : "You confirmed"}</strong>{turn.kind === "ask" && turn.contextMode !== "new_question" ? <span>{turn.contextMode === "follow_up" ? "Follow-up" : "Earlier conversation"}</span> : null}<span>{outcomeLabels[turn.outcome]}</span>{turn.occurredAt ? <time dateTime={turn.occurredAt}>{turn.occurredAt}</time> : null}</div>
      </div>
      <p>{turn.prompt}</p>
      {turn.said ? <blockquote>{turn.said}</blockquote> : null}
      {turn.answer ? <AnswerDetail answer={turn.answer} onOpenFigure={onOpenFigure} onReviewPlan={onReviewPlan} onUndoCorrection={onUndoCorrection} /> : turn.message ? <p className="conversation-answer-text">{turn.message}</p> : null}
      {turn.proposal && turn.proposal.status !== "open" && turn.proposal.message ? <p>{turn.proposal.message}</p> : null}
      <ProposalReply turn={turn} controls={controls} />
    </li>)}</ol>
  </section>;
}

export function ConversationDrawer({ result, selectedQueue, onSelectQueue, onOpenFigure, onReviewPlan, ask, controls, mode = "combined", accountingContext = null, onUndoCorrection, onClearAccountingContext, context, starterQuestions = [] }: { result: FeatureResult<ConversationData>; selectedQueue: string; onSelectQueue: (id: string) => void; onOpenFigure: (figureId: string) => void; onReviewPlan?: (draft: ConversationGoalDraft) => void; ask: AskControls | null; controls: ConversationControls; mode?: "ask" | "review" | "combined"; accountingContext?: AccountingContext | null; onClearAccountingContext?: () => void; onUndoCorrection?: (correctionId: string) => Promise<ActionResult>; context?: ConversationContextControls; starterQuestions?: readonly string[] }) {
  const actionSaid = controls.state.state === "settled" ? outcomePresentation(controls.state.verb, controls.state.result) : null;
  const conversationReadable = result.state === "ready" || result.state === "partial" || result.state === "needs_input";
  return <>
    {ask && mode !== "review" ? <AskBox ask={ask} context={context} starterQuestions={starterQuestions} accountingContext={accountingContext} onClearAccountingContext={onClearAccountingContext} /> : null}
    <PanelStateView result={result} copy={{ partial: "Some conversation details are unavailable.", needsInput: "This conversation needs input.", unavailable: { title: "Conversation unavailable", detail: "Conversation history is unavailable for this vault." }, failed: { title: "Conversation could not be loaded", detail: "Your saved messages could not be loaded. Try opening Ask Viva again." } }}>
      {(data) => {
        const proposalIsRestored = data.turns.some((turn) => turn.proposal?.status === "open");
        const questionControls = proposalIsRestored ? { ...controls, onConfirm: undefined } : controls;
        return <div className="conversation-body"><Timeline mode={mode} data={data} controls={controls} onOpenFigure={onOpenFigure} onReviewPlan={onReviewPlan} onUndoCorrection={onUndoCorrection} />{mode !== "ask" ? <Questions result={{ state: "ready", data: data.questions }} selectedQueue={selectedQueue} onSelectQueue={onSelectQueue} actions={questionControls} /> : null}</div>;
      }}
    </PanelStateView>
    {actionSaid && !conversationReadable ? <section className="conversation-action-outcome" role="status" aria-live="polite"><h3 id="conversation-action-outcome" tabIndex={-1}>{actionSaid.title}</h3><p>{actionSaid.detail}</p></section> : null}
  </>;
}
