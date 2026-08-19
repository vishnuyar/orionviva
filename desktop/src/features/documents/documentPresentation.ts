import type { DocumentPhase, SurfaceDocument } from "../../surface/types";

export type LifecyclePresentation =
  | { state: "ready"; title: string; detail: string }
  | { state: "missing"; title: "Lifecycle unavailable"; detail: "Lifecycle was not supplied by this fictional sample." }
  | { state: "unrecognized"; title: "Lifecycle not recognized"; detail: "This fictional sample supplies a lifecycle value this preview does not recognize. No later step is implied." };

export const sampleLifecycle: ReadonlyArray<{ phase: DocumentPhase; title: string; detail: string }> = [
  { phase: "captured", title: "Captured", detail: "The original is saved before reader work begins." },
  { phase: "queued", title: "Waiting for a reader", detail: "The captured original is waiting; this screen does not start reader work." },
  { phase: "reading", title: "Reading", detail: "Reader work is separate. This static sample is not running a model." },
  { phase: "held", title: "Held for review", detail: "A human decision is needed. Nothing is posted automatically." },
  { phase: "parked", title: "Parked", detail: "The document is kept, but this sample has no supported way to continue reading it." },
  { phase: "unresolved", title: "Needs resolution", detail: "The sample says an issue remains unresolved." },
  { phase: "read_ready", title: "Read complete", detail: "A read result is available; that is not verification or ledger posting." },
  { phase: "verified", title: "Verified", detail: "The sample says verification finished; this screen still does not post or send anything." },
];

export function lifecyclePresentation(value: string | null | undefined): LifecyclePresentation {
  if (!value?.trim()) return { state: "missing", title: "Lifecycle unavailable", detail: "Lifecycle was not supplied by this fictional sample." };
  const match = sampleLifecycle.find((item) => item.phase === value);
  return match ? { state: "ready", title: match.title, detail: match.detail } : { state: "unrecognized", title: "Lifecycle not recognized", detail: "This fictional sample supplies a lifecycle value this preview does not recognize. No later step is implied." };
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
