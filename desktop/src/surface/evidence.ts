import type { AccountView, ActivityView, DocumentsData, EvidenceLink, FeatureResult, FigureGrade, FigureView, SurfaceDocument, SurfaceSnapshot } from "./types";

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
export type EvidenceFigureView = Readonly<{ id: string; label: string; variant: "net-worth" | "account-balance" | "account-liability" | "account-unknown" | "activity-income" | "activity-spending"; display: string; measure: "balance" | "owed" | "spending" | "income" | null; currency: FieldAvailability<string>; grade: GradePresentation; precision: FigurePrecision; asOf: FieldAvailability<string>; coverage: FieldAvailability<string>; recordIds: FieldAvailability<readonly string[]>; provenance: FieldAvailability<string>; caveats: readonly string[]; evidenceLinks: readonly EvidenceLink[] }>;
export type EvidenceFigureResolution = { state: "ready"; figure: EvidenceFigureView } | { state: "missing" } | { state: "conflicted" };
export type EvidenceTargetResolution = { state: "ready"; document: SurfaceDocument } | { state: "missing_identity" } | { state: "documents_unavailable" } | { state: "missing_document" } | { state: "conflicted_identity" };

const missingAmount = "Amount unavailable from this preview read.";
function field(value: string | null | undefined): FieldAvailability<string> { return value && value.trim() ? { state: "supplied", value } : { state: "unavailable" }; }
function records(value: readonly string[] | undefined): FieldAvailability<readonly string[]> { return value?.length ? { state: "supplied", value } : { state: "unavailable" }; }
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
export function netWorthEvidenceFigure(figure: FigureView): EvidenceFigureView { return { id: `net-worth:${figure.id}`, label: "Net worth", variant: "net-worth", display: figure.display || missingAmount, measure: figure.measure, currency: field(figure.currency), grade: financialGrade(figure.grade, figure.gradeLabel, figure.gradeDescription), precision: figurePrecision(figure.exactness), asOf: field(figure.asOf), coverage: field(figure.coverage), recordIds: records(figure.recordIds), provenance: { state: "unavailable" }, caveats: figure.caveats, evidenceLinks: figure.evidenceLinks }; }
export function accountEvidenceFigure(account: AccountView): EvidenceFigureView { const base = account.name.trim() ? account.name : "Account name unavailable"; const label = account.measure === "balance" ? `${base} balance` : account.measure === "owed" ? `${base} amount owed` : base; return { id: `account:${account.id}`, label, variant: account.measure === "balance" ? "account-balance" : account.measure === "owed" ? "account-liability" : "account-unknown", display: account.display || missingAmount, measure: account.measure, currency: field(account.currency), grade: financialGrade(account.grade, account.gradeLabel, account.gradeDescription), precision: figurePrecision(account.exactness), asOf: field(account.asOf), coverage: field(account.coverage), recordIds: records(account.recordIds), provenance: field(account.provenance), caveats: [], evidenceLinks: account.evidenceLinks }; }
export function activityEvidenceFigure(activity: ActivityView): EvidenceFigureView { const base = activity.label.trim() ? activity.label : "Activity label unavailable"; return { id: `activity:${activity.id}`, label: `${base} ${activity.measure}`, variant: activity.measure === "income" ? "activity-income" : "activity-spending", display: activity.display || missingAmount, measure: activity.measure, currency: { state: "unavailable" }, grade: gradePresentation("not_applicable"), precision: figurePrecision(activity.exactness), asOf: { state: "unavailable" }, coverage: { state: "unavailable" }, recordIds: records(activity.recordIds), provenance: field(activity.provenance), caveats: [], evidenceLinks: activity.evidenceLinks }; }
function dataOf<T>(result: FeatureResult<T>): T | null { return result.state === "ready" || result.state === "partial" || result.state === "needs_input" ? result.data : null; }
export function resolveEvidenceFigure(snapshot: SurfaceSnapshot, figureId: string): EvidenceFigureResolution {
  const overview = dataOf(snapshot.overview); const activity = dataOf(snapshot.activity); const candidates: EvidenceFigureView[] = [];
  if (overview?.netWorth) candidates.push(netWorthEvidenceFigure(overview.netWorth));
  for (const account of overview?.accounts ?? []) candidates.push(accountEvidenceFigure(account));
  const canonicalActivity = activity ? activity.items : overview?.recent ?? [];
  for (const item of canonicalActivity) candidates.push(activityEvidenceFigure(item));
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
