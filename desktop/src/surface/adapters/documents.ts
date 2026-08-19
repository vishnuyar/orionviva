import type { DocumentsData, SurfaceDocument } from "../types";
import { booleanValue, isRecord, textValue, uniqueRecordsById } from "./primitives";

export function adaptDocuments(raw: unknown): DocumentsData | null {
  if (!isRecord(raw) || !Array.isArray(raw.documents)) return null;
  if (raw.documents.some((item) => !isRecord(item) || !textValue(item.id))) return null;
  const rows = uniqueRecordsById(raw.documents);
  const documents: SurfaceDocument[] = rows.map((item) => { const id = textValue(item.id); const docType = textValue(item.doc_type); const resolved = booleanValue(item.resolved); const rawAvailable = booleanValue(item.raw_available); return { id, name: id, state: resolved === true ? "Resolved" : resolved === false ? "Unresolved" : "Status unavailable", phaseLabel: "Not supplied", detail: docType, source: rawAvailable === true ? "Original available" : rawAvailable === false ? "Original unavailable" : "Original status unavailable", pages: "", provenance: "", evidenceLinks: [], docType, resolved, rawAvailable }; });
  return { documents, captureQueue: [], processingJobs: [], outboundRecords: [] };
}
