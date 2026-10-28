import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { DocumentsData, DocumentsPageReader, DocumentDetailResolution, FeatureResult } from "../surface/types";

export class DocumentCursorHistory {
  readonly slots: (string | null)[] = Object.seal(Array(32).fill(null));
  length = 0;
  push(token: string) {
    if (new TextEncoder().encode(token).length > 4096) throw new Error("cursor_too_large");
    if (this.length === 32) { this.slots.copyWithin(0, 1); this.length--; }
    this.slots[this.length++] = token;
  }
  previous() { if (this.length < 2) return null; this.slots[--this.length] = null; return this.slots[this.length - 1]; }
  reset() { this.slots.fill(null); this.length = 0; this.push(""); }
}
const dataOf = (result: FeatureResult<DocumentsData>) => "data" in result ? result.data : null;
const stripDetail = (data: DocumentsData): DocumentsData => ({ ...data, selectedDocument: undefined });
export function useDocumentsPage(initial: FeatureResult<DocumentsData>, reader: DocumentsPageReader | undefined,
    owner: object | null, selectedId: string, scopeKey = "") {
  const initialData = dataOf(initial);
  const [page, setPage] = useState<DocumentsData | null>(initialData);
  const [detail, setDetail] = useState<DocumentDetailResolution>({ state: "none", document: null });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [, rerender] = useState(0);
  const current = useRef({ owner, reader, initialData, scopeKey }); current.current = { owner, reader, initialData, scopeKey };
  const generation = useRef(0), detailGeneration = useRef(0);
  const busyRef = useRef(false);
  const pageRef = useRef(page); pageRef.current = page;
  const cursor = useRef("");
  const history = useRef(new DocumentCursorHistory());
  const cache = useRef<{ cursor: string; data: DocumentsData }[]>([]);
  const detailRef = useRef(detail); detailRef.current = detail;
  const lookup = useRef<{ id: string; owner: object | null; reader: DocumentsPageReader | undefined; scope: string; generation: number; promise: Promise<DocumentDetailResolution | null> } | null>(null);
  const heldOwner = useRef(owner);
  useLayoutEffect(() => () => { generation.current++; detailGeneration.current++; }, [owner]);
  useLayoutEffect(() => {
    const sameOwner = heldOwner.current === owner; heldOwner.current = owner;
    if (sameOwner && initialData?.contractVersion === "documents-page-v1" && pageRef.current?.revision === initialData.revision) {
      // A lazy destination read may finish after a source-link lookup. It
      // cannot erase an independent selection from the same revision.
      const bare = stripDetail(initialData);
      if (!cursor.current) { pageRef.current = bare; setPage(bare); }
      cache.current = [ { cursor: "", data: bare }, ...cache.current.filter((entry) => entry.cursor !== "") ].slice(0, 2);
      return;
    }
    if (sameOwner && owner && !initialData && pageRef.current) {
      setNotice("Statements could not be refreshed. The previous page and source selection remain visible."); return;
    }
    generation.current++; detailGeneration.current++;
    cursor.current = ""; history.current.reset(); cache.current = initialData ? [{ cursor: "", data: stripDetail(initialData) }] : [];
    pageRef.current = initialData ? stripDetail(initialData) : null; setPage(pageRef.current); detailRef.current = initialData?.selectedDocument ?? { state: "none", document: null }; setDetail(detailRef.current);
    busyRef.current = false; setBusy(false); setNotice("");
  }, [owner, initialData]);
  function resolve(id: string, force = false): Promise<DocumentDetailResolution | null> {
    const active = lookup.current;
    if (!force && active?.id === id && active.owner === current.current.owner && active.reader === current.current.reader && active.scope === current.current.scopeKey && active.generation === detailGeneration.current) return active.promise;
    const promise = resolveOnce(id, force);
    lookup.current = { id, owner: current.current.owner, reader: current.current.reader, scope: current.current.scopeKey, generation: detailGeneration.current, promise };
    void promise.finally(() => { if (lookup.current?.promise === promise) lookup.current = null; });
    return promise;
  }
  async function resolveOnce(id: string, force = false): Promise<DocumentDetailResolution | null> {
    if (!/^[0-9a-f]{64}$/.test(id)) return { state: "unavailable", reason: "invalid_selected_identity", document: null, id };
    detailGeneration.current++;
    if (!force && detailRef.current.state === "ready" && detailRef.current.id === id) return detailRef.current;
    const found = pageRef.current?.documents.filter((row) => row.id === id) ?? [];
    if (!force && found.length === 1 && found[0].detailUnavailable) { const value: DocumentDetailResolution = { state: "unavailable", reason: found[0].detailUnavailable, document: null, id }; setDetail(value); return value; }
    if (!force && found.length === 1 && !found[0].identityConflict && !found[0].detailRequiresLookup) { const value: DocumentDetailResolution = { state: "ready", document: found[0], id }; setDetail(value); return value; }
    const activeReader = current.current.reader;
    if (!activeReader) return { state: "unavailable", reason: "detail_reader_unavailable", document: null, id };
    const activeOwner = current.current.owner, activeScope = current.current.scopeKey, activeGeneration = ++detailGeneration.current;
    setDetail({ state: "pending", document: null, id });
    let result: FeatureResult<DocumentsData>;
    try { result = await activeReader({ contract_version: "documents-page-v1", ...(cursor.current ? { cursor: cursor.current } : {}), selected_document_id: id }); }
    catch { result = { state: "unavailable", reason: "detail_read_failed" }; }
    if (activeScope !== current.current.scopeKey || activeOwner !== current.current.owner || activeGeneration !== detailGeneration.current || activeReader !== current.current.reader) return null;
    const data = dataOf(result);
    const value: DocumentDetailResolution = data?.selectedDocument ? { ...data.selectedDocument, id } : { state: "unavailable", reason: "reason" in result ? result.reason : "detail_unavailable", document: null, id };
    // The tagged response is authoritative only for the identity requested.
    if (value.state === "ready" && value.document?.id !== id) return null;
    if (data && (!pageRef.current || data.revision !== pageRef.current.revision)) {
      const bare = stripDetail(data); cache.current = [{ cursor: "", data: bare }];
      cursor.current = ""; history.current.reset(); pageRef.current = bare; setPage(bare);
      setNotice("Statements changed. Showing the first page and checking the selected source again.");
    }
    setDetail(value); return value;
  }
  useEffect(() => {
    if (selectedId && pageRef.current?.contractVersion === "documents-page-v1") void resolve(selectedId);
    else { detailGeneration.current++; setDetail({ state: "none", document: null }); }
  }, [owner, initialData, selectedId, page?.revision, page?.page?.pageStart]);
  async function load(token: string, direction: "next" | "previous" | "first" | "retry") {
    if (busyRef.current || !current.current.reader) return;
    const activeReader = current.current.reader, activeOwner = current.current.owner, activeScope = current.current.scopeKey, activeGeneration = ++generation.current;
    detailGeneration.current++;
    busyRef.current = true; setBusy(true); setNotice("");
    const result = await activeReader({ contract_version: "documents-page-v1", ...(token ? { cursor: token } : {}), ...(selectedId ? { selected_document_id: selectedId } : {}) });
    if (activeScope !== current.current.scopeKey || activeOwner !== current.current.owner || activeGeneration !== generation.current || activeReader !== current.current.reader) return;
    const data = dataOf(result);
    if (!data) {
      busyRef.current = false; setBusy(false); setNotice("reason" in result && result.reason === "stale_cursor" ? "Statements changed. Use First page to refresh; your selection will be checked again." : "The next page could not be read. Your current page and selection are still here. Retry the page request.");
      return;
    }
    if (direction === "first") history.current.reset();
    else if (direction === "next") history.current.push(token);
    else if (direction === "previous") history.current.previous();
    cursor.current = token;
    const bare = stripDetail(data);
    if (data.revision !== pageRef.current?.revision) cache.current = [];
    // The session snapshot retains the initial page. Count that page as one
    // of the two cache slots instead of keeping two additional row pages.
    const first = cache.current.find((entry) => entry.cursor === "");
    cache.current = token && first && (!current.current.initialData || current.current.initialData.revision === data.revision) ? [first, { cursor: token, data: bare }] : [{ cursor: token, data: bare }];
    pageRef.current = bare; setPage(bare); busyRef.current = false; setBusy(false); setDetail(data.selectedDocument ? { ...data.selectedDocument, id: selectedId } : { state: "none", document: null });
    setNotice(direction === "first" ? "Statements refreshed from the first page." : ""); rerender((n) => n + 1);
  }
  let cachedRowCount = 0;
  for (const entry of cache.current) cachedRowCount += entry.data.documents.length;
  if (initialData && !cache.current.some((entry) => entry.data.documents === initialData.documents)) cachedRowCount += initialData.documents.length;
  const activeData = page ? { ...page, selectedDocument: detail } : initialData;
  return { result: activeData ? { state: "ready" as const, data: activeData } : initial,
    cancelPending: () => { generation.current++; detailGeneration.current++; busyRef.current = false; setBusy(false); setDetail((value) => value.state === "pending" ? { state: "unavailable", document: null, id: value.id, reason: "request_cancelled" } : value); },
    retrySelected: async () => { if (selectedId) await resolve(selectedId, true); },
    detail, resolve, busy, notice, canPrevious: history.current.length > 1,
    first: () => load("", "first"), next: () => page?.page?.nextCursor ? load(page.page.nextCursor, "next") : undefined,
    previous: () => { const token = history.current.length > 1 ? history.current.slots[history.current.length - 2] : null; if (token !== null) return load(token, "previous"); },
    cachedRowCount };
}
