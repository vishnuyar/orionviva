import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { listen } from "@tauri-apps/api/event";
import { BRIDGE_PROTOCOL, JOB_PROGRESS_EVENT } from "./bridge/contracts";
import type { BridgeRequest, BridgeResponse, BridgeTransport, DroppedPathsListener, JobProgressFrame, JobProgressListener, RememberedVaultOpen } from "./bridge/contracts";

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
          protocol: BRIDGE_PROTOCOL,
          request_id: frame.requestId,
          operation: frame.operation,
          payload: frame.payload,
        }),
      });
      return JSON.parse(response) as BridgeResponse<T>;
    },
    openRememberedVault: () => invoke<RememberedVaultOpen>("open_remembered_vault"),
    rememberVault: (vaultDirectory, passphrase) => invoke<void>("remember_vault", { vaultDirectory, passphrase }),
    pickVaultDirectory: async () => {
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Choose an OrionViva vault",
      });
      return typeof selected === "string" ? selected : null;
    },
    // The same call the vault folder uses, with different arguments. What
    // comes back is one path; the file itself is opened by the sidecar. One
    // document at a time, because one reply frame carries one answer and this
    // build has no channel that can report several as they happen.
    pickDocumentPaths: async () => {
      const selected = await open({
        directory: false,
        multiple: false,
        title: "Choose a file",
      });
      return typeof selected === "string" ? [selected] : [];
    },
    // The window layer takes an operating-system drop before the page can see
    // it, which is why no browser drop event fires for one. What arrives here
    // instead is the list of paths that landed on the window.
    subscribeToDroppedPaths: (listener: DroppedPathsListener) =>
      getCurrentWebview().onDragDropEvent((event) => {
        if (event.payload.type === "drop") listener(event.payload.paths);
      }),
    // A progress frame reaches this window on an event rather than in a
    // reply, because the reply arrives when the work is over. The host reads
    // the frame off the sidecar's own output and hands it here unchanged;
    // nothing between the two composes anything.
    subscribeToJobProgress: (listener: JobProgressListener) =>
      listen<JobProgressFrame>(JOB_PROGRESS_EVENT, (event) => listener(event.payload)),
  };
  window.orionVivaBridge = transport;
  return true;
}
