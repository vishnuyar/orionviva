import type { AccountView, DocumentsData, EvidenceLink, FeatureResult, FigureGrade, FigureMeasure, FigureView, SurfaceDocument, SurfaceSnapshot, UnmeasuredAccount } from "./types";

export type GradePresentation = { grade: FigureGrade; label: string; description: string };

export function gradePresentation(value: string | undefined): GradePresentation {
  switch (value) {
    case "verified": return { grade: "verified", label: "Verified", description: "Confirmed by a person or a completed verification step." };
    case "corroborated": return { grade: "corroborated", label: "Corroborated", description: "Supported by more than one source or matching record." };
    case "unverified": return { grade: "unverified", label: "Not yet verified", description: "Present in the vault, but not yet confirmed." };
    case "conflicted": return { grade: "conflicted", label: "Conflicting evidence", description: "The available records disagree and need review." };
    case "not_applicable": return { grade: "not_applicable", label: "Not applicable", description: "Evidence grading does not apply to this activity figure." };
    default: return { grade: "unavailable", label: "Evidence status unavailable", description: "This read did not provide a recognized evidence grade." };
  }
}

export type FieldAvailability<T> = { state: "supplied"; value: T } | { state: "unavailable" };
export type FigurePrecision =
  | { state: "exact"; label: "Exact"; detail: "The product read supplied this figure as exact." }
  | { state: "rounded"; label: "Rounded"; detail: "The product read supplied this figure as rounded." }
  | { state: "unrecognized"; label: "Exactness not recognized"; detail: "This read supplied an exactness value the preview does not recognize. The displayed figure is unchanged." }
  | { state: "unavailable"; label: "Exactness unavailable"; detail: "This read did not supply whether the displayed figure is exact or rounded." };
// `actionLabel` is what the control that opens this figure's evidence carries
// as its description, and `heading` is both what the drawer it opens is titled
// and what the control's own name continues with after the amount. Both are
// whole reviewed sentences where the read supplied them, and empty where it
// did not, in which case the composed forms below stand in.
export type EvidenceFigureView = Readonly<{ id: string; label: string; actionLabel: string; heading: string; variant: "net-worth" | "account-balance" | "account-liability" | "account-unknown" | "activity-income" | "activity-spending"; display: string; measure: FigureMeasure | null; currency: FieldAvailability<string>; grade: GradePresentation; precision: FigurePrecision; asOf: FieldAvailability<string>; coverage: FieldAvailability<readonly string[]>; unmeasured: readonly UnmeasuredAccount[]; recordIds: FieldAvailability<readonly string[]>; provenance: FieldAvailability<string>; caveats: readonly string[]; evidenceLinks: readonly EvidenceLink[] }>;
export type EvidenceFigureResolution = { state: "ready"; figure: EvidenceFigureView } | { state: "missing" } | { state: "conflicted" };
export type EvidenceTargetResolution = { state: "ready"; document: SurfaceDocument } | { state: "missing_identity" } | { state: "documents_unavailable" } | { state: "missing_document" } | { state: "conflicted_identity" };

const missingAmount = "Amount unavailable from this preview read.";
function field(value: string | null | undefined): FieldAvailability<string> { return value && value.trim() ? { state: "supplied", value } : { state: "unavailable" }; }
function records(value: readonly string[] | undefined): FieldAvailability<readonly string[]> { return value?.length ? { state: "supplied", value } : { state: "unavailable" }; }
// One sentence carried on its own becomes a list of one, so a figure whose
// scope is said in one line and one whose scope takes five are read the same
// way and neither is joined into a paragraph.
function lines(value: string | null | undefined): FieldAvailability<readonly string[]> { return value && value.trim() ? { state: "supplied", value: [value] } : { state: "unavailable" }; }
function financialGrade(grade: FigureGrade, label: string, description: string): GradePresentation {
  const fallback = gradePresentation(grade);
  return { ...fallback, label: label.trim() ? label : fallback.label, description: description.trim() ? description : fallback.description };
}
export function figurePrecision(value: string | null | undefined): FigurePrecision {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "exact") return { state: "exact", label: "Exact", detail: "The product read supplied this figure as exact." };
  if (normalized === "rounded") return { state: "rounded", label: "Rounded", detail: "The product read supplied this figure as rounded." };
  if (normalized) return { state: "unrecognized", label: "Exactness not recognized", detail: "This read supplied an exactness value the preview does not recognize. The displayed figure is unchanged." };
  return { state: "unavailable", label: "Exactness unavailable", detail: "This read did not supply whether the displayed figure is exact or rounded." };
}
export function netWorthEvidenceFigure(figure: FigureView): EvidenceFigureView { return { id: `net-worth:${figure.id}`, label: "Net worth", actionLabel: figure.evidenceLabel ?? "", heading: figure.evidenceHeading ?? "", variant: "net-worth", display: figure.display || missingAmount, measure: figure.measure, currency: field(figure.currency), grade: financialGrade(figure.grade, figure.gradeLabel, figure.gradeDescription), precision: figurePrecision(figure.exactness), asOf: field(figure.asOf), coverage: records(figure.coverage), unmeasured: figure.unmeasured ?? [], recordIds: records(figure.recordIds), provenance: { state: "unavailable" }, caveats: figure.caveats, evidenceLinks: figure.evidenceLinks }; }
export function accountEvidenceFigure(account: AccountView): EvidenceFigureView { const base = account.name.trim() ? account.name : "Account name unavailable"; const label = account.measure === "balance" ? `${base} balance` : account.measure === "owed" ? `${base} amount owed` : base; return { id: `account:${account.id}`, label, actionLabel: "", heading: "", variant: account.measure === "balance" ? "account-balance" : account.measure === "owed" ? "account-liability" : "account-unknown", display: account.display || missingAmount, measure: account.measure, currency: field(account.currency), grade: financialGrade(account.grade, account.gradeLabel, account.gradeDescription), precision: figurePrecision(account.exactness), asOf: field(account.asOf), coverage: lines(account.coverage), unmeasured: [], recordIds: records(account.recordIds), provenance: field(account.provenance), caveats: account.caveats ?? [], evidenceLinks: account.evidenceLinks }; }
function dataOf<T>(result: FeatureResult<T>): T | null { return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data : null; }
export function resolveEvidenceFigure(snapshot: SurfaceSnapshot, figureId: string): EvidenceFigureResolution {
  // Two kinds of figure open a drawer: the picture's own, and an account's.
  // A movement used to be a third, resolved off a shape only the fixture
  // demo produced; the live read composes movements as sentences with no
  // grade and no coverage, which is not a figure and has no drawer.
  const overview = dataOf(snapshot.overview); const candidates: EvidenceFigureView[] = [];
  for (const figure of overview?.picture.figures ?? []) candidates.push(netWorthEvidenceFigure(figure));
  for (const account of overview?.accounts ?? []) candidates.push(accountEvidenceFigure(account));
  const matches = candidates.filter((candidate) => candidate.id === figureId);
  if (!matches.length) return { state: "missing" };
  if (matches.length > 1) return { state: "conflicted" };
  return { state: "ready", figure: matches[0] };
}
export function resolveEvidenceTarget(result: FeatureResult<DocumentsData>, targetDocumentId: string): EvidenceTargetResolution {
  if (!targetDocumentId.trim()) return { state: "missing_identity" };
  const data = dataOf(result); if (!data) return { state: "documents_unavailable" };
  const matches = data.documents.filter((document) => document.id === targetDocumentId);
  if (!matches.length) return { state: "missing_document" };
  if (matches.length > 1) return { state: "conflicted_identity" };
  return { state: "ready", document: matches[0] };
}

export function documentById(documents: SurfaceDocument[], id: string): SurfaceDocument | undefined {
  return documents.find((document) => document.id === id);
}
