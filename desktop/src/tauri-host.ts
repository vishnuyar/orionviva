import { open } from "@tauri-apps/plugin-dialog";
import type { BridgeRequest, BridgeResponse, BridgeTransport } from "./app/bridge-client";

type TauriInternals = {
  invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
};

declare global {
  interface Window {
    __TAURI_INTERNALS__?: TauriInternals;
  }
}

export function installTauriBridge(): boolean {
  if (typeof window === "undefined" || !window.__TAURI_INTERNALS__ || window.orionVivaBridge) {
    return false;
  }

  const invoke = window.__TAURI_INTERNALS__.invoke;
  const transport: BridgeTransport = {
    request: async <T>(frame: BridgeRequest) => {
      const response = await invoke<string>("bridge_request", {
        frame: JSON.stringify({
          protocol: "1.0",
          request_id: frame.requestId,
          operation: frame.operation,
          payload: frame.payload,
        }),
      });
      return JSON.parse(response) as BridgeResponse<T>;
    },
    pickVaultDirectory: async () => {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Choose an OrionViva vault",
      });
      return typeof selected === "string" ? selected : null;
    },
  };
  window.orionVivaBridge = transport;
  return true;
}
