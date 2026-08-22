import { BridgeRefusal, BridgeUnreadable } from "./contracts";
import type { BridgeClient, BridgeTransport, DeclineReason, SurfaceName, SurfaceParameters, SurfaceReadResult } from "./contracts";

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
    ...(transport.pickVaultDirectory ? { pickVaultDirectory: transport.pickVaultDirectory } : {}),
    ...(transport.pickDocumentPaths ? { pickDocumentPaths: transport.pickDocumentPaths } : {}),
    ...(transport.subscribeToDroppedPaths ? { subscribeToDroppedPaths: transport.subscribeToDroppedPaths } : {}),
    ...(transport.subscribeToJobProgress ? { subscribeToJobProgress: transport.subscribeToJobProgress } : {}),
    readOverview: (parameters) => read("overview", parameters),
    readDocuments: () => read("documents"),
    readReview: (parameters) => read("review", parameters),
    readJobs: () => read("jobs"),
    readTrust: () => read("trust"),
    readActivity: () => read("activity"),
    handshake: () => request("bridge.handshake", {}),
    readCapabilities: () => request("viva.surface.capabilities", {}),
    cancelJob: (jobId: string) => request("viva.documents.cancel", { job_id: jobId }),
    rescanDocuments: () => request("viva.documents.rescan", {}),
    readSettings: () => request("viva.settings.read", {}),
    proposeSettings: (kind, fields) => request("viva.settings.propose", { kind, ...fields }),
    confirmSettings: (kind, fields, digest, key) => request("viva.settings.confirm", { kind, ...fields, digest, ...(key ? { key } : {}) }),
    exportVault: (archive: string) => request("viva.vault.export", { archive }),
    restoreVault: (archive: string, directory: string, passphrase: string) => request("viva.vault.restore", { archive, directory, passphrase }),
    askViva: (question: string, mirrored: boolean) => request("viva.conversation.ask", { question, mirrored }),
    answerQuestion: (questionId: string, said: string) => request("viva.review.answer", { question_id: questionId, said }),
    declineQuestion: (questionId, reason: DeclineReason) => request("viva.review.decline", { question_id: questionId, reason }),
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
