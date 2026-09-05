import { useEffect, useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ActivityActionResult, ActivityCorrectionState, ActivityCorrectionVerb, ActivityData, ActivityTransferReference, EvidenceLink, FeatureResult, MovementView } from "../../surface/types";

export type ActivityCorrectionControls = {
  state: ActivityCorrectionState;
  onAssignCategory: (movementId: string, categoryId: string) => void;
  onAssignMeaning: (movementId: string, meaning: string, counterparty: string) => void;
  onReplaceTags: (movementId: string, tagIds: readonly string[]) => void;
  onConfirmTransfer: (movementId: string, counterpartId: string) => void;
  onRejectTransfer: (movementId: string) => void;
  onUnlinkTransfer: (movementId: string, counterpartId: string) => void;
};
type ActivityProps = { result: FeatureResult<ActivityData>; correction?: ActivityCorrectionControls | null; onOpenEvidence: (link: EvidenceLink) => void; onLoadMore?: (() => void) | null; selectedMovement?: string };

function transferVerbTitle(verb: ActivityCorrectionVerb, state: "completed" | "refused" | "stale"): string | null {
  const titles = {
    confirm_transfer: { completed: "Transfer confirmed", refused: "Transfer confirmation refused", stale: "Transfer suggestion changed" },
    reject_transfer: { completed: "Transfer suggestion rejected", refused: "Transfer rejection refused", stale: "Transfer suggestion changed" },
    unlink_transfer: { completed: "Transfer unlinked", refused: "Transfer unlink refused", stale: "Transfer link changed" },
  } as const;
  if (verb !== "confirm_transfer" && verb !== "reject_transfer" && verb !== "unlink_transfer") return null;
  return titles[verb][state];
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
  const [meaning, setMeaning] = useState(movement.treatment.kind === "spending" || movement.treatment.kind === "loan" || movement.treatment.kind === "loan_repayment" ? movement.treatment.kind : "");
  const [counterparty, setCounterparty] = useState(movement.treatment.name);
  const [tagIds, setTagIds] = useState<readonly string[]>(movement.tags.map((tag) => tag.id));
  const [newTag, setNewTag] = useState("");
  const busy = controls.state.state === "working" || controls.state.state === "refreshing";
  const waitId = `activity-correction-wait-${useId()}`;
  useEffect(() => {
    setCategoryId(movement.category.id ?? "");
    setMeaning(movement.treatment.kind === "spending" || movement.treatment.kind === "loan" || movement.treatment.kind === "loan_repayment" ? movement.treatment.kind : "");
    setCounterparty(movement.treatment.name);
    setTagIds(movement.tags.map((tag) => tag.id));
    setNewTag("");
  }, [movement.category.id, movement.tags, movement.treatment.kind, movement.treatment.name]);
  function submitCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!busy && categoryId.trim()) controls.onAssignCategory(movement.id, categoryId);
  }
  function submitMeaning(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const needsName = meaning === "loan" || meaning === "loan_repayment";
    if (!busy && meaning && (!needsName || counterparty.trim())) controls.onAssignMeaning(movement.id, meaning, counterparty.trim());
  }
  function submitTags(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const coined = newTag.trim().toLowerCase();
    const complete = coined && !tagIds.includes(coined) ? [...tagIds, coined] : tagIds;
    if (!busy && complete.length <= data.vocabularies.tags.maxSelected) controls.onReplaceTags(movement.id, complete);
  }
  const canAssign = movement.actions.includes("assign_category");
  const canAssignMeaning = movement.actions.includes("assign_meaning");
  const canReplaceTags = movement.actions.includes("replace_tags");
  const canConfirmTransfer = movement.actions.includes("confirm_transfer");
  const canRejectTransfer = movement.actions.includes("reject_transfer");
  const canUnlinkTransfer = movement.actions.includes("unlink_transfer");
  const hasTransferContext = movement.transfer?.state === "suggested" || movement.transfer?.state === "linked";
  if (!canAssign && !canAssignMeaning && !canReplaceTags && !hasTransferContext) return null;
  const context = [movement.date, movement.description, movement.account, movement.display, movement.id].filter((part) => part.trim()).join(", ");
  const correctionParts = [...(canAssign ? ["category"] : []), ...(canAssignMeaning ? ["treatment"] : []), ...(canReplaceTags ? ["tags"] : []), ...(hasTransferContext ? ["transfer"] : [])];
  const correctionList = correctionParts.length <= 1
    ? correctionParts[0]
    : correctionParts.length === 2
      ? correctionParts.join(" or ")
      : `${correctionParts.slice(0, -1).join(", ")}, or ${correctionParts.at(-1)}`;
  const summary = correctionParts.length === 1 && correctionParts[0] === "transfer"
    ? movement.transfer?.state === "linked" ? "Review transfer link" : "Review transfer suggestion"
    : `Correct ${correctionList}`;
  const transferReferenceContext = (reference: ActivityTransferReference) => [reference.date, reference.description, reference.account, reference.display, reference.id].join(", ");
  const linkedCounterpart = movement.transfer?.state === "linked" ? movement.transfer.counterpart : null;
  return <details className="activity-correction">
    <summary aria-label={`${summary} for ${context}`}>{summary}</summary>
    <div className="activity-correction-forms">
      {canAssignMeaning ? <form onSubmit={submitMeaning}>
        <label>Treatment<select aria-label={`Treatment for ${context}`} value={meaning} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onChange={(event) => { if (!busy) setMeaning(event.target.value); }}>
          <option value="">Choose a treatment</option>
          {movement.direction === "out" ? <><option value="spending">Counted as spending</option><option value="loan">Loan lent to someone</option></> : <option value="loan_repayment">Loan repayment received</option>}
        </select></label>
        {meaning === "loan" ? <label>Person or loan name<input type="text" aria-label={`Person or loan name for ${context}`} value={counterparty} maxLength={80} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onChange={(event) => { if (!busy) setCounterparty(event.target.value); }} /></label> : null}
        {meaning === "loan_repayment" ? <label>Open loan<select aria-label={`Open loan for ${context}`} value={counterparty} aria-disabled={busy} aria-describedby={busy ? waitId : undefined} onChange={(event) => { if (!busy) setCounterparty(event.target.value); }}><option value="">Choose an open loan</option>{movement.loanRepaymentChoices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label> : null}
        <button className="secondary-button" type="submit" aria-label={`Save treatment for ${context}`} aria-disabled={busy || !meaning || ((meaning === "loan" || meaning === "loan_repayment") && !counterparty.trim())} aria-describedby={busy ? waitId : undefined}>Save treatment</button>
      </form> : null}
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
        <label>New tag<input type="text" aria-label={`New tag for ${context}`} value={newTag} maxLength={data.vocabularies.tags.maxLabelLength} aria-disabled={busy || tagIds.length >= data.vocabularies.tags.maxSelected} onChange={(event) => { if (!busy) setNewTag(event.target.value); }} /></label>
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
function Movements({ data, correction, onLoadMore, selectedMovement, onOpenEvidence }: { data: ActivityData; correction: ActivityCorrectionControls | null; onLoadMore: (() => void) | null; selectedMovement: string; onOpenEvidence: (link: EvidenceLink) => void }) {
  const movements = data.movements ?? [];
  const [query, setQuery] = useState("");
  const [account, setAccount] = useState("");
  const [category, setCategory] = useState("");
  const [tag, setTag] = useState("");
  const [reviewState, setReviewState] = useState("");
  const rows = useRef(new Map<string, HTMLLIElement>());
  const outcomeRef = useRef<HTMLDivElement>(null);
  const accounts = [...new Map(movements.filter((movement) => movement.accountId).map((movement) => [movement.accountId, movement.accountName || movement.account])).entries()];
  const categories = [...new Map(movements.filter((movement) => movement.category.valid && movement.category.id).map((movement) => [movement.category.id as string, movement.category.label])).entries()];
  const tags = [...new Map(movements.flatMap((movement) => movement.tagsValid ? movement.tags.map((item) => [item.id, item.label] as const) : [])).entries()];
  const visible = movements.filter((movement) => {
    const attention = movement.provisional || movement.actions.length > 0 || movement.transfer?.state === "suggested";
    const haystack = [movement.date, movement.description, movement.account, movement.accountName, movement.display, movement.category.label, movement.subcategory.label, ...movement.tags.map((item) => item.label)].join(" ").toLocaleLowerCase();
    return (!query.trim() || haystack.includes(query.trim().toLocaleLowerCase()))
      && (!account || movement.accountId === account)
      && (!category || movement.category.id === category)
      && (!tag || movement.tags.some((item) => item.id === tag))
      && (!reviewState || (reviewState === "attention" ? attention : !attention));
  });
  const clearFilters = () => { setQuery(""); setAccount(""); setCategory(""); setTag(""); setReviewState(""); };
  useEffect(() => {
    if (!correction || correction.state.state !== "settled") return;
    const said = outcomeCopy(correction.state.result, correction.state.verb);
    if (correction.state.refresh === "refreshed" && said.completed) {
      const row = rows.current.get(correction.state.movementId);
      if (row) { row.focus(); return; }
    }
    outcomeRef.current?.focus();
  }, [correction?.state]);
  useEffect(() => {
    if (!selectedMovement) return;
    rows.current.get(selectedMovement)?.focus();
  }, [selectedMovement, data]);
  return <section className="feature-panel activity-panel" aria-labelledby="transactions-panel-title">
    <header className="activity-header"><div className="detail-panel-label">Current vault read</div><h2 id="transactions-panel-title">Transactions</h2><p>{data.sentence}</p></header>
    {correction ? <CorrectionStatus state={correction.state} outcomeRef={outcomeRef} /> : null}
    {!movements.length ? <div className="empty-state"><strong>No transactions in this read</strong><span>{data.sentence}</span></div> : <>
      <section className="activity-controls" aria-labelledby="transaction-filters-title"><h3 id="transaction-filters-title">Find transactions</h3><label className="activity-search">Search<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Description, account, category, tag, or amount" /></label><details><summary>Filters</summary><div className="activity-filter-grid"><label>Account<select value={account} onChange={(event) => setAccount(event.target.value)}><option value="">All accounts</option>{accounts.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>Tag<select value={tag} onChange={(event) => setTag(event.target.value)}><option value="">All tags</option>{tags.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>Review state<select value={reviewState} onChange={(event) => setReviewState(event.target.value)}><option value="">Any review state</option><option value="attention">Needs attention</option><option value="clear">No action waiting</option></select></label></div></details><button className="secondary-button" type="button" onClick={clearFilters}>Clear filters</button><p className="activity-result-count" aria-live="polite">{visible.length === 1 ? "1 transaction shown." : `${visible.length} transactions shown.`}</p></section>
      {!visible.length ? <div className="empty-state"><strong>No transactions match these filters</strong><span>Clear the search or filters to return to the full transaction list.</span><button className="secondary-button" type="button" onClick={clearFilters}>Clear filters</button></div> : <ul className="activity-movements">{visible.map((movement) => <li key={movement.id} ref={(node) => { if (node) rows.current.set(movement.id, node); else rows.current.delete(movement.id); }} tabIndex={-1} className={movement.direction === "in" ? "activity-movement inflow" : "activity-movement outflow"}>
        <span className="activity-movement-when">{movement.date}</span>
        <span className="activity-movement-what"><strong>{movement.description || "No description was recorded for this movement."}</strong><small>{movement.account}</small></span>
        <span className="activity-movement-amount"><strong>{movement.display}</strong><small>{movement.direction === "in" ? "in" : "out"}</small></span>
        {movement.sentence ? <p className="activity-movement-note">{movement.sentence}</p> : null}
        <dl className="activity-movement-classification"><div><dt>Category</dt><dd>{movement.category.valid ? movement.category.label : "Category unavailable from this read"}</dd></div><div><dt>Treatment</dt><dd>{movement.treatment.kind === "spending" ? "Counted as spending" : movement.treatment.kind === "loan" ? `Loan lent · ${movement.treatment.name}` : movement.treatment.kind === "loan_repayment" ? `Loan repayment received · ${movement.treatment.name}` : movement.treatment.kind === "settlement" ? "Debt settlement" : movement.treatment.kind === "mixed" ? "Split is unresolved" : "Not counted as spending"}</dd></div><div><dt>Tags</dt><dd>{movement.tagsValid ? (movement.tags.length ? movement.tags.map((tag) => tag.label).join(", ") : "No tags recorded") : "Tags unavailable from this read"}</dd></div></dl>
        {correction ? <MovementCorrection movement={movement} data={data} controls={correction} /> : null}
        <details className="activity-source"><summary>Source details</summary>{movement.evidenceLinksValid && movement.evidenceLinks.length ? <ProofLinks label="Source statements" links={movement.evidenceLinks} onOpen={onOpenEvidence} /> : <p>{movement.evidenceLinksValid ? "No source statement link was supplied for this transaction." : "Source details are unavailable from this read."}</p>}</details>
      </li>)}</ul>}
      {data.beyond && data.beyond.count > 0 ? <div className="activity-beyond"><p>{data.beyond.count} more are in this vault and not in this list.</p>{onLoadMore ? <button className="secondary-button" type="button" onClick={onLoadMore}>Load 50 more</button> : null}</div> : null}
    </>}
  </section>;
}

export function Activity({ result, correction, onOpenEvidence, onLoadMore = null, selectedMovement = "" }: ActivityProps) {
  return <PanelStateView result={result} copy={{ partial: "Some transaction details are unavailable. Available transactions are shown below.", needsInput: "Some transactions need more information. Available transactions are shown below.", unavailable: { title: "Transactions unavailable", detail: "Transactions are not connected to this vault read." }, failed: { title: "Transactions could not be read", detail: "Transactions could not be read. The vault is still open." } }}>{(data) => <Movements data={data} correction={correction ?? null} onLoadMore={onLoadMore} selectedMovement={selectedMovement} onOpenEvidence={onOpenEvidence} />}</PanelStateView>;
}
