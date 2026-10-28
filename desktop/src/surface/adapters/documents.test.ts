import { describe, expect, it } from "vitest";
// The sentence a person is told, read from the pack that ships it.
import moments from "../../../../product/viva/persona/pack-v31/moments.json";
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

import { adaptDocumentsPage } from "./documents";
function pagePayload() {
  return { contract_version: "documents-page-v1", state: "ready", revision: { generation: "synthetic-g1" },
    documents: [{ id: "a".repeat(64), filename: "source.pdf" }], selected_document: { state: "none", reason: null, document: null },
    page: { total_documents: 794, total_unavailable_reason: null, page_start: 1, page_end: 1, page_count: 1, has_more: false, next_cursor: null },
    summary: { scope: "revision", counts: { total_documents: 794 }, unavailable_reason: null } };
}
it("requires the exact page tag, honest metadata and bounded distinct rows", () => {
  expect(adaptDocumentsPage({ documents: [] })).toBeNull();
  expect(adaptDocumentsPage(pagePayload())?.page?.totalDocuments).toBe(794);
  for (const mutation of [
    { contract_version: "future" }, { documents: Array(51).fill(pagePayload().documents[0]) },
    { documents: [pagePayload().documents[0], pagePayload().documents[0]], page: { ...pagePayload().page, page_count: 2, page_end: 2 } },
    { page: { ...pagePayload().page, total_documents: null, total_unavailable_reason: null } },
    { page: { ...pagePayload().page, has_more: true, next_cursor: "x" } },
    { page: { ...pagePayload().page, page_end: 3 } },
    { selected_document: { state: "ready", reason: null, document: { id: "invalid" } } },
    { reading_sentence: "雪".repeat(34000) },
  ]) expect(adaptDocumentsPage({ ...pagePayload(), ...mutation })).toBeNull();
  const noCount = { ...pagePayload(), page: { ...pagePayload().page, total_documents: null, total_unavailable_reason: "count_unavailable" } };
  expect(adaptDocumentsPage(noCount)?.page?.totalDocuments).toBeNull();
});

const retainedId = "a".repeat(64);
function retainedPage(retry: unknown, version: unknown = "retained-reading-v1") {
  return { contract_version: "documents-page-v1", retained_reading_version: version, state: "ready", documents: [{ id: retainedId, retry }],
    page: { page_start: 1, page_end: 1, page_count: 1, total_documents: 1, total_unavailable_reason: null, has_more: false, next_cursor: null },
    revision: {}, summary: { scope: "revision" }, selected_document: { state: "ready", reason: null, document: { id: retainedId, retry } } };
}
const availableRetry = { contract_version: "retained-reading-v1", state: "available", reason: "new_reading_available", confirmation_token: "opaque.token" };
describe("selected saved original new reading contract", () => {
  it("admits only selected metadata on the supported version and never list metadata", () => {
    const data = adaptDocumentsPage(retainedPage(availableRetry));
    expect(data?.selectedDocument?.document?.retry).toEqual({ state: "available", reason: "new_reading_available", confirmationToken: "opaque.token" });
    expect(data?.documents[0].retry).toBeUndefined();
    expect(adaptDocumentsPage(retainedPage(availableRetry, "future"))?.selectedDocument?.document?.retry).toBeUndefined();
    expect(adaptDocuments({ documents: [{ id: retainedId, retry: availableRetry }] })?.documents[0].retry).toBeUndefined();
  });
  it.each([null, {}, { ...availableRetry, extra: true }, { ...availableRetry, state: ["available"] }, { ...availableRetry, reason: ["new_reading_available"] }, { ...availableRetry, confirmation_token: "é" }, { ...availableRetry, confirmation_token: "x".repeat(1025) }, { ...availableRetry, confirmation_token: "" }, { ...availableRetry, confirmation_token: "line\nfeed" }, { ...availableRetry, state: "blocked" }, { ...availableRetry, reason: "already_accepted" }])("keeps ordinary document details but hides malformed optional capability %#", (retry) => {
    const data = adaptDocumentsPage(retainedPage(retry)); expect(data).not.toBeNull(); expect(data?.selectedDocument?.document?.retry).toBeUndefined();
  });
  it("carries unavailable reason without a usable confirmation", () => {
    expect(adaptDocumentsPage(retainedPage({ ...availableRetry, state: "blocked", reason: "financial_review", confirmation_token: null }))?.selectedDocument?.document?.retry).toEqual({ state: "blocked", reason: "financial_review", confirmationToken: null });
  });
});
