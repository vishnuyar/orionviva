import retainedCopy from "./bulk-retained-reading-v1.json";
import bulkCopy from "./bulk-upload-v1.json";
import { BulkDocumentSelection } from "./BulkDocumentSelection";
import type { BulkDocumentControls } from "./BulkDocumentSelection";
import { OriginalPreview } from "../../components/OriginalPreview";
import { useLayoutEffect, useRef, useState } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ChannelPresentation } from "../../components/actionChannel";
import type { CancelActionState, CaptureActionState, DocumentsData, EvidenceLink, FeatureResult, JobView, RescanActionState, SurfaceDocument, RetainedReadingSelection } from "../../surface/types";
import { documentRowLabel, resolveDocumentSelection } from "./documentPresentation";

// What a screen needs to say what became of a capture, and — where the host
// offers a way to choose a file — to start one. A source that cannot take a
// file at all carries none of this, so the control is absent rather than
// present and refusing; a host that can receive a dropped file but offers no
// picker carries the state without the control.
//
// `job` is what the sidecar last said about the work this screen started, or
// nothing. `onStop` is present only where the source can carry a stop, so a
// screen with nothing behind the control renders no control rather than one
// that would have to refuse.
export type CaptureControls = { state: CaptureActionState; onChoose: (() => void) | null; job: JobView | null; cancel: CancelActionState; onStop: ((jobId: string) => void) | null };
// What a screen needs to send this vault back over what it already holds, and
// to say what came of it. A source that cannot do it carries none of this.
export type RescanControls = { state: RescanActionState; onRescan: () => void; onReviewMovement?: (movementId: string) => void };
export type RetainedReadingControls = { selection: readonly RetainedReadingSelection[]; blocked: boolean; canSelect: (document: SurfaceDocument) => boolean; onAdd: (document: SurfaceDocument) => void; onRemove: (documentId: string) => void; onConfirm: () => void };
type DocumentsProps = { retained?: RetainedReadingControls; bulk?: BulkDocumentControls; onSourcePageConsumed?: (nonce: number) => void; sourcePageRequest?: { documentId: string; page: number; nonce: number }; paging?: { busy: boolean; notice: string; canPrevious: boolean; retrySelected?: () => void | Promise<void>; first: () => void | Promise<void>; previous: () => void | Promise<void>; next: () => void | Promise<void> }; previewReader?: import("../../surface/types").DocumentPreviewReader; subscribePreviewEnd?: (clear: () => void) => () => void; onOpenReview?: () => void; recoveryJobs?: readonly JobView[]; onRecoverDocument?: (jobId: string) => void; onOpenSettings?: () => void; rescan: RescanControls | null; result: FeatureResult<DocumentsData>; selectedDocument: string; capture: CaptureControls | null; jobStatus?: "available" | "unavailable"; jobCheck?: "idle" | "checking" | "failed" | "succeeded"; onRecheckJobs?: () => void; onSelectDocument: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onExploreSample: () => void; openingSample?: boolean };

// The one sentence this panel says, and the only place it is said. What the
// vault answered the last capture with stands until the next capture; where
// nothing has been captured in this session, the sentence the read wrote for
// the panel stands instead. Every one of them was written elsewhere.
function capturePresentation(state: CaptureActionState, panelSentence: string): ChannelPresentation | null {
  const reported = state.state === "idle" ? null : state.result;
  if (!reported) return panelSentence.trim() ? { title: "", detail: panelSentence } : null;
  if (reported.state !== "settled") return channelPresentation(reported);
  return { title: "", detail: reported.outcome.message.trim() || UNSPOKEN_REPLY };
}

// The sentence the read wrote for the panel, read without the state gate,
// because what the panel says about reading does not depend on the rows under
// it rendering.
function panelSentence(result: FeatureResult<DocumentsData>): string {
  return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data.readingSentence : "";
}

// The control a person pressed keeps its place in the tab order for as long as
// the vault is answering. A second press is refused in the handler and said in
// words beside it.
function CapturePanel({ state, onChoose, jobUnavailable, onOpenSettings }: { onOpenSettings?: () => void; state: CaptureActionState; onChoose: () => void; jobUnavailable: boolean }) {
  const working = state.state === "working";
  const choose = () => { if (!working) onChoose(); };
  return <section className="document-capture-status" id="document-capture-status" tabIndex={-1} aria-labelledby="document-capture-title">
    <div className="detail-panel-label">Import a document</div>
    <h2 id="document-capture-title">Add a statement</h2>
    <p>Choose one statement or financial document. It is encrypted and saved in this vault on this machine.</p>
    <p>A configured model may read this document using its service and incur charges. Without a reader, the saved file waits for reading.</p>
    <details className="document-import-guide"><summary>What happens after you add a file?</summary><ol><li><strong>Save the original.</strong> The file is encrypted in your vault.</li><li><strong>Read the document.</strong> Your configured reader extracts facts. Without a reader, the original waits.</li><li><strong>Check the result.</strong> The import result reports what was posted, held for resolution, or could not be read. Saving and reading alone do not verify figures.</li></ol></details>
    {onOpenSettings ? <button className="text-button" type="button" onClick={onOpenSettings}>Check document-reading settings</button> : null}
    <button className="secondary-button" type="button" aria-disabled={working || jobUnavailable} aria-describedby={working ? "document-capture-waiting" : jobUnavailable ? "document-job-unavailable" : undefined} onClick={() => { if (!jobUnavailable) choose(); }}>Choose statement file</button>
    {working ? <span className="action-explanation" id="document-capture-waiting">Your previous request is still running. Wait for its result before starting another.</span> : null}
  </section>;
}

// What the sidecar said it is doing, said back. Every number and every word
// here came off a progress frame: the step is the sidecar's name for it, the
// count is its own, and this renders them rather than deriving a percentage
// nobody chose. A job on its second attempt says so, because a bar that
// restarts with no word for why has told a person their work was lost.
function JobProgress({ job, cancel, onStop, retained = false }: { retained?: boolean; job: JobView; cancel: CancelActionState; onStop: ((jobId: string) => void) | null }) {
  const stopping = cancel.state === "working" && cancel.jobId === job.jobId;
  const running = job.state === "running" || job.state === "queued";
  const measured = job.total > 0;
  return <section className="document-job" aria-labelledby="document-job-title">
    <div className="detail-panel-label">Progress</div>
    <h2 id="document-job-title">{job.operation === "viva.documents.upload" ? "Adding your statement" : job.operation === "viva.documents.upload_many" ? retained ? retainedCopy.jobTitle : bulkCopy.jobTitle : "Work in progress"}</h2>
    {job.operation === "viva.documents.upload" || job.operation === "viva.documents.upload_many" || job.operation === "viva.documents.recover" ? <p>Import reference: <code>{job.jobId}</code></p> : null}
    <p className="document-job-step" role="status" aria-live="polite">{measured ? (running ? `Step ${job.completed} of ${job.total}${job.step ? ` — ${job.step}` : ""}` : `Finished at step ${job.completed} of ${job.total}`) : (job.step || (running ? "Waiting for progress from your vault…" : "Job has ended."))}</p>
    {job.attempt > 1 ? <p className="document-job-attempt">This is attempt {job.attempt}. The earlier one did not finish.</p> : null}
    {job.message ? <p className="document-job-message">{job.message}</p> : null}
    <progress className="document-job-bar" value={measured ? job.completed : undefined} max={measured ? job.total : undefined} aria-labelledby="document-job-title" />
    {onStop && running && job.cancellable ? <button className="secondary-button" type="button" aria-disabled={stopping} aria-describedby={stopping ? "document-job-stopping" : undefined} onClick={() => { if (!stopping) onStop(job.jobId); }}>Stop</button> : null}
    {stopping ? <span className="action-explanation" id="document-job-stopping">Asking your vault to stop. What has already finished is kept.</span> : null}
  </section>;
}

// A pass back over everything already here. It reads nothing new, so it costs
// nothing and asks for nothing — which is why the control says what it does
// rather than warning about it. What came of it is the backend's own sentences,
// one per kind of change; this composes none of them and counts nothing.
function RescanPanel({ rescan, jobUnavailable }: { rescan: RescanControls; jobUnavailable: boolean }) {
  const working = rescan.state.state === "working";
  const report = rescan.state.state === "settled" ? rescan.state.report : null;
  const unanswered = rescan.state.state === "settled" && !report && rescan.state.result.state !== "settled" ? channelPresentation(rescan.state.result) : null;
  return <details className="document-rescan" open={rescan.state.state !== "idle"}><summary id="document-rescan-title">Check for matching records</summary>
    <p>This looks for records that close each other, statements a second document now agrees with, and movements that are two halves of one transfer. It reads no document, so it costs nothing and sends nothing.</p>
    <button className="secondary-button" type="button" aria-disabled={working || jobUnavailable} aria-describedby={working ? "document-rescan-waiting" : jobUnavailable ? "document-job-unavailable" : undefined} onClick={() => { if (!working && !jobUnavailable) rescan.onRescan(); }}>Check records</button>
    {working ? <span className="action-explanation" id="document-rescan-waiting">Your previous request is still running. Wait for its result before starting another.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{report ? report.sentence : ""}</div>
    {report ? <div className="document-rescan-answer">
      <p>{report.sentence}</p>
      {report.changes.length ? <ul>{report.changes.map((change) => <li key={change.id}>{change.sentence}</li>)}</ul> : null}
      {report.standing.length ? <ul className="document-rescan-standing">{report.standing.map((item) => <li key={item.id}><span>{item.sentence}</span>{rescan.onReviewMovement ? (item.movementIds ?? []).map((movementId) => <button key={movementId} className="secondary-button" type="button" onClick={() => rescan.onReviewMovement?.(movementId)}>Review transfer</button>) : null}</li>)}</ul> : null}
    </div> : null}
    {unanswered ? <p className="document-rescan-answer"><strong>{unanswered.title}</strong> {unanswered.detail}</p> : null}
  </details>;
}

function ReadScope() {
  return <details className="document-scope"><summary>What this page can show</summary><p>See saved statements, their reading status, and what each contributed to your books. Choose View saved original to open a supported original locally. Bounded rendered text or images travel through the local bridge; original files and filesystem paths remain in the vault. Source-region highlights are unavailable.</p></details>;
}

function DocumentLibrary({ documents, selectedDocument, onSelectDocument }: { documents: readonly SurfaceDocument[]; selectedDocument: string; onSelectDocument: (id: string, origin: HTMLButtonElement) => void }) {
  return <section className="document-library" aria-labelledby="document-library-title"><h2 id="document-library-title" tabIndex={-1}>Your statements</h2><p>Select a statement to see its status and contribution.</p><ul className="document-list">{documents.map((document, occurrence) => {
    const identityCount = document.id.trim() ? documents.filter((candidate) => candidate.id === document.id).length : 0;
    const selectable = Boolean(document.id.trim()) && identityCount === 1 && !document.identityConflict;
    const selected = selectable && selectedDocument === document.id;
    return <li className="document-list-item" key={`${document.id || "blank-document"}-${occurrence}`}>
      {selectable ? <button className={selected ? "detail-row detail-row-button active" : "detail-row detail-row-button"} aria-pressed={selected} onClick={(event) => onSelectDocument(document.id, event.currentTarget)}><span><strong>{documentRowLabel(document)}</strong><small>{document.docType?.trim() || "Document type unavailable"}</small></span><span className="state-pill">{document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution unavailable"}</span></button> : <div className="detail-row document-row-unavailable"><span><strong>{document.id.trim() ? "Document selection unavailable" : "Document identity unavailable"}</strong><small>{document.id.trim() ? "This identity appears more than once and cannot be selected." : "This row has no stable document ID, so it cannot be selected."}</small></span></div>}
    </li>;
  })}</ul></section>;
}

function DetailField({ label, value, help, wide = false }: { label: string; value: string; help?: string; wide?: boolean }) {
  return <div className={wide ? "document-detail-field document-detail-field-wide" : "document-detail-field"}><span>{label}</span><strong>{value}</strong>{help && <small>{help}</small>}</div>;
}

// Documents a vault read links to each other. No read supplies one, so this
// says that and renders nothing else — a row of links this screen built out of
// a field the backend never fills would be a route to a document nothing said
// was related. It says it about the read, which is where the capability is
// missing, rather than about which vault a person happens to be in.
function RelatedEvidence() {
  return <section className="related-evidence"><h4>Related evidence</h4><p>Related-document links are not available here.</p></section>;
}

function Limitations({ canRead = false }: { canRead?: boolean }) {
  return <details className="document-limitations"><summary>Unavailable details</summary><ul><li id="document-page-review-unavailable">Source-region highlights are unavailable.</li><li>Focused correction is not connected.</li><li>Ledger posting is not available from this screen.</li><li>Outbound actions and outbound history are not connected.</li>{!canRead ? <li>No control here changes a document or vault.</li> : null}</ul></details>;
}

function readingLabel(reading: SurfaceDocument["reading"]): string {
  return reading === "never_read" ? "Not read yet" : reading === "read_yielded_nothing" ? "Read; no usable facts returned" : reading === "read" ? "Read" : "Reading status unavailable";
}

function DocumentDetail({ retained, onReviewSelection, document, onOpenEvidence, onOpenPage, onOpenReview, onReturnToList }: { retained?: RetainedReadingControls; onReviewSelection?: () => void; onReturnToList?: () => void; document: SurfaceDocument; onOpenEvidence: (link: EvidenceLink) => void; onOpenPage: (page: number) => void; onOpenReview?: () => void }) {
  const alreadySelected = retained?.selection.some((entry) => entry.documentId === document.id || entry.confirmationToken === document.retry?.confirmationToken) ?? false;
  const selectionFull = (retained?.selection.length ?? 0) >= 3;
  const canSelect = Boolean(retained && !retained.blocked && !alreadySelected && !selectionFull && retained.canSelect(document));
  const availability = !document.retry ? retainedCopy.detailsUnavailable : document.retry.state !== "available" ? retainedCopy.reasons[document.retry.reason]
    : alreadySelected ? retainedCopy.alreadySelected : retained?.blocked ? retainedCopy.sessionBlocked : selectionFull ? retainedCopy.selectionFull
      : !canSelect ? retainedCopy.confirmationUnavailable : retainedCopy.reasons[document.retry.reason];
  return <aside className="detail-panel document-detail"><div className="detail-panel-label">Selected statement</div><h3 id="selected-document-title" tabIndex={-1}>{documentRowLabel(document)}</h3>{onReturnToList ? <button className="text-button" type="button" onClick={onReturnToList}>Return to selected statement in list</button> : null}<div className="detail-panel-grid document-detail-grid document-status-grid">
    {document.docType?.trim() ? <DetailField label="Type" value={document.docType} /> : null}
    <DetailField label="Reading" value={readingLabel(document.reading)} help="Reading a document does not mean its figures were verified or posted." />
    <DetailField label="Resolution" value={document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution status unavailable"} help="Resolution status does not say whether the document was verified or posted." />
    {document.snapshotSentence?.trim() ? <DetailField wide label="Snapshot" value={document.snapshotSentence} /> : null}
    {document.activitySentence?.trim() ? <DetailField wide label="Brokerage activity" value={document.activitySentence} /> : null}
    {document.componentStatuses?.map((item, index) => <section className="detail-field detail-field-wide" key={index} aria-label={item.label}><h4>{item.label}</h4><strong>{({ accepted: "Accepted section", held: "Needs review", conflicted: "Conflicting evidence", unavailable: "Unavailable" })[item.disposition]}</strong><p>{item.reason}</p>{item.effectiveDate ? <p>Source date: {item.effectiveDate}</p> : null}{item.sourcePages.map((source) => <button className="text-button" type="button" key={source.page} onClick={() => onOpenPage(source.page)}>{source.label}</button>)}</section>)}
    {document.componentStatuses?.some((item) => item.disposition === "held" || item.disposition === "conflicted") && onOpenReview ? <button className="secondary-button" type="button" onClick={onOpenReview}>Review unresolved source sections</button> : null}
    {document.observationSections?.map((item, index) => <section className="detail-field detail-field-wide" key={`observation-${index}`} aria-label={item.label}><h4>{item.label}</h4><p>{item.lifecycle === "active" ? "Source observation retained" : item.lifecycle === "retracted" ? "Source observation retracted" : "Source observation superseded"}</p>{item.sourcePages.map((source) => <button className="text-button" type="button" key={source.page} onClick={() => onOpenPage(source.page)}>{source.label}</button>)}</section>)}
    {document.observationStatuses?.includes("retracted") ? <DetailField wide label="Source history" value="Some source observations were retracted. The saved document remains in this library." /> : document.observationStatuses?.includes("superseded") ? <DetailField wide label="Source history" value="Some source observations were replaced by a later correction." /> : null}
    <DetailField wide label="Contribution" value={document.contribution?.trim() || "No contribution information is available for this document."} />
  </div>{retained ? <section aria-label="Saved original reading availability"><h4>Read this saved original again</h4><p id="retained-document-availability" role="status" aria-live="polite" aria-atomic="true">{availability}</p>{document.retry?.state === "available" ? <button className="secondary-button" type="button" aria-describedby="retained-document-availability" aria-disabled={!canSelect} onClick={() => { if (canSelect) retained.onAdd(document); }}>Select saved original for a new reading</button> : null}{retained.selection.length > 0 && onReviewSelection ? <button className="secondary-button" type="button" aria-controls="retained-reading-title" onClick={onReviewSelection}>{retainedCopy.reviewSelection}</button> : null}</section> : null}{document.evidenceLinks.length ? <ProofLinks label="Source links" links={document.evidenceLinks} onOpen={onOpenEvidence} /> : null}<details className="document-technical-details"><summary>File and source details</summary><div className="detail-panel-grid document-detail-grid"><DetailField label="Document ID" value={document.id} help="The stable identity used inside this vault." /><DetailField label="Document name" value={document.name.trim() || "Document name unavailable"} />{!document.docType?.trim() ? <DetailField label="Type" value="Document type unavailable" /> : null}<DetailField label="Original" value={document.rawAvailable === true ? "Available" : document.rawAvailable === false ? "Unavailable" : "Original availability unavailable"} help="This status reports whether an original exists. Choose View saved original for a local preview where supported." /><DetailField label="Lifecycle" value="Lifecycle details unavailable" /><DetailField label="Pages" value="Page details unavailable" /><DetailField label="Source region" value="Source region unavailable" /><DetailField label="Provenance" value="Provenance unavailable" /></div><RelatedEvidence /><Limitations canRead={Boolean(retained)} /></details></aside>;
}

function CaptureReceipt({ capture, said, onOpenReview, retained = false }: { retained?: boolean; capture: CaptureControls | null; said: ChannelPresentation; onOpenReview?: () => void }) {
  const reply = capture?.state.state === "settled" && capture.state.result.state === "settled" ? capture.state.result.outcome : null;
  const terminal = reply?.terminalState;
  const terminalLabels = { captured_only: "Original saved", read_yielded_nothing: "Read; no usable facts returned", held: "Held for resolution", posted: "Posted to your books", duplicate: "Already in your vault" };
  return <section className="document-capture-answer" aria-label={capture?.state.state === "settled" ? retained ? "New reading result" : "Import result" : "Document reading status"}>
    {capture?.state.state === "settled" ? <h2>{retained ? "New reading result" : "Import result"}</h2> : null}
    {said.title ? <strong>{said.title}</strong> : null}<p>{said.detail}</p>
    {terminal || reply?.reading ? <dl className="document-receipt-facts">{terminal ? <div><dt>Result</dt><dd>{terminalLabels[terminal]}</dd></div> : null}{reply?.reading ? <div><dt>Reading</dt><dd>{readingLabel(reply.reading)}</dd></div> : null}</dl> : null}
    {terminal === "captured_only" ? <span className="action-explanation">Saving the original does not verify or post its figures.</span> : null}
    {onOpenReview && (terminal === "held" || reply?.kind === "waiting") ? <button type="button" className="secondary-button" onClick={onOpenReview}>Open Review</button> : null}
  </section>;
}

// A disappearing action records focus ownership before its DOM node is removed.
function RecoveryButton({ job, working, unavailable, onRecover, removedWhileFocused }: { job: JobView; working: boolean; unavailable: boolean; onRecover: (jobId: string) => void; removedWhileFocused: { current: boolean } }) {
  const button = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => () => {
    const element = button.current;
    if (element && element.ownerDocument.activeElement === element) removedWhileFocused.current = true;
  }, [removedWhileFocused]);
  return <button ref={button} type="button" className="secondary-button" aria-label={`Read saved original again — import ${job.jobId}`} aria-describedby={`document-recovery-consent${working ? " document-capture-waiting" : ""}${unavailable ? " document-job-unavailable" : ""}`} aria-disabled={working || unavailable} onClick={() => { if (!working && !unavailable) onRecover(job.jobId); }}>Read saved original again</button>;
}

// What became of the last capture a person asked for, and the capture control
// itself, both sit outside the documents read's state gate. A file that was
// sealed and a read that then failed still says the capture happened, instead
// of discarding the vault's own sentence with the panel under it, and the one
// control this screen has does not vanish on the read that would explain why.
//
// The region announcing it is mounted for the life of the screen and only its
// text changes, because a live region that arrives with its words is one
// several screen readers never announce.
function RetainedReadingSelectionPanel({ controls }: { controls: RetainedReadingControls }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const ownedFocus = useRef(false);
  useLayoutEffect(() => {
    if (ownedFocus.current) { ownedFocus.current = false; if (heading.current?.ownerDocument.activeElement === heading.current?.ownerDocument.body) heading.current?.focus(); }
  });
  return <section className="document-capture-status document-retained-reading" aria-labelledby="retained-reading-title">
    <h2 ref={heading} tabIndex={-1} id="retained-reading-title">{retainedCopy.selectionTitle}</h2>
    <p id="retained-reading-consent">{retainedCopy.detail}</p><p>{retainedCopy.session}</p>
    <p role="status" aria-live="polite">{controls.selection.length} of 3 saved originals selected.{controls.blocked ? " Reading is unavailable while another request is active, job status is unavailable, or document reading is disabled." : ""}</p>
    <ol>{controls.selection.map((entry) => <li key={entry.documentId}><strong>{entry.name}</strong><p>Document ID: <code>{entry.documentId}</code></p><p>{retainedCopy.reasons[entry.reason]}</p><button className="text-button" type="button" aria-label={`Remove ${entry.name} from new reading selection`} onClick={(event) => { ownedFocus.current = event.currentTarget.ownerDocument.activeElement === event.currentTarget; controls.onRemove(entry.documentId); }}>Remove</button></li>)}</ol>
    <button className="primary-button" type="button" aria-describedby="retained-reading-consent" aria-disabled={controls.blocked || !controls.selection.length} onClick={() => { if (!controls.blocked && controls.selection.length) controls.onConfirm(); }}>{retainedCopy.choose}</button>
  </section>;
}

export function Documents({ retained, bulk, onSourcePageConsumed, sourcePageRequest, paging, previewReader, subscribePreviewEnd, onOpenReview, recoveryJobs = [], onRecoverDocument, onOpenSettings, result, selectedDocument, capture, rescan, jobStatus = "available", jobCheck = "idle", onRecheckJobs, onSelectDocument, onOpenEvidence, onExploreSample, openingSample = false }: DocumentsProps) {
  const [localPageRequest, setLocalPageRequest] = useState<{ documentId: string; page: number; nonce: number } | null>(null);
  const sourcePageNonce = useRef(0);
  useLayoutEffect(() => { setLocalPageRequest(null); }, [selectedDocument]);

  const [rowIntent, setRowIntent] = useState<{ id: string; selectionAtStart: string; origin: HTMLButtonElement } | null>(null);
  const returnRow = useRef<HTMLButtonElement | null>(null);
  const returnDocumentId = useRef("");
  const [selectionAnnouncement, setSelectionAnnouncement] = useState("");
  const panel = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (returnDocumentId.current && returnDocumentId.current !== selectedDocument) { returnDocumentId.current = ""; returnRow.current = null; setSelectionAnnouncement(""); }
    const intent = rowIntent;
    if (!intent) return;
    if (selectedDocument !== intent.id) { if (selectedDocument !== intent.selectionAtStart) setRowIntent(null); return; }
    const data = "data" in result ? result.data : null;
    if (!data) { setRowIntent(null); return; }
    const selection = resolveDocumentSelection(data.documents, selectedDocument, data.selectedDocument);
    if (selection.state === "pending") return;
    setRowIntent(null);
    if (selection.state !== "ready" || sourcePageRequest?.documentId === intent.id || localPageRequest?.documentId === intent.id || panel.current?.querySelector("#original-preview-title")) return;
    const active = document.activeElement;
    if (active !== intent.origin && active !== document.body) return;
    const heading = panel.current?.querySelector<HTMLElement>("#selected-document-title");
    if (!heading) return;
    returnRow.current = intent.origin; returnDocumentId.current = intent.id;
    heading.focus(); heading.scrollIntoView?.({ block: "start" });
    setSelectionAnnouncement(`Selected statement: ${documentRowLabel(selection.document)}. Details are ready.`);
  }, [result, selectedDocument, sourcePageRequest, localPageRequest, rowIntent]);
  const recoveryHeading = useRef<HTMLHeadingElement>(null);
  const removedWhileFocused = useRef(false);
  useLayoutEffect(() => {
    if (!removedWhileFocused.current) return;
    removedWhileFocused.current = false;
    const target = recoveryHeading.current ?? panel.current;
    if (target && target.ownerDocument.activeElement === target.ownerDocument.body) target.focus();
  });
  const said = capturePresentation(capture ? capture.state : { state: "idle" }, panelSentence(result));
  const captureRegion = capture?.onChoose ? <CapturePanel onOpenSettings={onOpenSettings} state={capture.state} onChoose={capture.onChoose} jobUnavailable={jobStatus === "unavailable"} /> : null;
  const job = capture?.job ?? null;
  if (result.state === "absent" && !captureRegion && !said && !job && !rescan && jobStatus !== "unavailable" && !recoveryJobs.some((job) => job.recovery)) return null;
  return <section ref={panel} tabIndex={-1} aria-label="Statements" className="feature-panel documents-surface">
    <div role={selectionAnnouncement ? "status" : undefined} aria-live="polite" className="visually-hidden">{selectionAnnouncement}</div>
    {captureRegion}
    {retained && (result.state === "ready" || result.state === "partial" || result.state === "needs_input") && result.data.retainedReadingVersion === "retained-reading-v1" ? <RetainedReadingSelectionPanel controls={retained} /> : null}
    {bulk ? <BulkDocumentSelection controls={bulk} unavailable={jobStatus === "unavailable"} /> : null}
    {recoveryJobs.some((job) => job.recovery) ? <section className="document-job" aria-labelledby="document-recovery-title">
      <h2 ref={recoveryHeading} tabIndex={-1} id="document-recovery-title">Interrupted statements</h2>
      <p id="document-recovery-consent">Reading a saved original uses your configured document reader, may send it to that service, and may incur charges again. Nothing starts until you choose to read it again.</p>
      {capture?.state.state === "working" && !capture.onChoose ? <span className="action-explanation" id="document-capture-waiting">Your previous request is still running. Wait for its result before starting another.</span> : null}
      <ul>{recoveryJobs.filter((job) => job.recovery).map((job) => <li key={job.jobId}>
        <p>Import reference: <code>{job.jobId}</code></p>
        <p>{job.recovery?.message}</p>
        {job.recovery?.state === "available" && onRecoverDocument ? <RecoveryButton job={job} working={capture?.state.state === "working"} unavailable={jobStatus === "unavailable"} onRecover={onRecoverDocument} removedWhileFocused={removedWhileFocused} /> : null}
      </li>)}</ul>
    </section> : null}
    {jobStatus === "unavailable" ? <div className="action-explanation" id="document-job-unavailable"><strong>Job status unavailable.</strong> Recheck the job status. If it still cannot be read, reopen this vault before adding or rescanning statements. {onRecheckJobs ? <button className="secondary-button" type="button" aria-disabled={jobCheck === "checking"} aria-describedby={jobCheck === "checking" ? "document-job-check-status" : undefined} onClick={() => { if (jobCheck !== "checking") onRecheckJobs(); }}>Recheck job status</button> : null}</div> : null}
    {jobCheck !== "idle" ? <div className="visually-hidden" id="document-job-check-status" role="status" aria-live="polite">{jobCheck === "checking" ? "Checking job status…" : jobCheck === "failed" ? "Job status is still unavailable. Reopen this vault before starting the job again." : "Job status checked successfully."}</div> : null}
    {capture && job && jobStatus !== "unavailable" ? <JobProgress retained={bulk?.session?.mode === "retained"} job={job} cancel={capture.cancel} onStop={capture.onStop} /> : null}
    {capture ? <div className="visually-hidden" role="status" aria-live="polite">{said ? `${said.title ? `${said.title}. ` : ""}${said.detail}` : ""}</div> : null}
    {said ? <CaptureReceipt retained={bulk?.session?.mode === "retained"} capture={capture} said={said} onOpenReview={onOpenReview} /> : null}
    <PanelStateView result={result} copy={{ partial: "Some document details are unavailable. Available documents are shown below.", needsInput: "Some documents need review. Available document details are shown below.", unavailable: { title: "Documents unavailable", detail: "Document details are not available in this build." }, failed: { title: "Documents could not be read", detail: "The documents section could not be read. The private vault is still open." } }}>{(data) => {
    const selection = resolveDocumentSelection(data.documents, selectedDocument, data.selectedDocument);
    const activeId = selection.state === "ready" ? selection.document.id : selectedDocument;
    return <>
      {data.page && paging ? <nav className="document-paging" aria-label="Statement pages">
        <p aria-live="polite" aria-atomic="true">{data.page.totalDocuments === null ? `Statements ${data.page.pageStart}–${data.page.pageEnd}; total unavailable` : data.page.totalDocuments === 0 ? "No statements saved" : `Statements ${data.page.pageStart}–${data.page.pageEnd} of ${data.page.totalDocuments}`} <span>{data.page.pageCount} shown</span></p>
        <div><button className="secondary-button" aria-disabled={paging.busy} onClick={() => { if (!paging.busy) void paging.first(); }}>First page</button>
        <button className="secondary-button" aria-disabled={paging.busy || !paging.canPrevious} onClick={() => { if (!paging.busy && paging.canPrevious) void paging.previous(); }}>Previous</button>
        <button className="secondary-button" aria-disabled={paging.busy || !data.page.hasMore} onClick={() => { if (!paging.busy && data.page?.hasMore) void paging.next(); }}>Next</button></div>
        {paging.busy ? <p role="status">Reading statements…</p> : null}{paging.notice ? <p role="status">{paging.notice}</p> : null}
      </nav> : null}
      {!data.documents.length && data.page && data.page.totalDocuments !== 0 ? <div className="empty-state"><strong>No rows returned on this page</strong><span>The library total is unavailable or this page needs refreshing. Use First page to check again.</span></div> : !data.documents.length ? <div className="empty-state"><strong>No statements or documents yet</strong><span>Add a statement to begin, or open the sample vault to see a populated document index.</span><button className="secondary-button" aria-disabled={openingSample} aria-describedby={openingSample ? "vault-opening-from-documents" : undefined} onClick={() => { if (!openingSample) onExploreSample(); }}>{openingSample ? "Opening sample vault…" : "Open the sample vault"}</button>{openingSample ? <span className="action-explanation" id="vault-opening-from-documents">The sample vault is opening and its first read is still pending.</span> : null}</div> : <><div className="document-library-layout"><DocumentLibrary documents={data.documents} selectedDocument={activeId} onSelectDocument={(id, origin) => { setRowIntent({ id, origin, selectionAtStart: selectedDocument }); setSelectionAnnouncement(""); onSelectDocument(id); }} />{selection.state === "ready" ? <DocumentDetail retained={data.retainedReadingVersion === "retained-reading-v1" ? retained : undefined} onReviewSelection={() => {
      const target = panel.current?.querySelector<HTMLElement>("#retained-reading-title");
      target?.focus(); target?.scrollIntoView?.({ block: "start" });
    }} onReturnToList={selectionAnnouncement ? () => {
      const target = returnRow.current?.isConnected ? returnRow.current : panel.current?.querySelector<HTMLElement>("#document-library-title");
      target?.focus(); target?.scrollIntoView?.({ block: "nearest" });
    } : undefined} document={selection.document} onOpenEvidence={onOpenEvidence} onOpenReview={onOpenReview} onOpenPage={(page) => setLocalPageRequest({ documentId: selection.document.id, page, nonce: ++sourcePageNonce.current })} /> : selection.state === "missing" ? <div className="empty-state"><strong>Selected document unavailable</strong><span>The selected document is no longer present in the current vault read.</span></div> : selection.state === "conflicted_identity" ? <div className="empty-state"><strong>Document selection unavailable</strong><span>More than one document in this read uses the selected identity, so the interface will not choose between them.</span></div> : <div className="empty-state"><strong>{selection.state === "pending" ? "Finding selected document…" : "Document details unavailable"}</strong><span>{selection.state === "pending" ? "Checking this document in the active vault." : "The selected document could not be read. Retry its details to check again."}</span>{selection.state === "unavailable" && paging?.retrySelected ? <button className="secondary-button" onClick={() => void paging.retrySelected?.()}>Retry selected document</button> : null}</div>}</div>{selection.state === "ready" ? <OriginalPreview onOpenRequest={(nonce) => { if (sourcePageRequest?.nonce === nonce && localPageRequest?.documentId !== selection.document.id) onSourcePageConsumed?.(nonce); }} key={selection.document.id} documentId={selection.document.id} name={documentRowLabel(selection.document)} openRequest={localPageRequest?.documentId === selection.document.id ? localPageRequest : sourcePageRequest?.documentId === selection.document.id ? sourcePageRequest : undefined} read={previewReader} subscribeEnd={subscribePreviewEnd} /> : null}</>}
      <ReadScope />
    </>;
  }}</PanelStateView>
    {rescan ? <RescanPanel rescan={rescan} jobUnavailable={jobStatus === "unavailable"} /> : null}
  </section>;
}
