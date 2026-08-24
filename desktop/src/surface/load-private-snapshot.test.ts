import { describe, expect, it } from "vitest";
import { BridgeRefusal, BridgeUnreadable } from "../bridge/contracts";
import type { BridgeClient, SurfaceName } from "../bridge/contracts";
import { loadPrivateSnapshot } from "./load-private-snapshot";
import { privateSource, sampleSource } from "./sources";

function client(data: Partial<Record<SurfaceName, unknown>> = {}): BridgeClient {
  const defaults: Record<SurfaceName, unknown> = { overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 }, jobs: { state: "absent", jobs: [], running: [] }, trust: { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } }, activity: { state: "absent", sentence: "Nothing has moved.", beyond: { count: 0 } } };
  const read = async (surface: SurfaceName) => ({ surface, job_id: `test-${surface}`, data: surface in data ? data[surface] : defaults[surface] });
  return { openVault: async () => undefined, openSampleVault: async () => ({ title: "a frame title", detail: "a frame detail", leave: "a way out" }), readOverview: () => read("overview"), readDocuments: () => read("documents"), readReview: () => read("review"), readJobs: () => read("jobs"), readTrust: () => read("trust"), readActivity: () => read("activity"), assignActivityCategory: async () => ({ kind: "completed", message: "Category recorded.", state: null, reason: null }), replaceActivityTags: async () => ({ kind: "completed", message: "Tags recorded.", state: null, reason: null }), confirmActivityTransfer: async () => ({ kind: "completed", message: "Transfer confirmed.", state: null, reason: null }), rejectActivityTransfer: async () => ({ kind: "completed", message: "Suggestion rejected.", state: null, reason: null }), unlinkActivityTransfer: async () => ({ kind: "completed", message: "Transfer unlinked.", state: null, reason: null }), handshake: async () => ({ protocol: "2.0", transport: "json-lines", revision: "abcdef123456" }), readCapabilities: async () => ({ protocol: "2.0", capabilities: [], destinations: { overview: true, documents: true, review: true } }), askViva: async () => ({ kind: "completed", message: "Something.", state: { question: "what?", text: "Something.", answered: true, refusal: "", grade: "", grade_sentence: "", figures: [], spoken: { may_speak: true, withheld: "", parts: ["text"], text: "Something.", grade_sentence: "", citation_sentence: "", local_only: "Local only." } }, reason: null }), answerQuestion: async () => ({ kind: "completed", message: "Recorded.", state: null, reason: null }), declineQuestion: async () => ({ kind: "set_aside", message: "Set aside.", state: null, reason: null }), cancelJob: async () => ({ kind: "completed", message: "Stopped.", state: null, reason: null }), readLifecycle: async () => ({ state: "absent", revision: "abcdef123456", origin: "packaged", origin_sentence: "a sentence about how this copy got here", sentence: "a sentence about no channel", notes: [] }), readSettings: async () => ({ state: "ready", locale: "en-US", currency: "USD", adapter: "", model: "", base_url: "", key_set: false, can_send: false }), proposeSettings: async () => ({ kind: "proposal", message: "Here is what would change.", state: { kind: "presentation", changes: { locale: "en-IN" }, sends: false, digest: "abc123" }, reason: null }), confirmSettings: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }), rescanDocuments: async () => ({ kind: "completed", message: "Nothing changed.", state: { sentence: "Nothing changed.", changes: [], standing: [], link_count: 0 }, reason: null }), runMaintenance: async () => ({ kind: "completed", message: "Planned.", state: { dry_run: true, calls_spent: 0 }, reason: null }), writeDiagnostic: async () => ({ kind: "completed", message: "Written.", state: { file: "/tmp/d.json" }, reason: null }), exportVault: async () => ({ kind: "completed", message: "Copied.", state: null, reason: null }), restoreVault: async () => ({ kind: "completed", message: "Back.", state: null, reason: null }), uploadDocument: async () => ({ kind: "completed", message: "Saved.", state: null, reason: null }) };
}

describe("surface loading boundary", () => {

  it("reads the sample vault through the same loader as a private one", async () => {
    // Both vault kinds use the same reads; only the sample frame distinguishes
    // the sample source.
    const bridge = client();
    const sample = sampleSource(bridge, { title: "a frame title", detail: "a frame detail", leave: "a way out" });
    const snapshot = await sample.load();

    expect(sample.sample).toBe(true);
    expect(sample.frame?.title).toBe("a frame title");
    expect(snapshot.overview.state).toBe("ready");
    expect(privateSource(bridge).frame).toBeNull();
    expect(privateSource(bridge).sample).toBe(false);
  });

  it("exposes a typed private source seam", async () => {
    const source = privateSource(client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } }));
    const snapshot = await source.load();
    expect(source.id).toBe("bridge-client");
    expect(snapshot.review.state).toBe("ready");
  });

  it("exposes typed Activity outcomes without treating an action reply as a read", async () => {
    const source = privateSource({
      ...client(),
      assignActivityCategory: async () => ({ kind: "stale", message: "That movement is no longer in this read.", state: null, reason: "movement_missing" }),
      replaceActivityTags: async () => ({ kind: "refused", message: "Those tags are not available.", state: null, reason: "unknown_tag" }),
      confirmActivityTransfer: async () => ({ kind: "completed", message: "Transfer confirmed.", state: null, reason: null }),
      rejectActivityTransfer: async () => ({ kind: "stale", message: "That suggestion changed.", state: null, reason: "suggestion_changed" }),
      unlinkActivityTransfer: async () => ({ kind: "refused", message: "That link cannot be removed.", state: null, reason: "link_locked" }),
    });
    await expect(source.activityActions.assignCategory("movement:key", "housing")).resolves.toEqual({ state: "settled", outcome: { kind: "stale", message: "That movement is no longer in this read.", reason: "movement_missing" } });
    await expect(source.activityActions.replaceTags("movement:key", ["tax"])).resolves.toEqual({ state: "settled", outcome: { kind: "refused", message: "Those tags are not available.", reason: "unknown_tag" } });
    await expect(source.activityActions.confirmTransfer("movement:key", "movement:counterpart")).resolves.toEqual({ state: "settled", outcome: { kind: "completed", message: "Transfer confirmed.", reason: "" } });
    await expect(source.activityActions.rejectTransfer("movement:key")).resolves.toEqual({ state: "settled", outcome: { kind: "stale", message: "That suggestion changed.", reason: "suggestion_changed" } });
    await expect(source.activityActions.unlinkTransfer("movement:key", "movement:counterpart")).resolves.toEqual({ state: "settled", outcome: { kind: "refused", message: "That link cannot be removed.", reason: "link_locked" } });
  });

  it.each([
    ["proposal", { kind: "proposal", message: "Confirm this.", state: null, reason: null }],
    ["waiting", { kind: "waiting", message: "Waiting.", state: null, reason: null }],
    ["set aside", { kind: "set_aside", message: "Set aside.", state: null, reason: null }],
    ["document state", { kind: "completed", message: "Posted.", state: { terminal_state: "posted" }, reason: null }],
    ["extra field", { kind: "completed", message: "Recorded.", state: null, reason: null, job_id: "not-an-activity-receipt" }],
  ])("fails a non-Activity %s receipt closed as unreadable", async (_label, reply) => {
    const source = privateSource({ ...client(), assignActivityCategory: async () => reply });
    await expect(source.activityActions.assignCategory("movement:key", "housing")).resolves.toEqual({ state: "unreadable" });
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
    for (const source of [sampleSource(client(), { title: "t", detail: "d", leave: "l" }), privateSource(client())]) {
      expect(typeof source.reviewActions.answer).toBe("function");
      expect(typeof source.reviewActions.decline).toBe("function");
      expect(typeof source.reviewActions.reread).toBe("function");
    }
    await expect(actions.decline("q-1", "not_now")).resolves.toEqual({ state: "settled", outcome: { kind: "set_aside", message: "Set aside.", reason: "" } });
    await expect(actions.reread()).resolves.toEqual({ state: "ready", data: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } });
  });

  it("offers a fresh Trust read beside every Ask Viva action", async () => {
    let reads = 0;
    const base = client();
    const source = privateSource({
      ...base,
      readTrust: async () => ({
        surface: "trust", job_id: "trust-after-ask",
        data: { state: "ready", notes: [], outbound: { state: "ready", sentence: "One call left.", call_count: ++reads, phases: [], models: [], reported_models: [], model_sentence: "", span: null, cost: null, absences: [] } },
      }),
    });

    const reread = await source.conversationActions?.rereadTrust();

    expect(reads).toBe(1);
    expect(reread).toMatchObject({ state: "ready", data: { outbound: { callCount: 1, sentence: "One call left." } } });
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
