import type { DocumentDetailResolution, SurfaceDocument } from "../../surface/types";

// What a row calls a document: the name the vault recorded for the file where
// there is one, and the kind of document where there is not. The identity stays
// on the row beneath it, as a detail rather than as a title.
export function documentRowLabel(document: SurfaceDocument): string {
  return document.name.trim() || document.docType?.trim() || "Document type unavailable";
}

export type DocumentSelection =
  | { state: "empty" }
  | { state: "ready"; document: SurfaceDocument }
  | { state: "pending" }
  | { state: "unavailable" }
  | { state: "missing" }
  | { state: "conflicted_identity" };

function identityCount(documents: readonly SurfaceDocument[], id: string): number {
  return documents.filter((document) => document.id === id).length;
}

export function resolveDocumentSelection(documents: readonly SurfaceDocument[], selectedId: string, detail?: DocumentDetailResolution): DocumentSelection {
  if (selectedId && detail?.id === selectedId) {
    if (detail.state === "ready" && detail.document?.id === selectedId) return { state: "ready", document: detail.document };
    if (["missing", "conflicted_identity", "pending", "unavailable"].includes(detail.state)) return { state: detail.state as "missing" | "conflicted_identity" | "pending" | "unavailable" };
  }
  if (!selectedId.trim()) {
    const firstUnique = documents.find((document) => document.id.trim() && identityCount(documents, document.id) === 1);
    return firstUnique ? firstUnique.detailRequiresLookup ? { state: "pending" } : { state: "ready", document: firstUnique } : { state: "empty" };
  }
  const matches = documents.filter((document) => document.id === selectedId);
  if (!matches.length) return { state: detail ? "pending" : "missing" };
  if (matches.length > 1 || matches[0]?.identityConflict) return { state: "conflicted_identity" };
  return matches[0]?.detailRequiresLookup ? { state: "pending" } : { state: "ready", document: matches[0] };
}
