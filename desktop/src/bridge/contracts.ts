// The protocol version this shell speaks. The sidecar refuses a frame whose
// major version is not its own, so this is the shell's half of one constant
// and moves only when the sidecar's does.
export const BRIDGE_PROTOCOL = "2.0";

export type SurfaceName = "overview" | "documents" | "review" | "jobs" | "trust";
export type SurfaceParameters = Record<string, string | number>;
export type BridgeResponse<T> = { protocol: string; request_id: string; ok: boolean; result?: T; error?: { code: string; message: string } };
export type SurfaceReadResult = { surface: SurfaceName; job_id: string; data: unknown };
// What the sidecar said about itself when the shell first spoke to it, and what
// it says about its own registry. Both arrive unread: the transport carries the
// frame and something above it decides what it says.
export type HandshakeResult = { protocol: string; transport: string; revision: string };
// The two reasons a question may be set aside. The set is the sidecar's and is
// closed on both sides; sending anything else is refused before the engine runs.
export type DeclineReason = "not_now" | "dont_know";
export type BridgeRequest = { requestId: string; operation: string; payload: Record<string, unknown> };
// What the sidecar answered when it would not serve the request. The frame
// arrived and was answered, so this is not a transport failure; only the code
// below carries the vault itself saying no.
export class BridgeRefusal extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "BridgeRefusal";
    this.code = code;
  }
}
// The one refusal code that means the sidecar read the request and would not
// take it. The others say the frame was never served at all — an operation this
// build does not answer, a protocol it cannot speak, or a handler that raised —
// and each of those carries machine text where a sentence would be.
export const REQUEST_REFUSED = "invalid_request";
// The sidecar said it accepted the request and sent nothing to read. A handler
// ran and may have written, so this is never told as a request that never
// arrived.
export class BridgeUnreadable extends Error {
  constructor(operation: string) {
    super(operation);
    this.name = "BridgeUnreadable";
  }
}
// One progress frame, as the host delivers it. The shell reads the frame and
// nothing else about the transport: what a job is doing is the sidecar's to
// say, and a shell that computed a step from a reply would be a second author
// of the same fact.
export type JobProgressFrame = { protocol: string; request_id: string; event: string; result: unknown };
export type JobProgressListener = (frame: JobProgressFrame) => void;
// The window event one progress frame arrives on. This is the page's half of
// one constant and moves only when the native host's does.
export const JOB_PROGRESS_EVENT = "orionviva://job-progress";
// A dropped file is handed over as a path and nothing else. The bytes are
// opened by the sidecar, so nothing about the file's contents ever enters this
// window.
export type DroppedPathsListener = (paths: readonly string[]) => void;
export type BridgeTransport = {
  request: <T>(frame: BridgeRequest) => Promise<BridgeResponse<T>>;
  pickVaultDirectory?: () => Promise<string | null>;
  pickDocumentPaths?: () => Promise<readonly string[]>;
  subscribeToDroppedPaths?: (listen: DroppedPathsListener) => Promise<() => void>;
  subscribeToJobProgress?: (listen: JobProgressListener) => Promise<() => void>;
};
export type BridgeClient = {
  openVault: (vaultDirectory: string, passphrase: string) => Promise<void>;
  pickVaultDirectory?: () => Promise<string | null>;
  readOverview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  readDocuments: () => Promise<SurfaceReadResult>;
  readReview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  // What the sidecar is doing, or has just done. It is a read like any other
  // and answers absent for a sidecar that has run no job — which is not the
  // same fact as a sidecar that cannot say.
  readJobs: () => Promise<SurfaceReadResult>;
  // The complete outbound record, and what nothing on this machine can
  // establish about it. Both are the read's; neither is composed here.
  readTrust: () => Promise<SurfaceReadResult>;
  // Who answered and which build of it. Asked before a vault is open, because
  // the build that cannot open one is exactly the build somebody needs named.
  handshake: () => Promise<unknown>;
  // The reviewed registry, and which destinations a read reaches. The shell
  // used to carry a hand-written vocabulary in place of this.
  readCapabilities: () => Promise<unknown>;
  // One path per call. Several files are several frames, one after another,
  // because the sidecar answers one request before it reads the next.
  uploadDocument: (path: string) => Promise<unknown>;
  pickDocumentPaths?: () => Promise<readonly string[]>;
  subscribeToDroppedPaths?: (listen: DroppedPathsListener) => Promise<() => void>;
  subscribeToJobProgress?: (listen: JobProgressListener) => Promise<() => void>;
  // Stop one job, named by the identity the sidecar minted for it. A job is
  // stopped, never a document: what the vault holds when a job stops is
  // whatever its last finished step left there.
  cancelJob: (jobId: string) => Promise<unknown>;
  // A whole vault out, and a whole vault back. Only paths cross: the sidecar
  // opens every file itself, and nothing about a vault's contents ever enters
  // this window. The passphrase crosses on the way back for the same reason it
  // crosses to open a vault — the copy is verified by being opened, and only
  // the engine can open it.
  // One pass back over what this vault already holds. It carries nothing,
  // because a pass goes over the whole vault and a field naming part of it
  // would be this side asserting a scope the sweep does not have.
  rescanDocuments: () => Promise<unknown>;
  // What this machine has been told to do, and the yes that tells it. Asked
  // without a vault: a person with none yet still has to be able to say how
  // figures are written and whether a model may be reached at all.
  readSettings: () => Promise<unknown>;
  proposeSettings: (kind: "presentation" | "model", fields: Record<string, string>) => Promise<unknown>;
  // The key travels in this one call and nowhere else — not in a proposal, not
  // in a reply, not in a digest.
  confirmSettings: (kind: "presentation" | "model", fields: Record<string, string>, digest: string, key: string) => Promise<unknown>;
  exportVault: (archive: string) => Promise<unknown>;
  restoreVault: (archive: string, directory: string, passphrase: string) => Promise<unknown>;
  // An action answers with an outcome. It arrives unread, like a surface read:
  // the transport carries the frame and something above it decides what it says.
  answerQuestion: (questionId: string, said: string) => Promise<unknown>;
  declineQuestion: (questionId: string, reason: DeclineReason) => Promise<unknown>;
};

declare global { interface Window { orionVivaBridge?: BridgeTransport } }
