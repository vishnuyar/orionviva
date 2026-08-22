import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ChannelPresentation } from "../../components/actionChannel";
import type { CancelActionState, CaptureActionState, DocumentsData, EvidenceLink, FeatureResult, JobView, RescanActionState, SurfaceDocument, SurfaceMode } from "../../surface/types";
import { documentRowLabel, lifecyclePresentation, resolveDocumentSelection, sampleLifecycle } from "./documentPresentation";

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
export type RescanControls = { state: RescanActionState; onRescan: () => void };
type DocumentsProps = { rescan: RescanControls | null; result: FeatureResult<DocumentsData>; mode: SurfaceMode; selectedDocument: string; capture: CaptureControls | null; onSelectDocument: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onExploreSample: () => void };

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
    <h2 id="document-capture-title">Add a document</h2>
    <p>Choose a file and it is saved into this vault, encrypted, on this machine. It is not sent anywhere.</p>
    <button className="secondary-button" type="button" aria-disabled={working} aria-describedby={working ? "document-capture-waiting" : undefined} onClick={choose}>Choose a file</button>
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
      {report.standing.length ? <ul className="document-rescan-standing">{report.standing.map((item) => <li key={item.id}>{item.sentence}</li>)}</ul> : null}
    </div> : null}
    {unread ? <p className="document-rescan-answer">Your vault answered in a way this screen does not recognise, so it will not say what that pass did.</p> : null}
  </section>;
}

function SampleCaptureBoundary() {
  return <section className="document-capture-status" id="document-capture-status" tabIndex={-1} aria-labelledby="document-capture-title">
    <div className="detail-panel-label">Fictional sample</div>
    <h2 id="document-capture-title">A sample document journey</h2>
    <p>These are static fictional examples stored with the app. No file is selected, no vault event is written, no model call is made, nothing is sent, and no durable state changes.</p>
    <p>Nothing is added to a vault from the fictional sample.</p>
  </section>;
}

function LiveScope() {
  return <section className="document-scope"><h2>What this read can show</h2><p>This private-vault read supplies document identity, the name of the file where one was recorded, document type, resolution status, whether an original is available, whether it has been read, and what it put on your books. Lifecycle steps, pages, source regions, provenance, wait reasons, and recovery are not supplied. What a capture is doing while it runs is reported separately, by the sidecar doing it.</p></section>;
}

function SampleLifecycle() {
  return <section className="sample-lifecycle" aria-labelledby="sample-lifecycle-title"><h2 id="sample-lifecycle-title">Sample lifecycle</h2><p>These are fictional lifecycle meanings, not running jobs. A later state never starts automatically from this screen.</p><div className="sample-lifecycle-grid">{sampleLifecycle.map((item) => <article className="sample-lifecycle-card" key={item.phase}><span className="sample-lifecycle-icon" aria-hidden="true" /><strong>{item.title}</strong><p>{item.detail}</p></article>)}</div><p className="document-boundary">These labels describe distinct states. They do not imply that one starts the next. Ledger posting and outbound transmission are separate unavailable actions.</p></section>;
}

function DocumentLibrary({ documents, mode, selectedDocument, onSelectDocument }: { documents: readonly SurfaceDocument[]; mode: SurfaceMode; selectedDocument: string; onSelectDocument: (id: string) => void }) {
  return <section className="document-library" aria-labelledby="document-library-title"><h2 id="document-library-title">{mode === "demo" ? "Sample documents" : "Documents in this vault read"}</h2><p>{mode === "demo" ? "Every filename and detail below is fictional sample data." : "Only document identity, filename, type, resolution status, and original availability returned by this read are shown."}</p><ul className="document-list">{documents.map((document, occurrence) => {
    const identityCount = document.id.trim() ? documents.filter((candidate) => candidate.id === document.id).length : 0;
    const selectable = Boolean(document.id.trim()) && identityCount === 1;
    const selected = selectable && selectedDocument === document.id;
    return <li className="document-list-item" key={`${document.id || "blank-document"}-${occurrence}`}>
      {selectable ? <button className={selected ? "detail-row detail-row-button active" : "detail-row detail-row-button"} aria-pressed={selected} onClick={() => onSelectDocument(document.id)}><span><strong>{mode === "demo" ? document.name || "Document name unavailable" : documentRowLabel(document)}</strong><small>{mode === "demo" ? document.id : `Document ID · ${document.id}`}</small></span><span className="state-pill">{mode === "demo" ? lifecyclePresentation(document.phase).title : document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution unavailable"}</span></button> : <div className="detail-row document-row-unavailable"><span><strong>{document.id.trim() ? "Document selection unavailable" : "Document identity unavailable"}</strong><small>{document.id.trim() ? "This identity appears more than once and cannot be selected." : "This row has no stable document ID, so it cannot be selected."}</small></span></div>}
    </li>;
  })}</ul></section>;
}

function DetailField({ label, value, help }: { label: string; value: string; help?: string }) {
  return <div className="document-detail-field"><span>{label}</span><strong>{value}</strong>{help && <small>{help}</small>}</div>;
}

function RelatedEvidence({ mode, document, onOpenEvidence }: { mode: SurfaceMode; document: SurfaceDocument; onOpenEvidence: (link: EvidenceLink) => void }) {
  if (mode === "live") return <section className="related-evidence"><h4>Related evidence</h4><p>Related evidence is not supplied by the private-vault read.</p></section>;
  return <section className="related-evidence"><h4>Related evidence</h4>{document.evidenceLinks.length ? document.evidenceLinks.map((link) => <button className="text-button related-evidence-button" key={`${link.targetDocumentId}-${link.relation}-${link.page}`} onClick={() => onOpenEvidence(link)}><span>{link.label}</span><small>{link.relation.replace("_", " ")} · {link.page}</small></button>) : <p>No related evidence is included in this sample document.</p>}</section>;
}

function Limitations() {
  return <section className="document-limitations"><h4>Unavailable in this preview</h4><ul><li id="document-page-review-unavailable">Page and source-region review are not connected.</li><li>Focused correction is not connected.</li><li>Restart recovery is not connected: a job does not survive the sidecar it ran in.</li><li>Ledger posting is not available from this screen.</li><li>Outbound actions and outbound history are not connected.</li><li>No control here changes a document or vault.</li></ul></section>;
}

function DocumentDetail({ mode, document, onOpenEvidence }: { mode: SurfaceMode; document: SurfaceDocument; onOpenEvidence: (link: EvidenceLink) => void }) {
  if (mode === "live") return <aside className="detail-panel document-detail"><div className="detail-panel-label">Selected document</div><h3 id="selected-document-title" tabIndex={-1}>{document.docType?.trim() || "Document type unavailable"}</h3><div className="detail-panel-grid document-detail-grid">
    <DetailField label="Document ID" value={document.id} help="A document ID is a stable document identity. It is not a filename or record ID." />
    <DetailField label="Document name" value={document.name.trim() || "Document name was not supplied by this read."} />
    <DetailField label="Type" value={document.docType?.trim() || "Document type was not supplied by this read."} />
    <DetailField label="Resolution" value={document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution status was not supplied by this read."} help="Resolution status does not say whether the document was verified or posted." />
    <DetailField label="Unresolved reason" value="An unresolved reason is not supplied by this read." />
    <DetailField label="Original" value={document.rawAvailable === true ? "Available" : document.rawAvailable === false ? "Unavailable" : "Original availability was not supplied by this read."} help="This status says only whether an original is available; it does not say that the original can be opened or reviewed from this screen." />
    <DetailField label="Lifecycle" value="Lifecycle is not supplied by the private-vault read." />
    <DetailField label="Pages" value="Page details are not supplied by the private-vault read." />
    <DetailField label="Source region" value="Source region is not supplied by the private-vault read." />
    <DetailField label="Provenance" value="Provenance is not supplied by the private-vault read." />
    <DetailField label="Contribution" value={document.contribution?.trim() || "What this document contributed was not supplied by this read."} />
  </div><section className="document-wait"><h4>Wait or hold</h4><p>A wait reason is not supplied by the private-vault read.</p></section><RelatedEvidence mode={mode} document={document} onOpenEvidence={onOpenEvidence} /><Limitations /></aside>;

  const lifecycle = lifecyclePresentation(document.phase);
  return <aside className="detail-panel document-detail"><div className="detail-panel-label">Selected document</div><h3 id="selected-document-title" tabIndex={-1}>{document.name || "Document name was not supplied by this fictional sample."}</h3><div className="detail-panel-grid document-detail-grid">
    <DetailField label="Document ID" value={document.id} help="A document ID is a stable document identity. It is not a filename or record ID." />
    <DetailField label="Document name" value={document.name || "Document name was not supplied by this fictional sample."} />
    <DetailField label="Type" value={document.docType?.trim() || "Document type was not supplied by this fictional sample."} />
    <DetailField label="Resolution" value={document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution status was not supplied by this fictional sample."} />
    <DetailField label="Original" value={document.rawAvailable === true ? "Available" : document.rawAvailable === false ? "Unavailable" : "Original availability was not supplied by this fictional sample."} />
    <DetailField label="Lifecycle" value={lifecycle.title} help={lifecycle.detail} />
    <DetailField label="Pages" value={document.pages || "Page count was not supplied by this fictional sample."} />
    <DetailField label="Source region" value={document.sample?.region || "Source region was not supplied by this fictional sample."} />
    <DetailField label="Provenance" value={document.provenance || "Provenance was not supplied by this fictional sample."} />
    <DetailField label="Contribution" value={document.sample?.contribution || "Contribution was not supplied by this fictional sample."} />
    <DetailField label="Sample detail" value={document.detail || "Additional detail was not supplied by this fictional sample."} />
  </div><section className="document-wait"><h4>Wait or hold</h4><p>{document.sample?.waitReason || "Wait reason was not supplied by this fictional sample."}</p></section><RelatedEvidence mode={mode} document={document} onOpenEvidence={onOpenEvidence} /><Limitations /></aside>;
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
export function Documents({ result, mode, selectedDocument, capture, rescan, onSelectDocument, onOpenEvidence, onExploreSample }: DocumentsProps) {
  const said = capturePresentation(capture ? capture.state : { state: "idle" }, panelSentence(result));
  const captureRegion = capture?.onChoose ? <CapturePanel state={capture.state} onChoose={capture.onChoose} /> : mode === "demo" ? <SampleCaptureBoundary /> : null;
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
    return <>{mode === "live" && <LiveScope />}
      {!data.documents.length ? <div className="empty-state"><strong>{mode === "demo" ? "No sample documents" : "No documents yet"}</strong><span>{mode === "demo" ? "This fictional sample does not include any documents." : "Nothing has been added to this vault yet. Choose a file to add one."}</span>{mode === "live" && <button className="secondary-button" onClick={onExploreSample}>Explore fictional sample data</button>}</div> : <>{mode === "demo" && <SampleLifecycle />}<div className="document-library-layout"><DocumentLibrary documents={data.documents} mode={mode} selectedDocument={activeId} onSelectDocument={onSelectDocument} />{selection.state === "ready" ? <DocumentDetail mode={mode} document={selection.document} onOpenEvidence={onOpenEvidence} /> : selection.state === "missing" ? <div className="empty-state"><strong>Selected document unavailable</strong><span>The selected document is no longer present in the current vault read.</span></div> : selection.state === "conflicted_identity" ? <div className="empty-state"><strong>Document selection unavailable</strong><span>More than one document in this read uses the selected identity, so the interface will not choose between them.</span></div> : <div className="empty-state"><strong>Document identity unavailable</strong><span>No document with a unique stable identity can be selected from this read.</span></div>}</div></>}
    </>;
  }}</PanelStateView>
  </section>;
}
