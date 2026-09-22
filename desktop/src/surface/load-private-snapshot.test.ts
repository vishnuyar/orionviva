import { describe, expect, it, vi } from "vitest";
import { BridgeTimeout } from "../bridge/contracts";
import type { BridgeClient, JobProgressListener, SurfaceName } from "../bridge/contracts";
import { loadCoherentSnapshot, loadPrivateDestination, loadPrivateSnapshot, loadPrioritySnapshot, loadSecondarySnapshot, loadStartupSecondarySnapshot, privateActivityActions, privateDocumentActions, privateJobStream, privateSettingsActions, privateTransferActions, privateTrustActions } from "./load-private-snapshot";
import { privateSource } from "./sources";

const read = (surface: SurfaceName, data: unknown) => Promise.resolve({ surface, job_id: `job-${surface}`, data });

it("keeps read correlation out of the job stream while retaining named job progress", async () => {
  let emit: JobProgressListener = () => { throw new Error("not subscribed"); };
  const observed: string[] = [];
  const source = Object.assign(client(), {
    subscribeToJobProgress: async (listener: JobProgressListener) => { emit = listener; return () => undefined; },
  });
  const stop = await privateJobStream(source)!((job) => { observed.push(`${job.operation}:${job.state}`); });
  for (const operation of ["", "   ", "viva.documents.upload"]) {
    for (const status of ["started", "progress", "completed", "failed", "cancelled"]) {
      emit({ protocol: "2.1", request_id: "synthetic", event: "progress",
        result: { job_id: "synthetic-job", operation, status, completed: status === "completed" ? 1 : 0, total: 1, attempt: 1 } });
    }
  }
  expect(observed).toEqual(["running", "running", "completed", "failed", "cancelled"].map((state) => `viva.documents.upload:${state}`));
  stop();
});

it("waits for asynchronous publication before reading a coherent document snapshot", async () => {
  vi.useFakeTimers();
  try {
    let priorities = 0;
    let documents = 0;
    const source = Object.assign(client(), {
      readOverviewAccounts: () => {
        priorities += 1;
        return read("overview_accounts", priorities === 1
          ? { state: "degraded", freshness: "unavailable", lifecycle: "rebuilding", revision: "", overview: null, accounts: null, error: "read_store_unavailable" }
          : { state: "ready", freshness: "current", lifecycle: "caught_up", revision: "g-published", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" });
      },
      readDocuments: () => { documents += 1; return read("documents", { documents: [{ id: "synthetic", filename: "synthetic.txt" }] }); },
    });
    const pending = loadCoherentSnapshot(source);
    await vi.advanceTimersByTimeAsync(0);
    expect(documents).toBe(0);
    await vi.advanceTimersByTimeAsync(250);
    const result = await pending;
    expect(result.revision).toBe("g-published");
    expect(result.snapshot.documents).toMatchObject({ data: { documents: [{ name: "synthetic.txt" }] } });
    expect(priorities).toBe(3);
    expect(documents).toBe(1);
  } finally { vi.useRealTimers(); }
});

it("requests catch-up once and only polls reads while a job's publication is stale", async () => {
  vi.useFakeTimers();
  try {
    const refreshes: boolean[] = [];
    const source = Object.assign(client(), {
      readOverviewAccounts: (refresh = false) => {
        refreshes.push(refresh);
        const ready = refreshes.length === 3;
        return read("overview_accounts", { state: ready ? "ready" : "stale", freshness: ready ? "current" : "stale", lifecycle: ready ? "caught_up" : "stale", revision: ready ? "g-new" : "g-old", overview: { accounts: [] }, accounts: { accounts: [] }, error: ready ? "" : "read_store_stale" });
      },
    });
    const pending = loadPrioritySnapshot(source, undefined, true);
    await vi.advanceTimersByTimeAsync(500);
    expect((await pending).revision).toBe("g-new");
    expect(refreshes).toEqual([true, false, false]);
  } finally { vi.useRealTimers(); }
});

it("requests catch-up before a post-action coherent reread", async () => {
  const refreshes: boolean[] = [];
  const source = Object.assign(client(), {
    readOverviewAccounts: (refresh = false) => {
      refreshes.push(refresh);
      return read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "caught_up", revision: "g-after-action", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" });
    },
  });
  await loadCoherentSnapshot(source, undefined, undefined, undefined, undefined, true);
  expect(refreshes[0]).toBe(true);
});

it("bounds publication polling and leaves permanently stale or degraded reads unready", async () => {
  vi.useFakeTimers();
  try {
    let calls = 0;
    let lifecycle = "stale";
    const source = Object.assign(client(), {
      readOverviewAccounts: () => {
        calls += 1;
        return read("overview_accounts", lifecycle === "stale"
          ? { state: "stale", freshness: "stale", lifecycle, revision: "g-old", overview: { accounts: [] }, accounts: { accounts: [] }, error: "read_store_stale" }
          : { state: "degraded", freshness: "unavailable", lifecycle, revision: "", overview: null, accounts: null, error: "read_store_unavailable" });
      },
    });
    const pending = loadCoherentSnapshot(source).catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await pending).toBe("aggregate_revision_unavailable");
    expect(calls).toBe(241);
    lifecycle = "degraded";
    calls = 0;
    expect((await loadPrioritySnapshot(source, undefined, true)).freshness).toBe("unavailable");
    expect(calls).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
  } finally { vi.useRealTimers(); }
});

function client(conversation: unknown = { state: "ready", turns: [], questions: [], total: 0 }, planRead: unknown = { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] }): BridgeClient {
  return {
    openVault: async () => undefined,
    openSampleVault: async () => null,
    readOverview: () => read("overview", { accounts: [] }),
    readOverviewAccounts: () => read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-test", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }),
    readDocuments: () => read("documents", { documents: [] }),
    readConversation: () => read("conversation", conversation),
    readJobs: () => read("jobs", { state: "absent", jobs: [], running: [] }),
    readTrust: () => read("trust", { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } }),
    readActivity: () => read("activity", { state: "ready", sentence: "", items: [], beyond: { count: 0 }, vocabularies: { categories: { items: [], complete: true, limit: 40 }, tags: { items: [], complete: true, limit: 40, max_selected: 40, max_label_length: 80 } } }),
    readAccountLedger: () => read("account_ledger", {}),
    readPlans: () => read("plans", planRead),
    draftPlan: async () => ({ kind: "ready", message: "Draft ready.", draft: {} }),
    proposePlan: async () => ({ kind: "proposed", message: "Held.", state: null, reason: null }),
    confirmPlan: async () => ({ kind: "completed", message: "Recorded.", state: null, reason: null }),
    declinePlan: async () => ({ kind: "set_aside", message: "Set aside.", state: null, reason: null }),
    handshake: async () => ({ protocol: "2.0", transport: "json-lines", revision: "test" }),
    readCapabilities: async () => ({ protocol: "2.0", capabilities: [], destinations: { overview: true, documents: true, viva: true } }),
    uploadDocument: async () => ({ kind: "completed", message: "Saved.", state: null, reason: null }),
    cancelJob: async () => ({ kind: "completed", message: "Stopped.", state: null, reason: null }),
    readLifecycle: async () => ({ state: "absent", revision: "test", origin_sentence: "test", sentence: "test", notes: [] }),
    readSettings: async () => ({ state: "ready", locale: "en-US", currency: "USD", adapter: "", model: "", base_url: "", key_set: false, can_send: false }),
    proposeSettings: async () => ({ kind: "refused", message: "No.", reason: "test" }),
    confirmSettings: async () => ({ kind: "refused", message: "No.", reason: "test" }),
    runMaintenance: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    writeDiagnostic: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    exportVault: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    restoreVault: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    rescanDocuments: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    askViva: async () => ({ kind: "refused", message: "No model.", state: null, reason: "no_model_named" }),
    answerQuestion: async () => ({ kind: "completed", message: "Recorded.", state: null, reason: null }),
    confirmProposal: async () => ({ kind: "completed", message: "Recorded.", state: null, reason: null }),
    declineQuestion: async () => ({ kind: "set_aside", message: "Set aside.", state: null, reason: null }),
    assignActivityCategory: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    assignActivityClassification: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    assignActivityMeaning: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    replaceActivityTags: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    addActivityTags: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    removeActivityTags: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    confirmActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    rejectActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    unlinkActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
  };
}

describe("private conversation surface", () => {
  it("settles the priority bundle while a secondary destination is blocked", async () => {
    const blocked = Object.assign(client(), {
      readOverviewAccounts: () => read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-one", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }),
      readDocuments: () => new Promise<Awaited<ReturnType<BridgeClient["readDocuments"]>>>(() => undefined),
    });
    const secondary = loadSecondarySnapshot(blocked);
    const priority = await loadPrioritySnapshot(blocked);
    expect(priority.snapshot.overview.state).toBe("ready");
    expect(priority.revision).toBe("g-one");
    await expect(Promise.race([secondary.then(() => "settled"), Promise.resolve("blocked")])).resolves.toBe("blocked");
  });

  it("rejects a mixed Overview and Accounts bundle instead of combining revisions", async () => {
    let legacyReads = 0;
    const mixed = Object.assign(client(), {
      readOverview: () => { legacyReads += 1; return read("overview", { accounts: [] }); },
      readOverviewAccounts: () => read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-one", overview: { accounts: [] }, accounts: { accounts: [{ account: "other" }] }, error: "" }),
    });
    const priority = await loadPrioritySnapshot(mixed);
    expect(priority).toMatchObject({ revision: "", freshness: "unavailable", lifecycle: "degraded", retryable: true });
    expect(priority.snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(legacyReads).toBe(0);
  });

  it("does not enqueue legacy or raw-backed reads during routine startup", async () => {
    const touched: string[] = [];
    const guarded = Object.assign(client(), ...["readDocuments", "readConversation", "readReview", "readTrust", "readActivity", "readPlans"].map((name) => ({
      [name]: async () => { touched.push(name); throw new Error("startup read"); },
    })));
    const snapshot = await loadStartupSecondarySnapshot(guarded);
    expect(touched).toEqual([]);
    expect(snapshot.documents).toEqual({ state: "absent", reason: "not_asked" });
    expect(snapshot.conversation).toEqual({ state: "absent", reason: "not_asked" });
    expect(snapshot.review).toEqual({ state: "absent", reason: "not_asked" });
    expect(snapshot.activity).toEqual({ state: "absent", reason: "not_asked" });
  });

  it("retains a stale revision as data and exposes one retry state", async () => {
    const stale = Object.assign(client(), {
      readOverviewAccounts: () => read("overview_accounts", { state: "stale", freshness: "stale", lifecycle: "stale", revision: "g-prior", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }),
    });
    const priority = await loadPrioritySnapshot(stale);
    expect(priority).toMatchObject({ revision: "g-prior", freshness: "stale", retryable: true });
    expect(priority.snapshot.overview.state).toBe("ready");
  });

  it.each(["partial", "needs_input"] as const)("preserves a %s priority Overview outcome", async (state) => {
    const issue = { code: "incomplete_figure", message: "A named item needs attention." };
    const focused = Object.assign(client(), {
      readOverviewAccounts: () => read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-one", overview: { state, issues: [issue], accounts: [] }, accounts: { state, issues: [issue], accounts: [] }, error: "" }),
    });
    const priority = await loadPrioritySnapshot(focused);
    expect(priority.snapshot.overview).toMatchObject({ state, issues: [issue] });
    expect(priority.revision).toBe("g-one");
  });

  it("refuses an aggregate when a secondary read crosses an authenticated generation", async () => {
    let revision = "g-one";
    const guarded = Object.assign(client(), {
      readOverviewAccounts: () => read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision, overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }),
      readDocuments: () => { revision = "g-two"; return read("documents", { documents: [] }); },
    });
    await expect(privateSource(guarded).load()).rejects.toThrow("aggregate_revision_mismatch");
  });

  it("uses the paired priority route for the aggregate reread", async () => {
    const asked: string[] = [];
    const aggregate = Object.assign(client(), {
      readOverview: () => { asked.push("overview"); return read("overview", { accounts: [] }); },
      readOverviewAccounts: () => { asked.push("priority"); return read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-one", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }); },
    });
    const snapshot = await loadPrivateSnapshot(aggregate);
    expect(snapshot.overview.state).toBe("ready");
    expect(asked).toEqual(["priority", "priority"]);
  });

  it("makes eight bounded surface reads and returns the confirmed revision", async () => {
    const asked: string[] = [];
    const base = client();
    const observed = Object.assign({}, base, {
      readOverview: () => { throw new Error("bare overview route"); },
      readOverviewAccounts: () => { asked.push("overview_accounts"); return base.readOverviewAccounts(); },
      readDocuments: () => { asked.push("documents"); return read("documents", { documents: [] }); },
      readConversation: () => { asked.push("conversation"); return read("conversation", { turns: [], questions: [], total: 0 }); },
      readReview: () => { asked.push("review"); return read("review", { state: "ready", groups: [] }); },
      readTrust: () => { asked.push("trust"); return read("trust", { state: "ready", notes: [] }); },
      readActivity: () => { asked.push("activity"); return read("activity", { state: "ready", items: [] }); },
      readPlans: () => { asked.push("plans"); return read("plans", { state: "ready", goals: [], proposals: [] }); },
    });
    const result = await loadCoherentSnapshot(observed);
    expect(result.revision).toBe("g-test");
    expect(asked).toEqual(["overview_accounts", "documents", "conversation", "review", "trust", "activity", "plans", "overview_accounts"]);
  });

  it("reuses a supplied post-job start instead of requesting a third priority read", async () => {
    let priorities = 0;
    const observed = Object.assign(client(), {
      readOverviewAccounts: () => { priorities += 1; return read("overview_accounts", { state: "ready", freshness: "current", lifecycle: "equal", revision: "g-job", overview: { accounts: [] }, accounts: { accounts: [] }, error: "" }); },
    });
    const start = await loadPrioritySnapshot(observed, undefined, true);
    const result = await loadCoherentSnapshot(observed, undefined, undefined, undefined, start);
    expect(result.revision).toBe("g-job");
    expect(priorities).toBe(2);
  });

  it("settles priority and active destination while an unrelated aggregate secondary is blocked", async () => {
    let releaseDocuments: ((value: Awaited<ReturnType<BridgeClient["readDocuments"]>>) => void) | undefined;
    let aggregateSettled = false;
    const blocked = Object.assign(client(), {
      readDocuments: () => new Promise<Awaited<ReturnType<BridgeClient["readDocuments"]>>>((resolve) => { releaseDocuments = resolve; }),
    });
    const aggregate = loadPrivateSnapshot(blocked).finally(() => { aggregateSettled = true; });
    const priority = await loadPrioritySnapshot(blocked);
    const plans = await loadPrivateDestination(blocked, "plans");
    expect(priority.snapshot.overview.state).toBe("ready");
    expect(plans.plans?.state).toBe("ready");
    expect(aggregateSettled).toBe(false);
    releaseDocuments?.({ surface: "documents", job_id: "blocked-documents", data: { documents: [] } });
    expect((await aggregate).documents.state).toBe("ready");
  });

  it("loads durable turns and derives the overview question summary from the same read", async () => {
    const snapshot = await loadPrivateSnapshot(client({ state: "ready", turns: [{ id: "t-1", kind: "ask", occurred_at: "2026-08-29", prompt: "What changed?", said: "", question_id: "", outcome: "refused", message: "No model.", reason: "no_model_named", answer: {}, proposal: null }], questions: [{ id: "q-1", text: "What was this?", why: "Unknown." }], total: 1 }));
    expect(snapshot.conversation.state).toBe("ready");
    if (snapshot.conversation.state === "ready") expect(snapshot.conversation.data.turns[0].id).toBe("t-1");
    if (snapshot.conversation.state === "ready") expect(snapshot.conversation.data.questions.queue[0].id).toBe("q-1");
  });

  it("exposes ask and correction verbs through one conversation action object", () => {
    const actions = privateSource(client()).conversationActions;
    expect(actions).not.toBeNull();
    expect(typeof actions?.ask).toBe("function");
    expect(typeof actions?.answer).toBe("function");
    expect(typeof actions?.confirm).toBe("function");
    expect(typeof actions?.decline).toBe("function");
    expect(typeof actions?.reread).toBe("function");
  });

  it("exposes account ledger reads separately for navigation-time loading", () => {
    const source = privateSource(client());
    expect(typeof source.accountLedgerReader?.read).toBe("function");
  });

  it("fails the conversation read closed when a turn is malformed", async () => {
    const snapshot = await loadPrivateSnapshot(client({ state: "ready", turns: [{ kind: "ask" }], questions: [], total: 0 }));
    expect(snapshot.conversation).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("keeps a partial Plans read partial at the panel boundary", async () => {
    const snapshot = await loadPrivateSnapshot(client(undefined, { state: "partial", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] }));
    expect(snapshot.plans?.state).toBe("partial");
  });

  it("preserves typed timeouts through every action adapter", async () => {
    const timeout = new BridgeTimeout("test.write", true);
    const rejected = Object.assign(client(), {
      uploadDocument: async () => { throw timeout; },
      rescanDocuments: async () => { throw timeout; },
      cancelJob: async () => { throw timeout; },
      assignActivityCategory: async () => { throw timeout; },
      runMaintenance: async () => { throw timeout; },
      writeDiagnostic: async () => { throw timeout; },
      proposeSettings: async () => { throw timeout; },
      confirmSettings: async () => { throw timeout; },
      exportVault: async () => { throw timeout; },
      restoreVault: async () => { throw timeout; },
    });
    const documents = privateDocumentActions(rejected);
    const activity = privateActivityActions(rejected);
    const trust = privateTrustActions(rejected);
    const settings = privateSettingsActions(rejected);
    const transfer = privateTransferActions(rejected);
    const calls = [documents.upload("/statement.pdf"), documents.rescan(), documents.cancel("job"), activity.assignCategory("movement", "category"), trust.run(false), trust.diagnose("/diagnostic.json"), settings.propose("presentation", {}), settings.confirm("presentation", {}, "digest", ""), transfer.export("/copy.viva"), transfer.restore("/copy.viva", "/restored", "secret")];
    await Promise.all(calls.map((call) => expect(call).rejects.toBe(timeout)));
  });

  it("still maps ordinary rejected action calls to terminal unanswered results", async () => {
    const rejected = Object.assign(client(), { uploadDocument: async () => { throw new Error("offline"); } });
    await expect(privateDocumentActions(rejected).upload("/statement.pdf")).resolves.toEqual({ state: "unanswered" });
  });
});
