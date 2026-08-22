import { useState, type FormEvent } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { AskActionState, ConversationData, ConversationPrompt, ConversationTurn, FeatureResult, TurnView } from "../../surface/types";
import { presentConversationRows, resolveConversationPrompt, type PromptSelection } from "./conversationPresentation";

// What a screen needs to ask Viva a question. A source that cannot ask carries
// none of this, so the box is absent rather than present and refusing.
export type AskControls = { state: AskActionState; onAsk: (question: string, mirrored: boolean) => void };

// One answered turn, with the mirror that makes a spoken figure checkable: the
// sentence, the whole reviewed grade line, and every figure written in the
// words the sentence wrote it in, beside the records it rests on. Nothing here
// is composed — not the grade line, not the citation line, not the sentence
// saying why something was not spoken.
function AnsweredTurn({ turn }: { turn: TurnView }) {
  return <article className="conversation-answer" aria-labelledby="conversation-answer-title">
    <h3 id="conversation-answer-title">{turn.question}</h3>
    <p className="conversation-answer-text">{turn.text || turn.refusal}</p>
    {turn.gradeSentence ? <p className="conversation-answer-grade">{turn.gradeSentence}</p> : null}
    {turn.figures.length ? <dl className="conversation-answer-figures">{turn.figures.map((figure) => <div key={figure.id}>
      <dt>{figure.written || figure.id}</dt>
      <dd>{figure.what}{figure.recordIds.length ? ` · ${figure.recordIds.join(", ")}` : ""}</dd>
    </div>)}</dl> : null}
    {turn.spoken.withheld ? <p className="conversation-answer-withheld">{turn.spoken.withheld}</p> : null}
    {turn.spoken.citationSentence ? <p className="conversation-answer-citation">{turn.spoken.citationSentence}</p> : null}
  </article>;
}

// The box a person asks in. `mirrored` is true because this drawer is where the
// answer appears: the text is in front of the person by construction, and
// saying so is a fact about this screen rather than a preference somebody sets.
function AskBox({ ask }: { ask: AskControls }) {
  const [question, setQuestion] = useState("");
  const working = ask.state.state === "working";
  const settled = ask.state.state === "settled" ? ask.state : null;
  const said = settled && settled.result.state !== "settled"
    ? `${channelPresentation(settled.result).title}. ${channelPresentation(settled.result).detail}`
    : settled && !settled.turn && settled.result.state === "settled"
      ? settled.result.outcome.message.trim() || UNSPOKEN_REPLY
      : "";
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || !question.trim()) return;
    ask.onAsk(question.trim(), true);
    setQuestion("");
  }
  return <section className="conversation-ask" aria-labelledby="conversation-ask-title">
    <h3 id="conversation-ask-title">Ask about your money</h3>
    <form onSubmit={submit}>
      <label htmlFor="conversation-ask-question">Your question</label>
      <textarea id="conversation-ask-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} />
      <button className="primary-button" type="submit" aria-disabled={working} aria-describedby={working ? "conversation-ask-waiting" : undefined}>Ask</button>
    </form>
    {working ? <span className="action-explanation" id="conversation-ask-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{settled?.turn ? settled.turn.text || settled.turn.refusal : said}</div>
    {settled?.turn ? <AnsweredTurn turn={settled.turn} /> : null}
    {said ? <p className="conversation-answer-text">{said}</p> : null}
  </section>;
}

function TurnList({ turns }: { turns: readonly ConversationTurn[] }) {
  return <section className="conversation-thread" aria-labelledby="conversation-turns-title"><h3 id="conversation-turns-title">Supplied conversation turns</h3><p className="conversation-turn-order">Turns are shown in the order supplied to this view. The interface does not verify chronology.</p><ul>{presentConversationRows(turns, "turn").map((row) => {
    if (row.state === "missing_identity") return <li className="conversation-identity-state" key={row.key}><strong>Turn identity unavailable</strong><span>One or more conversation turns have no stable turn ID. They are not merged or presented as one turn.</span></li>;
    if (row.state === "conflicted_identity") return <li className="conversation-identity-state" key={row.key}><strong>Turn identity conflicted</strong><span>More than one conversation turn uses this turn ID. The interface will not merge them.</span><dl><div><dt>Turn ID</dt><dd>{row.id}</dd></div></dl></li>;
    const turn = row.item;
    return <li className={`conversation-turn ${turn.state}`} key={row.key}><div className="conversation-turn-meta"><strong>{`Supplied speaker: ${turn.speaker}`}</strong><span>{turn.state}</span></div><p>{turn.text.trim() ? turn.text : "Turn text was not supplied by this conversation view."}</p>{turn.citation && <div className="conversation-citation"><span>Supplied citation text: {turn.citation}</span><small>Citation text is not a document link. This conversation view does not supply a document identity.</small></div>}<dl><div><dt>Turn ID</dt><dd>{turn.id}</dd></div></dl></li>;
  })}</ul></section>;
}

function PromptRows({ prompts, selectedPrompt, selection, onSelectPrompt }: { prompts: readonly ConversationPrompt[]; selectedPrompt: string; selection: PromptSelection; onSelectPrompt: (id: string) => void }) {
  return <section className="conversation-prompts" aria-labelledby="conversation-prompts-title"><div className="conversation-section-heading"><div><h3 id="conversation-prompts-title">Supplied prompts</h3><p>Choose a supplied prompt to inspect its detail. Nothing is sent.</p></div><span className="conversation-readonly-badge">Read only</span></div><ul className="conversation-prompt-list">{presentConversationRows(prompts, "prompt").map((row) => {
    if (row.state === "missing_identity") return <li className="conversation-identity-state" key={row.key}><strong>Prompt identity unavailable</strong><span>This prompt has no stable ID, so it cannot be selected.</span></li>;
    if (row.state === "conflicted_identity") return <li className="conversation-identity-state" key={row.key}><strong>Prompt identity conflicted</strong><span>More than one prompt uses this ID. No prompt with this identity can be selected.</span><dl><div><dt>Prompt ID</dt><dd>{row.id}</dd></div></dl></li>;
    const prompt = row.item;
    const pressed = selection.state === "ready" && selection.prompt.id === prompt.id;
    return <li key={row.key}><button type="button" className={pressed ? "conversation-prompt active" : "conversation-prompt"} aria-pressed={pressed} onClick={() => onSelectPrompt(prompt.id)}><strong>{prompt.label.trim() ? prompt.label : "Prompt label was not supplied by this conversation view."}</strong><span>{prompt.detail.trim() ? prompt.detail : "Prompt detail was not supplied by this conversation view."}</span><span className="conversation-prompt-id">Prompt ID: {prompt.id}</span><small>{prompt.state}</small></button></li>;
  })}</ul><SelectedPrompt selection={selection} selectedPrompt={selectedPrompt} /></section>;
}

function SelectedPrompt({ selection, selectedPrompt }: { selection: PromptSelection; selectedPrompt: string }) {
  if (selection.state === "ready") {
    const prompt = selection.prompt;
    return <aside className="conversation-selected" aria-labelledby="selected-conversation-prompt-title"><div className="detail-panel-label">Selected prompt</div><h3 id="selected-conversation-prompt-title">{prompt.label.trim() ? prompt.label : "Prompt label was not supplied by this conversation view."}</h3><p>{prompt.detail.trim() ? prompt.detail : "Prompt detail was not supplied by this conversation view."}</p><dl><div><dt>Prompt ID</dt><dd>{prompt.id}</dd></div><div><dt>Prompt state</dt><dd>{prompt.state}</dd></div></dl></aside>;
  }
  let title = "Prompt selection unavailable";
  let detail = selection.state === "empty" && selection.reason === "no_prompts" ? "This conversation view does not contain prompts." : "This conversation view contains prompts, but none has a unique nonblank prompt ID.";
  let requestedId = "";
  if (selection.state === "missing") { title = "Selected prompt unavailable"; detail = "The selected prompt is no longer present in this conversation view."; requestedId = selection.requestedId; }
  if (selection.state === "conflicted_identity") { detail = "More than one prompt uses the selected identity, so the interface will not choose between them."; requestedId = selection.requestedId; }
  return <aside className="conversation-selected" aria-labelledby="selected-conversation-prompt-title"><div className="detail-panel-label">Selected prompt</div><h3 id="selected-conversation-prompt-title">{title}</h3><p>{detail}</p>{requestedId && <dl><div><dt>Requested prompt ID</dt><dd>{requestedId}</dd></div></dl>}{!requestedId && selectedPrompt && <dl><div><dt>Requested prompt ID</dt><dd>{selectedPrompt}</dd></div></dl>}</aside>;
}

function ConversationReady({ data, selectedPrompt, onSelectPrompt }: { data: ConversationData; selectedPrompt: string; onSelectPrompt: (id: string) => void }) {
  const view = { turns: data.turns, prompts: data.prompts };
  if (!view.turns.length && !view.prompts.length) return <div className="empty-state"><strong>No conversation content supplied</strong><span>This supplied Conversation view contains no turns or prompts. Empty content does not establish whether a model call occurred.</span></div>;
  const selection = resolveConversationPrompt(view.prompts, selectedPrompt);
  return <div className="conversation-body"><p className="conversation-intro">Displaying supplied conversation fields does not establish that a model call occurred.</p><TurnList turns={view.turns} /><PromptRows prompts={view.prompts} selectedPrompt={selectedPrompt} selection={selection} onSelectPrompt={onSelectPrompt} /></div>;
}

export function ConversationDrawer({ result, selectedPrompt, onSelectPrompt, ask }: { result: FeatureResult<ConversationData>; selectedPrompt: string; onSelectPrompt: (id: string) => void; ask: AskControls | null }) {
  // The box sits outside the read's state gate rather than inside it. What
  // answers a question is the engine; the read below supplies turns and
  // prompts, and a read that is not connected still has that to say. Hiding
  // the box behind it would tie one to the other, and hiding what the read
  // says behind the box would drop a true sentence about the product.
  return <>{ask ? <AskBox ask={ask} /> : null}<PanelStateView result={result} copy={{ partial: "Some conversation details are unavailable. Supplied read-only content is shown below.", needsInput: "Some conversation details need input, but this preview cannot accept or send a prompt. Supplied read-only content is shown below.", unavailable: { title: "Conversation isn’t connected yet", detail: "Viva is not connected to this vault in this preview. Opening this drawer does not send a prompt or call a model. This unavailable view does not establish whether earlier model activity occurred." }, failed: { title: "Conversation could not be read", detail: "The conversation view could not be read. Opening this drawer does not send a prompt or call a model. This failed read does not establish whether earlier model activity occurred. The private vault remains open." } }}>{(data) => <ConversationReady data={data} selectedPrompt={selectedPrompt} onSelectPrompt={onSelectPrompt} />}</PanelStateView></>;
}
