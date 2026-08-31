import type { DocumentReading, DocumentsData, SurfaceDocument } from "../types";
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

export function adaptDocuments(raw: unknown): DocumentsData | null {
  if (!isRecord(raw) || !Array.isArray(raw.documents)) return null;
  if (raw.documents.some((item) => !isRecord(item) || !textValue(item.id))) return null;
  const rows = uniqueRecordsById(raw.documents);
  const documents: SurfaceDocument[] = rows.map((item) => { const id = textValue(item.id); const docType = textValue(item.doc_type); const filename = textValue(item.filename); const resolved = booleanValue(item.resolved); const rawAvailable = booleanValue(item.raw_available); return { id, name: filename, contribution: textValue(item.contribution), state: resolved === true ? "Resolved" : resolved === false ? "Unresolved" : "Status unavailable", phaseLabel: "Not supplied", detail: docType, source: rawAvailable === true ? "Original available" : rawAvailable === false ? "Original unavailable" : "Original status unavailable", pages: "", provenance: "", evidenceLinks: [], docType, resolved, rawAvailable, reading: readingValue(item.reading), snapshotStatus: closedWord(item.snapshot_status, snapshotWords), snapshotSentence: textValue(item.snapshot_sentence), activityStatus: closedWord(item.activity_status, activityWords), activitySentence: textValue(item.activity_sentence) }; });
  return { documents, readingSentence: textValue(raw.reading_sentence), captureQueue: [], processingJobs: [], outboundRecords: [] };
}
