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
