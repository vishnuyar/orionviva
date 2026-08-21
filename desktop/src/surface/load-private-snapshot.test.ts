import { describe, expect, it } from "vitest";
import { BridgeRefusal, BridgeUnreadable } from "../bridge/contracts";
import type { BridgeClient, SurfaceName } from "../bridge/contracts";
import { loadPrivateSnapshot } from "./load-private-snapshot";
import { demoSource, privateSource } from "./sources";

function client(data: Partial<Record<SurfaceName, unknown>> = {}): BridgeClient {
  const defaults: Record<SurfaceName, unknown> = { overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } };
  const read = async (surface: SurfaceName) => ({ surface, job_id: `test-${surface}`, data: surface in data ? data[surface] : defaults[surface] });
  return { openVault: async () => undefined, readOverview: () => read("overview"), readDocuments: () => read("documents"), readReview: () => read("review"), declineQuestion: async () => ({ kind: "completed", message: "Set aside.", state: null, reason: null }), uploadDocument: async () => ({ kind: "completed", message: "Saved.", state: null, reason: null }) };
}

describe("surface loading boundary", () => {
  it("keeps the fixture-backed preview path explicit", async () => {
    const snapshot = await demoSource.load();
    expect(snapshot.overview.state).toBe("ready");
    if (snapshot.overview.state === "ready") expect(snapshot.overview.data.currentThrough).toBe("July 31, 2026");
    expect(demoSource.boundary).toBe("fixture");
  });

  it("provides one typed demo source boundary for the shell", async () => {
    const snapshot = await demoSource.load();
    expect(demoSource.id).toBe("synthetic-demo");
    expect(demoSource.label).toBe("Sample vault");
    expect(demoSource.mode).toBe("demo");
    expect(snapshot).toBe(await demoSource.load());
    expect([snapshot.overview.state, snapshot.documents.state, snapshot.activity.state]).toEqual(["ready", "ready", "ready"]);
  });

  it("exposes a typed private source seam", async () => {
    const source = privateSource(client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } }));
    const snapshot = await source.load();
    expect(source.boundary).toBe("bridge-ready");
    expect(snapshot.mode).toBe("live");
    expect(snapshot.review.state).toBe("ready");
  });

  it("settles surface reads independently", async () => {
    const base = client({ overview: { accounts: [] }, review: { questions: [], total: 0 } });
    const snapshot = await loadPrivateSnapshot({ ...base, readDocuments: async () => { throw new Error("bounded read failure"); } });
    expect([snapshot.overview.state, snapshot.documents.state, snapshot.review.state]).toEqual(["ready", "failed", "ready"]);
    expect(snapshot.documents).toEqual({ state: "failed", reason: "read_failed" });
  });

  it("maps fulfilled malformed unknown payloads to invalid payload failures", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: null, documents: "bad", review: [] }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("rejects a fulfilled overview payload without its owned accounts collection", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: {} }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.documents.state).toBe("ready");
    expect(snapshot.review.state).toBe("ready");
  });

  it("rejects a fulfilled documents payload without its owned documents collection", async () => {
    const snapshot = await loadPrivateSnapshot(client({ documents: { wrong: [] } }));
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.overview.state).toBe("ready");
    expect(snapshot.review.state).toBe("ready");
  });

  it("rejects a fulfilled review payload without its owned questions and numeric total", async () => {
    const missingTotal = await loadPrivateSnapshot(client({ review: { questions: [] } }));
    const wrongTotal = await loadPrivateSnapshot(client({ review: { questions: [], total: "0" } }));
    expect(missingTotal.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(wrongTotal.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("isolates malformed optional review summaries as an invalid review payload", async () => {
    const malformedTail = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: "0" }, pending: { count: 1 } } }));
    expect(malformedTail.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([malformedTail.overview.state, malformedTail.documents.state]).toEqual(["ready", "ready"]);

    const malformedPending = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: 2, amount: "2.00" }, pending: { count: -1 } } }));
    expect(malformedPending.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([malformedPending.overview.state, malformedPending.documents.state]).toEqual(["ready", "ready"]);
  });

  it("keeps explicit zero review summaries ready", async () => {
    const snapshot = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 } } }));
    expect(snapshot.review).toEqual({ state: "ready", data: { queue: [], count: 0, meta: { total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 }, invite: "", answeredByDocument: "" } } });
    expect([snapshot.overview.state, snapshot.documents.state]).toEqual(["ready", "ready"]);
  });

  it("rejects a malformed overview row without discarding valid sibling surfaces", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: { accounts: [{ name: "missing stable id" }] } }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([snapshot.documents.state, snapshot.review.state]).toEqual(["ready", "ready"]);
  });

  it("rejects a primitive document collection member", async () => {
    const snapshot = await loadPrivateSnapshot(client({ documents: { documents: ["not a document"] } }));
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("rejects a malformed review row even with an explicit numeric total", async () => {
    const snapshot = await loadPrivateSnapshot(client({ review: { questions: [{ text: "missing stable id" }], total: 1 } }));
    expect(snapshot.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("adversarially exercises all eight fulfilled and rejected combinations", async () => {
    for (let mask = 0; mask < 8; mask += 1) {
      const base = client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } });
      const reject = async (): Promise<never> => { throw new Error("bounded read failure"); };
      const snapshot = await loadPrivateSnapshot({ ...base, readOverview: mask & 1 ? base.readOverview : reject, readDocuments: mask & 2 ? base.readDocuments : reject, readReview: mask & 4 ? base.readReview : reject });
      expect([snapshot.overview.state, snapshot.documents.state, snapshot.review.state]).toEqual([mask & 1 ? "ready" : "failed", mask & 2 ? "ready" : "failed", mask & 4 ? "ready" : "failed"]);
    }
  });

  it("never imports demo facts into a private snapshot", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } }));
    const serialized = JSON.stringify(snapshot);
    for (const marker of ["Everyday checking", "$48,240.18", "silverline-checking", "Synthetic PDF"]) expect(serialized).not.toContain(marker);
  });

  it("carries the review verb on every source a screen can be given", async () => {
    const actions = privateSource(client()).reviewActions;
    // No source is without the verbs, so no screen has a state where the
    // controls are missing and none may carry copy describing one. A source
    // that dropped them would fail here rather than reach a person as a panel
    // saying actions are not connected.
    for (const source of [demoSource, privateSource(client())]) {
      expect(typeof source.reviewActions.decline).toBe("function");
      expect(typeof source.reviewActions.reread).toBe("function");
    }
    // The sample vault records nothing, so its verb refuses and says so. That
    // keeps the refusal a person may meet reachable with no vault open.
    await expect(demoSource.reviewActions.decline("sample", "not_now")).resolves.toMatchObject({ state: "settled", outcome: { kind: "refused", reason: "sample_vault" } });
    await expect(actions.decline("q-1", "not_now")).resolves.toEqual({ state: "settled", outcome: { kind: "completed", message: "Set aside.", reason: "" } });
    await expect(actions.reread()).resolves.toEqual({ state: "ready", data: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } });
  });

  it("keeps four unlike replies to one verb in four channels", async () => {
    const unanswered: BridgeClient = { ...client(), declineQuestion: async () => { throw new Error("sidecar gone"); } };
    const unreadable: BridgeClient = { ...client(), declineQuestion: async () => ({ kind: "invented" }) };
    const refused: BridgeClient = { ...client(), declineQuestion: async () => { throw new BridgeRefusal("invalid_request", "reason must be one of: dont_know, not_now"); } };
    // A code that does not mean the request was refused carries machine text —
    // here a Python exception's own repr — so it is read as a reply this screen
    // cannot make sense of rather than as the vault saying no.
    const raised: BridgeClient = { ...client(), declineQuestion: async () => { throw new BridgeRefusal("handler_failed", "'questions'"); } };
    const empty: BridgeClient = { ...client(), declineQuestion: async () => { throw new BridgeUnreadable("viva.review.decline"); } };

    await expect(privateSource(unanswered).reviewActions?.decline("q-1", "not_now")).resolves.toEqual({ state: "unanswered" });
    await expect(privateSource(unreadable).reviewActions?.decline("q-1", "not_now")).resolves.toEqual({ state: "unreadable" });
    await expect(privateSource(refused).reviewActions?.decline("q-1", "not_now")).resolves.toEqual({ state: "unserved" });
    await expect(privateSource(raised).reviewActions?.decline("q-1", "not_now")).resolves.toEqual({ state: "unreadable" });
    await expect(privateSource(empty).reviewActions?.decline("q-1", "not_now")).resolves.toEqual({ state: "unreadable" });
  });
});
