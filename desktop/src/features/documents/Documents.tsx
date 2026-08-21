import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { ChannelPresentation } from "../../components/actionChannel";
import type { CaptureActionState, DocumentsData, EvidenceLink, FeatureResult, SurfaceDocument, SurfaceMode } from "../../surface/types";
import { documentRowLabel, lifecyclePresentation, resolveDocumentSelection, sampleLifecycle } from "./documentPresentation";

// What a screen needs to say what became of a capture, and — where the host
// offers a way to choose a file — to start one. A source that cannot take a
// file at all carries none of this, so the control is absent rather than
// present and refusing; a host that can receive a dropped file but offers no
// picker carries the state without the control.
export type CaptureControls = { state: CaptureActionState; onChoose: (() => void) | null };
type DocumentsProps = { result: FeatureResult<DocumentsData>; mode: SurfaceMode; selectedDocument: string; capture: CaptureControls | null; onSelectDocument: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onExploreSample: () => void };

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

function SampleCaptureBoundary() {
  return <section className="document-capture-status" id="document-capture-status" tabIndex={-1} aria-labelledby="document-capture-title">
    <div className="detail-panel-label">Fictional sample</div>
    <h2 id="document-capture-title">A sample document journey</h2>
    <p>These are static fictional examples stored with the app. No file is selected, no vault event is written, no model call is made, nothing is sent, and no durable state changes.</p>
    <p>Nothing is added to a vault from the fictional sample.</p>
  </section>;
}

function LiveScope() {
  return <section className="document-scope"><h2>What this read can show</h2><p>This private-vault read supplies document identity, the name of the file where one was recorded, document type, resolution status, whether an original is available, and whether it has been read. Lifecycle steps, pages, source regions, provenance, contributions, wait reasons, jobs, progress, recovery, posting, and outbound history are not supplied.</p></section>;
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
  return <section className="document-limitations"><h4>Unavailable in this preview</h4><ul><li id="document-page-review-unavailable">Page and source-region review are not connected.</li><li>Focused correction is not connected.</li><li>Reader jobs, progress, cancellation, and restart recovery are not connected.</li><li>Ledger posting is not available from this screen.</li><li>Outbound actions and outbound history are not connected.</li><li>No control here changes a document or vault.</li></ul></section>;
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
    <DetailField label="Contribution" value="What this document contributed is not supplied by the private-vault read." />
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
export function Documents({ result, mode, selectedDocument, capture, onSelectDocument, onOpenEvidence, onExploreSample }: DocumentsProps) {
  const said = capturePresentation(capture ? capture.state : { state: "idle" }, panelSentence(result));
  const captureRegion = capture?.onChoose ? <CapturePanel state={capture.state} onChoose={capture.onChoose} /> : mode === "demo" ? <SampleCaptureBoundary /> : null;
  if (result.state === "absent" && !captureRegion && !said) return null;
  return <section className="feature-panel documents-surface">
    {captureRegion}
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
