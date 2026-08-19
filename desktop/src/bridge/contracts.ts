// The protocol version this shell speaks. The sidecar refuses a frame whose
// major version is not its own, so this is the shell's half of one constant
// and moves only when the sidecar's does.
export const BRIDGE_PROTOCOL = "2.0";

export type SurfaceName = "overview" | "documents" | "review";
export type SurfaceParameters = Record<string, string | number>;
export type BridgeResponse<T> = { protocol: string; request_id: string; ok: boolean; result?: T; error?: { code: string; message: string } };
export type SurfaceReadResult = { surface: SurfaceName; job_id: string; data: unknown };
export type BridgeRequest = { requestId: string; operation: string; payload: Record<string, unknown> };
export type BridgeTransport = { request: <T>(frame: BridgeRequest) => Promise<BridgeResponse<T>>; pickVaultDirectory?: () => Promise<string | null> };
export type BridgeClient = {
  openVault: (vaultDirectory: string, passphrase: string) => Promise<void>;
  pickVaultDirectory?: () => Promise<string | null>;
  readOverview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
  readDocuments: () => Promise<SurfaceReadResult>;
  readReview: (parameters?: SurfaceParameters) => Promise<SurfaceReadResult>;
};

declare global { interface Window { orionVivaBridge?: BridgeTransport } }
