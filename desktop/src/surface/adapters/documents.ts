import type { RetainedDocumentRetry, DocumentReading, DocumentsData, SurfaceDocument, SourceComponentView, SourceObservationView, SourcePageTarget } from "../types";
import { booleanValue, isRecord, textValue, uniqueRecordsById } from "./primitives";

const readingWords: readonly DocumentReading[] = ["never_read", "read_yielded_nothing", "read"];
const snapshotWords = ["posted", "held", "unavailable"] as const;
const activityWords = ["complete", "incomplete", "unavailable", "not_applicable"] as const;

// The reading word is taken only when it is one the contract closed over.
// Anything else is carried as nothing known rather than shown as itself.
function readingValue(value: unknown): DocumentReading | undefined {
  const word = textValue(value);
  return readingWords.find((candidate) => candidate === word);
}

function closedWord<T extends string>(value: unknown, words: readonly T[]): T | undefined {
  const word = textValue(value);
  return words.find((candidate) => candidate === word);
}

const componentKinds = ["deposit_terms", "deposit_balance", "mortgage_terms", "principal_balance", "loan_period", "payments", "escrow_balance", "settlement_sources_uses", "settlement_fees", "financed_fees", "old_loan_zero", "settlement_relationship", "old_loan_payoff_link", "settlement_cash_fee", "tax_paid", "tax_payment_link", "maturity", "payment", "counterpart"];
const observationKinds = ["deposit_terms", "mortgage_terms", "availability", "deposit_components", "mortgage_components", "refinance", "tax_receipt", "position_classification", "apr_context_v1"];
const reasonCodes = ["accepted", "missing_printed_fields", "unmatched_counterpart", "conflicting_source", "identity_unresolved", "reconciliation_failed", "source_unavailable", "review_required"];
function boundedText(raw: unknown): raw is string { return typeof raw === "string" && raw.length > 0 && new TextEncoder().encode(raw).length <= 4096; }
function sourcePages(raw: unknown, documentId: string): SourcePageTarget[] | null {
  if (!Array.isArray(raw) || raw.length > 32) return null;
  const pages: SourcePageTarget[] = [];
  for (const page of raw) {
    if (!isRecord(page) || page.document_id !== documentId || !/^[0-9a-f]{64}$/.test(documentId) || typeof page.page !== "number" || !Number.isInteger(page.page) || page.page < 1 || page.page > 200 || !boundedText(page.label)) return null;
    pages.push({ documentId, page: page.page, label: page.label });
  }
  return new Set(pages.map((page) => page.page)).size === pages.length ? pages : null;
}
export function parseSourceComponents(raw: unknown, docId: string): SourceComponentView[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > 128) return null;
  const result: SourceComponentView[] = [];
  for (const item of raw) {
    if (!isRecord(item) || !boundedText(item.component) || !componentKinds.includes(String(item.kind)) || !boundedText(item.label) || !["accepted", "held", "conflicted", "unavailable"].includes(String(item.disposition)) || !reasonCodes.includes(String(item.reason_code)) || !boundedText(item.reason)) return null;
    if ((item.disposition === "accepted") !== (item.reason_code === "accepted") || (item.disposition === "unavailable") !== (item.reason_code === "source_unavailable")) return null;
    if ((item.kind === "payment" || item.kind === "counterpart") ? !item.component.startsWith(`${item.kind}:`) : item.component !== item.kind) return null;
    const pages = sourcePages(item.source_pages, docId); if (!pages || (item.effective_date !== undefined && (typeof item.effective_date !== "string" || !new RegExp("^[0-9]{4}-[0-9]{2}-[0-9]{2}$").test(item.effective_date)))) return null;
    result.push({ effectiveDate: item.effective_date as string | undefined, component: item.component, kind: String(item.kind), label: item.label, disposition: item.disposition as SourceComponentView["disposition"], reasonCode: String(item.reason_code), reason: item.reason, sourcePages: pages });
  }
  return result;
}
function parseSourceObservations(raw: unknown, docId: string): SourceObservationView[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > 32) return null;
  const result: SourceObservationView[] = [];
  for (const item of raw) {
    if (!isRecord(item) || !observationKinds.includes(String(item.kind)) || !boundedText(item.label) || !["active", "superseded", "retracted"].includes(String(item.lifecycle))) return null;
    const pages = sourcePages(item.source_pages, docId); if (!pages) return null;
    result.push({ kind: String(item.kind), label: item.label, lifecycle: item.lifecycle as SourceObservationView["lifecycle"], sourcePages: pages });
  }
  return result;
}

export function adaptDocuments(raw: unknown): DocumentsData | null {
  if (!isRecord(raw) || !Array.isArray(raw.documents)) return null;
  if (raw.documents.some((item) => !isRecord(item) || !textValue(item.id))) return null;
  const rows = uniqueRecordsById(raw.documents);
  const documents: SurfaceDocument[] = rows.map((item) => { const id = textValue(item.id); const docType = textValue(item.doc_type); const filename = textValue(item.filename); const resolved = booleanValue(item.resolved); const rawAvailable = booleanValue(item.raw_available); return { detailUnavailable: typeof item.detail_unavailable === "string" ? item.detail_unavailable : undefined, componentStatuses: parseSourceComponents(item.component_statuses, id) ?? undefined, observationSections: parseSourceObservations(item.observation_sections, id) ?? undefined, observationStatuses: Array.isArray(item.observation_statuses) ? item.observation_statuses as SurfaceDocument["observationStatuses"] : undefined, identityConflict: item.identity_conflict === true, id, name: filename, contribution: textValue(item.contribution), state: resolved === true ? "Resolved" : resolved === false ? "Unresolved" : "Status unavailable", phaseLabel: "Not supplied", detail: docType, source: rawAvailable === true ? "Original available" : rawAvailable === false ? "Original unavailable" : "Original status unavailable", pages: "", provenance: "", evidenceLinks: [], docType, resolved, rawAvailable, reading: readingValue(item.reading), snapshotStatus: closedWord(item.snapshot_status, snapshotWords), snapshotSentence: textValue(item.snapshot_sentence), activityStatus: closedWord(item.activity_status, activityWords), activitySentence: textValue(item.activity_sentence) }; });
  return { documents, readingSentence: textValue(raw.reading_sentence), captureQueue: [], processingJobs: [], outboundRecords: [] };
}

const retainedReasons = ["new_reading_available", "already_accepted", "financial_review", "reading_in_progress", "uncertain_audit", "missing_original", "capture_conflict", "evidence_unavailable", "no_model", "stale_confirmation", "confirmation_used", "confirmation_unavailable"];
function retainedRetry(raw: unknown): RetainedDocumentRetry | undefined {
  if (!isRecord(raw) || Object.keys(raw).length !== 4 || raw.contract_version !== "retained-reading-v1" || typeof raw.state !== "string" || !["available", "blocked", "unavailable"].includes(raw.state) || typeof raw.reason !== "string" || !retainedReasons.includes(raw.reason)) return undefined;
  if (raw.state === "available" ? raw.reason !== "new_reading_available" || typeof raw.confirmation_token !== "string" || !new RegExp("^[\\x20-\\x7e]{1,1024}$").test(raw.confirmation_token) : raw.confirmation_token !== null || raw.reason === "new_reading_available") return undefined;
  return { state: raw.state as RetainedDocumentRetry["state"], reason: raw.reason as RetainedDocumentRetry["reason"], confirmationToken: raw.confirmation_token as string | null };
}

// A new client never interprets a legacy full array as a page.
export function adaptDocumentsPage(raw: unknown): DocumentsData | null {
  if (new TextEncoder().encode(JSON.stringify(raw)).length > 100000) return null;
  if (!isRecord(raw) || raw.contract_version !== "documents-page-v1" || raw.state !== "ready" ||
      !Array.isArray(raw.documents) || raw.documents.length > 50 || !isRecord(raw.page) ||
      !isRecord(raw.selected_document) || !isRecord(raw.revision) || !isRecord(raw.summary) || raw.summary.scope !== "revision") return null;
  const page = raw.page;
  const nonnegative = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
  if (![page.page_start, page.page_end, page.page_count].every(nonnegative) || page.page_count !== raw.documents.length ||
      (page.total_documents !== null && !nonnegative(page.total_documents)) ||
      (page.total_documents === null ? typeof page.total_unavailable_reason !== "string" : page.total_unavailable_reason !== null) ||
      typeof page.has_more !== "boolean" || (page.next_cursor !== null && (typeof page.next_cursor !== "string" || !page.next_cursor || new TextEncoder().encode(page.next_cursor).length > 4096)) ||
      page.has_more !== (page.next_cursor !== null) || (page.has_more && page.page_count !== 50) ||
      (typeof page.total_documents === "number" && (page.page_end as number) > page.total_documents) ||
      (page.page_count === 0 ? page.page_start !== 0 || page.page_end !== 0 : (page.page_start as number) < 1 || (page.page_end as number) - (page.page_start as number) + 1 !== page.page_count)) return null;
  if (raw.documents.some((item) => !isRecord(item) || typeof item.id !== "string" || !/^[0-9a-f]{64}$/.test(item.id)) ||
      new Set(raw.documents.map((item) => (item as Record<string, unknown>).id)).size !== raw.documents.length) return null;
  const evidenceRows = [...raw.documents, ...(isRecord(raw.selected_document.document) ? [raw.selected_document.document] : [])];
  for (const row of evidenceRows) {
    if (!isRecord(row) || typeof row.id !== "string" || !parseSourceComponents(row.component_statuses, row.id) || !parseSourceObservations(row.observation_sections, row.id)) return null;
    if (row.component_statuses !== undefined && (!Array.isArray(row.component_statuses) || row.component_statuses.length > 128 || row.component_statuses.some((component) => !isRecord(component) || typeof component.component !== "string" || new TextEncoder().encode(component.component).length > 4096 || !["accepted", "held", "conflicted", "unavailable"].includes(String(component.disposition))))) return null;
    if (row.observation_statuses !== undefined && (!Array.isArray(row.observation_statuses) || row.observation_statuses.length > 3 || row.observation_statuses.some((status) => !["active", "superseded", "retracted"].includes(String(status))))) return null;
  }
  const adapted = adaptDocuments(raw); if (!adapted) return null;
  const detail = raw.selected_document;
  if (!["none", "ready", "missing", "conflicted_identity", "unavailable"].includes(String(detail.state)) ||
      (detail.reason !== null && typeof detail.reason !== "string")) return null;
  let selected: SurfaceDocument | null = null;
  if (detail.state === "ready") {
    if (!isRecord(detail.document) || typeof detail.document.id !== "string" || !/^[0-9a-f]{64}$/.test(detail.document.id)) return null;
    selected = adaptDocuments({ documents: [detail.document] })?.documents[0] ?? null;
    if (!selected) return null;
    if (raw.retained_reading_version === "retained-reading-v1") selected = { ...selected, retry: retainedRetry(detail.document.retry) };
  } else if (detail.document !== null) return null;
  return { ...adapted, retainedReadingVersion: raw.retained_reading_version === "retained-reading-v1" ? "retained-reading-v1" : undefined, documents: adapted.documents.map((document) => ({ ...document, detailRequiresLookup: true })), contractVersion: "documents-page-v1", revision: JSON.stringify(raw.revision), summaryScope: "revision",
    selectedDocument: { state: detail.state as "none" | "ready" | "missing" | "conflicted_identity" | "unavailable", reason: detail.reason as string | null, document: selected },
    page: { totalDocuments: page.total_documents as number | null, totalUnavailableReason: page.total_unavailable_reason as string | null,
      pageStart: page.page_start as number, pageEnd: page.page_end as number, pageCount: page.page_count as number,
      hasMore: page.has_more, nextCursor: page.next_cursor as string | null } };
}
