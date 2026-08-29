import { describe, expect, it } from "vitest";
import type { BridgeClient, SurfaceName } from "../bridge/contracts";
import { loadPrivateSnapshot } from "./load-private-snapshot";
import { privateSource } from "./sources";

const read = (surface: SurfaceName, data: unknown) => Promise.resolve({ surface, job_id: `job-${surface}`, data });
function client(conversation: unknown = { state: "ready", turns: [], questions: [], total: 0 }, planRead: unknown = { state: "ready", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] }): BridgeClient {
  return {
    openVault: async () => undefined,
    openSampleVault: async () => null,
    readOverview: () => read("overview", { accounts: [] }),
    readDocuments: () => read("documents", { documents: [] }),
    readConversation: () => read("conversation", conversation),
    readJobs: () => read("jobs", { state: "absent", jobs: [], running: [] }),
    readTrust: () => read("trust", { state: "ready", notes: [], outbound: { state: "ready", sentence: "Nothing has left.", call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [] } }),
    readActivity: () => read("activity", { state: "ready", sentence: "", items: [], beyond: { count: 0 }, vocabularies: { categories: { items: [], complete: true, limit: 40 }, tags: { items: [], complete: true, limit: 40, max_selected: 40, max_label_length: 80 } } }),
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
    replaceActivityTags: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    confirmActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    rejectActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
    unlinkActivityTransfer: async () => ({ kind: "completed", message: "Done.", state: null, reason: null }),
  };
}

describe("private conversation surface", () => {
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

  it("fails the conversation read closed when a turn is malformed", async () => {
    const snapshot = await loadPrivateSnapshot(client({ state: "ready", turns: [{ kind: "ask" }], questions: [], total: 0 }));
    expect(snapshot.conversation).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("keeps a partial Plans read partial at the panel boundary", async () => {
    const snapshot = await loadPrivateSnapshot(client(undefined, { state: "partial", invitation: { title: "Make a plan", body: "Start when you are ready." }, goals: [], proposals: [] }));
    expect(snapshot.plans?.state).toBe("partial");
  });
});
