import { describe, expect, it } from "vitest";
import { adaptBulkDocuments } from "./bulk-documents";
const row = { ordinal: 0, document_id: "source-1", action: "awaiting", disposition: "read", reason: null };
describe("bulk terminal rows", () => {
  it("retains held, unread, and uncaptured outcomes separately", () => {
    expect(adaptBulkDocuments({ job_id: "chunk-1", rows: [row, { ...row, ordinal: 1, action: "parked", disposition: "never_read", reason: "no_model" }, { ...row, ordinal: 2, document_id: null, action: "failed", disposition: null, reason: "file_unavailable" }] }, 3)).toMatchObject({ jobId: "chunk-1", rows: [{ action: "awaiting", disposition: "read" }, { action: "parked", disposition: "never_read" }, { action: "failed", documentId: null, disposition: null }] });
  });
  it.each([
    { job_id: "chunk-1", rows: [] }, { job_id: "chunk-1", rows: [row], unknown: true },
    { job_id: "chunk-1", rows: [{ ...row, ordinal: 1 }] }, { job_id: "chunk-1", rows: [{ ...row, action: "verified" }] },
    { job_id: "chunk-1", rows: [{ ...row, disposition: "readish" }] }, { job_id: "chunk-1", rows: [{ ...row, reason: "provider raw body" }] },
    { job_id: "chunk-1", rows: [{ ...row, document_id: "" }] }, { job_id: "chunk-1", rows: [{ ...row, extra: true }] },
  ])("refuses missing, reordered or unknown wire facts %#", (raw) => { expect(adaptBulkDocuments(raw, 1)).toBeNull(); });
  it.each(["reason", "disposition"])("refuses array-coerced %s while preserving nullable and string values", (field) => {
    const valid = { ordinal: 0, document_id: "source-1", action: "parked", disposition: "read", reason: "no_model" };
    expect(adaptBulkDocuments({ job_id: "chunk-1", rows: [valid] }, 1)).not.toBeNull();
    expect(adaptBulkDocuments({ job_id: "chunk-1", rows: [{ ...valid, [field]: [valid[field as "reason" | "disposition"]] }] }, 1)).toBeNull();
    expect(adaptBulkDocuments({ job_id: "chunk-1", rows: [{ ...valid, [field]: null }] }, 1)).not.toBeNull();
  });

});

it("binds retained terminal outcomes to their selected ordinal and stable identity", () => {
 const id = "a".repeat(64), other = "b".repeat(64);
 const raw = { job_id: "retained", rows: [{ ...row, document_id: id, action: "refused", disposition: null, reason: "stale_confirmation" }] };
 expect(adaptBulkDocuments(raw, 1, [id])?.rows[0]).toMatchObject({ documentId: id, reason: "stale_confirmation" });
 expect(adaptBulkDocuments(raw, 1, [other])).toBeNull();
 expect(adaptBulkDocuments({ ...raw, rows: [{ ...raw.rows[0], document_id: null }] }, 1, [id])).toBeNull();
 expect(adaptBulkDocuments(raw, 1, [])).toBeNull();
});

import { adaptImportSession, adaptImportSessions, adaptImportChunk } from "./bulk-documents";
const queued = { session_id: "a".repeat(32), total: 1, completed: 0, remaining: 1, state: "pending", rows: [{ ordinal: 0, document_id: "b".repeat(64), filename: "synthetic.pdf", status: "pending", outcome: null }] };
it("accepts a bounded queue snapshot and rejects mismatched outcome identities", () => {
  expect(adaptImportSession(queued)?.rows[0].status).toBe("queued");
  expect(adaptImportSession({ ...queued, rows: [{ ...queued.rows[0], outcome: { ...row, document_id: "c".repeat(64) } }] })).toBeNull();
  expect(adaptImportSessions({ sessions: [queued, queued] })).toBeNull();
  expect(adaptImportChunk({ job_id: "saved", rows: [row], session: queued })?.session.sessionId).toBe(queued.session_id);
  expect(adaptImportSession({ ...queued, total: 2 })).toBeNull();
});

it("shows retained running rows as uncertain after interruption rather than active workers", () => {
  const result = adaptImportSession({ ...queued, state: "interrupted", rows: [{ ...queued.rows[0], status: "running" }] });
  expect(result?.rows[0].status).toBe("uncertain");
});

it.each(["total", "completed", "remaining"] as const)("rejects non-integer queue count %s without coercion", (field) => {
  for (const value of ["1", true, null, 0.5, Infinity, NaN]) {
    expect(adaptImportSession({ ...queued, [field]: value })).toBeNull();
  }
});
