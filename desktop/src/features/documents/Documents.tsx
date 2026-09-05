import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ChannelPresentation } from "../../components/actionChannel";
import type { CancelActionState, CaptureActionState, DocumentsData, EvidenceLink, FeatureResult, JobView, RescanActionState, SurfaceDocument } from "../../surface/types";
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
type DocumentsProps = { rescan: RescanControls | null; result: FeatureResult<DocumentsData>; selectedDocument: string; capture: CaptureControls | null; onSelectDocument: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onExploreSample: () => void };

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
function CapturePanel({ state, onChoose }: { state: CaptureActionState; onChoose: () => void }) {
  const working = state.state === "working";
  const choose = () => { if (!working) onChoose(); };
  return <section className="document-capture-status" id="document-capture-status" tabIndex={-1} aria-labelledby="document-capture-title">
    <div className="detail-panel-label">Capture</div>
    <h2 id="document-capture-title">Add a statement</h2>
    <p>Choose one statement or financial document. It is encrypted and saved in this vault on this machine.</p>
    <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "document-capture-waiting" : undefined} onClick={choose}>Choose statement file</button>
    {working ? <span className="action-explanation" id="document-capture-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
  </section>;
}

// What the sidecar said it is doing, said back. Every number and every word
// here came off a progress frame: the step is the sidecar's name for it, the
// count is its own, and this renders them rather than deriving a percentage
// nobody chose. A job on its second attempt says so, because a bar that
// restarts with no word for why has told a person their work was lost.
function JobProgress({ job, cancel, onStop }: { job: JobView; cancel: CancelActionState; onStop: ((jobId: string) => void) | null }) {
  const stopping = cancel.state === "working" && cancel.jobId === job.jobId;
  const running = job.state === "running" || job.state === "queued";
  return <section className="document-job" aria-labelledby="document-job-title">
    <div className="detail-panel-label">Progress</div>
    <h2 id="document-job-title">{job.operation || "Work in progress"}</h2>
    <p className="document-job-step" role="status" aria-live="polite">{running ? `Step ${job.completed} of ${job.total}${job.step ? ` — ${job.step}` : ""}` : `Finished at step ${job.completed} of ${job.total}`}</p>
    {job.attempt > 1 ? <p className="document-job-attempt">This is attempt {job.attempt}. The earlier one did not finish.</p> : null}
    {job.message ? <p className="document-job-message">{job.message}</p> : null}
    <progress className="document-job-bar" value={job.completed} max={job.total || 1} aria-labelledby="document-job-title" />
    {onStop && running && job.cancellable ? <button className="secondary-button" type="button" aria-disabled={stopping} aria-describedby={stopping ? "document-job-stopping" : undefined} onClick={() => { if (!stopping) onStop(job.jobId); }}>Stop</button> : null}
    {stopping ? <span className="action-explanation" id="document-job-stopping">Asking your vault to stop. What has already finished is kept.</span> : null}
  </section>;
}

// A pass back over everything already here. It reads nothing new, so it costs
// nothing and asks for nothing — which is why the control says what it does
// rather than warning about it. What came of it is the backend's own sentences,
// one per kind of change; this composes none of them and counts nothing.
function RescanPanel({ rescan }: { rescan: RescanControls }) {
  const working = rescan.state.state === "working";
  const report = rescan.state.state === "settled" ? rescan.state.report : null;
  const unread = rescan.state.state === "settled" && !report;
  return <section className="document-rescan" aria-labelledby="document-rescan-title">
    <div className="detail-panel-label">Go back over this vault</div>
    <h2 id="document-rescan-title">Look again at what is already here</h2>
    <p>This looks for records that close each other, statements a second document now agrees with, and movements that are two halves of one transfer. It reads no document, so it costs nothing and sends nothing.</p>
    <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "document-rescan-waiting" : undefined} onClick={() => { if (!working) rescan.onRescan(); }}>Look again</button>
    {working ? <span className="action-explanation" id="document-rescan-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{report ? report.sentence : ""}</div>
    {report ? <div className="document-rescan-answer">
      <p>{report.sentence}</p>
      {report.changes.length ? <ul>{report.changes.map((change) => <li key={change.id}>{change.sentence}</li>)}</ul> : null}
      {report.standing.length ? <ul className="document-rescan-standing">{report.standing.map((item) => <li key={item.id}><span>{item.sentence}</span>{rescan.onReviewMovement ? (item.movementIds ?? []).map((movementId) => <button key={movementId} className="secondary-button" type="button" onClick={() => rescan.onReviewMovement?.(movementId)}>Review transfer</button>) : null}</li>)}</ul> : null}
    </div> : null}
    {unread ? <p className="document-rescan-answer">Your vault answered in a way this screen does not recognise, so it will not say what that pass did.</p> : null}
  </section>;
}

function ReadScope() {
  return <details className="document-scope"><summary>What this page can show</summary><p>This vault read supplies document identity, filename, type, resolution status, original availability, reading status, and what the document put on your books. Page regions and lifecycle internals are not supplied.</p></details>;
}

function DocumentLibrary({ documents, selectedDocument, onSelectDocument }: { documents: readonly SurfaceDocument[]; selectedDocument: string; onSelectDocument: (id: string) => void }) {
  return <section className="document-library" aria-labelledby="document-library-title"><h2 id="document-library-title">Documents in this vault read</h2><p>Only document identity, filename, type, resolution status, and original availability returned by this read are shown.</p><ul className="document-list">{documents.map((document, occurrence) => {
    const identityCount = document.id.trim() ? documents.filter((candidate) => candidate.id === document.id).length : 0;
    const selectable = Boolean(document.id.trim()) && identityCount === 1;
    const selected = selectable && selectedDocument === document.id;
    return <li className="document-list-item" key={`${document.id || "blank-document"}-${occurrence}`}>
      {selectable ? <button className={selected ? "detail-row detail-row-button active" : "detail-row detail-row-button"} aria-pressed={selected} onClick={() => onSelectDocument(document.id)}><span><strong>{documentRowLabel(document)}</strong><small>{document.docType?.trim() || "Document type unavailable"}</small></span><span className="state-pill">{document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution unavailable"}</span></button> : <div className="detail-row document-row-unavailable"><span><strong>{document.id.trim() ? "Document selection unavailable" : "Document identity unavailable"}</strong><small>{document.id.trim() ? "This identity appears more than once and cannot be selected." : "This row has no stable document ID, so it cannot be selected."}</small></span></div>}
    </li>;
  })}</ul></section>;
}

function DetailField({ label, value, help }: { label: string; value: string; help?: string }) {
  return <div className="document-detail-field"><span>{label}</span><strong>{value}</strong>{help && <small>{help}</small>}</div>;
}

// Documents a vault read links to each other. No read supplies one, so this
// says that and renders nothing else — a row of links this screen built out of
// a field the backend never fills would be a route to a document nothing said
// was related. It says it about the read, which is where the capability is
// missing, rather than about which vault a person happens to be in.
function RelatedEvidence() {
  return <section className="related-evidence"><h4>Related evidence</h4><p>Related evidence is not supplied by this vault read.</p></section>;
}

function Limitations() {
  return <details className="document-limitations"><summary>Unavailable details</summary><ul><li id="document-page-review-unavailable">Page and source-region review are not connected.</li><li>Focused correction is not connected.</li><li>Ledger posting is not available from this screen.</li><li>Outbound actions and outbound history are not connected.</li><li>No control here changes a document or vault.</li></ul></details>;
}

function DocumentDetail({ document, onOpenEvidence }: { document: SurfaceDocument; onOpenEvidence: (link: EvidenceLink) => void }) {
  return <aside className="detail-panel document-detail"><div className="detail-panel-label">Selected statement</div><h3 id="selected-document-title" tabIndex={-1}>{document.name.trim() || document.docType?.trim() || "Document name unavailable"}</h3><div className="detail-panel-grid document-detail-grid document-status-grid">
    <DetailField label="Document name" value={document.name.trim() || "Document name was not supplied by this read."} />
    <DetailField label="Type" value={document.docType?.trim() || "Document type was not supplied by this read."} />
    <DetailField label="Resolution" value={document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution status was not supplied by this read."} help="Resolution status does not say whether the document was verified or posted." />
    <DetailField label="Snapshot" value={document.snapshotSentence?.trim() || "Snapshot status was not supplied by this read."} />
    <DetailField label="Brokerage activity" value={document.activitySentence?.trim() || "Activity status was not supplied by this read."} />
    <DetailField label="Original" value={document.rawAvailable === true ? "Available" : document.rawAvailable === false ? "Unavailable" : "Original availability was not supplied by this read."} help="This status says only whether an original is available; it does not say that the original can be opened or reviewed from this screen." />
    <DetailField label="Contribution" value={document.contribution?.trim() || "What this document contributed was not supplied by this read."} />
  </div><details className="document-technical-details"><summary>Technical details</summary><div className="detail-panel-grid document-detail-grid"><DetailField label="Document ID" value={document.id} help="The stable identity used inside this vault." /><DetailField label="Lifecycle" value="Lifecycle is not supplied by this vault read." /><DetailField label="Pages" value="Page details are not supplied by this vault read." /><DetailField label="Source region" value="Source region is not supplied by this vault read." /><DetailField label="Provenance" value="Provenance is not supplied by this vault read." /></div>{document.evidenceLinks.length ? <ProofLinks label="Source links" links={document.evidenceLinks} onOpen={onOpenEvidence} /> : null}<RelatedEvidence /><Limitations /></details></aside>;
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
export function Documents({ result, selectedDocument, capture, rescan, onSelectDocument, onOpenEvidence, onExploreSample }: DocumentsProps) {
  const said = capturePresentation(capture ? capture.state : { state: "idle" }, panelSentence(result));
  const captureRegion = capture?.onChoose ? <CapturePanel state={capture.state} onChoose={capture.onChoose} /> : null;
  const job = capture?.job ?? null;
  if (result.state === "absent" && !captureRegion && !said && !job && !rescan) return null;
  return <section className="feature-panel documents-surface">
    {captureRegion}
    {rescan ? <RescanPanel rescan={rescan} /> : null}
    {capture && job ? <JobProgress job={job} cancel={capture.cancel} onStop={capture.onStop} /> : null}
    {capture ? <div className="visually-hidden" role="status" aria-live="polite">{said ? `${said.title ? `${said.title}. ` : ""}${said.detail}` : ""}</div> : null}
    {said ? <div className="document-capture-answer">{said.title ? <strong>{said.title}</strong> : null}<p>{said.detail}</p></div> : null}
    <PanelStateView result={result} copy={{ partial: "Some document details are unavailable. Available documents are shown below.", needsInput: "Some documents need review. Available document details are shown below.", unavailable: { title: "Documents unavailable", detail: "Document details are not available in this build." }, failed: { title: "Documents could not be read", detail: "The documents section could not be read. The private vault is still open." } }}>{(data) => {
    const selection = resolveDocumentSelection(data.documents, selectedDocument);
    const activeId = selection.state === "ready" ? selection.document.id : selectedDocument;
    return <><ReadScope />
      {!data.documents.length ? <div className="empty-state"><strong>No statements or documents yet</strong><span>Add a statement to begin, or open the sample vault to see a populated document index.</span><button className="secondary-button" onClick={onExploreSample}>Open the sample vault</button></div> : <><div className="document-library-layout"><DocumentLibrary documents={data.documents} selectedDocument={activeId} onSelectDocument={onSelectDocument} />{selection.state === "ready" ? <DocumentDetail document={selection.document} onOpenEvidence={onOpenEvidence} /> : selection.state === "missing" ? <div className="empty-state"><strong>Selected document unavailable</strong><span>The selected document is no longer present in the current vault read.</span></div> : selection.state === "conflicted_identity" ? <div className="empty-state"><strong>Document selection unavailable</strong><span>More than one document in this read uses the selected identity, so the interface will not choose between them.</span></div> : <div className="empty-state"><strong>Document identity unavailable</strong><span>No document with a unique stable identity can be selected from this read.</span></div>}</div></>}
    </>;
  }}</PanelStateView>
  </section>;
}
