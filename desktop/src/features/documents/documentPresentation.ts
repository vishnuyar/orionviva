import type { SurfaceDocument } from "../../surface/types";

// What a row calls a document: the name the vault recorded for the file where
// there is one, and the kind of document where there is not. The identity stays
// on the row beneath it, as a detail rather than as a title.
export function documentRowLabel(document: SurfaceDocument): string {
  return document.name.trim() || document.docType?.trim() || "Document type unavailable";
}

export type DocumentSelection =
  | { state: "empty" }
  | { state: "ready"; document: SurfaceDocument }
  | { state: "missing" }
  | { state: "conflicted_identity" };

function identityCount(documents: readonly SurfaceDocument[], id: string): number {
  return documents.filter((document) => document.id === id).length;
}

export function resolveDocumentSelection(documents: readonly SurfaceDocument[], selectedId: string): DocumentSelection {
  if (!selectedId.trim()) {
    const firstUnique = documents.find((document) => document.id.trim() && identityCount(documents, document.id) === 1);
    return firstUnique ? { state: "ready", document: firstUnique } : { state: "empty" };
  }
  const matches = documents.filter((document) => document.id === selectedId);
  if (!matches.length) return { state: "missing" };
  if (matches.length > 1) return { state: "conflicted_identity" };
  return { state: "ready", document: matches[0] };
}
