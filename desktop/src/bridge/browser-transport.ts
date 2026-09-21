import { BRIDGE_PROTOCOL, BridgeTimeout } from "./contracts";
import type { BridgeRequest, BridgeResponse, BridgeTransport, JobProgressFrame, JobProgressListener, RememberedVaultOpen } from "./contracts";

const SESSION_KEY = "orionviva.browser.session";

export async function connectBrowser(onEnded: (message?: string) => void): Promise<BridgeTransport> {
  if (window.location.hostname !== "127.0.0.1") throw new Error("Open the browser from the OrionViva app on this computer.");
  const launch = new URLSearchParams(window.location.hash.slice(1)).get("launch");
  const page = crypto.randomUUID();
  window.history.replaceState(null, "", window.location.pathname);
  let token: string | null = null;
  if (launch) {
    sessionStorage.removeItem(SESSION_KEY);
    const response = await fetch("/__orionviva/claim", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ launch, page }) });
    if (!response.ok) throw new Error("This browser link has expired. Open a new session from OrionViva.");
    token = (await response.json() as { token: string }).token;
    sessionStorage.setItem(SESSION_KEY, token);
  } else {
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    if (navigation?.type === "reload") token = sessionStorage.getItem(SESSION_KEY);
    if (!token) throw new Error("Open this browser window from the OrionViva app. Additional tabs cannot take over your vault.");
    let resumed = false;
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await fetch("/__orionviva/resume", { method: "POST", headers: { authorization: `Bearer ${token}`, "x-orionviva-page": page, "content-type": "application/json" }, body: "{}" });
      if (response.ok) { resumed = true; break; }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    if (!resumed) throw new Error("Another browser tab is active, or access has ended. Return to OrionViva to open a new session.");
  }
  let ended = false;
  let vaultEpoch = 0;
  let timer: ReturnType<typeof setTimeout>;
  const listeners = new Set<JobProgressListener>();
  const release = () => {
    ended = true; clearTimeout(timer);
    navigator.sendBeacon("/__orionviva/release", JSON.stringify({ token, page }));
    onEnded();
  };
  window.addEventListener("pagehide", release, { once: true });
  function end(message?: string) {
    if (ended) return;
    ended = true; clearTimeout(timer);
    sessionStorage.removeItem(SESSION_KEY);
    window.removeEventListener("pagehide", release);
    onEnded(message);
  }
  async function call<T>(path: string, payload: unknown): Promise<T> {
    if (ended) throw new Error("Browser access has ended");
    let response: Response;
    try {
      response = await fetch(`/__orionviva/${path}`, { method: "POST", headers: { authorization: `Bearer ${token}`, "x-orionviva-page": page, "content-type": "application/json" }, body: JSON.stringify(payload), cache: "no-store" });
    } catch { end(); throw new BridgeTimeout(path, true); }
    if (response.status === 403) { end(); throw new Error("Browser access has ended"); }
    if (!response.ok) {
      const failure = await response.json().catch(() => ({})) as { error?: string; vault_epoch?: number };
      if (typeof failure.vault_epoch === "number") vaultEpoch = Math.max(vaultEpoch, failure.vault_epoch);
      if (failure.error === "vault_busy") throw new Error("vault_busy");
      if (failure.error === "vault_changed") { end("The active vault changed or is still finishing a request. Return to OrionViva and open a new browser session before trying again. No rejected request was retried."); throw new Error("The active vault changed"); }
      if (failure.error === "outcome_unknown") throw new BridgeTimeout(path, true);
      throw new Error("OrionViva could not complete this request");
    }
    return await response.json() as T;
  }
  const capabilities = await call<{ remember: boolean; vault_epoch: number; sequence: number }>("capabilities", {});
  vaultEpoch = capabilities.vault_epoch;
  let after = capabilities.sequence;
  let eventEpoch = capabilities.vault_epoch;
  async function poll() {
    try {
      const events = await call<{ vault_epoch: number; sequence: number; lost: boolean; frames: JobProgressFrame[] }>("events", { after, vault_epoch: eventEpoch });
      if (ended) return;
      if (events.vault_epoch === vaultEpoch) {
        if (events.lost) { end(); return; }
        for (const frame of events.frames) {
          if (!frame.request_id.startsWith(`${page}:`)) continue;
          const local = { ...frame, request_id: frame.request_id.slice(page.length + 1) };
          for (const listener of listeners) listener(local);
        }
        after = events.sequence;
        eventEpoch = events.vault_epoch;
      }
    } catch { end(); }
    if (!ended) timer = setTimeout(() => { void poll(); }, 500);
  }
  timer = setTimeout(() => { void poll(); }, 500);
  return {
    closeVault: async () => {
      const result = await call<{ response: null; vault_epoch: number }>("close", { vault_epoch: vaultEpoch });
      vaultEpoch = Math.max(vaultEpoch, result.vault_epoch);
    },
    request: async <T>(frame: BridgeRequest): Promise<BridgeResponse<T>> => {
      const result = await call<{ response: BridgeResponse<T>; vault_epoch: number }>("bridge", { vault_epoch: vaultEpoch, frame: { protocol: BRIDGE_PROTOCOL, request_id: `${page}:${frame.requestId}`, operation: frame.operation, payload: frame.payload } });
      if (result.vault_epoch < vaultEpoch) throw new Error("The active vault changed before this response arrived");
      vaultEpoch = result.vault_epoch;
      return { ...result.response, request_id: frame.requestId };
    },
    openRememberedVault: async () => {
      for (let attempt = 0; ; attempt++) {
        try {
          const result = await call<{ response: RememberedVaultOpen; vault_epoch: number }>("current", { vault_epoch: vaultEpoch });
          if (result.vault_epoch !== vaultEpoch) throw new Error("vault_busy");
          return result.response;
        }
        catch (error) {
          if (!(error instanceof Error) || error.message !== "vault_busy" || attempt >= 9) throw error;
          await new Promise((resolve) => setTimeout(resolve, 150));
        }
      }
    },
    ...(capabilities.remember ? { rememberVault: (directory: string, passphrase: string) => call<void>("remember", { directory, passphrase, vault_epoch: vaultEpoch }) } : {}),
    pickVaultDirectory: () => call<string | null>("pick-folder", {}),
    pickDocumentPaths: async () => { const path = await call<string | null>("pick-file", {}); return path ? [path] : []; },
    subscribeToJobProgress: async (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}

export async function installBrowserBridge(onEnded: (message?: string) => void): Promise<void> {
  window.orionVivaBridge = await connectBrowser(onEnded);
}
