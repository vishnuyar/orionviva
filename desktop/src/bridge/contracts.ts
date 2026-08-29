// The protocol version this shell speaks. The sidecar refuses a frame whose
// major version is not its own, so this is the shell's half of one constant
// and moves only when the sidecar's does.
export const BRIDGE_PROTOCOL = "2.0";

export type SurfaceName = "overview" | "documents" | "conversation" | "jobs" | "trust" | "activity";
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
// The refusal codes whose message is a reviewed sentence about a folder, and
// the only ones whose text this shell repeats. Every other code carries machine
// text — a handler that raised puts its exception into that field, and an
// exception raised inside the engine can carry an account name or an amount, so
// vault text would reach a screen ungraded, uncited and through no read model.
// The words a shell draws the sample vault's frame with. They are the
// engine's, not this window's: the one sentence in this product that says
// nothing here is real is a shipped sentence, and a shell composing its own
// would put it out of the pack's reach.
export type SampleFrame = { title: string; detail: string; leave: string };
export const OPEN_REFUSALS: readonly string[] = ["vault_absent", "vault_not_a_directory", "vault_wrong_passphrase"];
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
  // `create` is the person's own word for making a vault where they said to.
  // It is never inferred: a path typed with a letter wrong would otherwise be
  // answered with a brand-new empty vault, which reads as their records having
  // vanished.
  openVault: (vaultDirectory: string, passphrase: string, create: boolean) => Promise<void>;
  // The sample vault, opened from one affordance. It carries no directory and
  // no passphrase: where it lives and what opens it are the engine's, so there
  // is nowhere here to point it at a folder somebody keeps their own records
  // in, and nowhere to learn what would open it.
  openSampleVault: () => Promise<SampleFrame | null>;
  pickVaultDirectory?: () => Promise<string | null>;
  readOverview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  readDocuments: () => Promise<SurfaceReadResult>;
  readConversation: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  // What the sidecar is doing, or has just done. It is a read like any other
  // and answers absent for a sidecar that has run no job — which is not the
  // same fact as a sidecar that cannot say.
  readJobs: () => Promise<SurfaceReadResult>;
  // The complete outbound record, and what nothing on this machine can
  // establish about it. Both are the read's; neither is composed here.
  readTrust: () => Promise<SurfaceReadResult>;
  // What moved, and which way. Direction is the read's: on a card a purchase
  // posts positive, and a shell reading the sign would have it backwards.
  readActivity: () => Promise<SurfaceReadResult>;
  setAsideFinding?: (findingId: string) => Promise<unknown>;
  assignActivityCategory: (movementKey: string, categoryId: string) => Promise<unknown>;
  replaceActivityTags: (movementKey: string, tagIds: readonly string[]) => Promise<unknown>;
  confirmActivityTransfer: (movementKey: string, counterpartKey: string) => Promise<unknown>;
  rejectActivityTransfer: (movementKey: string) => Promise<unknown>;
  unlinkActivityTransfer: (movementKey: string, counterpartKey: string) => Promise<unknown>;
  // Who answered and which build of it. Asked before a vault is open, because
  // the build that cannot open one is exactly the build somebody needs named.
  handshake: () => Promise<unknown>;
  // The reviewed registry and the destinations its reads reach.
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
  // What happens when a new version exists. Asked without a vault, because a
  // person meets that question before they have opened anything.
  readLifecycle: () => Promise<unknown>;
  readSettings: () => Promise<unknown>;
  proposeSettings: (kind: "presentation" | "model", fields: Record<string, string>) => Promise<unknown>;
  // The key travels in this one call and nowhere else — not in a proposal, not
  // in a reply, not in a digest.
  confirmSettings: (kind: "presentation" | "model", fields: Record<string, string>, digest: string, key: string) => Promise<unknown>;
  // Unattended work. `spend` is a person's own word, defaulting to false:
  // the agent reaches a model, and a request that did not say so has not asked
  // for that.
  runMaintenance: (spend: boolean) => Promise<unknown>;
  // A file somebody can hand over. Only a path crosses; what goes in the file
  // is decided on the other side, from a list of what may be said.
  writeDiagnostic: (file: string) => Promise<unknown>;
  exportVault: (archive: string) => Promise<unknown>;
  restoreVault: (archive: string, directory: string, passphrase: string) => Promise<unknown>;
  // An action answers with an outcome. It arrives unread, like a surface read:
  // the transport carries the frame and something above it decides what it says.
  // One question, and whether its text will be in front of the person. The
  // second is a fact about this screen rather than a preference: it is the
  // input to the rule that a figure is never spoken with nowhere to check it.
  askViva: (question: string, mirrored: boolean) => Promise<unknown>;
  answerQuestion: (questionId: string, said: string) => Promise<unknown>;
  confirmProposal?: (proposalId: string, said: string, asked: string) => Promise<unknown>;
  declineQuestion: (questionId: string, reason: DeclineReason) => Promise<unknown>;
};

declare global { interface Window { orionVivaBridge?: BridgeTransport } }
