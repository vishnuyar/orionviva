import { describe, expect, it } from "vitest";
// The sentence a person is told, read from the pack that ships it.
import moments from "../../../../product/viva/persona/pack-v24/moments.json";
import { adaptDocuments } from "./documents";

const SAVED_NO_READER = moments.documents_saved_no_reader;

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
    expect(adaptDocuments({ documents: [] })).toEqual({ documents: [], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] });
  });

  it("uses stable returned ids and only reviewed fields", () => {
    const result = adaptDocuments({ documents: [{ id: "doc", doc_type: "statement", filename: "quarter-close.pdf", resolved: false, raw_available: true, invented: "ignore" }] });
    expect(result?.documents[0]).toMatchObject({ id: "doc", name: "quarter-close.pdf", docType: "statement", resolved: false, rawAvailable: true, provenance: "", evidenceLinks: [] });
    expect(JSON.stringify(result)).not.toContain("ignore");
  });

  it("carries the name of the file where one was recorded and nothing where one was not", () => {
    const named = adaptDocuments({ documents: [{ id: "doc", filename: "quarter-close.pdf" }] });
    const unnamed = adaptDocuments({ documents: [{ id: "doc", doc_type: "statement" }] });
    expect(named?.documents[0].name).toBe("quarter-close.pdf");
    expect(unnamed?.documents[0].name).toBe("");
  });

  it("carries the panel sentence exactly as it was written, and nothing when there is none", () => {
    const spoken = adaptDocuments({ documents: [], reading_sentence: SAVED_NO_READER });
    expect(spoken?.readingSentence).toBe(SAVED_NO_READER);
    expect(adaptDocuments({ documents: [], reading_sentence: 4 })?.readingSentence).toBe("4");
    expect(adaptDocuments({ documents: [] })?.readingSentence).toBe("");
    expect(adaptDocuments({ documents: [], reading_sentence: { text: "composed here" } })?.readingSentence).toBe("");
  });

  it("takes only the three reading words the contract closed over", () => {
    const result = adaptDocuments({ documents: [{ id: "a", reading: "never_read" }, { id: "b", reading: "read_yielded_nothing" }, { id: "c", reading: "read" }, { id: "d", reading: "invented_word" }, { id: "e" }] });
    expect(result?.documents.map((document) => document.reading)).toEqual(["never_read", "read_yielded_nothing", "read", undefined, undefined]);
  });

  it("deduplicates documents by stable id without name joins", () => {
    const result = adaptDocuments({ documents: [{ id: "b" }, { id: "a" }, { id: "b" }] });
    expect(result?.documents.map((document) => document.id)).toEqual(["b", "a"]);
  });
});
