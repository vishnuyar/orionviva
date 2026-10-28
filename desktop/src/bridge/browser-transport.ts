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
  let changingVault = false;
  const pendingVaultRequests = new Set<Promise<unknown>>();
  let timer: ReturnType<typeof setTimeout>;
  const listeners = new Set<JobProgressListener>();
  let released = false;
  function releaseOwnedPage() {
    if (released) return;
    released = true;
    try { navigator.sendBeacon("/__orionviva/release", JSON.stringify({ token, page })); }
    catch { /* Ending access still clears the private view if delivery fails. */ }
  }
  function finish(message: string | undefined, forgetSession: boolean) {
    if (ended) return;
    ended = true; clearTimeout(timer);
    window.removeEventListener("pagehide", release);
    if (forgetSession) sessionStorage.removeItem(SESSION_KEY);
    releaseOwnedPage();
    onEnded(message);
  }
  const release = () => finish(undefined, false);
  window.addEventListener("pagehide", release, { once: true });
  function end(message?: string) { finish(message, true); }
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
  const capabilities = await call<{ remember: boolean; backup_save?: boolean; campaign_file_chooser?: boolean; vault_epoch: number; sequence: number }>("capabilities", {});
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
  async function withVaultAccess<T>(switching: boolean, run: () => Promise<T>): Promise<T> {
    if (changingVault) throw new Error("vault_busy");
    if (switching) {
      changingVault = true;
      try {
        await Promise.allSettled([...pendingVaultRequests]);
        return await run();
      } finally { changingVault = false; }
    }
    const request = run();
    pendingVaultRequests.add(request);
    try { return await request; }
    finally { pendingVaultRequests.delete(request); }
  }
  async function pickCampaignDocuments(multiple = false): Promise<readonly string[]> {
    const files = await new Promise<readonly File[]>((resolve, reject) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "application/pdf,.pdf";
      input.multiple = multiple;
      input.setAttribute("aria-label", "Choose synthetic persona PDF");
      input.style.display = "none";
      const finish = (files: readonly File[]) => { input.remove(); resolve(files); };
      input.addEventListener("change", () => {
        const selected = Array.from(input.files ?? []);
        if (selected.length > (multiple ? 1000 : 1)) { input.remove(); reject(new Error("selection_over_limit")); }
        else finish(selected);
      }, { once: true });
      input.addEventListener("cancel", () => finish([]), { once: true });
      document.body.append(input);
      try { input.click(); }
      catch (failure) { input.remove(); reject(failure); }
    });
    const paths: string[] = [];
    for (const file of files) {
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      paths.push(await call<string>("campaign-file", { name: file.name, sha256 }));
    }
    return paths;
  }
  return {
    closeVault: () => withVaultAccess(true, async () => {
      const result = await call<{ response: null; vault_epoch: number }>("close", { vault_epoch: vaultEpoch });
      vaultEpoch = Math.max(vaultEpoch, result.vault_epoch);
    }),
    request: <T>(frame: BridgeRequest): Promise<BridgeResponse<T>> => withVaultAccess(frame.operation === "bridge.open_vault" || frame.operation === "bridge.open_demo_vault", async () => {
      const result = await call<{ response: BridgeResponse<T>; vault_epoch: number }>("bridge", { vault_epoch: vaultEpoch, frame: { protocol: BRIDGE_PROTOCOL, request_id: `${page}:${frame.requestId}`, operation: frame.operation, payload: frame.payload } });
      if (result.vault_epoch < vaultEpoch) throw new Error("The active vault changed before this response arrived");
      vaultEpoch = result.vault_epoch;
      return { ...result.response, request_id: frame.requestId };
    }),
    openRememberedVault: () => withVaultAccess(false, async () => {
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
    }),
    ...(capabilities.remember ? { rememberVault: (directory: string, passphrase: string) => call<void>("remember", { directory, passphrase, vault_epoch: vaultEpoch }) } : {}),
    ...(capabilities.backup_save === true ? { pickBackupSavePath: () => call<string | null>("save-backup", {}) } : {}),
    pickVaultDirectory: () => call<string | null>("pick-folder", {}),
    pickDocumentPaths: capabilities.campaign_file_chooser === true ? () => pickCampaignDocuments() : async () => { const path = await call<string | null>("pick-file", {}); return path ? [path] : []; },
    pickMultipleDocumentPaths: capabilities.campaign_file_chooser === true ? () => pickCampaignDocuments(true) : () => call<readonly string[]>("pick-files", {}),
    subscribeToJobProgress: async (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}

export async function installBrowserBridge(onEnded: (message?: string) => void): Promise<void> {
  window.orionVivaBridge = await connectBrowser(onEnded);
}
