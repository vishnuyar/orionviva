import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { BridgeRequest, BridgeResponse, BridgeTransport, SurfaceName } from "../bridge/contracts";
import type { SurfaceSource } from "../surface/sources";
import type { SurfaceSnapshot } from "../surface/types";
import { initialSession, liveReadingSnapshot, sessionReducer, unopenedSnapshot } from "./session";
import { useSurfaceSession } from "./useSurfaceSession";
import { destinations } from "./navigation";
import { retainSelection } from "./selection";

const liveSource: SurfaceSource = { id: "bridge-client", label: "Private vault", description: "Private", sample: false, frame: null, load: async () => liveReadingSnapshot(), activityActions: { assignCategory: async () => ({ state: "unanswered" }), assignMeaning: async () => ({ state: "unanswered" }), replaceTags: async () => ({ state: "unanswered" }), confirmTransfer: async () => ({ state: "unanswered" }), rejectTransfer: async () => ({ state: "unanswered" }), unlinkTransfer: async () => ({ state: "unanswered" }) }, documentActions: null, jobStream: null, transferActions: null, settingsActions: null, conversationActions: null, trustActions: null, describe: async () => ({ identity: { state: "unavailable", reason: "not asked" }, registry: { state: "unavailable", reason: "not asked" }, lifecycle: { state: "unavailable", reason: "not asked" } }) };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((onResolve, onReject) => { resolve = onResolve; reject = onReject; }); return { promise, resolve, reject }; }
function ok<T>(requestId: string, result: T): BridgeResponse<T> { return { protocol: "1.0", request_id: requestId, ok: true, result }; }
function emptyPayload(surface: SurfaceName) { return surface === "overview" ? { accounts: [] } : surface === "documents" ? { documents: [] } : surface === "conversation" ? { turns: [], questions: [], total: 0 } : surface === "jobs" ? { state: "absent", jobs: [], running: [] } : surface === "plans" ? { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] } : { questions: [], total: 0 }; }
function activityPayload(categoryId = "groceries", categoryLabel = "Groceries") {
  return {
    state: "ready", sentence: "Everything below came off a document you added.", beyond: { count: 0 },
    vocabularies: {
      categories: { items: [{ id: "groceries", label: "Groceries" }, { id: "housing", label: "Housing" }], complete: true, limit: 40 },
      tags: { items: [{ id: "trip", label: "Trip" }, { id: "tax", label: "Tax" }], complete: true, limit: 40, max_selected: 40, max_label_length: 80 },
    },
    items: [{ id: "movement:key", date: "2026-08-01", description: "shop", account: "acct:one", direction: "out", exact_value: "12.00", currency: "USD", display: "USD 12.00", nature: "spending", treatment: { kind: "spending", name: "" }, sentence: "", decided_by: "default", provisional: false, linked: false, category: { id: categoryId, label: categoryLabel }, tags: [{ id: "trip", label: "Trip" }], transfer: { state: "none" }, actions: ["assign_category", "assign_meaning", "replace_tags"] }],
  };
}
function transferActivityPayload(suggestedState: boolean) {
  const read = activityPayload();
  const transfer = suggestedState ? {
    state: "suggested", explanation: "A reviewed suggestion is available.", complete: true, limit: 20,
    candidates: [{ id: "movement:counterpart", date: "2026-08-02", description: "other side", account: "acct:two", direction: "in", exact_value: "12.00", currency: "USD", display: "USD 12.00", relationship: "Reviewed relationship." }],
  } : { state: "none" };
  return { ...read, items: [{ ...read.items[0], transfer, actions: suggestedState ? ["confirm_transfer", "reject_transfer"] : [] }] };
}
function completeSurfacePayload(surface: SurfaceName, refreshed = false): unknown {
  if (surface === "overview") return { accounts: [] };
  if (surface === "documents") return { documents: [] };
  if (surface === "conversation") return { turns: [], questions: [], total: 0 };
  if (surface === "jobs") return { state: "absent", jobs: [], running: [] };
  if (surface === "plans") return { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] };
  if (surface === "trust") return { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } };
  return refreshed ? activityPayload("housing", "Housing") : activityPayload();
}
function readyLive(): SurfaceSnapshot {
  return {
    ...liveReadingSnapshot(),
    overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [{ id: "account-live", name: "Live", kind: "", measure: null, exactValue: "", currency: "", display: "", grade: "unavailable", gradeLabel: "Evidence status unavailable", gradeDescription: "Unavailable", proofPresentation: { emphasis: "required", reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" }] } },
    documents: { state: "ready", data: { documents: [{ id: "document-live", name: "document-live", state: "Resolved", phaseLabel: "Not supplied", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } },
    conversation: { state: "ready", data: { turns: [], questions: { queue: [{ id: "question-live", label: "Question", detail: "", status: "Read only", action: "", type: "", evidence: "", state: "needs_input", outcome: null, disposition: null }], count: 1, meta: { total: 1, tail: null, pending: null, invite: "", answeredByDocument: "" } } } },
  };
}

describe("surface session", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("owns shell navigation and stable selection behavior", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "plans", "trust"]);
    expect(destinations.map((item) => item.label)).toEqual(["Overview", "Accounts", "Activity", "Documents", "Plans", "Trust"]);
    expect(retainSelection("b", ["c", "b", "a"])).toBe("b");
    expect(retainSelection("b", ["c", "a"])).toBe("c");
    expect(retainSelection("b", [])).toBe("");
  });
  it("starts with no vault open and no verbs, rather than inside somebody's invented money", () => {
    // Both sample and private vaults require an explicit open action.
    const state = initialSession();
    expect(state.phase).toBe("settled");
    expect(state.source).toBeNull();
    expect(state.snapshot.overview.state).toBe("absent");
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
    expect(reading.source).toBe(liveSource);
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

  it("replaces the Trust read with the one taken after an Ask Viva call", () => {
    const before = { ...initialSession(), requestId: 7, source: liveSource, snapshot: readyLive() };
    const trust = { state: "ready" as const, data: { notes: [], outbound: { sentence: "One call left.", callCount: 1, phases: [], models: [], reportedModels: [{ name: "provider-model", count: 1 }], modelSentence: "", span: null, cost: null, absences: [] } } };

    const after = sessionReducer(before, {
      type: "asked", requestId: 7, question: "What changed?", trust, conversation: before.snapshot.conversation,
      result: { state: "settled", outcome: { kind: "completed", message: "Answered.", reason: "" } },
      turn: null,
    });

    expect(after.snapshot.trust).toBe(trust);
    expect(after.snapshot.overview).toBe(before.snapshot.overview);
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
    expect(sessionReducer(current, { type: "open-failed", requestId: 3, said: "" })).toBe(current);
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
    expect(reset.source).toBeNull();
    expect(reset.snapshot).toEqual(unopenedSnapshot());
    expect(sessionReducer(reset, { type: "loaded", requestId: 1, snapshot: readyLive() })).toBe(reset);
  });

  it("current open failure retains the prior snapshot and settles", () => {
    const before = initialSession();
    const opening = sessionReducer(before, { type: "opening", requestId: 1 });
    const failed = sessionReducer(opening, { type: "open-failed", requestId: 1, said: "" });
    expect(failed.phase).toBe("settled");
    expect(failed.snapshot).toBe(before.snapshot);
    expect(failed.notice).toEqual({ kind: "refused", text: "The local vault could not be opened. Nothing came back saying why — a wrong folder or a wrong passphrase would have said so." });
  });

  it("reports the exact partial read notice after one failed result", () => {
    const snapshot = { ...readyLive(), documents: { state: "failed", reason: "read_failed" } as const };
    const current = { ...initialSession(), requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() };
    const settled = sessionReducer(current, { type: "loaded", requestId: 1, snapshot });
    expect(settled.notice).toEqual({ kind: "refused", text: "The private vault opened, but some surfaces could not be read. Your vault was not changed." });
  });

  it("reset during a pending open wins before the host resolves", async () => {
    const open = deferred<BridgeResponse<unknown>>();
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => frame.operation === "bridge.open_vault" ? open.promise as Promise<BridgeResponse<T>> : ok(frame.requestId, { surface: frame.payload.surface, job_id: "job", data: emptyPayload(frame.payload.surface as SurfaceName) } as T) };
    const { result } = renderHook(() => useSurfaceSession());
    let pending!: Promise<boolean>;
    act(() => { pending = result.current.openVault("/first", "secret", false); });
    await waitFor(() => expect(result.current.session.phase).toBe("opening"));
    act(() => result.current.resetDemo());
    expect(result.current.session.source).toBeNull();
    open.resolve(ok("open-1", { state: "opened" }));
    await act(async () => { await pending; });
    expect(result.current.session.source).toBeNull();
    expect(result.current.session.snapshot).toEqual(unopenedSnapshot());
    expect(result.current.session.notice).toEqual({ kind: "acknowledged", text: "Closed. Nothing from that vault is on this screen." });
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
    act(() => { firstPending = result.current.openVault("/first", "secret", false); secondPending = result.current.openVault("/second", "secret", false); });
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
    const oldReads = Array.from({ length: 5 }, () => deferred<BridgeResponse<unknown>>());
    let openCount = 0; let oldReadIndex = 0;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") { openCount += 1; return ok(frame.requestId, { state: "opened" } as T); }
      if (openCount === 1) return oldReads[oldReadIndex++].promise as Promise<BridgeResponse<T>>;
      const data = frame.payload.surface === "overview" ? { accounts: [{ account: "new-private", name: "New private" }] } : frame.payload.surface === "documents" ? { documents: [] } : frame.payload.surface === "conversation" ? { turns: [], questions: [], total: 0 } : emptyPayload(frame.payload.surface as SurfaceName);
      return ok(frame.requestId, { surface: frame.payload.surface, job_id: "new", data } as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    let older!: Promise<boolean>; let newer!: Promise<boolean>;
    act(() => { older = result.current.openVault("/old", "secret", false); });
    await waitFor(() => expect(result.current.session.phase).toBe("reading"));
    act(() => { newer = result.current.openVault("/new", "secret", false); });
    await act(async () => { await newer; });
    if (result.current.session.snapshot.overview.state === "ready") expect(result.current.session.snapshot.overview.data.accounts[0].id).toBe("new-private");
    oldReads[0].resolve(ok("old-0", { surface: "overview", job_id: "old", data: { accounts: [] } }));
    oldReads[1].reject(new Error("stale read failure"));
    oldReads[2].resolve(ok("old-2", { surface: "conversation", job_id: "old", data: { turns: [], questions: [], total: 0 } }));
    oldReads[3].resolve(ok("old-3", { surface: "trust", job_id: "old", data: emptyPayload("trust") }));
    oldReads[4].resolve(ok("old-4", { surface: "activity", job_id: "old", data: emptyPayload("activity") }));
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
    act(() => { older = result.current.openVault("/old", "secret", false); newer = result.current.openVault("/new", "secret", false); });
    await act(async () => { await newer; });
    first.reject(new Error("stale private details"));
    await act(async () => { await older; });
    expect(result.current.session.requestId).toBe(2);
    expect(result.current.session.notice).toBeNull();
  });

  it("setting a question aside sends the reason, re-reads review, and reports what happened", async () => {
    const frames: BridgeRequest[] = [];
    let declined = false;
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.conversation.decline") {
        declined = true;
        return ok(frame.requestId, { kind: "completed", message: "Set aside until something changes.", state: null, reason: null } as T);
      }
      const surface = frame.payload.surface as SurfaceName;
      const review = declined
        ? { questions: [], total: 0, pending: { count: 1 } }
        : { questions: [{ id: "question-live" }], total: 1, pending: { count: 0 } };
      const data = surface === "conversation" ? { turns: [], ...review } : emptyPayload(surface);
      return ok(frame.requestId, { surface, job_id: "job", data } as T);
    } };
    window.orionVivaBridge = transport;

    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    expect(result.current.session.selectedQueue).toBe("question-live");

    await act(async () => { await result.current.declineQuestion("question-live", "not_now"); });

    const sent = frames.filter((frame) => frame.operation === "viva.conversation.decline");
    expect(sent.map((frame) => frame.payload)).toEqual([{ question_id: "question-live", reason: "not_now" }]);
    expect(result.current.session.questionAction).toEqual({
      state: "settled",
      questionId: "question-live",
      verb: "decline",
      result: { state: "settled", outcome: { kind: "completed", message: "Set aside until something changes.", reason: "" } },
    });
    // The question is set aside, not destroyed: the read that followed says so.
    if (result.current.session.snapshot.conversation.state === "ready") expect(result.current.session.snapshot.conversation.data.questions.meta.pending).toEqual({ count: 1 });
    expect(result.current.session.selectedQueue).toBe("");
    // Only review was asked for again. Nothing else claims to have been re-read.
    expect(frames.filter((frame) => frame.payload.surface === "overview")).toHaveLength(1);

    act(() => result.current.selectQueue("another-question"));
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
  });

  it("does not carry what was done on one screen to another", async () => {
    const { result } = renderHook(() => useSurfaceSession());

    // Leaving the screen ends the account of what was done on it. A notice
    // still standing on return reports an act on something the person is no
    // longer looking at, minutes after it happened.
    act(() => result.current.navigate("overview"));
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
    act(() => result.current.navigate("documents"));
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
  });

  it("a verb pressed with no vault open does nothing rather than answering for one", async () => {
    // Every verb comes from an opened source; without one, no vault is read.
    const { result } = renderHook(() => useSurfaceSession());
    const before = JSON.stringify(result.current.session.snapshot.conversation);

    await act(async () => { await result.current.declineQuestion("sample-question", "not_now"); });

    expect(result.current.session.source).toBeNull();
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
    expect(JSON.stringify(result.current.session.snapshot.conversation)).toBe(before);
  });

  it("a refusal reaches the session with its reason, and a bridge failure is bounded", async () => {
    let call = 0;
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.conversation.decline") {
        if (++call === 1) return ok(frame.requestId, { kind: "refused", message: "That question is no longer open.", state: null, reason: "not_open" } as T);
        throw new Error("the sidecar went away");
      }
      const surface = frame.payload.surface as SurfaceName;
      return ok(frame.requestId, { surface, job_id: "job", data: surface === "conversation" ? { turns: [], questions: [{ id: "question-live" }], total: 1 } : emptyPayload(surface) } as T);
    } };
    window.orionVivaBridge = transport;

    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    await act(async () => { await result.current.declineQuestion("question-live", "not_now"); });
    expect(result.current.session.questionAction).toMatchObject({ result: { state: "settled", outcome: { kind: "refused", reason: "not_open" } } });

    act(() => result.current.selectQueue("question-live"));
    await act(async () => { await result.current.declineQuestion("question-live", "not_now"); });
    expect(result.current.session.questionAction).toMatchObject({ result: { state: "unanswered" } });
  });

  it("does not carry a sidecar error's own words into the session", async () => {
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.conversation.decline") return { protocol: "1.0", request_id: frame.requestId, ok: false, error: { code: "invalid_request", message: "question_id must be a non-empty string" } };
      const surface = frame.payload.surface as SurfaceName;
      return ok(frame.requestId, { surface, job_id: "job", data: surface === "conversation" ? { turns: [], questions: [{ id: "question-live" }], total: 1 } : emptyPayload(surface) } as T);
    } };
    window.orionVivaBridge = transport;

    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    await act(async () => { await result.current.declineQuestion("question-live", "not_now"); });

    // The sidecar read the request and would not take it, which is a state of
    // its own; what it wrote about it names a payload field and is for a log.
    expect(result.current.session.questionAction).toMatchObject({ result: { state: "unserved" } });
    expect(JSON.stringify(result.current.session.questionAction)).not.toContain("question_id");
  });

  it("retains the old snapshot through Activity working and outcome phases, replacing it only from a full reread", () => {
    const before = readyLive();
    const refreshed = { ...readyLive(), disclosure: { title: "Refreshed", subtitle: "All surfaces", detail: "A complete new snapshot." } };
    const base = { ...initialSession(), requestId: 7, source: liveSource, snapshot: before };
    const working = sessionReducer(base, { type: "activity-correcting", requestId: 7, movementId: "movement:key", verb: "category" });
    expect(working.snapshot).toBe(before);
    const outcome = sessionReducer(working, { type: "activity-outcome", requestId: 7, movementId: "movement:key", verb: "category", result: { state: "settled", outcome: { kind: "completed", message: "Recorded.", reason: "" } } });
    expect(outcome.snapshot).toBe(before);
    const settled = sessionReducer(outcome, { type: "activity-refreshed", requestId: 7, movementId: "movement:key", verb: "category", result: outcome.activityAction.state === "refreshing" ? outcome.activityAction.result : { state: "unanswered" }, snapshot: refreshed });
    expect(settled.snapshot).toBe(refreshed);
    const failed = sessionReducer(outcome, { type: "activity-refresh-failed", requestId: 7, movementId: "movement:key", verb: "category", result: outcome.activityAction.state === "refreshing" ? outcome.activityAction.result : { state: "unanswered" } });
    expect(failed.snapshot).toBe(before);
    expect(failed.activityAction).toMatchObject({ state: "settled", refresh: "failed" });
  });

  it("orders an Activity action before one full reread, suppresses cross-verb duplicates, and never patches optimistically", async () => {
    const frames: BridgeRequest[] = [];
    const actionReply = deferred<BridgeResponse<unknown>>();
    const refreshGate = deferred<void>();
    let refreshing = false;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_category") return actionReply.promise as Promise<BridgeResponse<T>>;
      if (frame.operation === "viva.activity.replace_tags") return ok(frame.requestId, { kind: "completed", message: "Tags recorded.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") {
        if (refreshing) await refreshGate.promise;
        const surface = frame.payload.surface as SurfaceName;
        return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface, refreshing) } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    expect(result.current.session.snapshot.activity.state).toBe("ready");
    frames.length = 0;

    let pending!: Promise<void>;
    act(() => {
      pending = result.current.assignActivityCategory("movement:key", "housing");
      void result.current.assignActivityCategory("movement:key", "groceries");
      void result.current.replaceActivityTags("movement:key", ["tax"]);
    });
    expect(result.current.session.activityAction).toMatchObject({ state: "working", movementId: "movement:key", verb: "category" });
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].category.id).toBe("groceries");
    expect(frames.filter((frame) => frame.operation.startsWith("viva.activity."))).toHaveLength(1);

    refreshing = true;
    await act(async () => { actionReply.resolve(ok("activity-action", { kind: "completed", message: "Category recorded.", state: null, reason: null })); await Promise.resolve(); });
    await waitFor(() => expect(result.current.session.activityAction.state).toBe("refreshing"));
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].category.id).toBe("groceries");
    act(() => { void result.current.replaceActivityTags("movement:key", []); });
    expect(frames.filter((frame) => frame.operation.startsWith("viva.activity."))).toHaveLength(1);
    expect(frames.filter((frame) => frame.operation === "viva.surface.read")).toHaveLength(6);

    await act(async () => { refreshGate.resolve(); await pending; });
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "refreshed", result: { state: "settled", outcome: { kind: "completed" } } });
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].category.id).toBe("housing");
    const relevant = frames.filter((frame) => frame.operation.startsWith("viva.activity.") || frame.operation === "viva.surface.read");
    expect(relevant.map((frame) => frame.operation)).toEqual(["viva.activity.assign_category", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
    expect(relevant[0].payload).toEqual({ movement_key: "movement:key", category_id: "housing" });
    expect(relevant.slice(1).map((frame) => frame.payload.surface)).toEqual(["overview", "documents", "conversation", "trust", "activity", "plans"]);
  });

  it.each(["refused", "stale"] as const)("fully rereads after a typed %s Activity outcome", async (kind) => {
    const frames: BridgeRequest[] = [];
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.replace_tags") return ok(frame.requestId, { kind, message: `${kind} answer.`, state: null, reason: kind } as T);
      if (frame.operation === "viva.surface.read") { const surface = frame.payload.surface as SurfaceName; return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface) } as T); }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    frames.length = 0;
    await act(async () => { await result.current.replaceActivityTags("movement:key", []); });
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "refreshed", result: { state: "settled", outcome: { kind } } });
    expect(frames.map((frame) => frame.operation)).toEqual(["viva.activity.replace_tags", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
  });

  it.each([
    ["confirm", "viva.activity.confirm_transfer", { movement_key: "movement:key", counterpart_key: "movement:counterpart" }],
    ["reject", "viva.activity.reject_transfer", { movement_key: "movement:key" }],
    ["unlink", "viva.activity.unlink_transfer", { movement_key: "movement:key", counterpart_key: "movement:counterpart" }],
  ] as const)("frames %s transfer correction before the mandatory full-surface reread", async (verb, operation, expectedPayload) => {
    const frames: BridgeRequest[] = [];
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation.startsWith("viva.activity.")) return ok(frame.requestId, { kind: "completed", message: "Transfer state recorded.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") { const surface = frame.payload.surface as SurfaceName; return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface) } as T); }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    frames.length = 0;
    await act(async () => {
      if (verb === "confirm") await result.current.confirmActivityTransfer("movement:key", "movement:counterpart");
      else if (verb === "reject") await result.current.rejectActivityTransfer("movement:key");
      else await result.current.unlinkActivityTransfer("movement:key", "movement:counterpart");
    });
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "refreshed", result: { state: "settled", outcome: { kind: "completed" } } });
    expect(frames.map((frame) => frame.operation)).toEqual([operation, "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
    expect(frames[0].payload).toEqual(expectedPayload);
    expect(frames.slice(1).map((frame) => frame.payload.surface)).toEqual(["overview", "documents", "conversation", "trust", "activity", "plans"]);
  });

  it("retains the suggested transfer through confirm and refresh, then replaces it only from the full reread", async () => {
    const actionReply = deferred<BridgeResponse<unknown>>();
    const refreshGate = deferred<void>();
    let afterWrite = false;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.confirm_transfer") return actionReply.promise as Promise<BridgeResponse<T>>;
      if (frame.operation === "viva.surface.read") {
        if (afterWrite) await refreshGate.promise;
        const surface = frame.payload.surface as SurfaceName;
        const data = surface === "activity" ? transferActivityPayload(!afterWrite) : completeSurfacePayload(surface);
        return ok(frame.requestId, { surface, job_id: "job", data } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    const oldSnapshot = result.current.session.snapshot;
    let pending!: Promise<void>;
    act(() => { pending = result.current.confirmActivityTransfer("movement:key", "movement:counterpart"); });
    expect(result.current.session.snapshot).toBe(oldSnapshot);
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].transfer?.state).toBe("suggested");
    afterWrite = true;
    await act(async () => { actionReply.resolve(ok("confirm", { kind: "completed", message: "Transfer confirmed.", state: null, reason: null })); await Promise.resolve(); });
    await waitFor(() => expect(result.current.session.activityAction.state).toBe("refreshing"));
    expect(result.current.session.snapshot).toBe(oldSnapshot);
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].transfer?.state).toBe("suggested");
    await act(async () => { refreshGate.resolve(); await pending; });
    expect(result.current.session.snapshot).not.toBe(oldSnapshot);
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].transfer?.state).toBe("none");
  });

  it("still fully rereads after an impossible Activity receipt is bounded as unreadable", async () => {
    const frames: BridgeRequest[] = [];
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_category") return ok(frame.requestId, { kind: "proposal", message: "Confirm this.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") { const surface = frame.payload.surface as SurfaceName; return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface) } as T); }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    frames.length = 0;
    await act(async () => { await result.current.assignActivityCategory("movement:key", "housing"); });
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "refreshed", result: { state: "unreadable" } });
    expect(frames.map((frame) => frame.operation)).toEqual(["viva.activity.assign_category", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read", "viva.surface.read"]);
  });

  it("retains the old full picture and outcome when any post-write surface read is invalid", async () => {
    let activityReads = 0;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_category") return ok(frame.requestId, { kind: "completed", message: "Category recorded.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") {
        const surface = frame.payload.surface as SurfaceName;
        if (surface === "activity") activityReads += 1;
        const data = surface === "activity" && activityReads > 1 ? null : completeSurfacePayload(surface, true);
        return ok(frame.requestId, { surface, job_id: "job", data } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    const oldPicture = result.current.session.snapshot;
    await act(async () => { await result.current.assignActivityCategory("movement:key", "housing"); });
    expect(result.current.session.snapshot).toBe(oldPicture);
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "failed", result: { state: "settled", outcome: { kind: "completed" } } });
  });
});
