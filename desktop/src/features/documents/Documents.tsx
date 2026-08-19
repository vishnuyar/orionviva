import { PanelStateView } from "../../components/PanelStateView";
import type { DocumentsData, EvidenceLink, FeatureResult, SurfaceDocument, SurfaceMode } from "../../surface/types";
import { lifecyclePresentation, resolveDocumentSelection, sampleLifecycle } from "./documentPresentation";

type DocumentsProps = { result: FeatureResult<DocumentsData>; mode: SurfaceMode; selectedDocument: string; onSelectDocument: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onExploreSample: () => void };

function CaptureAvailability({ mode }: { mode: SurfaceMode }) {
  const demo = mode === "demo";
  return <section className="document-capture-status" id="document-capture-status" tabIndex={-1} aria-labelledby="document-capture-title">
    <div className="detail-panel-label">{demo ? "Fictional sample" : "Capture"}</div>
    <h2 id="document-capture-title">{demo ? "A sample document journey" : "Document capture unavailable"}</h2>
    <p>{demo ? "These are static fictional examples stored with the app. No file is selected, no vault event is written, no model call is made, nothing is sent, and no durable state changes." : "Choosing or dropping a file is not connected in this preview. No file is selected or saved; no vault event, model call, outbound action, or durable change occurs."}</p>
    <button className="secondary-button" disabled aria-describedby="document-capture-explanation">Choose a local file</button>
    <span className="action-explanation" id="document-capture-explanation">{demo ? "File selection and drag-and-drop are not available in the fictional sample." : "File selection and drag-and-drop are unavailable for this vault."}</span>
  </section>;
}

function LiveScope() {
  return <section className="document-scope"><h2>What this read can show</h2><p>This private-vault read supplies document identity, document type, resolution status, and whether an original is available. Lifecycle steps, reader availability, pages, source regions, provenance, contributions, wait reasons, jobs, progress, recovery, posting, and outbound history are not supplied.</p></section>;
}

function SampleLifecycle() {
  return <section className="sample-lifecycle" aria-labelledby="sample-lifecycle-title"><h2 id="sample-lifecycle-title">Sample lifecycle</h2><p>These are fictional lifecycle meanings, not running jobs. A later state never starts automatically from this screen.</p><div className="sample-lifecycle-grid">{sampleLifecycle.map((item) => <article className="sample-lifecycle-card" key={item.phase}><span className="sample-lifecycle-icon" aria-hidden="true" /><strong>{item.title}</strong><p>{item.detail}</p></article>)}</div><p className="document-boundary">These labels describe distinct states. They do not imply that one starts the next. Ledger posting and outbound transmission are separate unavailable actions.</p></section>;
}

function DocumentLibrary({ documents, mode, selectedDocument, onSelectDocument }: { documents: readonly SurfaceDocument[]; mode: SurfaceMode; selectedDocument: string; onSelectDocument: (id: string) => void }) {
  return <section className="document-library" aria-labelledby="document-library-title"><h2 id="document-library-title">{mode === "demo" ? "Sample documents" : "Documents in this vault read"}</h2><p>{mode === "demo" ? "Every filename and detail below is fictional sample data." : "Only document identity, type, resolution status, and original availability returned by this read are shown."}</p><ul className="document-list">{documents.map((document, occurrence) => {
    const identityCount = document.id.trim() ? documents.filter((candidate) => candidate.id === document.id).length : 0;
    const selectable = Boolean(document.id.trim()) && identityCount === 1;
    const selected = selectable && selectedDocument === document.id;
    return <li className="document-list-item" key={`${document.id || "blank-document"}-${occurrence}`}>
      {selectable ? <button className={selected ? "detail-row detail-row-button active" : "detail-row detail-row-button"} aria-pressed={selected} onClick={() => onSelectDocument(document.id)}><span><strong>{mode === "demo" ? document.name || "Document name unavailable" : document.docType?.trim() || "Document type unavailable"}</strong><small>{mode === "demo" ? document.id : `Document ID · ${document.id}`}</small></span><span className="state-pill">{mode === "demo" ? lifecyclePresentation(document.phase).title : document.resolved === true ? "Resolved" : document.resolved === false ? "Unresolved" : "Resolution unavailable"}</span></button> : <div className="detail-row document-row-unavailable"><span><strong>{document.id.trim() ? "Document selection unavailable" : "Document identity unavailable"}</strong><small>{document.id.trim() ? "This identity appears more than once and cannot be selected." : "This row has no stable document ID, so it cannot be selected."}</small></span></div>}
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
  return <section className="document-limitations"><h4>Unavailable in this preview</h4><ul><li id="document-page-review-unavailable">Page and source-region review are not connected.</li><li>Focused correction is not connected.</li><li>Reader jobs, progress, cancellation, and restart recovery are not connected.</li><li>Ledger posting is not available from this screen.</li><li>Outbound actions and outbound history are not connected.</li><li>No control here changes a document or vault.</li></ul><button className="secondary-button" disabled aria-describedby="document-page-review-unavailable">Open page review</button></section>;
}

function DocumentDetail({ mode, document, onOpenEvidence }: { mode: SurfaceMode; document: SurfaceDocument; onOpenEvidence: (link: EvidenceLink) => void }) {
  if (mode === "live") return <aside className="detail-panel document-detail"><div className="detail-panel-label">Selected document</div><h3 id="selected-document-title" tabIndex={-1}>{document.docType?.trim() || "Document type unavailable"}</h3><div className="detail-panel-grid document-detail-grid">
    <DetailField label="Document ID" value={document.id} help="A document ID is a stable document identity. It is not a filename or record ID." />
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

export function Documents({ result, mode, selectedDocument, onSelectDocument, onOpenEvidence, onExploreSample }: DocumentsProps) {
  return <PanelStateView result={result} copy={{ partial: "Some document details are unavailable. Available documents are shown below.", needsInput: "Some documents need review. Available document details are shown below.", unavailable: { title: "Documents unavailable", detail: "Document details are not available in this build." }, failed: { title: "Documents could not be read", detail: "The documents section could not be read. The private vault is still open." } }}>{(data) => {
    const selection = resolveDocumentSelection(data.documents, selectedDocument);
    const activeId = selection.state === "ready" ? selection.document.id : selectedDocument;
    return <section className="feature-panel documents-surface"><CaptureAvailability mode={mode} />{mode === "live" && <LiveScope />}
      {!data.documents.length ? <div className="empty-state"><strong>{mode === "demo" ? "No sample documents" : "No documents yet"}</strong><span>{mode === "demo" ? "This fictional sample does not include any documents." : "This vault has no captured documents. Document import is not connected in this preview."}</span>{mode === "live" && <button className="secondary-button" onClick={onExploreSample}>Explore fictional sample data</button>}</div> : <>{mode === "demo" && <SampleLifecycle />}<div className="document-library-layout"><DocumentLibrary documents={data.documents} mode={mode} selectedDocument={activeId} onSelectDocument={onSelectDocument} />{selection.state === "ready" ? <DocumentDetail mode={mode} document={selection.document} onOpenEvidence={onOpenEvidence} /> : selection.state === "missing" ? <div className="empty-state"><strong>Selected document unavailable</strong><span>The selected document is no longer present in the current vault read.</span></div> : selection.state === "conflicted_identity" ? <div className="empty-state"><strong>Document selection unavailable</strong><span>More than one document in this read uses the selected identity, so the interface will not choose between them.</span></div> : <div className="empty-state"><strong>Document identity unavailable</strong><span>No document with a unique stable identity can be selected from this read.</span></div>}</div></>}
    </section>;
  }}</PanelStateView>;
}
