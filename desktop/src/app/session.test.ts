import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { BridgeRequest, BridgeResponse, BridgeTransport, SurfaceName } from "../bridge/contracts";
import type { SurfaceSource } from "../surface/sources";
import { sampleSnapshot } from "../surface/sources";
import type { SurfaceSnapshot } from "../surface/types";
import { initialSession, liveReadingSnapshot, sessionReducer } from "./session";
import { useSurfaceSession } from "./useSurfaceSession";
import { destinations } from "./navigation";
import { retainSelection } from "./selection";

const liveSource: SurfaceSource = { id: "bridge-client", label: "Private vault", description: "Private", boundary: "bridge-ready", mode: "live", load: async () => liveReadingSnapshot() };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((onResolve, onReject) => { resolve = onResolve; reject = onReject; }); return { promise, resolve, reject }; }
function ok<T>(requestId: string, result: T): BridgeResponse<T> { return { protocol: "1.0", request_id: requestId, ok: true, result }; }
function emptyPayload(surface: SurfaceName) { return surface === "overview" ? { accounts: [] } : surface === "documents" ? { documents: [] } : { questions: [], total: 0 }; }
function readyLive(): SurfaceSnapshot {
  return {
    ...liveReadingSnapshot(),
    overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "Opened local vault", netWorth: null, accounts: [{ id: "account-live", name: "Live", kind: "", measure: null, exactValue: "", currency: "", display: "", grade: "unavailable", gradeLabel: "Evidence status unavailable", gradeDescription: "Unavailable", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" }], recent: [] } },
    documents: { state: "ready", data: { documents: [{ id: "document-live", name: "document-live", state: "Resolved", phaseLabel: "Not supplied", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] }], captureQueue: [], processingJobs: [], outboundRecords: [] } },
    review: { state: "ready", data: { queue: [{ id: "question-live", label: "Question", detail: "", status: "Read only", action: "", type: "", evidence: "", state: "needs_input", outcome: null, disposition: null }], count: 1, meta: { total: 1, tail: null, pending: null, invite: "", answeredByDocument: "" } } },
  };
}

describe("surface session", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("owns shell navigation and stable selection behavior", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "review", "trust"]);
    expect(destinations.map((item) => item.label)).toEqual(["Overview", "Accounts", "Activity", "Documents", "Review", "Trust"]);
    expect(retainSelection("b", ["c", "b", "a"])).toBe("b");
    expect(retainSelection("b", ["c", "a"])).toBe("c");
    expect(retainSelection("b", [])).toBe("");
  });
  it("starts settled with matching sample source and snapshot", () => {
    const state = initialSession();
    expect(state.phase).toBe("settled");
    expect(state.source.mode).toBe(state.snapshot.mode);
    expect(state.requestId).toBe(0);
  });

  it("allocates opening state without replacing the prior snapshot", () => {
    const before = initialSession();
    const opening = sessionReducer(before, { type: "opening", requestId: 1 });
    expect(opening.phase).toBe("opening");
    expect(opening.snapshot).toBe(before.snapshot);
    expect(opening.source).toBe(before.source);
  });

  it("switches atomically to a source-free live reading state", () => {
    const opening = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const reading = sessionReducer(opening, { type: "reading", requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() });
    expect(reading.phase).toBe("reading");
    expect(reading.source.mode).toBe(reading.snapshot.mode);
    expect(JSON.stringify(reading.snapshot)).not.toContain("Everyday checking");
  });

  it("commits a current loaded request exactly into settled selections", () => {
    const opening = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const reading = sessionReducer(opening, { type: "reading", requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() });
    const settled = sessionReducer(reading, { type: "loaded", requestId: 1, snapshot: readyLive() });
    expect(settled.phase).toBe("settled");
    expect(settled.selectedAccount).toBe("account-live");
    expect(settled.selectedDocument).toBe("document-live");
    expect(settled.selectedQueue).toBe("question-live");
  });

  it("retains a valid stable selection and falls back after removal", () => {
    const snapshot = readyLive();
    if (snapshot.overview.state !== "ready") throw new Error("fixture");
    snapshot.overview.data.accounts.unshift({ ...snapshot.overview.data.accounts[0], id: "account-other" });
    const current = { ...initialSession(), requestId: 2, source: liveSource, snapshot: liveReadingSnapshot(), selectedAccount: "account-live" };
    expect(sessionReducer(current, { type: "loaded", requestId: 2, snapshot }).selectedAccount).toBe("account-live");
    snapshot.overview.data.accounts = snapshot.overview.data.accounts.filter((account) => account.id !== "account-live");
    expect(sessionReducer(current, { type: "loaded", requestId: 2, snapshot }).selectedAccount).toBe("account-other");
  });

  it("ignores stale reading, loaded, and failure actions", () => {
    const current = sessionReducer(initialSession(), { type: "opening", requestId: 4 });
    expect(sessionReducer(current, { type: "reading", requestId: 3, source: liveSource, snapshot: liveReadingSnapshot() })).toBe(current);
    expect(sessionReducer(current, { type: "loaded", requestId: 3, snapshot: readyLive() })).toBe(current);
    expect(sessionReducer(current, { type: "open-failed", requestId: 3 })).toBe(current);
    expect(sessionReducer(current, { type: "load-failed", requestId: 3 })).toBe(current);
  });

  it("a newer open request prevents an older loaded request", () => {
    const first = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const second = sessionReducer(first, { type: "opening", requestId: 2 });
    expect(sessionReducer(second, { type: "loaded", requestId: 1, snapshot: readyLive() })).toBe(second);
  });

  it("reset wins atomically over pending work", () => {
    const pending = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const reset = sessionReducer(pending, { type: "reset", requestId: 2 });
    expect(reset.snapshot).toBe(sampleSnapshot);
    expect(reset.source.mode).toBe("demo");
    expect(reset.source.mode).toBe(reset.snapshot.mode);
    expect(sessionReducer(reset, { type: "loaded", requestId: 1, snapshot: readyLive() })).toBe(reset);
  });

  it("current open failure retains the prior snapshot and settles", () => {
    const before = initialSession();
    const opening = sessionReducer(before, { type: "opening", requestId: 1 });
    const failed = sessionReducer(opening, { type: "open-failed", requestId: 1 });
    expect(failed.phase).toBe("settled");
    expect(failed.snapshot).toBe(before.snapshot);
    expect(failed.notice).toContain("could not be opened");
  });

  it("reports the exact partial read notice after one failed result", () => {
    const snapshot = { ...readyLive(), documents: { state: "failed", reason: "read_failed" } as const };
    const current = { ...initialSession(), requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() };
    const settled = sessionReducer(current, { type: "loaded", requestId: 1, snapshot });
    expect(settled.notice).toBe("The private vault opened, but some surfaces could not be read. Your vault was not changed.");
  });

  it("reset during a pending open wins before the host resolves", async () => {
    const open = deferred<BridgeResponse<unknown>>();
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => frame.operation === "bridge.open_vault" ? open.promise as Promise<BridgeResponse<T>> : ok(frame.requestId, { surface: frame.payload.surface, job_id: "job", data: emptyPayload(frame.payload.surface as SurfaceName) } as T) };
    const { result } = renderHook(() => useSurfaceSession());
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.openVault("/first", "secret"); });
    await waitFor(() => expect(result.current.session.phase).toBe("opening"));
    act(() => result.current.resetDemo());
    expect(result.current.session.source.mode).toBe("demo");
    open.resolve(ok("open-1", { state: "opened" }));
    await act(async () => { await pending; });
    expect(result.current.session.source.mode).toBe("demo");
    expect(result.current.session.snapshot).toBe(sampleSnapshot);
    expect(result.current.session.notice).toBe("Sample vault reset to the fictional data stored with the app.");
  });

  it("two opens resolving out of order keep the newest private request", async () => {
    const first = deferred<BridgeResponse<unknown>>();
    const second = deferred<BridgeResponse<unknown>>();
    let opens = 0;
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return (++opens === 1 ? first.promise : second.promise) as Promise<BridgeResponse<T>>;
      const data = frame.payload.surface === "overview" ? { accounts: [{ account: "newest-account", name: "Newest account" }] } : frame.payload.surface === "documents" ? { documents: [] } : { questions: [], total: 0 };
      return ok(frame.requestId, { surface: frame.payload.surface, job_id: "job", data } as T);
    } };
    window.orionVivaBridge = transport;
    const { result } = renderHook(() => useSurfaceSession());
    let firstPending!: Promise<boolean>; let secondPending!: Promise<boolean>;
    act(() => { firstPending = result.current.openVault("/first", "secret"); secondPending = result.current.openVault("/second", "secret"); });
    second.resolve(ok("open-2", { state: "opened" }));
    await act(async () => { await secondPending; });
    expect(result.current.session.requestId).toBe(2);
    expect(result.current.session.snapshot.overview.state).toBe("ready");
    if (result.current.session.snapshot.overview.state === "ready") expect(result.current.session.snapshot.overview.data.accounts[0].id).toBe("newest-account");
    first.resolve(ok("open-1", { state: "opened" }));
    await act(async () => { await firstPending; });
    expect(result.current.session.requestId).toBe(2);
    if (result.current.session.snapshot.overview.state === "ready") expect(result.current.session.snapshot.overview.data.accounts[0].id).toBe("newest-account");
  });

  it("a newer private request beats reads from an older request", async () => {
    const oldReads = [deferred<BridgeResponse<unknown>>(), deferred<BridgeResponse<unknown>>(), deferred<BridgeResponse<unknown>>()];
    let openCount = 0; let oldReadIndex = 0;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") { openCount += 1; return ok(frame.requestId, { state: "opened" } as T); }
      if (openCount === 1) return oldReads[oldReadIndex++].promise as Promise<BridgeResponse<T>>;
      const data = frame.payload.surface === "overview" ? { accounts: [{ account: "new-private", name: "New private" }] } : frame.payload.surface === "documents" ? { documents: [] } : { questions: [], total: 0 };
      return ok(frame.requestId, { surface: frame.payload.surface, job_id: "new", data } as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    let older!: Promise<boolean>; let newer!: Promise<boolean>;
    act(() => { older = result.current.openVault("/old", "secret"); });
    await waitFor(() => expect(result.current.session.phase).toBe("reading"));
    act(() => { newer = result.current.openVault("/new", "secret"); });
    await act(async () => { await newer; });
    if (result.current.session.snapshot.overview.state === "ready") expect(result.current.session.snapshot.overview.data.accounts[0].id).toBe("new-private");
    oldReads[0].resolve(ok("old-0", { surface: "overview", job_id: "old", data: { accounts: [] } }));
    oldReads[1].reject(new Error("stale read failure"));
    oldReads[2].resolve(ok("old-2", { surface: "review", job_id: "old", data: { questions: [], total: 0 } }));
    await act(async () => { await older; });
    expect(result.current.session.requestId).toBe(2);
    expect(result.current.session.notice).toBeNull();
    if (result.current.session.snapshot.overview.state === "ready") expect(result.current.session.snapshot.overview.data.accounts[0].id).toBe("new-private");
  });

  it("a stale open failure emits no notice after a newer request settles", async () => {
    const first = deferred<BridgeResponse<unknown>>();
    let opens = 0;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") { opens += 1; return opens === 1 ? first.promise as Promise<BridgeResponse<T>> : ok(frame.requestId, { state: "opened" } as T); }
      return ok(frame.requestId, { surface: frame.payload.surface, job_id: "job", data: emptyPayload(frame.payload.surface as SurfaceName) } as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    let older!: Promise<boolean>; let newer!: Promise<boolean>;
    act(() => { older = result.current.openVault("/old", "secret"); newer = result.current.openVault("/new", "secret"); });
    await act(async () => { await newer; });
    first.reject(new Error("stale private details"));
    await act(async () => { await older; });
    expect(result.current.session.requestId).toBe(2);
    expect(result.current.session.notice).toBeNull();
  });
});
