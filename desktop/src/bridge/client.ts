import { BridgeRefusal, BridgeUnreadable } from "./contracts";
import type { BridgeClient, BridgeTransport, DeclineReason, SampleFrame, SurfaceName, SurfaceParameters, SurfaceReadResult } from "./contracts";

// The frame's words, read off the reply that opened the sample vault. Every
// field must be there and be a sentence: a frame drawn with a blank line in it
// would be a frame that says less than it promises, and a shell filling that
// blank in would be writing the sentence the pack ships. A reply this cannot
// read gets no frame, and the caller treats a missing frame as a refusal.
function sampleFrame(result: unknown): SampleFrame | null {
  if (typeof result !== "object" || result === null) return null;
  const frame = (result as { frame?: unknown }).frame;
  if (typeof frame !== "object" || frame === null) return null;
  const said = frame as { title?: unknown; detail?: unknown; leave?: unknown };
  if (typeof said.title !== "string" || !said.title.trim()) return null;
  if (typeof said.detail !== "string" || !said.detail.trim()) return null;
  if (typeof said.leave !== "string" || !said.leave.trim()) return null;
  return { title: said.title, detail: said.detail, leave: said.leave };
}

export function createHostBridgeClient(transport: BridgeTransport): BridgeClient {
  let requestNumber = 0;
  async function request<T>(operation: string, payload: Record<string, unknown>): Promise<T> {
    const requestId = `desktop-${++requestNumber}`;
    const response = await transport.request<T>({ requestId, operation, payload });
    // Three unlike failures, kept apart: a sidecar that answered and said no,
    // a sidecar that answered and sent nothing to read, and a sidecar that
    // could not be reached. Only the last is a rejected transport call, and
    // only it is a request that never arrived.
    if (!response.ok) throw new BridgeRefusal(response.error?.code ?? "", response.error?.message ?? "");
    if (response.result === undefined) throw new BridgeUnreadable(operation);
    return response.result;
  }
  function read(surface: SurfaceName, parameters: SurfaceParameters = {}): Promise<SurfaceReadResult> {
    return request("viva.surface.read", { surface, parameters, job_id: `desktop-${surface}-${requestNumber + 1}` });
  }
  return {
    openVault: async (vaultDirectory, passphrase, create) => { await request("bridge.open_vault", { vault_directory: vaultDirectory, passphrase, create }); },
    openSampleVault: async () => sampleFrame(await request<unknown>("bridge.open_demo_vault", {})),
    ...(transport.pickVaultDirectory ? { pickVaultDirectory: transport.pickVaultDirectory } : {}),
    ...(transport.pickDocumentPaths ? { pickDocumentPaths: transport.pickDocumentPaths } : {}),
    ...(transport.subscribeToDroppedPaths ? { subscribeToDroppedPaths: transport.subscribeToDroppedPaths } : {}),
    ...(transport.subscribeToJobProgress ? { subscribeToJobProgress: transport.subscribeToJobProgress } : {}),
    readOverview: (parameters) => read("overview", parameters),
    readDocuments: () => read("documents"),
    readConversation: (parameters) => read("conversation", parameters),
    readJobs: () => read("jobs"),
    readTrust: () => read("trust"),
    readActivity: () => read("activity"),
    readPlans: () => read("plans"),
    draftPlan: (payload) => request("viva.plans.draft", payload),
    proposePlan: (payload) => request("viva.plans.propose", payload),
    confirmPlan: (proposalId) => request("viva.plans.confirm", { proposal_id: proposalId }),
    declinePlan: (proposalId) => request("viva.plans.decline", { proposal_id: proposalId }),
    setAsideFinding: (findingId: string) => request("viva.overview.set_aside_finding", { finding_id: findingId }),
    assignActivityCategory: (movementKey: string, categoryId: string) => request("viva.activity.assign_category", { movement_key: movementKey, category_id: categoryId }),
    assignActivityMeaning: (movementKey: string, meaning: string, counterparty: string) => request("viva.activity.assign_meaning", { movement_key: movementKey, meaning, counterparty }),
    replaceActivityTags: (movementKey: string, tagIds: readonly string[]) => request("viva.activity.replace_tags", { movement_key: movementKey, tag_ids: [...tagIds] }),
    confirmActivityTransfer: (movementKey: string, counterpartKey: string) => request("viva.activity.confirm_transfer", { movement_key: movementKey, counterpart_key: counterpartKey }),
    rejectActivityTransfer: (movementKey: string) => request("viva.activity.reject_transfer", { movement_key: movementKey }),
    unlinkActivityTransfer: (movementKey: string, counterpartKey: string) => request("viva.activity.unlink_transfer", { movement_key: movementKey, counterpart_key: counterpartKey }),
    handshake: () => request("bridge.handshake", {}),
    readCapabilities: () => request("viva.surface.capabilities", {}),
    cancelJob: (jobId: string) => request("viva.documents.cancel", { job_id: jobId }),
    rescanDocuments: () => request("viva.documents.rescan", {}),
    readLifecycle: () => request("viva.lifecycle.read", {}),
    readSettings: () => request("viva.settings.read", {}),
    proposeSettings: (kind, fields) => request("viva.settings.propose", { kind, ...fields }),
    confirmSettings: (kind, fields, digest, key) => request("viva.settings.confirm", { kind, ...fields, digest, ...(key ? { key } : {}) }),
    runMaintenance: (spend: boolean) => request("viva.maintenance.run", { spend }),
    writeDiagnostic: (file: string) => request("viva.maintenance.diagnose", { file }),
    exportVault: (archive: string) => request("viva.vault.export", { archive }),
    restoreVault: (archive: string, directory: string, passphrase: string) => request("viva.vault.restore", { archive, directory, passphrase }),
    askViva: (question: string, mirrored: boolean, planRequest = false) => request("viva.conversation.ask", { question, mirrored, plan_request: planRequest }),
    answerQuestion: (questionId: string, said: string) => request("viva.conversation.answer", { question_id: questionId, said }),
    confirmProposal: (proposalId: string, said: string, asked: string) => request("viva.conversation.confirm", { proposal_id: proposalId, said, asked }),
    declineQuestion: (questionId, reason: DeclineReason) => request("viva.conversation.decline", { question_id: questionId, reason }),
    // The payload is the path and nothing else. A job identity is the
    // sidecar's to mint, so this side never sends one and the field set alone
    // refuses one that was sent.
    uploadDocument: (path: string) => request("viva.documents.upload", { path }),
  };
}

export function createDetectedBridgeClient(): BridgeClient | null {
  return typeof window !== "undefined" && window.orionVivaBridge ? createHostBridgeClient(window.orionVivaBridge) : null;
}

export function hasHostBridge(): boolean {
  return typeof window !== "undefined" && Boolean(window.orionVivaBridge);
}
