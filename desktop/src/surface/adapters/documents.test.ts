import { describe, expect, it } from "vitest";
import { adaptDocuments } from "./documents";

describe("documents adapter", () => {
  it("rejects malformed payloads", () => {
    expect(adaptDocuments(null)).toBeNull();
    expect(adaptDocuments([])).toBeNull();
    expect(adaptDocuments({})).toBeNull();
    expect(adaptDocuments({ wrong: [] })).toBeNull();
    expect(adaptDocuments({ documents: "not-an-array" })).toBeNull();
    expect(adaptDocuments({ documents: [{ name: "missing stable id" }] })).toBeNull();
  });

  it("accepts only an explicit empty reviewed document collection", () => {
    expect(adaptDocuments({ documents: [] })).toEqual({ documents: [], captureQueue: [], processingJobs: [], outboundRecords: [] });
  });

  it("uses stable returned ids and only reviewed fields", () => {
    const result = adaptDocuments({ documents: [{ id: "doc", doc_type: "statement", resolved: false, raw_available: true, invented: "ignore" }] });
    expect(result?.documents[0]).toMatchObject({ id: "doc", name: "doc", docType: "statement", resolved: false, rawAvailable: true, provenance: "", evidenceLinks: [] });
    expect(JSON.stringify(result)).not.toContain("ignore");
  });

  it("deduplicates documents by stable id without name joins", () => {
    const result = adaptDocuments({ documents: [{ id: "b" }, { id: "a" }, { id: "b" }] });
    expect(result?.documents.map((document) => document.id)).toEqual(["b", "a"]);
  });
});
