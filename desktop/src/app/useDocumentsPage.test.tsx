import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentCursorHistory, useDocumentsPage } from "./useDocumentsPage";
import type { DocumentsData, DocumentsPageReader, FeatureResult } from "../surface/types";
const id = (n: number) => n.toString(16).padStart(64, "0");
function data(start = 0, total = 794): DocumentsData {
  const count = Math.min(50, total - start);
  return { contractVersion: "documents-page-v1", revision: "g1", summaryScope: "revision",
    documents: Array.from({ length: count }, (_, n) => ({ id: id(start + n + 1), name: `${start + n + 1}.pdf`, state: "", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] })),
    page: { pageStart: count ? start + 1 : 0, pageEnd: start + count, pageCount: count, totalDocuments: total, totalUnavailableReason: null, hasMore: start + count < total, nextCursor: start + count < total ? String(start + count) : null },
    selectedDocument: { state: "none", document: null }, readingSentence: "global sentence", captureQueue: [], processingJobs: [], outboundRecords: [] };
}
const pagesByCursor = new Map(Array.from({ length: 16 }, (_, n) => [String(n * 50), data(n * 50)]));
const pageForCursor = (cursor = "") => ({ ...pagesByCursor.get(cursor || "0")! });
const ready = (value: DocumentsData): FeatureResult<DocumentsData> => ({ state: "ready", data: value });

describe("bounded Documents state", () => {
  it("has exactly32 bounded cursor slots, evicts oldest, and supports First without a token", () => {
    const history = new DocumentCursorHistory(); history.reset();
    for (let n = 0; n < 40; n++) history.push(String(n));
    expect(history.slots).toHaveLength(32); expect(history.length).toBe(32); expect(history.slots[0]).toBe("8");
    expect(() => history.push("雪".repeat(1400))).toThrow();
    history.reset(); expect(history.slots[0]).toBe(""); expect(history.length).toBe(1);
  });
  it("traverses16 pages without accumulating more than100 rows and preserves an off-page selection", async () => {
    const initial = ready(data());
    const reader: DocumentsPageReader = vi.fn(async (request) => {
      const value = pageForCursor(request.cursor);
      value.selectedDocument = { state: "ready", document: { ...data(793).documents[0] } };
      return ready(value);
    });
    const owner = {};
    const { result } = renderHook(() => useDocumentsPage(initial, reader, owner, id(794)));
    await waitFor(() => expect(result.current.detail.state).toBe("ready"));
    for (let n = 0; n < 15; n++) {
      await act(async () => { await result.current.next(); });
      expect(result.current.cachedRowCount).toBeLessThanOrEqual(100);
      expect(result.current.detail.document?.id).toBe(id(794));
    }
    expect("data" in result.current.result && result.current.result.data.page?.pageCount).toBe(44);
    await act(async () => { await result.current.first(); });
    expect("data" in result.current.result && result.current.result.data.page?.pageStart).toBe(1);
  });
  it("keeps previous page and detail on failed continuation and permits retry", async () => {
    const initial = ready(data()); let failed = true;
    const reader: DocumentsPageReader = vi.fn(async (request) => failed && request.cursor ? { state: "unavailable" as const, reason: "temporary" } : ready(pageForCursor(request.cursor)));
    const owner = {}; const { result } = renderHook(() => useDocumentsPage(initial, reader, owner, ""));
    await act(async () => { await result.current.next(); });
    expect("data" in result.current.result && result.current.result.data.page?.pageStart).toBe(1);
    expect(result.current.notice).toContain("Retry"); failed = false;
    await act(async () => { await result.current.next(); });
    expect("data" in result.current.result && result.current.result.data.page?.pageStart).toBe(51);
  });
  it("discards a detail response from another selection or vault", async () => {
    const initial = ready(data()); const pending: ((result: FeatureResult<DocumentsData>) => void)[] = [];
    const reader: DocumentsPageReader = vi.fn(() => new Promise<FeatureResult<DocumentsData>>((resolve) => pending.push(resolve)));
    const ownerA = {}, ownerB = {};
    const { result, rerender } = renderHook(({ owner }) => useDocumentsPage(initial, reader, owner, ""), { initialProps: { owner: ownerA } });
    let workA: Promise<unknown>, workB: Promise<unknown>;
    act(() => { workA = result.current.resolve(id(700)); });
    act(() => { workB = result.current.resolve(id(701)); });
    const b = data(); b.selectedDocument = { state: "ready", document: { ...data().documents[0], id: id(701) } };
    await act(async () => { pending[1](ready(b)); await workB; });
    const a = data(); a.selectedDocument = { state: "ready", document: { ...data().documents[0], id: id(700) } };
    await act(async () => { pending[0](ready(a)); await workA; });
    expect(result.current.detail.document?.id).toBe(id(701));
    let workC: Promise<unknown>; act(() => { workC = result.current.resolve(id(702)); });
    rerender({ owner: ownerB });
    await act(async () => { pending[2](ready(a)); await workC; });
    expect(result.current.detail.state).toBe("none");
  });
});

it("never promotes a bounded row summary to authoritative selected detail, including an in-page identity", async () => {
  const value = data(0, 1); value.documents[0].detailRequiresLookup = true;
  let release!: () => void;
  const reader: DocumentsPageReader = vi.fn(async () => {
    await new Promise<void>((resolve) => { release = resolve; });
    return ready({ ...value, selectedDocument: { state: "ready", document: { ...value.documents[0], detailRequiresLookup: false, contribution: "Authoritative independent detail" } } });
  });
  const initial = ready(value); const owner = {};
  const view = renderHook(() => useDocumentsPage(initial, reader, owner, id(1)));
  expect(view.result.current.detail.state).toBe("pending");
  expect(view.result.current.detail.document).toBeNull();
  await act(async () => release());
  expect(view.result.current.detail.state).toBe("ready");
  expect(view.result.current.detail.document?.contribution).toBe("Authoritative independent detail");
  expect(reader).toHaveBeenCalledOnce();
});
