import type { ReactNode, RefObject } from "react";
import { resolveEvidenceFigure, resolveEvidenceTarget, type EvidenceFigureView, type FieldAvailability, type GradePresentation } from "../surface/evidence";
import type { EvidenceLink, SurfaceSnapshot } from "../surface/types";
import { FeatureBoundary } from "./FeatureBoundary";

export type EvidenceSelection = { figureId: string };
type DrawerProps = { snapshot: SurfaceSnapshot; selection: EvidenceSelection; onDismiss: () => void; onOpenDocument: (link: EvidenceLink) => void; renderEvidenceBadge: (grade: GradePresentation) => ReactNode; drawerRef?: RefObject<HTMLElement | null>; closeRef?: RefObject<HTMLButtonElement | null> };
const unavailableAmount = "Amount unavailable from this preview read.";
function supplied(value: FieldAvailability<string>, fallback: string) { return value.state === "supplied" ? value.value : fallback; }
function relationLabel(relation: string) { switch (relation) { case "same_period": return "Same period"; case "same_account": return "Same account"; case "settles_question": return "Settles question"; case "corroborates": return "Corroborates"; default: return "Relationship not recognized"; } }
function measureLabel(measure: EvidenceFigureView["measure"]) { switch (measure) { case "balance": return "Balance"; case "owed": return "Amount owed"; case "spending": return "Spending"; case "income": return "Income"; default: return "Measurement type was not supplied by this read."; } }

function TargetState({ link, snapshot, onOpenDocument }: { link: EvidenceLink; snapshot: SurfaceSnapshot; onOpenDocument: (link: EvidenceLink) => void }) {
  const label = link.label.trim() || "Source label unavailable";
  const target = resolveEvidenceTarget(snapshot.documents, link.targetDocumentId);
  if (target.state === "ready") return <button className="evidence-source-action" onClick={() => onOpenDocument(link)}>Open {target.document.name}</button>;
  const copy = target.state === "missing_identity" ? ["Source target unavailable", "This evidence reference does not include a document identity."]
    : target.state === "documents_unavailable" ? ["Documents unavailable", "Documents are not available in the current vault read."]
      : target.state === "missing_document" ? ["Source document unavailable", `This evidence points to “${label}”, but that document is not present in the current vault read.`]
        : ["Source target unavailable", `More than one document has the identity “${link.targetDocumentId}” in the current vault read. No document was opened.`];
  return <div className="evidence-target-state"><strong>{copy[0]}</strong><span>{copy[1]}</span></div>;
}

export function EvidenceDrawer({ snapshot, selection, onDismiss, onOpenDocument, renderEvidenceBadge, drawerRef, closeRef }: DrawerProps) {
  const resolution = resolveEvidenceFigure(snapshot, selection.figureId);
  const label = resolution.state === "ready" ? resolution.figure.label : "this figure";
  return <><div className="evidence-backdrop" aria-hidden="true" onClick={onDismiss} /><aside ref={drawerRef} id="figure-evidence-drawer" className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="figure-evidence-title" aria-describedby="figure-evidence-summary" tabIndex={-1}>
    <div className="evidence-drawer-topline"><div><span className="evidence-boundary">{snapshot.mode === "demo" ? "Sample figure · Fictional data" : "Private vault figure · Opened on this device"}</span><h2 id="figure-evidence-title">Evidence for {label}</h2><p id="figure-evidence-summary">Status, source records, and limits for the displayed figure.</p></div><button ref={closeRef} className="evidence-close" aria-label="Close evidence" onClick={onDismiss}>×</button></div>
    <FeatureBoundary resetKey={`${snapshot.mode}-${selection.figureId}`}>
      {resolution.state === "missing" ? <div className="empty-state"><strong>Evidence unavailable</strong><span>This figure is no longer present in the current vault read.</span></div>
        : resolution.state === "conflicted" ? <div className="empty-state"><strong>Evidence unavailable</strong><span>More than one figure in this read uses this identity, so the interface will not choose between them.</span></div>
          : <EvidenceContents figure={resolution.figure} snapshot={snapshot} onOpenDocument={onOpenDocument} renderEvidenceBadge={renderEvidenceBadge} />}
    </FeatureBoundary>
  </aside></>;
}

function EvidenceContents({ figure, snapshot, onOpenDocument, renderEvidenceBadge }: { figure: EvidenceFigureView; snapshot: SurfaceSnapshot; onOpenDocument: (link: EvidenceLink) => void; renderEvidenceBadge: (grade: GradePresentation) => ReactNode }) {
  return <div className="evidence-sections">
    <section><h3>Evidence status</h3>{renderEvidenceBadge(figure.grade)}<p>{figure.grade.description}</p><div className={`precision-state ${figure.precision.state}`}><strong>{figure.precision.label}</strong><span>{figure.precision.detail}</span></div></section>
    <section><h3>Figure details</h3><dl className="evidence-detail-grid"><div><dt>Displayed figure</dt><dd>{figure.display || unavailableAmount}</dd></div><div><dt>Measure</dt><dd>{measureLabel(figure.measure)}</dd></div><div><dt>Currency</dt><dd>{supplied(figure.currency, "Currency was not supplied by this read.")}</dd></div><div><dt>Measured</dt><dd>{supplied(figure.asOf, "Measurement date was not supplied by this read.")}</dd></div><div><dt>Coverage</dt><dd>{supplied(figure.coverage, "Coverage was not supplied by this read.")}</dd></div></dl></section>
    <section><h3>Records behind this figure</h3><p>These are record identities, not document links.</p>{figure.recordIds.state === "supplied" ? <ul className="record-identity-list">{figure.recordIds.value.map((recordId) => <li key={recordId}>{recordId}</li>)}</ul> : <p>Record identities were not supplied by this read.</p>}</section>
    <section><h3>Source trail</h3><p>{supplied(figure.provenance, "Provenance details were not supplied by this read.")}</p>{figure.evidenceLinks.length ? <div className="evidence-source-list">{figure.evidenceLinks.map((link) => <div className="evidence-source-row" key={`${link.targetDocumentId}-${link.label}-${link.relation}-${link.page}`}><strong>{link.label.trim() || "Source label unavailable"}</strong><span>{relationLabel(link.relation)}</span><span>{link.page.trim() || "Page or region was not supplied by this read."}</span><TargetState link={link} snapshot={snapshot} onOpenDocument={onOpenDocument} /></div>)}</div> : <p>No document target was supplied for this figure.</p>}</section>
    <section><h3>Limits and omissions</h3>{figure.caveats.length ? <ul>{figure.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul> : <p>Caveats were not supplied by this read.</p>}</section>
  </div>;
}
