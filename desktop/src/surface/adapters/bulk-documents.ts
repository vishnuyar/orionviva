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

function importSummary(raw: unknown): import("../types").ImportSessionSummary | null {
  if (!isRecord(raw) || typeof raw.session_id !== "string" || !/^[a-f0-9]{32}$/.test(raw.session_id)
    || !["pending", "running", "interrupted", "completed", "stopped"].includes(String(raw.state))
    || typeof raw.total !== "number" || !Number.isInteger(raw.total) || raw.total < 1 || raw.total > 1000
    || typeof raw.completed !== "number" || !Number.isInteger(raw.completed) || raw.completed < 0 || raw.completed > raw.total
    || typeof raw.remaining !== "number" || !Number.isInteger(raw.remaining) || raw.remaining < 0 || raw.remaining > raw.total) return null;
  if (raw.label !== undefined && (typeof raw.label !== "string" || raw.label.length > 240)) return null;
  return { label: raw.label as string | undefined, sessionId: raw.session_id, total: raw.total, completed: raw.completed, remaining: raw.remaining, state: raw.state as import("../types").ImportSessionSummary["state"] };
}
export function adaptImportSessions(raw: unknown): readonly import("../types").ImportSessionSummary[] | null {
  if (!isRecord(raw) || !Array.isArray(raw.sessions) || raw.sessions.length > 1000) return null;
  const rows = raw.sessions.map(importSummary);
  return rows.some((row) => !row) || new Set(rows.map((row) => row?.sessionId)).size !== rows.length ? null : rows as import("../types").ImportSessionSummary[];
}
export function adaptImportSession(raw: unknown): import("../types").ImportSessionSnapshot | null {
  const summary = importSummary(raw);
  if (!summary || !isRecord(raw) || !Array.isArray(raw.rows) || raw.rows.length !== summary.total) return null;
  const rows: import("../types").BulkDocumentRow[] = [];
  for (const [ordinal, row] of raw.rows.entries()) {
    if (!isRecord(row) || row.ordinal !== ordinal || typeof row.filename !== "string" || row.filename.length > 4096
      || !["capturing", "pending", "running", "interrupted", "posted", "conflict", "gap", "identity", "awaiting", "parked", "duplicate", "refused", "failed", "cancelled"].includes(String(row.status))
      || !(row.document_id === null || typeof row.document_id === "string" && /^[a-f0-9]{64}$/.test(row.document_id))) return null;
    const status = row.status === "pending" || row.status === "capturing" ? "queued" : row.status === "running" ? summary.state === "interrupted" ? "uncertain" : "working" : row.status === "interrupted" ? "uncertain" : row.status as import("../types").BulkDocumentOutcome["action"];
    let outcome: BulkDocumentOutcome | undefined;
    if (row.outcome !== undefined && row.outcome !== null) {
      if (!isRecord(row.outcome)) return null;
      const adapted = adaptBulkDocuments({ job_id: "saved", rows: [{ ...row.outcome, ordinal: 0 }] }, 1);
      if (!adapted || adapted.rows[0].documentId !== row.document_id) return null;
      outcome = { ...adapted.rows[0], ordinal };
    }
    rows.push({ path: row.filename, documentId: row.document_id ?? undefined, status, outcome });
  }
  return { ...summary, rows };
}
export function adaptImportChunk(raw: unknown): import("../types").ImportChunkResult | null {
  if (!isRecord(raw)) return null;
  const session = adaptImportSession(raw.session);
  if (!session || !Array.isArray(raw.rows)) return null;
  const result = raw.rows.length ? adaptBulkDocuments({ job_id: raw.job_id, rows: raw.rows }, raw.rows.length) : { jobId: "", rows: [] };
  return result ? { ...result, session } : null;
}
