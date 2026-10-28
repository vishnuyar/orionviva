import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connectBrowser } from "./browser-transport";

let pageNumber = 0;
let hide: (() => void) | undefined;
let fetcher: ReturnType<typeof vi.fn>;
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });

beforeEach(() => {
  vi.useFakeTimers();
  hide = undefined;
  sessionStorage.clear();
  vi.stubGlobal("window", {
    location: { hostname: "127.0.0.1", hash: "#launch=launch-secret", pathname: "/loopback.html" },
    history: { replaceState: vi.fn() },
    addEventListener: vi.fn((_event, listener) => { hide = listener; }),
    removeEventListener: vi.fn(),
  });
  vi.stubGlobal("crypto", { randomUUID: () => `page-${++pageNumber}` });
  vi.stubGlobal("performance", { getEntriesByType: () => [{ type: "reload" }] });
  vi.stubGlobal("navigator", { sendBeacon: vi.fn().mockReturnValue(true) });
  fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("claim")) return response({ token: "session-secret" });
    if (url.endsWith("capabilities")) return response({ remember: true, vault_epoch: 0, sequence: 4096 });
    if (url.endsWith("events")) return response({ vault_epoch: 0, sequence: 4096, lost: false, frames: [] });
    return response(null);
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("installed browser transport", () => {
  it("exchanges launch credentials once, removes the fragment, and binds requests to the page and vault", async () => {
    const bridge = await connectBrowser(vi.fn());
    expect(window.history.replaceState).toHaveBeenCalledWith(null, "", "/loopback.html");
    const claim = JSON.parse(fetcher.mock.calls[0][1].body);
    expect(claim).toMatchObject({ launch: "launch-secret" });
    fetcher.mockResolvedValueOnce(response({ response: { protocol: "2.1", request_id: "wire", ok: true, result: {} }, vault_epoch: 1 }));
    await bridge.request({ requestId: "desktop-1", operation: "bridge.open_vault", payload: { vault_directory: "/synthetic", passphrase: "synthetic phrase", create: true } });
    const sent = fetcher.mock.calls.at(-1)!;
    expect(JSON.parse(sent[1].body)).toMatchObject({ vault_epoch: 0, frame: { request_id: `${claim.page}:desktop-1` } });
    expect(sent[1].headers["x-orionviva-page"]).toBe(claim.page);
    await bridge.rememberVault!("/synthetic", "synthetic phrase");
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body).vault_epoch).toBe(1);
    expect(sessionStorage.getItem("orionviva.browser.session")).toBe("session-secret");
    expect([...Array(sessionStorage.length)].map((_, i) => sessionStorage.getItem(sessionStorage.key(i)!)).join("")).not.toContain("synthetic phrase");
  });

  it("does not reuse request identities after a page reload and releases the previous page", async () => {
    const first = await connectBrowser(vi.fn());
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 0 }));
    await first.request({ requestId: "desktop-1", operation: "bridge.handshake", payload: {} });
    const firstId = JSON.parse(fetcher.mock.calls.at(-1)![1].body).frame.request_id;
    hide!();
    expect(navigator.sendBeacon).toHaveBeenCalledWith("/__orionviva/release", expect.stringContaining("session-secret"));
    window.location.hash = "";
    const second = await connectBrowser(vi.fn());
    expect(fetcher.mock.calls.some(([url]) => url.endsWith("resume"))).toBe(true);
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 0 }));
    await second.request({ requestId: "desktop-1", operation: "bridge.handshake", payload: {} });
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body).frame.request_id).not.toBe(firstId);
  });

  it("refuses a copied tab credential when the server still owns another page", async () => {
    window.location.hash = "";
    sessionStorage.setItem("orionviva.browser.session", "copied-token");
    fetcher.mockResolvedValue(response(null, 409));
    const connected = connectBrowser(vi.fn());
    const rejected = expect(connected).rejects.toThrow("Another browser tab is active");
    await vi.advanceTimersByTimeAsync(1000);
    await rejected;
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it("revocation clears credentials and removes the app even before a vault is open", async () => {
    const ended = vi.fn();
    await connectBrowser(ended);
    fetcher.mockResolvedValue(response(null, 403));
    await vi.advanceTimersByTimeAsync(500);
    expect(ended).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("orionviva.browser.session")).toBeNull();
  });

  it("clears the rendered private app before a history snapshot can retain it", async () => {
    const ended = vi.fn();
    await connectBrowser(ended);
    hide!();
    expect(ended).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("events"))).toHaveLength(0);
  });

  it("closes the host vault and uses the new epoch for subsequent requests", async () => {
    const bridge = await connectBrowser(vi.fn());
    fetcher.mockResolvedValueOnce(response({ response: null, vault_epoch: 1 }));
    await bridge.closeVault!();
    expect(fetcher.mock.calls.at(-1)![0]).toBe("/__orionviva/close");
    fetcher.mockResolvedValueOnce(response({ response: { state: "absent" }, vault_epoch: 1 }));
    expect(await bridge.openRememberedVault!()).toEqual({ state: "absent" });
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body).vault_epoch).toBe(1);
  });

  it("drains sent reads before closing and rejects new requests without ending browser access", async () => {
    const ended = vi.fn();
    const bridge = await connectBrowser(ended);
    let finishRead!: (response: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRead = resolve; }));
    const read = bridge.request({ requestId: "reading", operation: "viva.surface.read", payload: {} });
    const closing = bridge.closeVault!();
    const blocked = expect(bridge.request({ requestId: "late", operation: "viva.surface.read", payload: {} })).rejects.toThrow("vault_busy");
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("close"))).toHaveLength(0);
    fetcher.mockResolvedValueOnce(response({ response: null, vault_epoch: 1 }));
    finishRead(response({ response: { ok: true }, vault_epoch: 0 }));
    await read; await closing; await blocked;
    expect(ended).not.toHaveBeenCalled();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("bridge"))).toHaveLength(1);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("close"))).toHaveLength(1);
  });

  it.each([undefined, false, "true", 1])("keeps save unavailable without an explicit true host capability (%s)", async (backup_save) => {
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : { remember: false, backup_save, vault_epoch: 0, sequence: 0 }));
    const bridge = await connectBrowser(vi.fn());
    expect(bridge.pickBackupSavePath).toBeUndefined();
  });

  it("opens the authenticated backup chooser only when advertised and preserves cancellation", async () => {
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : { remember: false, backup_save: true, vault_epoch: 0, sequence: 0 }));
    const bridge = await connectBrowser(vi.fn());
    fetcher.mockResolvedValueOnce(response("/synthetic/copy.orionvault"));
    await expect(bridge.pickBackupSavePath!()).resolves.toBe("/synthetic/copy.orionvault");
    const [url, options] = fetcher.mock.calls.at(-1)!;
    expect(url).toBe("/__orionviva/save-backup");
    expect(options.headers.authorization).toBe("Bearer session-secret");
    expect(options.headers["x-orionviva-page"]).toMatch(/^page-/);
    fetcher.mockResolvedValueOnce(response(null));
    await expect(bridge.pickBackupSavePath!()).resolves.toBeNull();
  });

  it("uses host file dialogs and respects platforms without protected remembering", async () => {
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : url.endsWith("capabilities") ? { remember: false, vault_epoch: 0 } : "/synthetic/document.pdf"));
    const bridge = await connectBrowser(vi.fn());
    expect(bridge.rememberVault).toBeUndefined();
    expect(await bridge.pickDocumentPaths!()).toEqual(["/synthetic/document.pdf"]);
    expect(await bridge.pickVaultDirectory!()).toBe("/synthetic/document.pdf");
  });

  it("hashes an actual HTML file selection for the authenticated campaign-only resolver", async () => {
    const digest = vi.fn(async (_algorithm, bytes) => {
      expect(Array.from(new Uint8Array(bytes))).toEqual([37, 80, 68, 70]);
      return new Uint8Array(32).fill(171).buffer;
    });
    vi.stubGlobal("crypto", { randomUUID: () => `page-${++pageNumber}`, subtle: { digest } });
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : url.endsWith("capabilities") ? { remember: false, campaign_file_chooser: true, vault_epoch: 0, sequence: 0 } : "/original/persona.pdf"));
    const input = document.createElement("input");
    const create = vi.spyOn(document, "createElement").mockReturnValueOnce(input);
    const click = vi.spyOn(input, "click").mockImplementation(() => {
      Object.defineProperty(input, "files", { value: [{ name: "persona.pdf", arrayBuffer: async () => new Uint8Array([37, 80, 68, 70]).buffer }] });
      input.dispatchEvent(new Event("change"));
    });
    try {
      const bridge = await connectBrowser(vi.fn());
      await expect(bridge.pickDocumentPaths!()).resolves.toEqual(["/original/persona.pdf"]);
      expect(input.type).toBe("file");
      expect(input.multiple).toBe(false);
      expect(input.isConnected).toBe(false);
      expect(digest).toHaveBeenCalledWith("SHA-256", expect.any(ArrayBuffer));
      const [url, options] = fetcher.mock.calls.at(-1)!;
      expect(url).toBe("/__orionviva/campaign-file");
      expect(JSON.parse(options.body)).toEqual({ name: "persona.pdf", sha256: "ab".repeat(32) });
      expect(options.headers.authorization).toBe("Bearer session-secret");
      expect(options.headers["x-orionviva-page"]).toMatch(/^page-/);
    } finally { click.mockRestore(); create.mockRestore(); }
  });

  it("cancels the HTML campaign chooser without resolving or capturing a source", async () => {
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : { remember: false, campaign_file_chooser: true, vault_epoch: 0, sequence: 0 }));
    const input = document.createElement("input");
    const create = vi.spyOn(document, "createElement").mockReturnValueOnce(input);
    const click = vi.spyOn(input, "click").mockImplementation(() => { input.dispatchEvent(new Event("cancel")); });
    try {
      const bridge = await connectBrowser(vi.fn());
      await expect(bridge.pickDocumentPaths!()).resolves.toEqual([]);
      expect(input.isConnected).toBe(false);
      expect(fetcher.mock.calls.some(([url]) => url.endsWith("campaign-file"))).toBe(false);
    } finally { click.mockRestore(); create.mockRestore(); }
  });

  it("resolves every actual file in a campaign multiselection before returning paths", async () => {
    const digest = vi.fn(async (_algorithm: string, bytes: ArrayBuffer) => new Uint8Array(32).fill(new Uint8Array(bytes)[0]).buffer);
    vi.stubGlobal("crypto", { randomUUID: () => `page-${++pageNumber}`, subtle: { digest } });
    fetcher.mockImplementation(async (url: string, options?: { body: string }) => response(url.endsWith("claim") ? { token: "session-secret" } : url.endsWith("capabilities") ? { remember: false, campaign_file_chooser: true, vault_epoch: 0, sequence: 0 } : `/original/${JSON.parse(options!.body).name}`));
    const input = document.createElement("input"); const create = vi.spyOn(document, "createElement").mockReturnValueOnce(input);
    const click = vi.spyOn(input, "click").mockImplementation(() => {
      Object.defineProperty(input, "files", { value: [{ name: "first.pdf", arrayBuffer: async () => new Uint8Array([1]).buffer }, { name: "second.pdf", arrayBuffer: async () => new Uint8Array([2]).buffer }] });
      input.dispatchEvent(new Event("change"));
    });
    try {
      const bridge = await connectBrowser(vi.fn());
      await expect(bridge.pickMultipleDocumentPaths!()).resolves.toEqual(["/original/first.pdf", "/original/second.pdf"]);
      expect(input.multiple).toBe(true); expect(input.isConnected).toBe(false); expect(digest).toHaveBeenCalledTimes(2);
      const selections = fetcher.mock.calls.filter(([url]) => url.endsWith("campaign-file")).map(([, options]) => JSON.parse(options.body));
      expect(selections).toEqual([{ name: "first.pdf", sha256: "01".repeat(32) }, { name: "second.pdf", sha256: "02".repeat(32) }]);
    } finally { click.mockRestore(); create.mockRestore(); }
  });

  it("uses a separate authenticated multiple-file route in normal browser mode", async () => {
    const bridge = await connectBrowser(vi.fn()); fetcher.mockResolvedValueOnce(response(["/first.pdf", "/second.pdf"]));
    await expect(bridge.pickMultipleDocumentPaths!()).resolves.toEqual(["/first.pdf", "/second.pdf"]);
    expect(fetcher.mock.calls.at(-1)![0]).toBe("/__orionviva/pick-files");
    fetcher.mockResolvedValueOnce(response("/backup.orionvault")); await expect(bridge.pickDocumentPaths!()).resolves.toEqual(["/backup.orionvault"]);
    expect(fetcher.mock.calls.at(-1)![0]).toBe("/__orionviva/pick-file");
  });

  it("drains a bulk request before allowing a vault switch", async () => {
    const bridge = await connectBrowser(vi.fn()); let finish!: (value: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const bulk = bridge.request({ requestId: "bulk-1", operation: "viva.documents.upload_many", payload: { paths: ["/first.pdf", "/second.pdf"] } });
    const closing = bridge.closeVault!(); expect(fetcher.mock.calls.some(([url]) => url.endsWith("close"))).toBe(false);
    await expect(bridge.request({ requestId: "next", operation: "viva.documents.upload_many", payload: { paths: ["/third.pdf"] } })).rejects.toThrow("vault_busy");
    fetcher.mockResolvedValueOnce(response({ response: null, vault_epoch: 1 }));
    finish(response({ response: { ok: true, result: { job_id: "chunk-1", rows: [] } }, vault_epoch: 0 }));
    await bulk; await closing; expect(fetcher.mock.calls.at(-1)![0]).toBe("/__orionviva/close");
  });

  it("releases its authenticated page once when a failed event channel ends an outstanding bulk request", async () => {
    const ended = vi.fn(); const bridge = await connectBrowser(ended);
    let complete!: (value: Response) => void;
    fetcher.mockImplementation((url: string) => url.endsWith("bridge") ? new Promise<Response>((resolve) => { complete = resolve; }) : url.endsWith("events") ? Promise.reject(new Error("synthetic event disconnect")) : Promise.resolve(response(null)));
    const bulk = bridge.request({ requestId: "active-bulk", operation: "viva.documents.upload_many", payload: { paths: ["/first.pdf", "/second.pdf"] } });
    await vi.advanceTimersByTimeAsync(500);
    expect(ended).toHaveBeenCalledOnce(); expect(sessionStorage.getItem("orionviva.browser.session")).toBeNull();
    expect(navigator.sendBeacon).toHaveBeenCalledOnce(); expect(navigator.sendBeacon).toHaveBeenCalledWith("/__orionviva/release", JSON.stringify({ token: "session-secret", page: `page-${pageNumber}` }));
    hide!(); expect(navigator.sendBeacon).toHaveBeenCalledOnce(); expect(ended).toHaveBeenCalledOnce();
    complete(response({ response: { ok: true }, vault_epoch: 0 })); await bulk;
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("bridge"))).toHaveLength(1);
  });

  it.each(["throws", "not-queued"])("clears access and notifies once when release delivery %s", async (failure) => {
    const ended = vi.fn(); await connectBrowser(ended);
    if (failure === "throws") vi.mocked(navigator.sendBeacon).mockImplementation(() => { throw new Error("synthetic unavailable beacon"); });
    else vi.mocked(navigator.sendBeacon).mockReturnValue(false);
    fetcher.mockRejectedValue(new Error("synthetic disconnect"));
    await vi.advanceTimersByTimeAsync(500);
    expect(ended).toHaveBeenCalledOnce(); expect(sessionStorage.getItem("orionviva.browser.session")).toBeNull();
    expect(window.removeEventListener).toHaveBeenCalledWith("pagehide", hide);
    hide!(); expect(navigator.sendBeacon).toHaveBeenCalledOnce(); expect(ended).toHaveBeenCalledOnce();
  });

  it("releases the current page on an explicit fetch failure without replaying the bulk request", async () => {
    const ended = vi.fn(); const bridge = await connectBrowser(ended); fetcher.mockRejectedValueOnce(new Error("synthetic bridge disconnect"));
    await expect(bridge.request({ requestId: "lost-bulk", operation: "viva.documents.upload_many", payload: { paths: ["/first.pdf"] } })).rejects.toMatchObject({ name: "BridgeTimeout", mayHaveWritten: true });
    expect(navigator.sendBeacon).toHaveBeenCalledOnce(); expect(ended).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("bridge"))).toHaveLength(1);
  });

  it("starts progress at the host cursor after reload and ignores delayed progress from a previous vault", async () => {
    const ended = vi.fn();
    const bridge = await connectBrowser(ended);
    const listener = vi.fn();
    await bridge.subscribeToJobProgress!(listener);
    let deliver!: (value: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { deliver = resolve; }));
    await vi.advanceTimersByTimeAsync(500);
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body)).toEqual({ after: 4096, vault_epoch: 0 });
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 1 }));
    await bridge.request({ requestId: "open", operation: "bridge.open_vault", payload: {} });
    deliver(response({ vault_epoch: 0, sequence: 4097, lost: true, frames: [{ request_id: `page-${pageNumber}:old` }] }));
    await vi.advanceTimersByTimeAsync(0);
    expect(listener).not.toHaveBeenCalled();
    expect(ended).not.toHaveBeenCalled();
  });

  it("waits for a switching vault before restoring its identity", async () => {
    const bridge = await connectBrowser(vi.fn());
    fetcher.mockResolvedValueOnce(response({ error: "vault_busy", vault_epoch: 1 }, 409));
    fetcher.mockResolvedValueOnce(response({ response: { state: "opened", directory: "/synthetic/new" }, vault_epoch: 1 }));
    const opening = bridge.openRememberedVault!();
    await vi.advanceTimersByTimeAsync(150);
    expect(await opening).toEqual({ state: "opened", directory: "/synthetic/new" });
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body)).toEqual({ vault_epoch: 1 });
  });

  it("drains a failed old read before opening and retains the new vault epoch", async () => {
    const bridge = await connectBrowser(vi.fn());
    let rejectOld!: (value: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { rejectOld = resolve; }));
    const oldRead = bridge.request({ requestId: "old", operation: "viva.surface.read", payload: {} });
    const failed = expect(oldRead).rejects.toThrow();
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 1 }));
    const opening = bridge.request({ requestId: "open", operation: "bridge.open_vault", payload: {} });
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("bridge"))).toHaveLength(1);
    rejectOld(response({ error: "request_failed", vault_epoch: 0 }, 502));
    await failed;
    await opening;
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 1 }));
    await bridge.request({ requestId: "new", operation: "viva.surface.read", payload: {} });
    expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body).vault_epoch).toBe(1);
  });

  it("does not retry a write whose outcome is unknown", async () => {
    const bridge = await connectBrowser(vi.fn());
    fetcher.mockResolvedValueOnce(response({ error: "outcome_unknown", vault_epoch: 0 }, 502));
    await expect(bridge.request({ requestId: "write", operation: "viva.documents.upload", payload: { path: "/synthetic" } })).rejects.toMatchObject({ name: "BridgeTimeout", mayHaveWritten: true });
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("bridge"))).toHaveLength(1);
  });
});
