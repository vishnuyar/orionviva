import type { BridgeClient, BridgeTransport, SurfaceName, SurfaceParameters, SurfaceReadResult } from "./contracts";

export function createHostBridgeClient(transport: BridgeTransport): BridgeClient {
  let requestNumber = 0;
  async function request<T>(operation: string, payload: Record<string, unknown>): Promise<T> {
    const requestId = `desktop-${++requestNumber}`;
    const response = await transport.request<T>({ requestId, operation, payload });
    if (!response.ok || response.result === undefined) throw new Error(response.error?.message ?? "desktop bridge request failed");
    return response.result;
  }
  function read(surface: SurfaceName, parameters: SurfaceParameters = {}): Promise<SurfaceReadResult> {
    return request("viva.surface.read", { surface, parameters, job_id: `desktop-${surface}-${requestNumber + 1}` });
  }
  return {
    openVault: async (vaultDirectory, passphrase) => { await request("bridge.open_vault", { vault_directory: vaultDirectory, passphrase }); },
    ...(transport.pickVaultDirectory ? { pickVaultDirectory: transport.pickVaultDirectory } : {}),
    readOverview: (parameters) => read("overview", parameters),
    readDocuments: () => read("documents"),
    readReview: (parameters) => read("review", parameters),
  };
}

export function createDetectedBridgeClient(): BridgeClient | null {
  return typeof window !== "undefined" && window.orionVivaBridge ? createHostBridgeClient(window.orionVivaBridge) : null;
}

export function hasHostBridge(): boolean {
  return typeof window !== "undefined" && Boolean(window.orionVivaBridge);
}
