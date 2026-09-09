import { BRIDGE_PROTOCOL } from "./contracts";
import type { BridgeRequest, BridgeResponse, BridgeTransport } from "./contracts";

export function createLoopbackTransport(location: Pick<Location, "hostname" | "hash">, fetchRequest: typeof fetch): BridgeTransport | null {
  if (location.hostname !== "127.0.0.1") return null;
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  if (!token) return null;
  return {
    request: async <T>(frame: BridgeRequest): Promise<BridgeResponse<T>> => {
      const response = await fetchRequest("/__orionviva/bridge", {
        method: "POST",
        headers: {
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          protocol: BRIDGE_PROTOCOL,
          request_id: frame.requestId,
          operation: frame.operation,
          payload: frame.payload,
        }),
      });
      if (!response.ok) throw new Error(`loopback bridge returned HTTP ${response.status}`);
      return await response.json() as BridgeResponse<T>;
    },
  };
}

export function installLoopbackBridge(): boolean {
  if (typeof window === "undefined" || window.orionVivaBridge) return false;
  const transport = createLoopbackTransport(window.location, fetch);
  if (!transport) return false;
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  window.orionVivaBridge = transport;
  return true;
}
