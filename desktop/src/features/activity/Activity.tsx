import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ActivityActionResult, ActivityCorrectionState, ActivityCorrectionVerb, ActivityData, ActivityTransferReference, EvidenceLink, FeatureResult, MovementView } from "../../surface/types";

export type ActivityCorrectionControls = {
  state: ActivityCorrectionState;
  onAssignCategory: (movementId: string, categoryId: string) => void;
  onReplaceTags: (movementId: string, tagIds: readonly string[]) => void;
  onConfirmTransfer: (movementId: string, counterpartId: string) => void;
  onRejectTransfer: (movementId: string) => void;
  onUnlinkTransfer: (movementId: string, counterpartId: string) => void;
};
type ActivityProps = { result: FeatureResult<ActivityData>; correction?: ActivityCorrectionControls | null; onOpenEvidence: (link: EvidenceLink) => void };

function transferVerbTitle(verb: ActivityCorrectionVerb, state: "completed" | "refused" | "stale"): string | null {
  const titles = {
    confirm_transfer: { completed: "Transfer confirmed", refused: "Transfer confirmation refused", stale: "Transfer suggestion changed" },
    reject_transfer: { completed: "Transfer suggestion rejected", refused: "Transfer rejection refused", stale: "Transfer suggestion changed" },
    unlink_transfer: { completed: "Transfer unlinked", refused: "Transfer unlink refused", stale: "Transfer link changed" },
  } as const;
  return verb === "category" || verb === "tags" ? null : titles[verb][state];
}

function outcomeCopy(result: ActivityActionResult, verb: ActivityCorrectionVerb): { title: string; detail: string; completed: boolean } {
  if (result.state !== "settled") return { ...channelPresentation(result), completed: false };
  const detail = result.outcome.message.trim() || UNSPOKEN_REPLY;
  switch (result.outcome.kind) {
    case "completed": return { title: transferVerbTitle(verb, "completed") ?? "Correction recorded", detail, completed: true };
    case "refused": return { title: transferVerbTitle(verb, "refused") ?? "Correction refused", detail, completed: false };
    case "stale": return { title: transferVerbTitle(verb, "stale") ?? "Correction out of date", detail, completed: false };
  }
}

function CorrectionStatus({ state, outcomeRef }: { state: ActivityCorrectionState; outcomeRef: RefObject<HTMLDivElement | null> }) {
  if (state.state === "idle") return null;
  if (state.state === "working") return <div ref={outcomeRef} className="activity-correction-status working" role="status" aria-live="polite" tabIndex={-1}>
    <strong>Saving this correction</strong><span>Waiting for your vault to answer. The old picture stays on screen.</span>
  </div>;
  const said = outcomeCopy(state.result, state.verb);
  const refresh = state.state === "refreshing"
    ? "Reading the full picture again. The old picture stays on screen until that read finishes."
    : state.refresh === "failed"
      ? "The full picture could not be read again. The old picture is still on screen and is stale."
      : "The full picture was read again.";
  return <div ref={outcomeRef} className={`activity-correction-status ${state.state === "settled" && state.refresh === "failed" ? "failed" : "settled"}`} role="status" aria-live="polite" tabIndex={-1}>
    <strong>{said.title}</strong><span>{said.detail}</span><span>{refresh}</span>
  </div>;
}

function MovementCorrection({ movement, data, controls }: { movement: MovementView; data: ActivityData; controls: ActivityCorrectionControls }) {
  const [categoryId, setCategoryId] = useState(movement.category.id ?? "");
  const [tagIds, setTagIds] = useState<readonly string[]>(movement.tags.map((tag) => tag.id));
  const busy = controls.state.state === "working" || controls.state.state === "refreshing";
  const waitId = `activity-correction-wait-${movement.id}`;
  useEffect(() => {
    setCategoryId(movement.category.id ?? "");
    setTagIds(movement.tags.map((tag) => tag.id));
  }, [movement.category.id, movement.tags]);
  function submitCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!busy && categoryId.trim()) controls.onAssignCategory(movement.id, categoryId);
  }
  function submitTags(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!busy) controls.onReplaceTags(movement.id, tagIds);
  }
  const canAssign = movement.actions.includes("assign_category");
  const canReplaceTags = movement.actions.includes("replace_tags");
  const canConfirmTransfer = movement.actions.includes("confirm_transfer");
  const canRejectTransfer = movement.actions.includes("reject_transfer");
  const canUnlinkTransfer = movement.actions.includes("unlink_transfer");
  const hasTransferContext = movement.transfer?.state === "suggested" || movement.transfer?.state === "linked";
  if (!canAssign && !canReplaceTags && !hasTransferContext) return null;
  const context = [movement.date, movement.description, movement.account, movement.display, movement.id].filter((part) => part.trim()).join(", ");
  const correctionParts = [...(canAssign ? ["category"] : []), ...(canReplaceTags ? ["tags"] : []), ...(hasTransferContext ? ["transfer"] : [])];
  const summary = correctionParts.length === 1 && correctionParts[0] === "transfer"
    ? movement.transfer?.state === "linked" ? "Review transfer link" : "Review transfer suggestion"
    : correctionParts.length === 3 ? "Correct category, tags, or transfer"
      : correctionParts.length === 2 ? `Correct ${correctionParts[0]} or ${correctionParts[1]}`
        : correctionParts[0] === "category" ? "Correct category" : "Correct tags";
  const transferReferenceContext = (reference: ActivityTransferReference) => [reference.date, reference.description, reference.account, reference.display, reference.id].join(", ");
  const linkedCounterpart = movement.transfer?.state === "linked" ? movement.transfer.counterpart : null;
  return <details className="activity-correction">
    <summary aria-label={`${summary} for ${context}`}>{summary}</summary>
    <div className="activity-correction-forms">
      {canAssign ? <form onSubmit={submitCategory}>
        <label>Category<select aria-label={`Category for ${context}`} value={categoryId} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onChange={(event) => { if (!busy) setCategoryId(event.target.value); }}>
          <option value="">Choose an existing category</option>
          {data.vocabularies.categories.items.map((choice) => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
        </select></label>
        <button className="secondary-button" type="submit" aria-label={`Save category for ${context}`} aria-disabled={busy || !categoryId.trim()} aria-describedby={busy ? waitId : undefined}>Save category</button>
      </form> : null}
      {canReplaceTags ? <form onSubmit={submitTags}>
        <fieldset aria-label={`Tags for ${context}`}><legend>Tags</legend><div className="activity-tag-choices">{data.vocabularies.tags.items.map((choice) => {
          const checked = tagIds.includes(choice.id);
          const atLimit = !checked && tagIds.length >= data.vocabularies.tags.maxSelected;
          return <label key={choice.id}><input type="checkbox" aria-label={`${choice.label} tag for ${context}`} checked={checked} aria-disabled={busy || atLimit} aria-describedby={busy ? waitId : undefined} onChange={(event) => {
            if (busy || atLimit) return;
            setTagIds(event.target.checked ? [...tagIds, choice.id] : tagIds.filter((id) => id !== choice.id));
          }} />{choice.label}</label>;
        })}</div></fieldset>
        <button className="secondary-button" type="submit" aria-label={`Save complete tag set for ${context}`} aria-disabled={busy} aria-describedby={busy ? waitId : undefined}>Save complete tag set</button>
      </form> : null}
      {movement.transfer?.state === "suggested" ? <section className="activity-transfer-correction" aria-label={`Transfer suggestion for ${context}`}>
        <h4>Transfer suggestion</h4>
        <p>{movement.transfer.explanation}</p>
        <div className="activity-transfer-candidates">{movement.transfer.candidates.map((candidate) => {
          const candidateContext = transferReferenceContext(candidate);
          return <article key={candidate.id} aria-label={`Possible counterpart ${candidateContext}`}>
            <strong>{candidate.description}</strong>
            <span>{candidate.date} · {candidate.account} · {candidate.display} · {candidate.direction}</span>
            <p>{candidate.relationship}</p>
            {canConfirmTransfer ? <button className="secondary-button" type="button" aria-label={`Confirm transfer for ${context}; counterpart ${candidateContext}`} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onClick={() => { if (!busy) controls.onConfirmTransfer(movement.id, candidate.id); }}>Confirm transfer</button> : null}
          </article>;
        })}</div>
        {canRejectTransfer ? <button className="secondary-button" type="button" aria-label={`Reject transfer suggestion for ${context}`} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onClick={() => { if (!busy) controls.onRejectTransfer(movement.id); }}>Reject suggestion</button> : null}
      </section> : null}
      {movement.transfer?.state === "linked" && linkedCounterpart ? <section className="activity-transfer-correction" aria-label={`Transfer link for ${context}`}>
        <h4>Transfer link</h4>
        <p>{movement.transfer.explanation}</p>
        <strong>{linkedCounterpart.description}</strong>
        <span>{linkedCounterpart.date} · {linkedCounterpart.account} · {linkedCounterpart.display} · {linkedCounterpart.direction}</span>
        <p>{movement.transfer.relationship}</p>
        {canUnlinkTransfer ? <button className="secondary-button" type="button" aria-label={`Unlink transfer for ${context}; counterpart ${transferReferenceContext(linkedCounterpart)}`} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onClick={() => { if (!busy) controls.onUnlinkTransfer(movement.id, linkedCounterpart.id); }}>Unlink transfer</button> : null}
      </section> : null}
      {busy ? <p id={waitId} className="action-explanation">Your vault is answering the last correction and then reading the full picture. Pressing again does nothing until both finish.</p> : null}
    </div>
  </details>;
}

// Every financial word here is the backend's. Corrections appear only where
// the same row advertises one, and their choices come only from the complete
// read-level vocabularies.
function Movements({ data, correction }: { data: ActivityData; correction: ActivityCorrectionControls | null }) {
  const movements = data.movements ?? [];
  const rows = useRef(new Map<string, HTMLLIElement>());
  const outcomeRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!correction || correction.state.state !== "settled") return;
    const said = outcomeCopy(correction.state.result, correction.state.verb);
    if (correction.state.refresh === "refreshed" && said.completed) {
      const row = rows.current.get(correction.state.movementId);
      if (row) { row.focus(); return; }
    }
    outcomeRef.current?.focus();
  }, [correction?.state]);
  return <section className="feature-panel activity-panel">
    <header className="activity-header"><div className="detail-panel-label">Current vault read</div><h2>What moved</h2><p>{data.sentence}</p></header>
    {correction ? <CorrectionStatus state={correction.state} outcomeRef={outcomeRef} /> : null}
    {!movements.length ? <div className="empty-state"><strong>No movements in this read</strong><span>{data.sentence}</span></div> : <>
      <ul className="activity-movements">{movements.map((movement) => <li key={movement.id} ref={(node) => { if (node) rows.current.set(movement.id, node); else rows.current.delete(movement.id); }} tabIndex={-1} className={movement.direction === "in" ? "activity-movement inflow" : "activity-movement outflow"}>
        <span className="activity-movement-when">{movement.date}</span>
        <span className="activity-movement-what"><strong>{movement.description || "No description was recorded for this movement."}</strong><small>{movement.account}</small></span>
        <span className="activity-movement-amount"><strong>{movement.display}</strong><small>{movement.direction === "in" ? "in" : "out"}</small></span>
        {movement.sentence ? <p className="activity-movement-note">{movement.sentence}</p> : null}
        <dl className="activity-movement-classification"><div><dt>Category</dt><dd>{movement.category.valid ? movement.category.label : "Category unavailable from this read"}</dd></div><div><dt>Tags</dt><dd>{movement.tagsValid ? (movement.tags.length ? movement.tags.map((tag) => tag.label).join(", ") : "No tags recorded") : "Tags unavailable from this read"}</dd></div></dl>
        {correction ? <MovementCorrection movement={movement} data={data} controls={correction} /> : null}
      </li>)}</ul>
      {data.beyond && data.beyond.count > 0 ? <p className="activity-beyond">{data.beyond.count} more are in this vault and not in this list.</p> : null}
    </>}
  </section>;
}

export function Activity({ result, correction }: ActivityProps) {
  return <PanelStateView result={result} copy={{ partial: "Some activity details are unavailable. Available movements are shown below.", needsInput: "Some activity details need more information. Available movements are shown below.", unavailable: { title: "Activity unavailable", detail: "Activity is not connected to this vault read." }, failed: { title: "Activity could not be read", detail: "Activity could not be read. The vault is still open." } }}>{(data) => <Movements data={data} correction={correction ?? null} />}</PanelStateView>;
}
