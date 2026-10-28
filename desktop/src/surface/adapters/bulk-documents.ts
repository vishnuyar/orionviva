import type { BulkDocumentResult, BulkDocumentOutcome } from "../types";
import { isRecord } from "./primitives";

const actions = ["posted", "conflict", "gap", "identity", "awaiting", "parked", "duplicate", "refused", "failed", "cancelled"] as const;
const readings = ["read", "read_yielded_nothing", "never_read"];
const reasons = ["file_unavailable", "not_a_regular_file", "file_over_size_limit", "file_unreadable", "read_failed", "job_cancelled", "no_model", "outcome_unknown", "new_reading_available", "already_accepted", "financial_review", "reading_in_progress", "uncertain_audit", "missing_original", "capture_conflict", "evidence_unavailable", "stale_confirmation", "confirmation_used", "confirmation_unavailable"];
export function adaptBulkDocuments(raw: unknown, expected: number, expectedIds?: readonly string[]): BulkDocumentResult | null {
  if (!isRecord(raw) || Object.keys(raw).length !== 2 || typeof raw.job_id !== "string" || !raw.job_id.trim() || !Array.isArray(raw.rows) || raw.rows.length !== expected || expected < 1 || expected > 3) return null;
  const rows: BulkDocumentOutcome[] = [];
  for (const [ordinal, row] of raw.rows.entries()) {
    if (!isRecord(row) || Object.keys(row).length !== 5 || row.ordinal !== ordinal || !actions.some((action) => action === row.action)
      || !(row.document_id === null || typeof row.document_id === "string" && row.document_id.trim().length > 0)
      || !(row.disposition === null || typeof row.disposition === "string" && readings.includes(row.disposition))
      || !(row.reason === null || typeof row.reason === "string" && reasons.includes(row.reason))) return null;
    if (expectedIds && (expectedIds.length !== expected || row.document_id !== expectedIds[ordinal])) return null;
    rows.push({ ordinal, documentId: row.document_id as string | null, action: row.action as BulkDocumentOutcome["action"], disposition: row.disposition as BulkDocumentOutcome["disposition"], reason: row.reason as string | null });
  }
  return { jobId: raw.job_id, rows };
}
