import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BridgeRefusal, BridgeTimeout, REQUEST_REFUSED } from "../bridge/contracts";
import type { BulkDocumentResult, DocumentActions, JobView, SurfaceDocument } from "../surface/types";
import { initialSession } from "./session";
import { useDocumentIntake } from "./useDocumentIntake";

type Context = Parameters<typeof useDocumentIntake>[0];
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (failure: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function result(paths: readonly string[], jobId = "chunk-1"): BulkDocumentResult { return { jobId, rows: paths.map((_, ordinal) => ({ ordinal, documentId: `source-${ordinal}`, action: ordinal === 0 ? "awaiting" : "posted", disposition: "read", reason: null })) }; }
function fixture(paths = ["/one.pdf", "/two.pdf", "/three.pdf", "/four.pdf"]) {
  const uploadMany = vi.fn(async (chunk: readonly string[]) => result(chunk));
  const actions: DocumentActions = { uploadMany, upload: vi.fn(), cancel: vi.fn(async () => ({ state: "unanswered" } as const)), readJobs: vi.fn(async () => ({ state: "ready", data: { jobs: [], running: [] } } as never)), rescan: vi.fn(), reread: vi.fn() };
  const source = {} as NonNullable<Context["source"]>;
  const context: Context = { session: { ...initialSession(), source }, dispatch: vi.fn(), hostBridge: { pickMultipleDocumentPaths: vi.fn(async () => paths) } as never, requestId: { current: 1 }, dropped: { current: undefined }, documentActions: actions, source, sourceIdentity: { current: source } };
  const refreshAfterAction = vi.fn(async () => null);
  const hook = renderHook(() => useDocumentIntake(context, { refreshAfterAction }));
  return { ...hook, context, uploadMany, actions, refreshAfterAction };
}
const job: JobView = { jobId: "active-chunk", operation: "viva.documents.upload_many", state: "running", completed: 0, total: 3, message: "", step: "reading", attempt: 1, steps: [], cancellable: true };
describe("session bulk admission", () => {
  it("waits for the current chunk before admitting at most three more", async () => {
    const f = fixture(); const first = deferred<BulkDocumentResult>(); f.uploadMany.mockImplementationOnce(() => first.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.uploadMany).toHaveBeenCalledTimes(1));
    expect(f.uploadMany.mock.calls[0][0]).toEqual(["/one.pdf", "/two.pdf", "/three.pdf"]);
    expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["working", "working", "working", "queued"]);
    await act(async () => { first.resolve(result(["one", "two", "three"])); await completion; });
    expect(f.uploadMany.mock.calls[1][0]).toEqual(["/four.pdf"]);
    expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["awaiting", "posted", "posted", "awaiting"]);
  });
  it("retains all 794 input rows after 265 chunk jobs", async () => {
    const paths = Array.from({ length: 794 }, (_, i) => `/document-${i}.pdf`); const f = fixture(paths);
    f.uploadMany.mockImplementation(async (chunk) => result(chunk, `chunk-${f.uploadMany.mock.calls.length}`));
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.uploadMany).toHaveBeenCalledTimes(265); expect(f.result.current.bulkSession?.rows).toHaveLength(794); expect(f.result.current.bulkSession?.jobIds).toHaveLength(265);
    expect(f.uploadMany.mock.calls.every(([chunk]) => chunk.length >= 1 && chunk.length <= 3)).toBe(true);
  });
  it("stops queued admissions and cancels an active job once its identity arrives", async () => {
    const f = fixture(); const first = deferred<BulkDocumentResult>(); f.uploadMany.mockImplementationOnce(() => first.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.uploadMany).toHaveBeenCalledTimes(1));
    act(() => f.result.current.stopBulkDocuments()); expect(f.result.current.bulkSession?.state).toBe("stopping");
    f.context.session = { ...f.context.session, jobs: [job] }; f.rerender();
    await waitFor(() => expect(f.actions.cancel).toHaveBeenCalledWith("active-chunk"));
    f.rerender(); expect(f.actions.cancel).toHaveBeenCalledTimes(1);
    await act(async () => { first.resolve(result(["one", "two", "three"])); await completion; });
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.result.current.bulkSession?.rows[3].status).toBe("not_started");
    expect(f.result.current.bulkSession?.rows[0].status).toBe("awaiting");
  });
  it("does not cancel a late previous chunk when stopping the current chunk", async () => {
    const f = fixture(Array.from({ length: 7 }, (_, i) => `/selected-${i}.pdf`)); const second = deferred<BulkDocumentResult>();
    f.uploadMany.mockImplementationOnce(async (paths) => result(paths, "previous-chunk")).mockImplementationOnce(() => second.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.uploadMany).toHaveBeenCalledTimes(2));
    act(() => f.result.current.stopBulkDocuments());
    f.context.session = { ...f.context.session, jobs: [{ ...job, jobId: "previous-chunk" }] }; f.rerender();
    expect(f.actions.cancel).not.toHaveBeenCalled();
    f.context.session = { ...f.context.session, jobs: [{ ...job, jobId: "previous-chunk" }, job] }; f.rerender();
    await waitFor(() => expect(f.actions.cancel).toHaveBeenCalledWith("active-chunk"));
    await act(async () => { second.resolve(result(["four", "five", "six"], "active-chunk")); await completion; });
    expect(f.uploadMany).toHaveBeenCalledTimes(2); expect(f.result.current.bulkSession?.rows[6].status).toBe("not_started");
  });
  it("stops after outcome unknown, rechecks jobs and never retries", async () => {
    const f = fixture(); f.uploadMany.mockRejectedValueOnce(new BridgeTimeout("viva.documents.upload_many", true));
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.actions.readJobs).toHaveBeenCalledTimes(1);
    expect(f.result.current.bulkSession?.state).toBe("uncertain"); expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["uncertain", "uncertain", "uncertain", "not_started"]);
  });
  it("does not automatically continue after the backend reports cancellation", async () => {
    const f = fixture(); const completed = result(["one", "two", "three"]);
    f.uploadMany.mockResolvedValueOnce({ ...completed, rows: completed.rows.map((row) => ({ ...row, action: "cancelled", reason: "job_cancelled" })) });
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.result.current.bulkSession?.rows[3].status).toBe("not_started");
  });
  it("stops on a returned uncertain settlement without discarding other terminal rows", async () => {
    const f = fixture(); const completed = result(["one", "two", "three"]);
    f.uploadMany.mockResolvedValueOnce({ ...completed, rows: completed.rows.map((row, ordinal) => ordinal === 1 ? { ...row, action: "failed", disposition: null, reason: "outcome_unknown" } : row) });
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.result.current.bulkSession?.state).toBe("uncertain");
    expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["awaiting", "uncertain", "posted", "not_started"]);
  });
  it("distinguishes a refused request from an uncertain admitted request", async () => {
    const f = fixture(); f.uploadMany.mockRejectedValueOnce(new BridgeRefusal(REQUEST_REFUSED, ""));
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.uploadMany).toHaveBeenCalledTimes(1);
    expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["refused", "refused", "refused", "not_started"]);
    expect(f.result.current.bulkSession?.state).toBe("finished");
  });
  it("refuses more than 1000 selections before admission", async () => {
    const f = fixture(Array(1001).fill("/selected.pdf")); let answer;
    await act(async () => { answer = await f.result.current.chooseBulkDocuments(); });
    expect(answer).toBe("over_limit"); expect(f.uploadMany).not.toHaveBeenCalled();
  });
  it("does not publish late replies or dispatch another chunk after vault generation changes", async () => {
    const f = fixture(); const first = deferred<BulkDocumentResult>(); f.uploadMany.mockImplementationOnce(() => first.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.uploadMany).toHaveBeenCalledTimes(1));
    f.context.requestId.current += 1;
    await act(async () => { first.resolve(result(["one", "two", "three"])); await completion; });
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.refreshAfterAction).not.toHaveBeenCalled();
  });
  it("stops future admission when the hook unmounts and keeps the current call intact", async () => {
    const f = fixture(); const first = deferred<BulkDocumentResult>(); f.uploadMany.mockImplementationOnce(() => first.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.uploadMany).toHaveBeenCalledTimes(1)); f.unmount();
    first.resolve(result(["one", "two", "three"])); await completion;
    expect(f.uploadMany).toHaveBeenCalledTimes(1); expect(f.refreshAfterAction).not.toHaveBeenCalled();
  });
});

function savedDocument(letter = "a", token = `token-${letter}`): SurfaceDocument { return { id: letter.repeat(64), name: `${letter}.pdf`, state: "", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [], retry: { state: "available", reason: "new_reading_available", confirmationToken: token } }; }
function retainedFixture() {
 const f = fixture(); const reading = vi.fn(async (entries: readonly { documentId: string }[]) => ({ jobId: "new-reading", rows: entries.map((entry, ordinal) => ({ ordinal, documentId: entry.documentId, action: "posted" as const, disposition: "read" as const, reason: null })) }));
 f.actions.readRetained = reading; f.rerender(); return { ...f, reading };
}
describe("explicit new reading selection", () => {
 it("selects at most three distinct identities and tokens without reading, then consumes one confirmation synchronously", async () => {
  const f = retainedFixture();
  act(() => { for (const letter of ["a", "b", "c", "d"]) f.result.current.addRetainedReading(savedDocument(letter)); });
  expect(f.result.current.retainedSelection).toHaveLength(3); expect(f.reading).not.toHaveBeenCalled();
  const confirm = f.result.current.confirmRetainedReadings;
  await act(async () => { confirm(); confirm(); await Promise.resolve(); });
  expect(f.reading).toHaveBeenCalledTimes(1); expect(f.uploadMany).not.toHaveBeenCalled();
  expect(f.reading.mock.calls[0][0]).toEqual(["a", "b", "c"].map((letter) => ({ documentId: letter.repeat(64), name: `${letter}.pdf`, reason: "new_reading_available", confirmationToken: `token-${letter}` })));
  expect(f.result.current.retainedSelection).toHaveLength(0); expect(f.result.current.bulkSession?.mode).toBe("retained");
  act(() => f.result.current.addRetainedReading(savedDocument())); expect(f.result.current.retainedSelection).toHaveLength(0);
 });
 it("invalidates the old rendered confirmation after removal and does not silently replace a selected token", () => {
  const f = retainedFixture(); act(() => f.result.current.addRetainedReading(savedDocument()));
  const stale = f.result.current.confirmRetainedReadings;
  act(() => f.result.current.addRetainedReading(savedDocument("a", "new-token")));
  expect(f.result.current.retainedSelection[0].confirmationToken).toBe("token-a");
  act(() => { f.result.current.removeRetainedReading("a".repeat(64)); stale(); }); expect(f.reading).not.toHaveBeenCalled();
 });
 it("keeps a lost reply uncertain without retry or restoring consumed selection", async () => {
  const f = retainedFixture(); f.reading.mockRejectedValueOnce(new BridgeTimeout("viva.documents.upload_many", true));
  act(() => f.result.current.addRetainedReading(savedDocument()));
  await act(async () => { f.result.current.confirmRetainedReadings(); });
  expect(f.result.current.bulkSession?.state).toBe("uncertain"); expect(f.result.current.retainedSelection).toHaveLength(0);
  f.rerender(); expect(f.reading).toHaveBeenCalledTimes(1); expect(f.actions.readJobs).toHaveBeenCalledTimes(1);
 });
 it("blocks disabled reader and unavailable jobs, and discards unstarted selection with source ownership", () => {
  const f = retainedFixture(); f.context.session = { ...f.context.session, jobStatus: "unavailable" }; f.rerender();
  act(() => f.result.current.addRetainedReading(savedDocument())); expect(f.result.current.retainedSelection).toHaveLength(0);
  f.context.session = { ...f.context.session, jobStatus: "available", settings: { state: "ready", data: { canSend: false } } as never }; f.rerender();
  act(() => f.result.current.addRetainedReading(savedDocument())); expect(f.result.current.retainedSelection).toHaveLength(0);
  f.context.session = { ...f.context.session, settings: { state: "absent", reason: "not_asked" } }; f.rerender();
  act(() => f.result.current.addRetainedReading(savedDocument())); expect(f.result.current.retainedSelection).toHaveLength(1);
  const old = f.result.current.confirmRetainedReadings;
  f.context.sourceIdentity.current = {} as never; act(() => old()); expect(f.reading).not.toHaveBeenCalled();
  f.context.source = f.context.sourceIdentity.current; f.rerender(); expect(f.result.current.retainedSelection).toHaveLength(0);
 });
});

it("keeps stale confirmation refusal explicit and requires another manual selection and confirmation", async () => {
 const f = retainedFixture(); f.reading.mockResolvedValueOnce({ jobId: "refused-new-reading", rows: [{ ordinal: 0, documentId: "a".repeat(64), action: "refused", disposition: null, reason: "stale_confirmation" }] } as never);
 act(() => f.result.current.addRetainedReading(savedDocument())); await act(async () => f.result.current.confirmRetainedReadings());
 expect(f.result.current.bulkSession?.rows[0].outcome?.reason).toBe("stale_confirmation"); expect(f.result.current.retainedSelection).toHaveLength(0); expect(f.reading).toHaveBeenCalledTimes(1);
 act(() => f.result.current.addRetainedReading(savedDocument("a", "fresh-token"))); expect(f.reading).toHaveBeenCalledTimes(1);
 await act(async () => f.result.current.confirmRetainedReadings()); expect(f.reading).toHaveBeenCalledTimes(2);
});
it("stops an owned retained reading and preserves identities until its terminal reply", async () => {
 const f = retainedFixture(); const pending = deferred<BulkDocumentResult>(); f.reading.mockImplementationOnce(() => pending.promise as never);
 act(() => { f.result.current.addRetainedReading(savedDocument()); f.result.current.addRetainedReading(savedDocument("b")); });
 act(() => f.result.current.confirmRetainedReadings()); act(() => f.result.current.stopBulkDocuments());
 f.context.session = { ...f.context.session, jobs: [job] }; f.rerender();
 await waitFor(() => expect(f.actions.cancel).toHaveBeenCalledWith(job.jobId)); expect(f.result.current.bulkSession?.state).toBe("stopping");
 await act(async () => pending.resolve({ jobId: job.jobId, rows: ["a", "b"].map((letter, ordinal) => ({ ordinal, documentId: letter.repeat(64), action: "cancelled", disposition: null, reason: "job_cancelled" })) }));
 expect(f.reading).toHaveBeenCalledTimes(1); expect(f.result.current.bulkSession?.rows.map((row) => row.documentId)).toEqual(["a".repeat(64), "b".repeat(64)]);
});
it("rejects old callbacks after generation changes, model disabling, and unmount", () => {
 const f = retainedFixture(); act(() => f.result.current.addRetainedReading(savedDocument())); const stale = f.result.current.confirmRetainedReadings;
 f.context.session = { ...f.context.session, settings: { state: "ready", data: { canSend: false } } as never }; f.rerender(); act(() => stale()); expect(f.reading).not.toHaveBeenCalled();
 f.context.session = { ...f.context.session, settings: { state: "absent", reason: "not_asked" } }; f.rerender(); f.context.requestId.current += 1; act(() => stale()); expect(f.reading).not.toHaveBeenCalled();
 f.rerender(); expect(f.result.current.retainedSelection).toHaveLength(0); act(() => f.result.current.addRetainedReading(savedDocument())); const last = f.result.current.confirmRetainedReadings;
 f.unmount(); act(() => last()); expect(f.reading).not.toHaveBeenCalled();
});

function savedImport(remaining = 4): import("../surface/types").ImportSessionSnapshot {
  return { sessionId: "a".repeat(32), total: 4, completed: 4 - remaining, remaining, state: remaining ? "pending" : "completed", rows: ["one", "two", "three", "four"].map((path, ordinal) => ({ path: `${path}.pdf`, documentId: "b".repeat(64), status: ordinal < 4 - remaining ? "posted" : "queued" })) };
}
function queuedFixture() {
  const f = fixture();
  const enqueueImport = vi.fn(async () => savedImport());
  const listImports = vi.fn(async () => [] as import("../surface/types").ImportSessionSummary[]);
  const resumeImport = vi.fn(async () => ({ ...result(["one", "two", "three"]), session: savedImport(1) }));
  const inspectImport = vi.fn(async (_sessionId: string) => savedImport());
  f.context.documentActions = { ...f.actions, enqueueImport, listImports, resumeImport, inspectImport };
  f.rerender();
  return { ...f, enqueueImport, listImports, resumeImport, inspectImport };
}
describe("durable encrypted selections", () => {
  it("enqueues the whole folder once and refreshes each committed chunk before continuing", async () => {
    const f = queuedFixture();
    const second = deferred<import("../surface/types").ImportChunkResult>();
    f.resumeImport.mockImplementationOnce(async () => ({ ...result(["one", "two", "three"]), session: savedImport(1) })).mockImplementationOnce(() => second.promise as never);
    let completion!: Promise<unknown>;
    act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.resumeImport).toHaveBeenCalledTimes(2));
    expect(f.enqueueImport).toHaveBeenCalledWith(["/one.pdf", "/two.pdf", "/three.pdf", "/four.pdf"]);
    expect(f.uploadMany).not.toHaveBeenCalled();
    expect(f.refreshAfterAction).toHaveBeenCalledTimes(1);
    expect(f.result.current.bulkSession?.rows.map((row) => row.status)).toEqual(["posted", "posted", "posted", "queued"]);
    await act(async () => { second.resolve({ ...result(["four"], "last"), session: savedImport(0) }); await completion; });
    expect(f.refreshAfterAction).toHaveBeenCalledTimes(2);
    expect(f.result.current.pendingImports).toHaveLength(0);
  });
  it("stops capture admission while originals are being saved and does not start a reading", async () => {
    const f = queuedFixture(); const saving = deferred<import("../surface/types").ImportSessionSnapshot>();
    f.enqueueImport.mockImplementationOnce(() => saving.promise);
    let completion!: Promise<unknown>; act(() => { completion = f.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(f.enqueueImport).toHaveBeenCalledOnce());
    expect(f.result.current.bulkSession?.state).toBe("running");
    act(() => f.result.current.stopBulkDocuments());
    f.context.session = { ...f.context.session, jobs: [job] }; f.rerender();
    await waitFor(() => expect(f.actions.cancel).toHaveBeenCalledWith("active-chunk"));
    await act(async () => { saving.resolve({ ...savedImport(), state: "stopped" }); await completion; });
    expect(f.resumeImport).not.toHaveBeenCalled(); expect(f.result.current.pendingImports).toHaveLength(1);
    expect(f.result.current.bulkSession?.state).toBe("paused");
  });
  it("discovers retained selections after reopening but only continues on an explicit gesture", async () => {
    const f = queuedFixture(); f.listImports.mockResolvedValue([savedImport()]);
    f.context.source = {} as never; f.context.sourceIdentity.current = f.context.source; f.rerender();
    await waitFor(() => expect(f.result.current.pendingImports).toHaveLength(1));
    expect(f.resumeImport).not.toHaveBeenCalled();
    f.resumeImport.mockResolvedValue({ ...result(["one"]), session: savedImport(0) });
    await act(async () => { f.result.current.resumeImportSession("a".repeat(32)); });
    expect(f.resumeImport).toHaveBeenCalledOnce();
  });
  it("does not continue an uncertain paid request or apply replies after vault switching", async () => {
    const f = queuedFixture();
    f.resumeImport.mockResolvedValue({ ...result(["one"]), session: { ...savedImport(), state: "interrupted" } });
    await act(async () => { await f.result.current.chooseBulkDocuments(); });
    expect(f.resumeImport).toHaveBeenCalledOnce(); expect(f.result.current.bulkSession?.state).toBe("uncertain");
    const another = queuedFixture(); const saving = deferred<import("../surface/types").ImportSessionSnapshot>();
    another.enqueueImport.mockImplementationOnce(() => saving.promise);
    let completion!: Promise<unknown>; act(() => { completion = another.result.current.chooseBulkDocuments(); });
    await waitFor(() => expect(another.enqueueImport).toHaveBeenCalledOnce());
    another.context.requestId.current += 1;
    await act(async () => { saving.resolve(savedImport()); await completion; });
    expect(another.resumeImport).not.toHaveBeenCalled();
  });
});

it.each(["enqueue", "continue"] as const)("keeps explicit %s refusal distinct from an uncertain admitted request", async (boundary) => {
  const f = queuedFixture();
  const failure = new BridgeRefusal(REQUEST_REFUSED, "unreviewed machine details");
  if (boundary === "enqueue") f.enqueueImport.mockRejectedValueOnce(failure);
  else f.resumeImport.mockRejectedValueOnce(failure);
  await act(async () => { await f.result.current.chooseBulkDocuments(); });
  expect(f.result.current.bulkSession?.state).toBe("refused");
  expect(f.actions.readJobs).not.toHaveBeenCalled();
  expect(f.context.dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: "captured", result: { state: "unserved" } }));
  expect(JSON.stringify(vi.mocked(f.context.dispatch).mock.calls)).not.toContain("unreviewed machine details");
});
it("requires inspecting interrupted saved results before a manual continuation", async () => {
  const f = queuedFixture();
  const saved = { ...savedImport(), state: "interrupted" as const };
  f.listImports.mockResolvedValue([saved]);
  const inspectImport = vi.fn(async () => saved);
  f.context.documentActions = { ...f.context.documentActions!, inspectImport };
  f.context.source = {} as never; f.context.sourceIdentity.current = f.context.source; f.rerender();
  await waitFor(() => expect(f.result.current.pendingImports).toHaveLength(1));
  act(() => f.result.current.resumeImportSession(saved.sessionId));
  expect(f.resumeImport).not.toHaveBeenCalled();
  await act(async () => { await f.result.current.inspectImportSession(saved.sessionId); });
  expect(inspectImport).toHaveBeenCalledWith(saved.sessionId);
  expect(f.result.current.bulkSession?.state).toBe("uncertain");
  expect(f.resumeImport).not.toHaveBeenCalled();
  f.resumeImport.mockResolvedValue({ ...result(["one"]), session: savedImport(0) });
  await act(async () => { f.result.current.resumeImportSession(saved.sessionId); });
  expect(f.resumeImport).toHaveBeenCalledOnce();
});

it("invalidates inspection A when another selection replaces its displayed document rows", async () => {
  const f = queuedFixture();
  const interruptedA = { ...savedImport(), label: "selection-a.pdf", state: "interrupted" as const };
  const pendingB = { ...savedImport(), sessionId: "c".repeat(32), label: "selection-b.pdf" };
  f.listImports.mockResolvedValue([interruptedA, pendingB]);
  const inspectImport = vi.fn(async (sessionId: string) => sessionId === interruptedA.sessionId ? interruptedA : pendingB);
  f.context.documentActions = { ...f.context.documentActions!, inspectImport };
  f.context.source = {} as never; f.context.sourceIdentity.current = f.context.source; f.rerender();
  await waitFor(() => expect(f.result.current.pendingImports).toHaveLength(2));
  await act(async () => { await f.result.current.inspectImportSession(interruptedA.sessionId); });
  expect(f.result.current.inspectedImport).toBe(interruptedA.sessionId);
  const oldContinue = f.result.current.resumeImportSession;
  f.resumeImport.mockResolvedValue({ ...result(["b"]), session: { ...savedImport(0), sessionId: pendingB.sessionId } });
  await act(async () => { f.result.current.resumeImportSession(pendingB.sessionId); });
  expect(f.result.current.inspectedImport).toBeNull();
  expect(f.resumeImport).toHaveBeenCalledOnce();
  act(() => { f.result.current.resumeImportSession(interruptedA.sessionId); oldContinue(interruptedA.sessionId); });
  expect(f.resumeImport).toHaveBeenCalledOnce();
  await act(async () => { await f.result.current.inspectImportSession(interruptedA.sessionId); });
  expect(inspectImport.mock.calls.map(([sessionId]) => sessionId)).toEqual([interruptedA.sessionId, pendingB.sessionId, interruptedA.sessionId]);
});

it("publishes inspected saved rows with a live Stop before the first resumed chunk answers", async () => {
  const f = queuedFixture();
  f.listImports.mockResolvedValue([savedImport()]);
  f.context.source = {} as never; f.context.sourceIdentity.current = f.context.source; f.rerender();
  await waitFor(() => expect(f.result.current.pendingImports).toHaveLength(1));
  const reading = deferred<import("../surface/types").ImportChunkResult>();
  f.resumeImport.mockImplementationOnce(() => reading.promise as never);
  act(() => { f.result.current.resumeImportSession("a".repeat(32)); });
  await waitFor(() => expect(f.resumeImport).toHaveBeenCalledOnce());
  expect(f.inspectImport).toHaveBeenCalledWith("a".repeat(32));
  expect(f.inspectImport.mock.invocationCallOrder[0]).toBeLessThan(f.resumeImport.mock.invocationCallOrder[0]);
  expect(f.result.current.bulkSession).toMatchObject({ state: "running", rows: savedImport().rows });
  act(() => { f.result.current.stopBulkDocuments(); });
  expect(f.result.current.bulkSession?.state).toBe("stopping");
  f.context.session = { ...f.context.session, jobs: [job] }; f.rerender();
  await waitFor(() => expect(f.actions.cancel).toHaveBeenCalledWith("active-chunk"));
  f.rerender(); expect(f.actions.cancel).toHaveBeenCalledOnce();
  await act(async () => { reading.resolve({ ...result(["one", "two", "three"]), session: { ...savedImport(1), state: "stopped" } }); });
  expect(f.resumeImport).toHaveBeenCalledOnce();
  expect(f.result.current.bulkSession?.state).toBe("paused");
});
it("does not admit a saved chunk after its prerequisite inspection returns for an old vault generation", async () => {
  const f = queuedFixture();
  f.listImports.mockResolvedValue([savedImport()]);
  f.context.source = {} as never; f.context.sourceIdentity.current = f.context.source; f.rerender();
  await waitFor(() => expect(f.result.current.pendingImports).toHaveLength(1));
  const inspecting = deferred<import("../surface/types").ImportSessionSnapshot>();
  f.inspectImport.mockImplementationOnce(() => inspecting.promise);
  act(() => { f.result.current.resumeImportSession("a".repeat(32)); });
  await waitFor(() => expect(f.inspectImport).toHaveBeenCalledOnce());
  f.context.requestId.current += 1;
  await act(async () => { inspecting.resolve(savedImport()); });
  expect(f.resumeImport).not.toHaveBeenCalled();
});
