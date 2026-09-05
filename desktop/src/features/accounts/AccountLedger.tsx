import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { AlertTriangle, Check, ChevronLeft, CopyCheck, HelpCircle, X } from "lucide-react";
import { channelPresentation, UNSPOKEN_REPLY } from "../../components/actionChannel";
import type { AccountLedgerData, AccountLedgerMovement, ActivityActionResult, ActivityCorrectionState, ActivityData, ConversationData, EvidenceLink, FeatureResult, MovementView, QuestionView, ReviewTransactionTarget } from "../../surface/types";

export type LedgerCorrectionResult = { result: ActivityActionResult; refresh: "refreshed" | "failed" } | null;
export type LedgerCorrectionControls = {
  state: ActivityCorrectionState;
  onAssignClassification: (movementIds: readonly string[], categoryId: string, subcategoryId: string) => Promise<LedgerCorrectionResult>;
  onAddTags: (movementIds: readonly string[], tagIds: readonly string[]) => Promise<LedgerCorrectionResult>;
  onRemoveTags: (movementIds: readonly string[], tagIds: readonly string[]) => Promise<LedgerCorrectionResult>;
};

type Props = {
  accountId: string;
  loadingAccountName?: string;
  requestedReviewTarget?: Readonly<ReviewTransactionTarget>;
  backLabel?: string;
  read: (accountId: string, cursor?: string, limit?: number) => Promise<FeatureResult<AccountLedgerData>>;
  activityResult: FeatureResult<ActivityData>;
  conversationResult: FeatureResult<ConversationData>;
  correction: LedgerCorrectionControls | null;
  onBack: () => void;
  onOpenEvidence: (link: EvidenceLink) => void;
  onOpenQuestion: (questionId: string, movementId?: string) => void;
  onReviewTransfer?: (movementId: string) => void;
  onDrawerOpenChange?: (open: boolean) => void;
  drawerActive?: boolean;
  renderOverlay?: (content: ReactNode) => ReactNode;
  pageTitleRef: RefObject<HTMLElement | null>;
};

type Filters = { text: string; from: string; to: string; category: string; subcategory: string; tag: string; treatment: string };
type ActionOrigin = { kind: "drawer" | "batch"; key: string };
const EMPTY_FILTERS: Filters = { text: "", from: "", to: "", category: "", subcategory: "", tag: "", treatment: "" };
const NARROW_FILTERS_QUERY = "(max-width: 620px)";

function batchFingerprint(ids: readonly string[]): string {
  return JSON.stringify(ids);
}

function actionableSelectionFingerprint(selection: ReadonlySet<string>, visibleIds: readonly string[]): string | null {
  const visible = new Set(visibleIds);
  if (!selection.size || [...selection].some((id) => !visible.has(id))) return null;
  const actionable = visibleIds.filter((id) => selection.has(id));
  return actionable.length === selection.size ? batchFingerprint(actionable) : null;
}

function sameOrigin(left: ActionOrigin | null, right: ActionOrigin): boolean {
  return left?.kind === right.kind && left.key === right.key;
}

function dataOf<T>(result: FeatureResult<T>): T | null {
  return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data : null;
}

function movements(data: AccountLedgerData): AccountLedgerMovement[] {
  return data.groups.flatMap((group) => group.movements);
}

function mergePage(current: AccountLedgerData, next: AccountLedgerData, requestedCursor: string, seenCursors: ReadonlySet<string>): { data: AccountLedgerData; firstId: string } | null {
  if (next.scope.kind !== current.scope.kind || next.scope.accountId !== current.scope.accountId || next.revision !== current.revision || next.page.limit !== current.page.limit) return null;
  if (JSON.stringify(next.account) !== JSON.stringify(current.account) || JSON.stringify(next.coverage) !== JSON.stringify(current.coverage) || JSON.stringify(next.reconciliation) !== JSON.stringify(current.reconciliation)) return null;
  const currentRows = movements(current); const nextRows = movements(next);
  const seen = new Set(currentRows.flatMap((row) => [row.id, ...row.deduplication.memberMovementIds]));
  const nextIds = nextRows.flatMap((row) => row.deduplication.memberMovementIds);
  if (!nextRows.length || nextRows.length !== next.page.returned || new Set(nextIds).size !== nextIds.length
      || nextRows.some((row) => row.deduplication.memberMovementIds.some((id) => seen.has(id)))) return null;
  if (current.page.remaining !== next.page.returned + next.page.remaining || (next.page.nextCursor !== null && (next.page.nextCursor === requestedCursor || seenCursors.has(next.page.nextCursor)))) return null;
  if ((next.page.remaining === 0) !== (next.page.nextCursor === null)) return null;
  const last = currentRows[currentRows.length - 1]; const first = nextRows[0];
  if (last && (first.date > last.date || (first.date === last.date && first.id >= last.id))) return null;
  const byMonth = new Map(current.groups.map((group) => [group.month, { ...group, movements: [...group.movements] }]));
  for (const group of next.groups) {
    const additions = [...group.movements];
    const prior = byMonth.get(group.month);
    if (prior) prior.movements.push(...additions);
    else byMonth.set(group.month, { ...group, movements: additions });
  }
  const sources = [...current.sources];
  const sourceById = new Map(sources.map((source) => [source.documentId, source]));
  for (const source of next.sources) {
    const repeated = sourceById.get(source.documentId);
    if (repeated && JSON.stringify(repeated) !== JSON.stringify(source)) return null;
    if (!repeated) { sources.push(source); sourceById.set(source.documentId, source); }
  }
  return { data: { ...next, sources, groups: [...byMonth.values()].filter((group) => group.movements.length > 0) }, firstId: first.id };
}

function exactQuestionForTarget(row: AccountLedgerMovement, target: Readonly<ReviewTransactionTarget>, questions: readonly QuestionView[]): QuestionView | null {
  if (row.id !== target.canonicalMovementId || row.accountId !== target.accountId
      || row.deduplication.canonicalMovementId !== target.canonicalMovementId
      || JSON.stringify(row.deduplication.memberMovementIds) !== JSON.stringify(target.memberMovementIds)
      || !target.memberMovementIds.includes(target.requestedMovementId)) return null;
  const exactQuestions = questions.filter((question) => question.id === target.questionId);
  if (exactQuestions.length !== 1) return null;
  const question = exactQuestions[0];
  const refs = question.refs;
  if (!refs) return null;
  const plural = refs.movements;
  const candidates = refs.candidates;
  if (refs.account !== undefined && refs.account !== target.accountId) return null;
  if (refs.movement !== undefined && refs.movement !== target.requestedMovementId) return null;
  if (plural !== undefined && (new Set(plural).size !== plural.length
      || plural.some((identity) => !target.memberMovementIds.includes(identity)))) return null;
  if (candidates !== undefined && (new Set(candidates).size !== candidates.length
      || candidates.some((identity) => !target.memberMovementIds.includes(identity)))) return null;
  const requestedByRefs = refs.movement === target.requestedMovementId
    || Boolean(plural?.length && plural[0] === target.requestedMovementId);
  if (!requestedByRefs) return null;
  if (refs.document && refs.doc_id && refs.document !== refs.doc_id) return null;
  const document = refs.document || refs.doc_id;
  if (document && !row.evidenceLinks.some((link) => link.targetDocumentId === document)) return null;
  return question;
}

function questionsFor(row: AccountLedgerMovement, questions: readonly QuestionView[]): QuestionView[] {
  const identities = new Set([row.id, ...row.deduplication.memberMovementIds]);
  const related = questions.filter((question) => (question.refs?.movement ? identities.has(question.refs.movement) : false) || Boolean(question.refs?.movements?.some((id) => identities.has(id))));
  return [...new Map(related.map((question) => [question.id, question])).values()];
}

function exactActivityMovement(row: AccountLedgerMovement, data: ActivityData | null): MovementView | null {
  if (!data) return null;
  const identities = new Set([row.id, ...row.deduplication.memberMovementIds]);
  const matches = data.movements.filter((movement) => movement.accountId === row.accountId && identities.has(movement.id));
  return matches.length === 1 ? matches[0] : null;
}

function treatmentLabel(row: AccountLedgerMovement): string {
  if (row.treatment.kind === "spending") return "Spending";
  if (row.treatment.kind === "loan") return `Loan · ${row.treatment.name}`;
  if (row.treatment.kind === "loan_repayment") return `Loan repayment · ${row.treatment.name}`;
  if (row.treatment.kind === "settlement") return "Debt settlement";
  if (row.treatment.kind === "mixed") return "Unresolved split";
  return "Not spending";
}

function markersFor(row: AccountLedgerMovement, questions: readonly QuestionView[]) {
  return [
    ...(questionsFor(row, questions).length ? [{ label: "Viva needs an answer", icon: <HelpCircle aria-hidden="true" className="account-ledger-icon" />, kind: "question" }] : []),
    ...(row.classification?.grade === "conflicted" ? [{ label: "Classification evidence conflicts", icon: <AlertTriangle aria-hidden="true" className="account-ledger-icon" />, kind: "conflict" }] : []),
    ...(row.transfer?.state === "suggested" ? [{ label: "Possible transfer needs a decision", icon: <CopyCheck aria-hidden="true" className="account-ledger-icon" />, kind: "transfer" }] : []),
  ];
}

function coverageLabel(data: AccountLedgerData): string {
  if (data.coverage.state === "unavailable") return "Statement coverage is unavailable.";
  if (data.coverage.state === "gapped") return `Coverage has ${data.coverage.gaps.length} missing period${data.coverage.gaps.length === 1 ? "" : "s"} across ${data.coverage.runs.length} supplied runs.`;
  if (data.coverage.state === "discontinuous") return `Coverage is discontinuous across ${data.coverage.runs.length} supplied runs.`;
  return "Statement coverage is continuous.";
}

function balanceStateLabel(data: AccountLedgerData): string {
  if (data.reconciliation.balance === "reconciled") return "Balance reconciled";
  if (data.reconciliation.balance === "conflicted") return "Balance evidence conflicts";
  return "Balance reconciliation unavailable";
}

function actionCopy(receipt: LedgerCorrectionResult, ledgerRead: "ready" | "failed") {
  if (!receipt) return { title: "Your vault did not answer", detail: "No correction result was available.", success: false };
  if (receipt.result.state !== "settled") return { ...channelPresentation(receipt.result), success: false };
  const detail = receipt.result.outcome.message.trim() || UNSPOKEN_REPLY;
  if (receipt.result.outcome.kind !== "completed") return { title: receipt.result.outcome.kind === "stale" ? "Correction out of date" : "Correction refused", detail, success: false };
  if (receipt.refresh === "failed" || ledgerRead === "failed") return { title: "Correction recorded; ledger refresh failed", detail: `${detail} The account ledger remains stale.`, success: false };
  return { title: "Correction recorded", detail, success: true };
}

function LedgerStatus({ working, receipt, ledgerRead }: { working: boolean; receipt: LedgerCorrectionResult | undefined; ledgerRead: "ready" | "failed" }) {
  if (working) return <div className="account-ledger-status" role="status" aria-live="polite">
<strong>Saving changes</strong>
<span>The old ledger stays on screen until the vault and account ledger have both been read again.</span>
</div>;
  if (receipt === undefined) return null;
  const copy = actionCopy(receipt, ledgerRead);
  return <div className={`account-ledger-status ${copy.success ? "success" : "failed"}`} role="status" aria-live="polite" tabIndex={-1}>
<strong>{copy.title}</strong>
<span>{copy.detail}</span>
</div>;
}

function ClassificationEditor({ ids, data, busy, initial, onSave }: { ids: readonly string[]; data: ActivityData; busy: boolean; initial?: AccountLedgerMovement; onSave: (category: string, subcategory: string) => void }) {
  const [category, setCategory] = useState(initial?.category.id ?? "");
  const [subcategory, setSubcategory] = useState(initial?.subcategory.id ?? "");
  const choices = data.vocabularies.subcategories.items.filter((item) => item.categoryId === category);
  useEffect(() => { setCategory(initial?.category.id ?? ""); setSubcategory(initial?.subcategory.id ?? ""); }, [initial?.id, initial?.category.id, initial?.subcategory.id]);
  function submit(event: FormEvent) { event.preventDefault(); if (!busy && category && subcategory) onSave(category, subcategory); }
  if (!data.vocabularies.categories.complete || !data.vocabularies.subcategories.complete) return <p className="account-ledger-unavailable">Category editing is unavailable because the complete category hierarchy was not supplied.</p>;
  return <form className="account-ledger-editor" onSubmit={submit}>
<label>Category<select value={category} aria-label={`Category for ${ids.length} selected transaction${ids.length === 1 ? "" : "s"}`} onChange={(event) => { setCategory(event.target.value); setSubcategory(""); }}>
<option value="">Choose a category</option>{data.vocabularies.categories.items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
</label>
<label>Subcategory<select value={subcategory} aria-label={`Subcategory for ${ids.length} selected transaction${ids.length === 1 ? "" : "s"}`} aria-disabled={!category} onChange={(event) => { if (category) setSubcategory(event.target.value); }}>
<option value="">Choose a subcategory</option>{choices.map((item) => <option key={`${item.categoryId}-${item.id}`} value={item.id}>{item.label}</option>)}</select>
</label>
<button className="secondary-button" type="submit" aria-disabled={busy || !category || !subcategory}>Save category and subcategory</button>
</form>;
}

function TagEditor({ ids, data, busy, resetKey, onAdd, onRemove }: { ids: readonly string[]; data: ActivityData; busy: boolean; resetKey: number; onAdd: (tags: readonly string[]) => void; onRemove: (tags: readonly string[]) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => { setSelected([]); }, [resetKey]);
  if (!data.vocabularies.tags.complete) return <p className="account-ledger-unavailable">Tag editing is unavailable because the complete tag vocabulary was not supplied.</p>;
  return <fieldset className="account-ledger-tag-editor">
<legend>Tags</legend>
<div>{data.vocabularies.tags.items.map((tag) => <label key={tag.id}>
<input type="checkbox" checked={selected.includes(tag.id)} onChange={(event) => { setSelected(event.target.checked ? [...selected, tag.id] : selected.filter((id) => id !== tag.id)); }} />{tag.label}</label>)}</div>
<span className="account-ledger-tag-actions">
<button className="secondary-button" type="button" aria-disabled={busy || !selected.length} onClick={() => { if (!busy && selected.length) onAdd(selected); }}>Add selected tags</button>
<button className="secondary-button" type="button" aria-disabled={busy || !selected.length} onClick={() => { if (!busy && selected.length) onRemove(selected); }}>Remove selected tags</button>
</span>
<small>Changes apply only to {ids.length === 1 ? "this transaction" : `the ${ids.length} checked transactions`} and preserve unrelated tags.</small>
</fieldset>;
}

function TransactionDrawer({ row, questions, data, canReviewTransfer, busy, working, showFeedback, blockedByOtherAction, receipt, ledgerRead, editorRevision, closeRef, drawerRef, onClose, onQuestion, onEvidence, onReviewTransfer, onClassification, onAddTags, onRemoveTags }: { row: AccountLedgerMovement; questions: readonly QuestionView[]; data: ActivityData | null; canReviewTransfer: boolean; busy: boolean; working: boolean; showFeedback: boolean; blockedByOtherAction: boolean; receipt: LedgerCorrectionResult | undefined; ledgerRead: "ready" | "failed"; editorRevision: number; closeRef: RefObject<HTMLButtonElement | null>; drawerRef: RefObject<HTMLElement | null>; onClose: () => void; onQuestion: (id: string) => void; onEvidence: (link: EvidenceLink) => void; onReviewTransfer: () => void; onClassification: (category: string, subcategory: string) => void; onAddTags: (tags: readonly string[]) => void; onRemoveTags: (tags: readonly string[]) => void }) {
  const related = questionsFor(row, questions);
  return <>
<div className="conversation-backdrop" aria-hidden="true" onClick={onClose} />
<aside ref={drawerRef} className="account-transaction-drawer" role="dialog" aria-modal="true" aria-labelledby="account-transaction-title" tabIndex={-1}>
<header>
<div>
<span className="detail-panel-label">Transaction details</span>
<h2 id="account-transaction-title">{row.description || "Description unavailable"}</h2>
</div>
<button ref={closeRef} type="button" className="conversation-close" aria-label="Close transaction details" onClick={onClose}>
<X className="account-ledger-icon" />
</button>
</header>
{showFeedback ? <LedgerStatus working={working} receipt={receipt} ledgerRead={ledgerRead} /> : blockedByOtherAction ? <div className="account-ledger-status" role="status" aria-live="polite"><strong>Another change is being saved</strong><span>You can stage edits here now; saving this transaction will be available when the earlier transaction change finishes.</span></div> : null}
<section>
<h3>Transaction summary</h3>
<dl className="account-transaction-summary">
<div>
<dt>Date</dt>
<dd>{row.date}</dd>
</div>
<div>
<dt>Amount</dt>
<dd>{row.display}</dd>
</div>
<div>
<dt>Account</dt>
<dd>{row.accountName}</dd>
</div>
<div>
<dt>Direction</dt>
<dd>{row.directionDisplay}</dd>
</div>
</dl>
</section>{related.length ? <section>
<h3>Required decision</h3>{related.map((question) => <article key={question.id}>
<strong>{question.label}</strong>
<p>{question.detail}</p>
<button className="secondary-button" type="button" onClick={() => onQuestion(question.id)}>Answer this question</button>
</article>)}</section> : null}{row.transfer?.state === "suggested" ? <section className="account-ledger-transfer" aria-label="Possible transfer">
<h3>Possible transfer</h3>
<p>{row.transfer.explanation}</p>
<div className="account-ledger-transfer-candidates">{row.transfer.candidates.map((candidate) => <article key={candidate.id} aria-label={`Possible counterpart ${candidate.description}`}>
<h4>{candidate.description}</h4>
<dl className="account-transaction-summary">
<div><dt>Other account</dt><dd>{candidate.accountName}</dd></div>
<div><dt>Account identity</dt><dd>{candidate.accountId}</dd></div>
<div><dt>Date</dt><dd>{candidate.date}</dd></div>
<div><dt>Amount</dt><dd>{candidate.display}</dd></div>
<div><dt>Direction</dt><dd>{candidate.direction}</dd></div>
</dl>
<p>{candidate.relationship}</p>
</article>)}</div>
{canReviewTransfer ? <button className="secondary-button" type="button" onClick={onReviewTransfer}>Review transfer controls in Transactions</button> : null}
</section> : row.transfer?.state === "linked" ? <section className="account-ledger-transfer" aria-label="Linked transfer">
<h3>Linked transfer</h3>
<p>{row.transfer.explanation}</p>
<h4>{row.transfer.counterpart.description}</h4>
<dl className="account-transaction-summary">
<div><dt>Other account</dt><dd>{row.transfer.counterpart.accountName}</dd></div>
<div><dt>Account identity</dt><dd>{row.transfer.counterpart.accountId}</dd></div>
<div><dt>Date</dt><dd>{row.transfer.counterpart.date}</dd></div>
<div><dt>Amount</dt><dd>{row.transfer.counterpart.display}</dd></div>
<div><dt>Direction</dt><dd>{row.transfer.counterpart.direction}</dd></div>
</dl>
<p>{row.transfer.relationship}</p>
{canReviewTransfer ? <button className="secondary-button" type="button" onClick={onReviewTransfer}>Review transfer controls in Transactions</button> : null}
</section> : null}<section>
<h3>Category and subcategory</h3>
<p>{row.category.valid ? row.category.label : "Category unavailable"}{row.subcategory.id ? ` · ${row.subcategory.label}` : " · No subcategory"}</p>{row.classification ? <p>{row.classification.provenance} · {row.classification.grade}</p> : null}{data ? <ClassificationEditor ids={[row.id]} data={data} busy={busy} initial={row} onSave={onClassification} /> : <p className="account-ledger-unavailable">Editing is unavailable from this read.</p>}</section>
<section>
<h3>Tags</h3>
<p>{row.tags.length ? row.tags.map((tag) => tag.label).join(", ") : "No tags recorded"}</p>{data ? <TagEditor ids={[row.id]} data={data} busy={busy} resetKey={editorRevision} onAdd={onAddTags} onRemove={onRemoveTags} /> : null}</section>
<section>
<h3>Treatment and status</h3>
<p>{treatmentLabel(row)}</p>{row.sentence ? <p>{row.sentence}</p> : null}</section>
<section>
<h3>Source evidence</h3>{row.evidenceLinks.length ? row.evidenceLinks.map((link) => <button className="proof-link" type="button" key={`${link.targetDocumentId}-${link.page}-${link.region}`} onClick={() => onEvidence(link)}>{link.label || "Source document"}{link.page ? ` · page ${link.page}` : ""}{link.region ? ` · ${link.region}` : ""}</button>) : <p>No transaction-level source location was supplied.</p>}</section>
</aside>
</>;
}

export function AccountLedger({ accountId, loadingAccountName, requestedReviewTarget, backLabel = "Back to accounts", read, activityResult, conversationResult, correction, onBack, onOpenEvidence, onOpenQuestion, onReviewTransfer = () => undefined, onDrawerOpenChange = () => undefined, drawerActive = true, renderOverlay = (content) => content, pageTitleRef }: Props) {
  const [result, setResult] = useState<FeatureResult<AccountLedgerData> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawerId, setDrawerId] = useState("");
  const [working, setWorking] = useState(false);
  const [receipt, setReceipt] = useState<LedgerCorrectionResult | undefined>(undefined);
  const [ledgerRead, setLedgerRead] = useState<"ready" | "failed">("ready");
  const [actionOrigin, setActionOrigin] = useState<ActionOrigin | null>(null);
  const [successfulEdit, setSuccessfulEdit] = useState<{ origin: ActionOrigin; revision: number } | null>(null);
  const [narrowFilters, setNarrowFilters] = useState(() => typeof globalThis.matchMedia === "function" && globalThis.matchMedia(NARROW_FILTERS_QUERY).matches);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [requestedLocation, setRequestedLocation] = useState<"idle" | "locating" | "not_found" | "bounded" | "failed">("idle");
  const generation = useRef(0);
  const actionRequest = useRef(0);
  const paginationRequest = useRef(0);
  const actionInFlight = useRef(false);
  const cursorsSeen = useRef(new Set<string>());
  const selectedRef = useRef<ReadonlySet<string>>(selected);
  const visibleIdsRef = useRef<readonly string[]>([]);
  const readRef = useRef(read);
  readRef.current = read;
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerOpenerRef = useRef<HTMLElement | null>(null);
  const requestedDrawerDismissed = useRef(false);
  const drawerWasActive = useRef(drawerActive);
  const backRef = useRef<HTMLButtonElement>(null);
  const requestedTargetIdentity = requestedReviewTarget ? JSON.stringify(requestedReviewTarget) : "";

  function closeDrawer(restoreFocus: boolean) {
    const target = drawerOpenerRef.current;
    if (requestedReviewTarget) requestedDrawerDismissed.current = true;
    setDrawerId("");
    onDrawerOpenChange(false);
    if (restoreFocus) requestAnimationFrame(() => (target?.isConnected ? target : pageTitleRef.current)?.focus());
  }

  function openDrawer(movementId: string, opener: HTMLElement | null = null) {
    drawerOpenerRef.current = opener;
    setDrawerId(movementId);
    onDrawerOpenChange(true);
  }

  useLayoutEffect(() => {
    if (!drawerId) return undefined;
    const rootOverflow = document.documentElement.style.overflow;
    const bodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const focusable = () => [...(drawerRef.current?.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])') ?? [])].filter((element) => element.getAttribute("aria-disabled") !== "true");
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeDrawer(true); return; }
      if (event.key !== "Tab") return;
      const available = focusable();
      if (!available.length) { event.preventDefault(); drawerRef.current?.focus(); return; }
      const first = available[0]; const last = available[available.length - 1];
      if (!available.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const onFocusIn = (event: FocusEvent) => { if (drawerRef.current && event.target instanceof Node && !drawerRef.current.contains(event.target)) (closeRef.current ?? drawerRef.current).focus(); };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => { document.removeEventListener("keydown", onKeyDown); document.removeEventListener("focusin", onFocusIn); document.documentElement.style.overflow = rootOverflow; document.body.style.overflow = bodyOverflow; };
  }, [drawerId]);

  useEffect(() => {
    if (drawerId && drawerWasActive.current && !drawerActive) setDrawerId("");
    drawerWasActive.current = drawerActive;
  }, [drawerActive, drawerId]);

  useEffect(() => { requestedDrawerDismissed.current = false; }, [accountId, requestedTargetIdentity]);

  useEffect(() => {
    if (typeof globalThis.matchMedia !== "function") { setNarrowFilters(false); return undefined; }
    const media = globalThis.matchMedia(NARROW_FILTERS_QUERY);
    const update = (event: MediaQueryListEvent | MediaQueryList) => setNarrowFilters(event.matches);
    update(media);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", update);
      return () => media.removeEventListener("change", update);
    }
    media.addListener(update);
    return () => media.removeListener(update);
  }, []);

  async function replaceRead(capturedGeneration: number, capturedAccount: string) {
    const next = await readRef.current(capturedAccount);
    if (capturedGeneration !== generation.current || capturedAccount !== accountId) return false;
    const nextData = dataOf(next);
    if (!nextData || nextData.scope.accountId !== capturedAccount) return false;
    setResult(next);
    return true;
  }

  useEffect(() => {
    const current = ++generation.current;
    actionRequest.current += 1; paginationRequest.current += 1; actionInFlight.current = false; cursorsSeen.current = new Set();
    setResult(null); setFilters(EMPTY_FILTERS); setFiltersExpanded(false); setSelected(new Set()); setDrawerId(""); onDrawerOpenChange(false); setReceipt(undefined); setActionOrigin(null); setSuccessfulEdit(null); setLoadMoreFailed(false); setWorking(false); setRequestedLocation(requestedReviewTarget ? "locating" : "idle");
    void (async () => {
      try {
        const first = await readRef.current(accountId);
        if (current !== generation.current) return;
        const firstData = dataOf(first);
        if (!firstData || firstData.scope.accountId !== accountId) {
          setResult(firstData ? { state: "failed", reason: "invalid_payload" } : first);
          if (requestedReviewTarget) setRequestedLocation("failed");
          return;
        }
        let combined = firstData;
        let nextCursor = combined.page.nextCursor;
        const seen = new Set<string>();
        let continuations = 0;
        const requestedQuestions = dataOf(conversationResult)?.questions.queue ?? [];
        const exactRow = () => requestedReviewTarget && combined.scope.accountId === requestedReviewTarget.accountId
          && combined.account.id === requestedReviewTarget.accountId
          ? movements(combined).find((row) => exactQuestionForTarget(row, requestedReviewTarget, requestedQuestions)) : undefined;
        let found = exactRow();
        while (requestedReviewTarget && !found && nextCursor && continuations < 3) {
          const cursor = nextCursor;
          const page = await readRef.current(accountId, cursor, combined.page.limit);
          if (current !== generation.current) return;
          const pageData = dataOf(page);
          const merged = pageData ? mergePage(combined, pageData, cursor, seen) : null;
          if (!merged) { setResult({ state: "ready", data: combined }); setRequestedLocation("failed"); return; }
          seen.add(cursor); combined = merged.data; nextCursor = combined.page.nextCursor; continuations += 1; found = exactRow();
        }
        setResult({ state: "ready", data: combined });
        cursorsSeen.current = seen;
        if (requestedReviewTarget) {
          if (found) { setRequestedLocation("idle"); if (!requestedDrawerDismissed.current) openDrawer(found.id); }
          else setRequestedLocation(nextCursor ? "bounded" : "not_found");
        }
      } catch {
        if (current === generation.current) { setResult({ state: "failed", reason: "read_failed" }); if (requestedReviewTarget) setRequestedLocation("failed"); }
      }
    })();
    return () => { generation.current += 1; };
  }, [accountId, requestedReviewTarget, conversationResult]);

  const data = result ? dataOf(result) : null;
  const allRows = useMemo(() => data ? movements(data) : [], [data]);
  const conversation = dataOf(conversationResult);
  const questions = conversation?.questions.queue ?? [];
  const activity = dataOf(activityResult);
  const categories = [...new Map(allRows.filter((row) => row.category.id).map((row) => [row.category.id!, row.category.label])).entries()];
  const subcategories = [...new Map(allRows.filter((row) => row.subcategory.id).map((row) => [row.subcategory.id!, row.subcategory.label])).entries()];
  const tags = [...new Map(allRows.flatMap((row) => row.tags).map((tag) => [tag.id, tag.label])).entries()];
  const treatments = [...new Set(allRows.map((row) => row.treatment.kind))];
  const visible = allRows.filter((row) => {
    const text = `${row.description} ${row.category.label} ${row.subcategory.label} ${row.tags.map((tag) => tag.label).join(" ")}`.toLocaleLowerCase();
    return (!filters.text || text.includes(filters.text.toLocaleLowerCase())) && (!filters.from || row.date >= filters.from) && (!filters.to || row.date <= filters.to) && (!filters.category || row.category.id === filters.category) && (!filters.subcategory || row.subcategory.id === filters.subcategory) && (!filters.tag || row.tags.some((tag) => tag.id === filters.tag)) && (!filters.treatment || row.treatment.kind === filters.treatment);
  });
  const visibleIds = visible.map((row) => row.id);
  selectedRef.current = selected;
  visibleIdsRef.current = visibleIds;
  const visibleSet = new Set(visibleIds);
  const selectedIds = visibleIds.filter((id) => selected.has(id));
  const currentBatchOrigin: ActionOrigin = { kind: "batch", key: batchFingerprint(selectedIds) };
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const activeFilters = [
    filters.text ? `Search: ${filters.text}` : "",
    filters.from ? `From: ${filters.from}` : "",
    filters.to ? `To: ${filters.to}` : "",
    filters.category ? `Category: ${categories.find(([id]) => id === filters.category)?.[1] ?? filters.category}` : "",
    filters.subcategory ? `Subcategory: ${subcategories.find(([id]) => id === filters.subcategory)?.[1] ?? filters.subcategory}` : "",
    filters.tag ? `Tag: ${tags.find(([id]) => id === filters.tag)?.[1] ?? filters.tag}` : "",
    filters.treatment ? `Type: ${filters.treatment.replaceAll("_", " ")}` : "",
  ].filter(Boolean);
  const drawerRow = allRows.find((row) => row.id === drawerId) ?? null;
  const requestedQuestion = requestedReviewTarget ? allRows.map((row) => exactQuestionForTarget(row, requestedReviewTarget, questions)).find((question) => question !== null) ?? null : null;
  const displayedQuestions = requestedReviewTarget ? (requestedQuestion ? [requestedQuestion] : []) : questions;
  const activityMovement = drawerRow ? exactActivityMovement(drawerRow, activity) : null;
  const canReviewTransfer = Boolean(activityMovement && (activityMovement.actions.includes("confirm_transfer") || activityMovement.actions.includes("reject_transfer") || activityMovement.actions.includes("unlink_transfer")));
  const currentDrawerOrigin: ActionOrigin | null = drawerRow ? { kind: "drawer", key: drawerRow.id } : null;
  const drawerOwnsFeedback = currentDrawerOrigin ? sameOrigin(actionOrigin, currentDrawerOrigin) : false;
  const batchOwnsFeedback = sameOrigin(actionOrigin, currentBatchOrigin);
  const busy = working || correction?.state.state === "working" || correction?.state.state === "refreshing";

  useEffect(() => {
    setSelected((current) => {
      const next = new Set([...current].filter((id) => visibleSet.has(id)));
      return next.size === current.size && [...next].every((id) => current.has(id)) ? current : next;
    });
  }, [accountId, result, filters.text, filters.from, filters.to, filters.category, filters.subcategory, filters.tag, filters.treatment]);

  async function run(origin: ActionOrigin, requestedIds: readonly string[], command: (movementIds: readonly string[]) => Promise<LedgerCorrectionResult>, clearAfterSuccess: boolean) {
    if (busy || actionInFlight.current) return;
    const actionable = requestedIds.filter((id, index) => visibleSet.has(id) && requestedIds.indexOf(id) === index);
    if (!actionable.length || actionable.length !== requestedIds.length) return;
    const capturedGeneration = generation.current; const capturedAccount = accountId; const request = ++actionRequest.current;
    actionInFlight.current = true;
    setActionOrigin(origin); setWorking(true); setReceipt(undefined);
    try {
      const nextReceipt = await command(actionable);
      if (capturedGeneration !== generation.current || capturedAccount !== accountId || request !== actionRequest.current) return;
      let refreshed = false;
      if (nextReceipt?.result.state === "settled" && nextReceipt.result.outcome.kind === "completed" && nextReceipt.refresh === "refreshed") {
        try { refreshed = await replaceRead(capturedGeneration, capturedAccount); }
        catch { refreshed = false; }
      }
      if (capturedGeneration !== generation.current || capturedAccount !== accountId || request !== actionRequest.current) return;
      setLedgerRead(refreshed || nextReceipt?.result.state !== "settled" || nextReceipt.result.outcome.kind !== "completed" ? "ready" : "failed");
      setReceipt(nextReceipt);
      if (refreshed) {
        setSuccessfulEdit((current) => ({ origin, revision: (current?.revision ?? 0) + 1 }));
        if (clearAfterSuccess && actionableSelectionFingerprint(selectedRef.current, visibleIdsRef.current) === origin.key) {
          setSelected((current) => {
            const liveVisibility = visibleIdsRef.current;
            if (actionableSelectionFingerprint(current, liveVisibility) !== origin.key) return current;
            const next = new Set<string>();
            selectedRef.current = next;
            return next;
          });
        }
      }
    } catch { if (capturedGeneration === generation.current && capturedAccount === accountId && request === actionRequest.current) { setReceipt(null); setLedgerRead("failed"); } }
    finally { if (capturedGeneration === generation.current && capturedAccount === accountId && request === actionRequest.current) { actionInFlight.current = false; setWorking(false); } }
  }

  async function loadMore() {
    if (!data?.page.nextCursor || loadingMore) return;
    const current = data; const requestedCursor = current.page.nextCursor;
    if (!requestedCursor) return;
    const capturedGeneration = generation.current; const capturedAccount = accountId; const request = ++paginationRequest.current;
    setLoadingMore(true); setLoadMoreFailed(false);
    try {
      const next = await readRef.current(capturedAccount, requestedCursor, current.page.limit);
      if (capturedGeneration !== generation.current || capturedAccount !== accountId || request !== paginationRequest.current) return;
      const page = dataOf(next);
      const merged = page ? mergePage(current, page, requestedCursor, cursorsSeen.current) : null;
      if (!merged) setLoadMoreFailed(true);
      else {
        cursorsSeen.current.add(requestedCursor);
        setResult({ state: "ready", data: merged.data });
        requestAnimationFrame(() => document.getElementById(`ledger-row-${merged.firstId}`)?.focus());
      }
    } catch { if (capturedGeneration === generation.current && capturedAccount === accountId && request === paginationRequest.current) setLoadMoreFailed(true); }
    finally { if (capturedGeneration === generation.current && capturedAccount === accountId && request === paginationRequest.current) setLoadingMore(false); }
  }

  if (result === null) return <section className="feature-panel account-ledger-state" aria-live="polite">
<button className="text-button" type="button" onClick={onBack}>
<ChevronLeft className="account-ledger-icon" />{backLabel}</button>
<div className="empty-state">
{loadingAccountName ? <h2>{loadingAccountName}</h2> : null}
<strong>Reading account ledger</strong>
<span>Loading this account’s stitched transaction history…</span>
</div>
</section>;
  if (!data) {
    const copy = result.state === "absent" && result.reason === "stale_read" ? ["Account ledger changed", "This read became stale before it could be shown. Return to accounts and open it again."] : result.state === "unavailable" || result.state === "absent" ? ["Account ledger unavailable", "This vault did not supply a ledger for the selected account."] : ["Account ledger could not be read", "No transaction from the failed read is being shown."];
    return <section className="feature-panel account-ledger-state">
<button ref={backRef} className="text-button" type="button" onClick={onBack}>
<ChevronLeft className="account-ledger-icon" />{backLabel}</button>
<div className="empty-state">
{loadingAccountName ? <h2>{loadingAccountName}</h2> : null}
<strong>{copy[0]}</strong>
<span>{copy[1]}</span>{requestedReviewTarget ? <button className="secondary-button" type="button" onClick={() => onOpenQuestion(requestedReviewTarget.questionId)}>Answer in conversation</button> : null}
</div>
</section>;
  }

  const groupedVisible = data.groups.map((group) => ({ ...group, movements: group.movements.filter((row) => visibleIds.includes(row.id)) })).filter((group) => group.movements.length);
  const emptyTitle = allRows.length ? "No matching transactions" : "No transactions in this account ledger";
  const emptyDetail = allRows.length ? "Clear or change the active filters to show loaded transactions." : "No transaction rows were supplied for this account.";
  const loadMoreNotice = loadMoreFailed ? <div className="account-ledger-status failed" role="status">
<strong>Ledger continuation could not be verified</strong>
<span>The transactions and continuation already loaded remain on screen. Try loading more again.</span>
</div> : null;
  const requestedFallback = requestedReviewTarget ? <button className="secondary-button" type="button" onClick={() => onOpenQuestion(requestedReviewTarget.questionId)}>Answer in conversation</button> : null;
  const requestedLocationNotice = requestedLocation === "locating" ? <div className="account-ledger-status" role="status" aria-live="polite"><strong>Locating exact transaction</strong><span>Reading bounded ledger pages until the referenced canonical row is found.</span></div>
    : requestedLocation === "not_found" ? <div className="account-ledger-status failed" role="status"><strong>Referenced transaction is not in this account ledger</strong><span>No transaction was opened. Answer the existing question in its conversation instead.</span>{requestedFallback}</div>
      : requestedLocation === "bounded" ? <div className="account-ledger-status failed" role="status"><strong>Referenced transaction is beyond the bounded search</strong><span>No transaction was opened. You can load more deterministically or answer in the conversation; the interface will not choose another row.</span>{requestedFallback}</div>
        : requestedLocation === "failed" ? <div className="account-ledger-status failed" role="status"><strong>Referenced transaction could not be verified</strong><span>No transaction was opened from this request. Answer the existing question in its conversation instead.</span>{requestedFallback}</div> : null;
  const filterControls = <section className="account-ledger-filters" aria-label="Transaction filters">
<label>Search<input type="search" value={filters.text} onChange={(event) => setFilters({ ...filters, text: event.target.value })} />
</label>
<label>From<input type="date" value={filters.from} onChange={(event) => setFilters({ ...filters, from: event.target.value })} />
</label>
<label>To<input type="date" value={filters.to} onChange={(event) => setFilters({ ...filters, to: event.target.value })} />
</label>{categories.length ? <label>Category<select value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })}>
<option value="">All categories</option>{categories.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
</label> : null}{subcategories.length ? <label>Subcategory<select value={filters.subcategory} onChange={(event) => setFilters({ ...filters, subcategory: event.target.value })}>
<option value="">All subcategories</option>{subcategories.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
</label> : null}{tags.length ? <label>Tag<select value={filters.tag} onChange={(event) => setFilters({ ...filters, tag: event.target.value })}>
<option value="">All tags</option>{tags.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
</label> : null}{treatments.length ? <label>Type<select value={filters.treatment} onChange={(event) => setFilters({ ...filters, treatment: event.target.value })}>
<option value="">All transaction types</option>{treatments.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select>
</label> : null}<div className="account-ledger-filter-summary">
<span>{visible.length} visible of {allRows.length} loaded transactions</span>{activeFilterCount ? <>
{activeFilters.map((label) => <span key={label} className="account-ledger-filter-chip">{label}</span>)}
<button type="button" className="text-button" onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</button>
</> : null}</div>
</section>;
  return <>
<section className="account-ledger-page" inert={drawerRow ? true : undefined}>
<header className="account-ledger-heading">
<button ref={backRef} className="text-button" type="button" onClick={onBack}>
<ChevronLeft className="account-ledger-icon" />{backLabel}</button>
<div>
<span className="detail-panel-label">{data.account.type} · {data.account.maskedNumber}</span>
<h2>{data.account.name}</h2>{data.account.balance.state === "available" ? <p className="account-ledger-balance">
<strong>{data.account.balance.display}</strong>
<span>{data.account.balance.kind === "amount_owed" ? "Amount owed" : "Current balance"} · {data.account.balance.asOf} · Evidence {data.account.balance.grade}</span>
</p> : <p>Balance unavailable: this ledger has no authoritative balance observation.</p>}</div>
<p className={`account-ledger-balance-state balance-${data.reconciliation.balance}`}>{balanceStateLabel(data)}</p>
</header>
<section className="account-ledger-coverage" aria-label="Source coverage">
<strong>Source coverage</strong>
<span>{coverageLabel(data)}</span>{data.coverage.gaps.map((gap) => <span className="account-ledger-gap" key={`${gap.from}-${gap.to}`}>Missing statement coverage: {gap.from} to {gap.to}</span>)}<details>
<summary>Overlap and duplicate handling</summary>
<p>{data.reconciliation.overlap.state === "none_observed" ? "No overlapping statement periods were observed." : `${data.reconciliation.overlap.groups.length} overlapping statement period${data.reconciliation.overlap.groups.length === 1 ? " was" : "s were"} found.`}</p>
<p>{data.reconciliation.overlap.deduplication.collapsed.length} exact duplicate posting group{data.reconciliation.overlap.deduplication.collapsed.length === 1 ? " was" : "s were"} collapsed; {data.reconciliation.overlap.deduplication.unresolved.length} candidate pair{data.reconciliation.overlap.deduplication.unresolved.length === 1 ? " remains" : "s remain"} unresolved.</p>
<p>Running balance is omitted because it is not authoritatively available.</p>
</details>
</section>
{!drawerRow && actionOrigin?.kind === "batch" && (batchOwnsFeedback || (!working && selectedIds.length === 0)) ? <LedgerStatus working={working} receipt={receipt} ledgerRead={ledgerRead} /> : null}
{loadMoreNotice}
{requestedLocationNotice}
{narrowFilters ? <details className="account-ledger-filter-disclosure" open={filtersExpanded} onToggle={(event) => setFiltersExpanded(event.currentTarget.open)}>
<summary>Filters <span>{visible.length} visible · {activeFilterCount ? `${activeFilterCount} active` : "none active"}</span></summary>
{filterControls}
</details> : filterControls}{visible.length ? <label className="account-ledger-select-visible">
<input type="checkbox" checked={visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))} onChange={(event) => setSelected((current) => { const next = new Set(current); visibleIds.forEach((id) => event.target.checked ? next.add(id) : next.delete(id)); return next; })} />Select visible loaded transactions only</label> : null}{selectedIds.length && activity && correction ? <section className="account-ledger-batch" aria-label="Batch edit selected transactions">
<strong>{selectedIds.length} selected</strong>
{busy && !batchOwnsFeedback ? <div className="account-ledger-status" role="status" aria-live="polite"><strong>Another change is being saved</strong><span>You can stage batch edits now; saving them will be available when the earlier transaction change finishes.</span></div> : null}
<ClassificationEditor ids={selectedIds} data={activity} busy={busy} onSave={(category, subcategory) => void run(currentBatchOrigin, selectedIds, (ids) => correction.onAssignClassification(ids, category, subcategory), true)} />
<TagEditor ids={selectedIds} data={activity} busy={busy} resetKey={successfulEdit && sameOrigin(successfulEdit.origin, currentBatchOrigin) ? successfulEdit.revision : 0} onAdd={(tagIds) => void run(currentBatchOrigin, selectedIds, (ids) => correction.onAddTags(ids, tagIds), true)} onRemove={(tagIds) => void run(currentBatchOrigin, selectedIds, (ids) => correction.onRemoveTags(ids, tagIds), true)} />
</section> : null}<div className="account-ledger-groups">{groupedVisible.map((group) => <section key={group.month} aria-labelledby={`ledger-month-${group.month}`}>
<h3 id={`ledger-month-${group.month}`}>{group.label}</h3>
<ul>{group.movements.map((row) => { const markers = markersFor(row, displayedQuestions); return <li key={row.id} id={`ledger-row-${row.id}`} tabIndex={-1} className={`account-ledger-row ${markers.map((marker) => `attention-${marker.kind}`).join(" ")}`}>
<label className="account-ledger-check">
<input type="checkbox" aria-label={`Select ${row.description || row.id}`} checked={selected.has(row.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); event.target.checked ? next.add(row.id) : next.delete(row.id); return next; })} />
</label><span className="account-ledger-markers">{markers.map((marker) => <span key={marker.kind} className={`account-ledger-marker marker-${marker.kind}`} title={marker.label} aria-label={marker.label}>{marker.icon}</span>)}</span><button type="button" className="account-ledger-row-button" onClick={(event) => openDrawer(row.id, event.currentTarget)}>
<span className="account-ledger-date">{row.date}</span>
<span className="account-ledger-description">
<strong>{row.description || "Description unavailable"}</strong>
<small>{row.category.label}{row.subcategory.id ? ` · ${row.subcategory.label}` : ""}{row.tags.length ? ` · ${row.tags.map((tag) => tag.label).join(", ")}` : ""}</small>
</span>
<span className="account-ledger-amount">
<strong>{row.display}</strong>
<small>{row.directionDisplay} · {treatmentLabel(row)}</small>
</span>
</button>
</li>; })}</ul>
</section>)}</div>{!visible.length ? <div className="empty-state">
<strong>{emptyTitle}</strong>
<span>{emptyDetail}</span>
</div> : null}{data.page.nextCursor ? <button id="account-ledger-load-more" className="secondary-button account-ledger-load-more" type="button" aria-disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "Loading more…" : `Load more (${data.page.remaining} remaining)`}</button> : null}</section>{drawerRow && currentDrawerOrigin ? renderOverlay(<TransactionDrawer row={drawerRow} questions={displayedQuestions} data={activity} canReviewTransfer={canReviewTransfer} busy={busy} working={working} showFeedback={drawerOwnsFeedback} blockedByOtherAction={busy && !drawerOwnsFeedback} receipt={receipt} ledgerRead={ledgerRead} editorRevision={successfulEdit && sameOrigin(successfulEdit.origin, currentDrawerOrigin) ? successfulEdit.revision : 0} closeRef={closeRef} drawerRef={drawerRef} onClose={() => closeDrawer(true)} onQuestion={(questionId) => { const movementId = drawerRow.id; closeDrawer(false); onOpenQuestion(questionId, movementId); }} onEvidence={(link) => { closeDrawer(false); onOpenEvidence(link); }} onReviewTransfer={() => { const movementId = activityMovement?.id ?? drawerRow.id; closeDrawer(false); onReviewTransfer(movementId); }} onClassification={(category, subcategory) => correction && void run(currentDrawerOrigin, [drawerRow.id], (ids) => correction.onAssignClassification(ids, category, subcategory), false)} onAddTags={(tagIds) => correction && void run(currentDrawerOrigin, [drawerRow.id], (ids) => correction.onAddTags(ids, tagIds), false)} onRemoveTags={(tagIds) => correction && void run(currentDrawerOrigin, [drawerRow.id], (ids) => correction.onRemoveTags(ids, tagIds), false)} />) : null}</>;
}
