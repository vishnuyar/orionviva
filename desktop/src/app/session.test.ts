import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { BridgeRequest, BridgeResponse, BridgeTransport, SurfaceName } from "../bridge/contracts";
import type { SurfaceSource } from "../surface/sources";
import type { SurfaceSnapshot } from "../surface/types";
import { initialSession, liveReadingSnapshot, sessionReducer, unopenedSnapshot } from "./session";
import { authoritativeQuestionReread, useSurfaceSession } from "./useSurfaceSession";
import { destinations } from "./navigation";
import { retainSelection } from "./selection";

const liveSource: SurfaceSource = { id: "bridge-client", label: "Private vault", description: "Private", sample: false, frame: null, load: async () => liveReadingSnapshot(), activityActions: { read: async () => ({ state: "absent", reason: "not asked" }), assignCategory: async () => ({ state: "unanswered" }), assignClassification: async () => ({ state: "unanswered" }), assignMeaning: async () => ({ state: "unanswered" }), replaceTags: async () => ({ state: "unanswered" }), addTags: async () => ({ state: "unanswered" }), removeTags: async () => ({ state: "unanswered" }), confirmTransfer: async () => ({ state: "unanswered" }), rejectTransfer: async () => ({ state: "unanswered" }), unlinkTransfer: async () => ({ state: "unanswered" }) }, documentActions: null, jobStream: null, transferActions: null, settingsActions: null, conversationActions: null, trustActions: null, describe: async () => ({ identity: { state: "unavailable", reason: "not asked" }, registry: { state: "unavailable", reason: "not asked" }, lifecycle: { state: "unavailable", reason: "not asked" } }) };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((onResolve, onReject) => { resolve = onResolve; reject = onReject; }); return { promise, resolve, reject }; }
function ok<T>(requestId: string, result: T): BridgeResponse<T> { return { protocol: "1.0", request_id: requestId, ok: true, result }; }
function emptyPayload(surface: SurfaceName) { return surface === "overview" ? { accounts: [] } : surface === "documents" ? { documents: [] } : surface === "conversation" ? { turns: [], questions: [], total: 0 } : surface === "review" ? { contract: "ReviewSummary.v1", state: "ready", title: "Review", summary: "Nothing needs your answer.", actionable_count: 0, shown_count: 0, remaining_count: 0, types: [], groups: [] } : surface === "jobs" ? { state: "absent", jobs: [], running: [] } : surface === "plans" ? { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] } : surface === "trust" ? { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } } : surface === "activity" ? activityPayload() : { questions: [], total: 0 }; }
function rawReviewBinding(questionId: string, label: string, reason: string) {
  const target = { kind: "conversation", question_id: questionId, disclosure: "No exact transaction was supplied." };
  return { item_id: `question:${questionId}`, question_id: questionId, question_kind: "identity", label, reason, refs: { movement: "", movements: [], candidates: [], document: "", doc_id: "", account: "" }, target, status: "open", primary_action: "open_question", allowed_actions: ["open_question"] };
}
function reviewPayload(questionId = "question-live") {
  const label = "Question", reason = "The vault asked it.";
  const binding = rawReviewBinding(questionId, label, reason);
  const item = { id: `question:${questionId}`, type: "question", type_label: "Question", marker: "?", marker_label: "Viva needs an answer", label, reason, status: "open", context: { date: "", amount: "", account: "", merchant: "" }, target: binding.target, primary_action: "open_question", action_label: "Answer question", allowed_actions: ["open_question"], binding };
  return { contract: "ReviewSummary.v1", state: "ready", title: "Review", summary: "1 item needs an answer.", actionable_count: 1, shown_count: 1, remaining_count: 0, types: [{ id: "questions", label: "Questions", count: 1 }], groups: [{ id: "questions", label: "Questions", count: 1, items: [item] }] };
}
function conversationQuestion(questionId = "question-live", label = "Question", reason = "The vault asked it.") {
  return { id: questionId, kind: "identity", text: label, why: reason, refs: {}, review_binding: rawReviewBinding(questionId, label, reason) };
}
function adaptedReviewBinding(questionId = "question-live", label = "Question", reason = "The vault asked it.") {
  return { itemId: `question:${questionId}`, questionId, questionKind: "identity", label, reason, refs: { movement: "", movements: [], candidates: [], document: "", documentId: "", account: "" }, target: { kind: "conversation" as const, questionId, disclosure: "No exact transaction was supplied." }, status: "open" as const, primaryAction: "open_question" as const, allowedActions: ["open_question" as const] };
}
function reviewPayloadForIds(questionIds: readonly string[], total = questionIds.length) {
  const seed = reviewPayload(questionIds[0] ?? "seed");
  const seedItem = seed.groups[0].items[0];
  const items = questionIds.map((questionId) => {
    const label = `Question ${questionId}`;
    const binding = rawReviewBinding(questionId, label, seedItem.reason);
    return { ...seedItem, id: `question:${questionId}`, label, target: binding.target, binding };
  });
  return {
    ...seed,
    summary: `${total} items need an answer.`,
    actionable_count: total,
    shown_count: items.length,
    remaining_count: total - items.length,
    types: items.length ? [{ id: "questions", label: "Questions", count: items.length }] : [],
    groups: items.length ? [{ id: "questions", label: "Questions", count: items.length, items }] : [],
  };
}
function activityPayload(categoryId = "groceries", categoryLabel = "Groceries") {
  return {
    state: "ready", sentence: "Everything below came off a document you added.", beyond: { count: 0 },
    vocabularies: {
      categories: { items: [{ id: "groceries", label: "Groceries" }, { id: "housing", label: "Housing" }], complete: true, limit: 40 },
      tags: { items: [{ id: "trip", label: "Trip" }, { id: "tax", label: "Tax" }], complete: true, limit: 40, max_selected: 40, max_label_length: 80 },
    },
    items: [{ id: "movement:key", date: "2026-08-01", description: "shop", account: "acct:one", account_id: "acct:one", account_name: "Everyday account", direction: "out", exact_value: "12.00", currency: "USD", display: "USD 12.00", nature: "spending", treatment: { kind: "spending", name: "" }, sentence: "", decided_by: "default", provisional: false, linked: false, category: { id: categoryId, label: categoryLabel }, subcategory: { id: null, label: "" }, classification: { grade: "verified", provenance: "human" }, tags: [{ id: "trip", label: "Trip" }], evidence_links: [], transfer: { state: "none" }, actions: ["assign_category", "assign_meaning", "replace_tags"] }],
  };
}
function transferActivityPayload(suggestedState: boolean) {
  const read = activityPayload();
  const transfer = suggestedState ? {
    state: "suggested", explanation: "A reviewed suggestion is available.", complete: true, limit: 20,
    candidates: [{ id: "movement:counterpart", date: "2026-08-02", description: "other side", account: "acct:two", account_id: "acct:two", account_name: "Savings", direction: "in", exact_value: "12.00", currency: "USD", display: "USD 12.00", relationship: "Reviewed relationship." }],
  } : { state: "none" };
  return { ...read, items: [{ ...read.items[0], transfer, actions: suggestedState ? ["confirm_transfer", "reject_transfer"] : [] }] };
}
function completeSurfacePayload(surface: SurfaceName, refreshed = false): unknown {
  if (surface === "overview") return { accounts: [] };
  if (surface === "documents") return { documents: [] };
  if (surface === "conversation") return { turns: [], questions: [], total: 0 };
  if (surface === "review") return emptyPayload("review");
  if (surface === "jobs") return { state: "absent", jobs: [], running: [] };
  if (surface === "plans") return { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] };
  if (surface === "trust") return { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } };
  return refreshed ? activityPayload("housing", "Housing") : activityPayload();
}
function readyLive(): SurfaceSnapshot {
  return {
    ...liveReadingSnapshot(),
    overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [{ id: "account-live", name: "Live", maskedNumber: "", kind: "", measure: null, exactValue: "", currency: "", display: "", grade: "unavailable", gradeLabel: "Evidence status unavailable", gradeDescription: "Unavailable", proofPresentation: { emphasis: "required", reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" }] } },
    documents: { state: "ready", data: { documents: [{ id: "document-live", name: "document-live", state: "Resolved", phaseLabel: "Not supplied", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } },
    conversation: { state: "ready", data: { turns: [], questions: { queue: [{ id: "question-live", label: "Question", detail: "The vault asked it.", status: "Read only", action: "", type: "identity", evidence: "The vault asked it.", state: "needs_input", outcome: null, disposition: null, reviewBinding: adaptedReviewBinding() }], count: 1, meta: { total: 1, tail: null, pending: null, invite: "", answeredByDocument: "" } } } },
    review: { state: "ready", data: { contract: "ReviewSummary.v1", title: "Review", summary: "1 item needs an answer.", actionableCount: 1, shownCount: 1, remainingCount: 0, types: [{ id: "questions", label: "Questions", count: 1 }], groups: [{ id: "questions", label: "Questions", count: 1, items: [{ id: "question:question-live", type: "question", typeLabel: "Question", marker: "?", markerLabel: "Viva needs an answer", label: "Question", reason: "The vault asked it.", status: "open", context: { date: "", amount: "", account: "", merchant: "" }, target: { kind: "conversation", questionId: "question-live", disclosure: "No exact transaction was supplied." }, primaryAction: "open_question", actionLabel: "Answer question", allowedActions: ["open_question"], binding: adaptedReviewBinding() }] }] } },
  };
}

function withReadyReview(snapshot = readyLive()): SurfaceSnapshot {
  return snapshot;
}

function pairedQuestionSnapshot(reviewIds: readonly string[], conversationIds: readonly string[], total = reviewIds.length): SurfaceSnapshot {
  const snapshot = readyLive();
  if (snapshot.review?.state !== "ready" || snapshot.conversation.state !== "ready") throw new Error("paired fixture");
  const reviewSeed = snapshot.review.data.groups[0].items[0];
  const questionSeed = snapshot.conversation.data.questions.queue[0];
  const items = reviewIds.map((id) => ({ ...reviewSeed, id: `question:${id}`, target: { kind: "conversation" as const, questionId: id, disclosure: "No exact transaction was supplied." }, binding: adaptedReviewBinding(id) }));
  const questions = conversationIds.map((id) => ({ ...questionSeed, id, reviewBinding: adaptedReviewBinding(id) }));
  return { ...snapshot,
    review: { state: "ready", data: { ...snapshot.review.data, actionableCount: total, shownCount: items.length, remainingCount: total - items.length, types: items.length ? [{ id: "questions", label: "Questions", count: items.length }] : [], groups: items.length ? [{ id: "questions", label: "Questions", count: items.length, items }] : [] } },
    conversation: { state: "ready", data: { ...snapshot.conversation.data, questions: { ...snapshot.conversation.data.questions, queue: questions, count: total, meta: { ...snapshot.conversation.data.questions.meta, total, tail: { count: total - questions.length, amount: "" } } } } },
  };
}

function pairedTransactionSnapshot(): SurfaceSnapshot {
  const snapshot = pairedQuestionSnapshot(["question-live"], ["question-live"]);
  if (snapshot.review?.state !== "ready" || snapshot.conversation.state !== "ready") throw new Error("transaction fixture");
  const target = { kind: "transaction" as const, questionId: "question-live", accountId: "acct-1", requestedMovementId: "member-2", canonicalMovementId: "member-1", memberMovementIds: ["member-1", "member-2"] };
  const binding = { ...adaptedReviewBinding(), questionKind: "nature", refs: { movement: "member-2", movements: ["member-1", "member-2"], candidates: [], document: "doc-1", documentId: "doc-1", account: "acct-1" }, target, primaryAction: "open_transaction" as const, allowedActions: ["open_transaction" as const] };
  const item = snapshot.review.data.groups[0].items[0];
  const question = snapshot.conversation.data.questions.queue[0];
  return {
    ...snapshot,
    review: { state: "ready", data: { ...snapshot.review.data, groups: [{ ...snapshot.review.data.groups[0], items: [{ ...item, target, primaryAction: "open_transaction", actionLabel: "Review transaction", allowedActions: ["open_transaction"], binding }] }] } },
    conversation: { state: "ready", data: { ...snapshot.conversation.data, questions: { ...snapshot.conversation.data.questions, queue: [{ ...question, type: "nature", refs: { movement: "member-2", movements: ["member-1", "member-2"], document: "doc-1", doc_id: "doc-1", account: "acct-1" }, reviewBinding: binding }] } } },
  };
}

describe("surface session", () => {
  afterEach(() => { delete window.orionVivaBridge; });

  it("owns shell navigation and stable selection behavior", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "review", "plans", "trust"]);
    expect(destinations.map((item) => item.label)).toEqual(["Overview", "Accounts", "Transactions", "Statements", "Review", "Plans", "Trust & settings"]);
    expect(destinations.map((item) => item.placement)).toEqual(["primary", "primary", "primary", "primary", "primary", "primary", "utility"]);
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

  it("keeps the last good vault picture until a replacement read commits", () => {
    const lastGood = readyLive();
    const current = { ...initialSession(), source: liveSource, snapshot: lastGood, destination: "trust" as const, selectedAccount: "account-live" };
    const opening = sessionReducer(current, { type: "opening", requestId: 1 });
    const reading = sessionReducer(opening, { type: "reading", requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() });

    expect(reading.phase).toBe("reading");
    expect(reading.source).toBe(liveSource);
    expect(reading.snapshot).toBe(lastGood);
    expect(reading.destination).toBe("trust");
    expect(reading.selectedAccount).toBe("account-live");
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

    const refreshed = sessionReducer(before, { type: "mutation-loaded", requestId: 7, snapshot: { ...before.snapshot, trust } });
    const after = sessionReducer(refreshed, {
      type: "asked", requestId: 7, question: "What changed?",
      result: { state: "settled", outcome: { kind: "completed", message: "Answered.", reason: "" } },
      turn: null,
      authoritative: true,
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

  it("retains the selected vault and requires an explicit reopen when every surface read fails", () => {
    const failure = { state: "failed", reason: "read_failed" } as const;
    const failedSnapshot: SurfaceSnapshot = {
      ...readyLive(),
      overview: failure,
      documents: failure,
      activity: failure,
      conversation: failure,
      review: failure,
      plans: failure,
      trust: failure,
    };
    const lastGood = readyLive();
    const current = { ...initialSession(), requestId: 1, source: liveSource, snapshot: lastGood };
    const settled = sessionReducer(current, { type: "loaded", requestId: 1, snapshot: failedSnapshot });

    expect(settled.source).toBe(liveSource);
    expect(settled.snapshot).toBe(lastGood);
    expect(settled.snapshot.overview).toBe(lastGood.overview);
    expect(settled.snapshot.trust).toBe(lastGood.trust);
    expect(settled.notice).toEqual({
      kind: "refused",
      text: "The vault connection was lost while its surfaces were being read. The selected vault has not been replaced, but it must be reopened before it can be used.",
    });
  });

  it("keeps the selected vault identity when a surface load rejects", () => {
    const lastGood = readyLive();
    const current = { ...initialSession(), phase: "reading" as const, requestId: 1, source: liveSource, snapshot: lastGood };
    const settled = sessionReducer(current, { type: "load-failed", requestId: 1 });

    expect(settled.source).toBe(liveSource);
    expect(settled.snapshot).toBe(lastGood);
    expect(settled.notice?.text).toContain("must be reopened");
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

  it("restores persisted maintenance receipts when a vault opens", async () => {
    const restored = { job_id: "viva.maintenance.run-4", operation: "viva.maintenance.run", state: "failed", completed: 1, total: 2, message: "Interrupted when the app closed; start maintenance again to continue.", step: "planned", attempt: 1, steps: ["planned", "spent"], cancellable: false };
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.surface.read") {
        const surface = frame.payload.surface as SurfaceName;
        const data = surface === "jobs" ? { state: "ready", jobs: [restored], running: [] } : completeSurfacePayload(surface);
        return ok(frame.requestId, { surface, job_id: "job", data } as T);
      }
      return ok(frame.requestId, {} as T);
    } };

    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });

    expect(result.current.session.jobs).toHaveLength(1);
    expect(result.current.session.jobs[0]).toMatchObject({ jobId: restored.job_id, operation: "viva.maintenance.run", state: "failed" });
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
        : { questions: [conversationQuestion()], total: 1, pending: { count: 0 } };
      const data = surface === "conversation"
        ? { turns: [], ...review }
        : surface === "review"
          ? (declined ? emptyPayload("review") : reviewPayload())
          : emptyPayload(surface);
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
      authoritative: true,
      resolved: true,
    });
    // The question is set aside, not destroyed: the read that followed says so.
    if (result.current.session.snapshot.conversation.state === "ready") expect(result.current.session.snapshot.conversation.data.questions.meta.pending).toEqual({ count: 1 });
    expect(result.current.session.selectedQueue).toBe("");
    // A mutation refreshes every financial surface.
    expect(frames.filter((frame) => frame.payload.surface === "overview")).toHaveLength(2);

    act(() => result.current.selectQueue("another-question"));
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
  });

  it("does not let a deferred question reply update or reread after navigation", async () => {
    const reply = deferred<BridgeResponse<unknown>>();
    const frames: BridgeRequest[] = [];
    let declineRequestId = "";
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.conversation.decline") { declineRequestId = frame.requestId; return reply.promise as Promise<BridgeResponse<T>>; }
      const surface = frame.payload.surface as SurfaceName;
      const data = surface === "conversation" ? { turns: [], questions: [conversationQuestion()], total: 1 }
        : surface === "review" ? reviewPayload() : emptyPayload(surface);
      return ok(frame.requestId, { surface, job_id: "job", data } as T);
    } };
    window.orionVivaBridge = transport;
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    const readsBefore = frames.filter((frame) => frame.operation === "viva.surface.read").length;

    let pending!: Promise<void>;
    act(() => { pending = result.current.declineQuestion("question-live", "not_now"); });
    expect(result.current.session.questionAction).toMatchObject({ state: "working", questionId: "question-live" });
    act(() => result.current.navigate("accounts"));
    reply.resolve(ok(declineRequestId, { kind: "completed", message: "Set aside.", state: null, reason: null }));
    await act(async () => { await pending; });

    expect(result.current.session.destination).toBe("accounts");
    expect(result.current.session.questionAction).toEqual({ state: "idle" });
    expect(frames.filter((frame) => frame.operation === "viva.surface.read")).toHaveLength(readsBefore);
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

  it("rejects late question receipts after navigation or question selection changes", () => {
    const base = { ...initialSession(), requestId: 7, source: liveSource, snapshot: withReadyReview(), destination: "review" as const };
    const working = sessionReducer(base, { type: "question-acting", requestId: 7, questionId: "question-live", verb: "answer" });
    const completion = { type: "question-acted", requestId: 7, questionId: "question-live", verb: "answer",
      result: { state: "settled", outcome: { kind: "completed", message: "Recorded.", reason: "" } }, authoritative: true, resolved: true } as const;
    const navigated = sessionReducer(working, { type: "navigate", destination: "accounts" });
    const selected = sessionReducer(working, { type: "select-queue", id: "another-question" });

    expect(sessionReducer(navigated, completion)).toBe(navigated);
    expect(sessionReducer(selected, completion)).toBe(selected);
    expect(navigated.questionAction).toEqual({ state: "idle" });
    expect(selected.questionAction).toEqual({ state: "idle" });
  });

  it("requires both Review and conversation to be data-bearing for an authoritative question reread", () => {
    const ready = withReadyReview();
    expect(authoritativeQuestionReread(ready)).toBe(true);
    for (const unavailable of [
      { state: "absent", reason: "locked" },
      { state: "unavailable", reason: "unsupported" },
      { state: "failed", reason: "read_failed" },
    ] as const) {
      expect(authoritativeQuestionReread({ ...ready, review: unavailable })).toBe(false);
      expect(authoritativeQuestionReread({ ...ready, conversation: unavailable })).toBe(false);
    }
    expect(authoritativeQuestionReread({ ...ready, overview: { state: "failed", reason: "read_failed" } })).toBe(false);
    expect(authoritativeQuestionReread(null)).toBe(false);
  });

  it("requires exact ordered one-to-one Review targets and conversation questions", () => {
    const fifteen = Array.from({ length: 15 }, (_unused, index) => `question-${index + 1}`);
    expect(authoritativeQuestionReread(pairedQuestionSnapshot(fifteen, fifteen))).toBe(true);
    expect(authoritativeQuestionReread(pairedQuestionSnapshot(fifteen, fifteen.slice(0, -1), 15))).toBe(false);
    expect(authoritativeQuestionReread(pairedQuestionSnapshot(fifteen.slice(0, -1), fifteen, 15))).toBe(false);
    expect(authoritativeQuestionReread(pairedQuestionSnapshot(fifteen, [...fifteen.slice(0, -1), fifteen[0]], 15))).toBe(false);
    expect(authoritativeQuestionReread(pairedQuestionSnapshot(fifteen, [...fifteen].reverse(), 15))).toBe(false);
  });

  it("binds same-ID Review rows to the exact question words, refs, target, status, and actions", () => {
    const valid = pairedTransactionSnapshot();
    expect(authoritativeQuestionReread(valid)).toBe(true);
    for (const contradiction of ["review-label", "review-reason", "conversation-label", "document-ref", "account-target", "canonical-target", "requested-target", "member-target", "actions", "status"] as const) {
      const candidate = structuredClone(valid);
      if (candidate.review?.state !== "ready" || candidate.conversation.state !== "ready") throw new Error("semantic fixture");
      const item = candidate.review.data.groups[0].items[0];
      const question = candidate.conversation.data.questions.queue[0];
      if (contradiction === "review-label") item.label = "Changed Review label";
      if (contradiction === "review-reason") item.reason = "Changed Review reason";
      if (contradiction === "conversation-label") question.label = "Changed conversation label";
      if (contradiction === "document-ref") question.refs = { ...question.refs, document: "doc-2" };
      if (question.reviewBinding?.target.kind === "transaction") {
        const transactionTarget = question.reviewBinding.target;
        if (contradiction === "account-target") question.reviewBinding = { ...question.reviewBinding, target: { ...transactionTarget, accountId: "acct-2" } };
        if (contradiction === "canonical-target") question.reviewBinding = { ...question.reviewBinding, target: { ...transactionTarget, canonicalMovementId: "member-2" } };
        if (contradiction === "requested-target") question.reviewBinding = { ...question.reviewBinding, target: { ...transactionTarget, requestedMovementId: "member-1" } };
        if (contradiction === "member-target") question.reviewBinding = { ...question.reviewBinding, target: { ...transactionTarget, memberMovementIds: ["member-1"] } };
      }
      if (contradiction === "actions") question.reviewBinding = { ...question.reviewBinding!, primaryAction: "open_question", allowedActions: ["open_question"] };
      if (contradiction === "status") question.reviewBinding = { ...question.reviewBinding!, status: "closed" as "open" };

      expect(authoritativeQuestionReread(candidate), contradiction).toBe(false);
      const state = { ...initialSession(), requestId: 7, source: liveSource, snapshot: valid };
      const after = sessionReducer(state, { type: "mutation-loaded", requestId: 7, snapshot: candidate });
      expect(after.snapshot, contradiction).toBe(valid);
      expect(after.notice?.kind, contradiction).toBe("refused");
    }
  });

  it("fails a structurally ready but semantically mismatched initial pair closed", () => {
    const mismatch = pairedQuestionSnapshot(["review-question"], ["conversation-question"]);
    const opening = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const reading = sessionReducer(opening, { type: "reading", requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() });
    const loaded = sessionReducer(reading, { type: "loaded", requestId: 1, snapshot: mismatch });

    expect(loaded.snapshot.review?.state).toBe("failed");
    expect(loaded.snapshot.conversation.state).toBe("failed");
    expect(loaded.selectedQueue).toBe("");
    expect(loaded.notice?.text).toContain("disagreed about which questions are actionable");
  });

  it("fails a same-ID semantic mismatch closed on initial load", () => {
    const mismatch = pairedTransactionSnapshot();
    if (mismatch.review?.state !== "ready") throw new Error("semantic fixture");
    mismatch.review.data.groups[0].items[0].reason = "A different reason under the same identity.";
    const opening = sessionReducer(initialSession(), { type: "opening", requestId: 1 });
    const reading = sessionReducer(opening, { type: "reading", requestId: 1, source: liveSource, snapshot: liveReadingSnapshot() });
    const loaded = sessionReducer(reading, { type: "loaded", requestId: 1, snapshot: mismatch });

    expect(loaded.snapshot.review?.state).toBe("failed");
    expect(loaded.snapshot.conversation.state).toBe("failed");
    expect(loaded.selectedQueue).toBe("");
  });

  it("retains the whole prior mutation snapshot for every non-data Review/conversation asymmetry", () => {
    const before = withReadyReview();
    const nonData = [
      { state: "failed", reason: "read_failed" },
      { state: "unavailable", reason: "not_served" },
      { state: "absent", reason: "not_read" },
      { state: "absent", reason: "locked" },
      { state: "absent", reason: "refused" },
    ] as const;
    for (const side of ["review", "conversation"] as const) {
      for (const unavailable of nonData) {
        const candidate: SurfaceSnapshot = side === "review"
          ? { ...before, disclosure: { ...before.disclosure, title: "New snapshot" }, review: unavailable }
          : { ...before, disclosure: { ...before.disclosure, title: "New snapshot" }, conversation: unavailable };
        const state = { ...initialSession(), requestId: 7, source: liveSource, snapshot: before };
        const after = sessionReducer(state, { type: "mutation-loaded", requestId: 7, snapshot: candidate });
        expect(after.snapshot, `${side}/${unavailable.state}/${unavailable.reason}`).toBe(before);
        expect(after.snapshot.review).toBe(before.review);
        expect(after.snapshot.conversation).toBe(before.conversation);
        expect(after.notice?.kind).toBe("refused");
      }
    }
  });

  it("commits a mutation snapshot only when Review and conversation both carry data", () => {
    const before = withReadyReview();
    const candidate = { ...withReadyReview(), disclosure: { ...before.disclosure, title: "Authoritative new snapshot" } };
    const state = { ...initialSession(), requestId: 7, source: liveSource, snapshot: before };
    const after = sessionReducer(state, { type: "mutation-loaded", requestId: 7, snapshot: candidate });

    expect(after.snapshot).toBe(candidate);
    expect(after.notice).toBeNull();
  });

  it("keeps an Ask receipt and draft authority false when its mutation reread has only one half of the pair", () => {
    const before = withReadyReview();
    const state = { ...initialSession(), requestId: 7, source: liveSource, snapshot: before };
    const working = sessionReducer(state, { type: "asking", requestId: 7, question: "What changed?" });
    const retained = sessionReducer(working, { type: "mutation-loaded", requestId: 7,
      snapshot: { ...before, review: { state: "absent", reason: "locked" } } });
    const answered = sessionReducer(retained, { type: "asked", requestId: 7, question: "What changed?",
      result: { state: "settled", outcome: { kind: "completed", message: "Answered.", reason: "" } }, turn: null, authoritative: false });

    expect(answered.snapshot).toBe(before);
    expect(answered.notice?.text).toContain("prior questions and count remain");
    expect(answered.askAction).toMatchObject({ state: "settled", authoritative: false, result: { state: "settled" } });
  });

  it.each([
    ["an invalid Review reread", false],
    ["both authoritative rereads", true],
  ] as const)("applies the universal pair gate after Ask with %s", async (_label, pairReady) => {
    let asked = false;
    const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.conversation.ask") {
        asked = true;
        return ok(frame.requestId, { kind: "completed", message: "Answered.", state: null, reason: null } as T);
      }
      const surface = frame.payload.surface as SurfaceName;
      const data = surface === "conversation"
        ? (asked ? { turns: [], questions: [], total: 0 } : { turns: [], questions: [conversationQuestion()], total: 1 })
        : surface === "review"
          ? (asked ? (pairReady ? emptyPayload("review") : { state: "locked" }) : reviewPayload())
          : emptyPayload(surface);
      return ok(frame.requestId, { surface, job_id: "job", data } as T);
    } };
    window.orionVivaBridge = transport;
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    const priorReview = result.current.session.snapshot.review;
    const priorConversation = result.current.session.snapshot.conversation;

    await act(async () => { await result.current.askViva("What changed?", true); });

    if (pairReady) {
      expect(result.current.session.snapshot.review).not.toBe(priorReview);
      if (result.current.session.snapshot.review?.state === "ready") expect(result.current.session.snapshot.review.data.actionableCount).toBe(0);
      if (result.current.session.snapshot.conversation.state === "ready") expect(result.current.session.snapshot.conversation.data.questions.queue).toEqual([]);
      expect(result.current.session.askAction).toMatchObject({ state: "settled", authoritative: true });
    } else {
      expect(result.current.session.snapshot.review).toBe(priorReview);
      expect(result.current.session.snapshot.conversation).toBe(priorConversation);
      expect(result.current.session.askAction).toMatchObject({ state: "settled", authoritative: false, result: { state: "settled" } });
      expect(result.current.session.notice?.kind).toBe("refused");
    }
  });

  it.each(["valid", "missing", "duplicate", "changed-reason"] as const)(
    "keeps a fifteen-question Ask reread atomic when Review targets are %s",
    async (variant) => {
      const ids = Array.from({ length: 15 }, (_unused, index) => `question-${index + 1}`);
      let asked = false;
      const transport: BridgeTransport = { request: async <T>(frame: BridgeRequest) => {
        if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
        if (frame.operation === "viva.conversation.ask") {
          asked = true;
          return ok(frame.requestId, { kind: "completed", message: "Answered.", state: null, reason: null } as T);
        }
        const surface = frame.payload.surface as SurfaceName;
        let data: unknown = emptyPayload(surface);
        if (surface === "conversation") data = { turns: [], questions: ids.map((id) => conversationQuestion(id, `Question ${id}`)), total: ids.length };
        if (surface === "review") {
          const reviewIds = !asked || variant === "valid" || variant === "changed-reason"
            ? ids
            : variant === "missing"
              ? ids.slice(0, -1)
              : [...ids.slice(0, -1), ids[0]];
          const reviewData = reviewPayloadForIds(reviewIds, ids.length);
          if (asked && variant === "changed-reason") {
            reviewData.groups[0].items[0].reason = "A changed reason under the same ID.";
            reviewData.groups[0].items[0].binding.reason = "A changed reason under the same ID.";
          }
          data = reviewData;
        }
        return ok(frame.requestId, { surface, job_id: "job", data } as T);
      } };
      window.orionVivaBridge = transport;
      const { result } = renderHook(() => useSurfaceSession());
      await act(async () => { await result.current.openVault("/vault", "secret", false); });
      expect(result.current.session.snapshot.review?.state).toBe("ready");
      if (result.current.session.snapshot.review?.state === "ready") expect(result.current.session.snapshot.review.data.shownCount).toBe(15);
      const priorReview = result.current.session.snapshot.review;
      const priorConversation = result.current.session.snapshot.conversation;

      await act(async () => { await result.current.askViva("What changed?", true); });

      if (variant === "valid") {
        expect(result.current.session.snapshot.review).not.toBe(priorReview);
        expect(result.current.session.askAction).toMatchObject({ state: "settled", authoritative: true });
      } else {
        expect(result.current.session.snapshot.review).toBe(priorReview);
        expect(result.current.session.snapshot.conversation).toBe(priorConversation);
        expect(result.current.session.askAction).toMatchObject({ state: "settled", authoritative: false });
        expect(result.current.session.notice?.kind).toBe("refused");
      }
    },
  );

  it("rejects a stale mutation pair even when both late surfaces carry data", () => {
    const before = withReadyReview();
    const state = { ...initialSession(), requestId: 8, source: liveSource, snapshot: before };
    expect(sessionReducer(state, { type: "mutation-loaded", requestId: 7, snapshot: withReadyReview() })).toBe(state);
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
      return ok(frame.requestId, { surface, job_id: "job", data: surface === "conversation" ? { turns: [], questions: [conversationQuestion()], total: 1 } : surface === "review" ? reviewPayload() : emptyPayload(surface) } as T);
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
      return ok(frame.requestId, { surface, job_id: "job", data: surface === "conversation" ? { turns: [], questions: [conversationQuestion()], total: 1 } : surface === "review" ? reviewPayload() : emptyPayload(surface) } as T);
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

  it("retains an Activity receipt without committing an asymmetric Review/conversation reread", () => {
    const before = readyLive();
    const base = { ...initialSession(), requestId: 7, source: liveSource, snapshot: before };
    const working = sessionReducer(base, { type: "activity-correcting", requestId: 7, movementId: "movement:key", verb: "category" });
    const result = { state: "settled", outcome: { kind: "completed", message: "Recorded.", reason: "" } } as const;
    const outcome = sessionReducer(working, { type: "activity-outcome", requestId: 7, movementId: "movement:key", verb: "category", result });
    const after = sessionReducer(outcome, { type: "activity-refreshed", requestId: 7, movementId: "movement:key", verb: "category", result,
      snapshot: { ...readyLive(), conversation: { state: "unavailable", reason: "not_served" } } });

    expect(after.snapshot).toBe(before);
    expect(after.activityAction).toMatchObject({ state: "settled", refresh: "failed", result });
    expect(after.notice?.text).toContain("prior questions and count remain");
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
    expect(frames.filter((frame) => frame.operation === "viva.surface.read")).toHaveLength(8);

    await act(async () => { refreshGate.resolve(); await pending; });
    expect(result.current.session.activityAction).toMatchObject({ state: "settled", refresh: "refreshed", result: { state: "settled", outcome: { kind: "completed" } } });
    if (result.current.session.snapshot.activity.state === "ready") expect(result.current.session.snapshot.activity.data.movements[0].category.id).toBe("housing");
    const relevant = frames.filter((frame) => frame.operation.startsWith("viva.activity.") || frame.operation === "viva.surface.read");
    expect(relevant.map((frame) => frame.operation)).toEqual(["viva.activity.assign_category", ...Array(8).fill("viva.surface.read")]);
    expect(relevant[0].payload).toEqual({ movement_key: "movement:key", category_id: "housing" });
    expect(relevant.slice(1).map((frame) => frame.payload.surface)).toEqual(["overview", "documents", "conversation", "review", "trust", "activity", "plans", "jobs"]);
    expect(relevant.find((frame) => frame.payload.surface === "activity")?.payload.parameters).toEqual({ limit: 50, focus: "movement:key" });
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
    expect(frames.map((frame) => frame.operation)).toEqual(["viva.activity.replace_tags", ...Array(8).fill("viva.surface.read")]);
  });

  it("retains an exact batch selection in action state and rereads instead of patching it", async () => {
    const frames: BridgeRequest[] = [];
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      frames.push(frame);
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_classification") return ok(frame.requestId, { kind: "completed", message: "Classification recorded.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") { const surface = frame.payload.surface as SurfaceName; return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface, true) } as T); }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });
    const oldSnapshot = result.current.session.snapshot;
    frames.length = 0;

    const selection = ["movement:key", "movement:two"];
    await act(async () => {
      const correction = result.current.assignActivityClassification(
        selection, "groceries", "supermarket");
      selection[1] = "movement:mutated-after-dispatch";
      await correction;
    });

    expect(result.current.session.snapshot).not.toBe(oldSnapshot);
    expect(result.current.session.activityAction).toMatchObject({
      state: "settled", verb: "classification", movementId: "movement:key",
      movementIds: ["movement:key", "movement:two"], refresh: "refreshed",
    });
    expect(frames[0]).toMatchObject({
      operation: "viva.activity.assign_classification",
      payload: { movement_ids: ["movement:key", "movement:two"], category_id: "groceries", subcategory_id: "supermarket" },
    });
    expect(frames.slice(1).map((frame) => frame.operation)).toEqual(Array(8).fill("viva.surface.read"));
    expect(frames.find((frame) => frame.payload.surface === "activity")?.payload.parameters).toEqual({ limit: 50, focus: "movement:key" });
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
    expect(frames.map((frame) => frame.operation)).toEqual([operation, ...Array(8).fill("viva.surface.read")]);
    expect(frames[0].payload).toEqual(expectedPayload);
    expect(frames.slice(1).map((frame) => frame.payload.surface)).toEqual(["overview", "documents", "conversation", "review", "trust", "activity", "plans", "jobs"]);
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

  it("does not let an older Load More response replace Activity after a mutation refresh", async () => {
    const page = deferred<BridgeResponse<unknown>>();
    let afterWrite = false;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_category") {
        afterWrite = true;
        return ok(frame.requestId, { kind: "completed", message: "Category recorded.", state: null, reason: null } as T);
      }
      if (frame.operation === "viva.surface.read") {
        const surface = frame.payload.surface as SurfaceName;
        if (surface === "activity" && (frame.payload.parameters as { limit?: number }).limit === 100) return page.promise as Promise<BridgeResponse<T>>;
        const raw = surface === "activity" ? activityPayload(afterWrite ? "housing" : "groceries", afterWrite ? "Housing" : "Groceries") : completeSurfacePayload(surface);
        if (surface === "activity" && !afterWrite) (raw as ReturnType<typeof activityPayload>).beyond.count = 1;
        return ok(frame.requestId, { surface, job_id: "job", data: raw } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault", "secret", false); });

    let paging!: Promise<void>;
    act(() => { paging = result.current.loadMoreActivity(); });
    await act(async () => { await result.current.assignActivityCategory("movement:key", "housing"); });
    page.resolve(ok("page", { surface: "activity", job_id: "page", data: activityPayload("groceries", "Groceries") }));
    await act(async () => { await paging; });

    if (result.current.session.snapshot.activity.state !== "ready") throw new Error("fixture");
    expect(result.current.session.snapshot.activity.data.movements[0].category.id).toBe("housing");
  });

  it("makes an in-flight account ledger non-renderable when another vault opens with the same account id", async () => {
    const ledger = deferred<BridgeResponse<unknown>>();
    let opens = 0;
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") { opens += 1; return ok(frame.requestId, { state: "opened" } as T); }
      if (frame.operation === "viva.surface.read") {
        const surface = frame.payload.surface as SurfaceName;
        if (surface === "account_ledger" && opens === 1) return ledger.promise as Promise<BridgeResponse<T>>;
        return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface) } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault-a", "secret", false); });
    let pending!: ReturnType<typeof result.current.readAccountLedger>;
    act(() => { pending = result.current.readAccountLedger("acct:one"); });
    await act(async () => { await result.current.openVault("/vault-b", "secret", false); });
    ledger.resolve(ok("ledger-a", { surface: "account_ledger", job_id: "ledger-a", data: {} }));
    let read!: Awaited<typeof pending>;
    await act(async () => { read = await pending; });
    expect(read).toEqual({ state: "absent", reason: "stale_read" });
  });

  it("makes an in-flight account ledger non-renderable after a projection mutation", async () => {
    const ledger = deferred<BridgeResponse<unknown>>();
    window.orionVivaBridge = { request: async <T>(frame: BridgeRequest) => {
      if (frame.operation === "bridge.open_vault") return ok(frame.requestId, { state: "opened" } as T);
      if (frame.operation === "viva.activity.assign_category") return ok(frame.requestId, { kind: "completed", message: "Category recorded.", state: null, reason: null } as T);
      if (frame.operation === "viva.surface.read") {
        const surface = frame.payload.surface as SurfaceName;
        if (surface === "account_ledger") return ledger.promise as Promise<BridgeResponse<T>>;
        return ok(frame.requestId, { surface, job_id: "job", data: completeSurfacePayload(surface, true) } as T);
      }
      return ok(frame.requestId, {} as T);
    } };
    const { result } = renderHook(() => useSurfaceSession());
    await act(async () => { await result.current.openVault("/vault-a", "secret", false); });
    let pending!: ReturnType<typeof result.current.readAccountLedger>;
    act(() => { pending = result.current.readAccountLedger("acct:one"); });
    await act(async () => { await result.current.assignActivityCategory("movement:key", "housing"); });
    ledger.resolve(ok("ledger-before-write", { surface: "account_ledger", job_id: "ledger-before-write", data: {} }));
    let read!: Awaited<typeof pending>;
    await act(async () => { read = await pending; });
    expect(read).toEqual({ state: "absent", reason: "stale_read" });
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
    expect(frames.map((frame) => frame.operation)).toEqual(["viva.activity.assign_category", ...Array(8).fill("viva.surface.read")]);
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
