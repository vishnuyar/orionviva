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

  it("uses host file dialogs and respects platforms without protected remembering", async () => {
    fetcher.mockImplementation(async (url: string) => response(url.endsWith("claim") ? { token: "session-secret" } : url.endsWith("capabilities") ? { remember: false, vault_epoch: 0 } : "/synthetic/document.pdf"));
    const bridge = await connectBrowser(vi.fn());
    expect(bridge.rememberVault).toBeUndefined();
    expect(await bridge.pickDocumentPaths!()).toEqual(["/synthetic/document.pdf"]);
    expect(await bridge.pickVaultDirectory!()).toBe("/synthetic/document.pdf");
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

  it("does not let a late error restore the previous vault epoch", async () => {
    const bridge = await connectBrowser(vi.fn());
    let rejectOld!: (value: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((resolve) => { rejectOld = resolve; }));
    const oldRead = bridge.request({ requestId: "old", operation: "viva.surface.read", payload: {} });
    const failed = expect(oldRead).rejects.toThrow();
    fetcher.mockResolvedValueOnce(response({ response: { ok: true }, vault_epoch: 1 }));
    await bridge.request({ requestId: "open", operation: "bridge.open_vault", payload: {} });
    rejectOld(response({ error: "request_failed", vault_epoch: 0 }, 502));
    await failed;
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
