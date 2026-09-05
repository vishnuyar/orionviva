import { afterEach, describe, expect, it, vi } from "vitest";
// The published event shape, so a change to it stops this test compiling
// rather than leaving a mocked payload asserting a shape nothing sends.
import type { DragDropEvent } from "@tauri-apps/api/webview";
import { installTauriBridge } from "./tauri-host";

const opened = vi.fn();
const subscribed = vi.fn();
const invoked = vi.fn(async (command: string, _args?: Record<string, unknown>) => {
  if (command === "open_remembered_vault") return { state: "opened", directory: "/remembered/vault" };
  return "{}";
});

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (options: unknown) => opened(options) }));
vi.mock("@tauri-apps/api/webview", () => ({ getCurrentWebview: () => ({ onDragDropEvent: async (handler: unknown) => { subscribed(handler); return () => {}; } }) }));

function install() {
  delete window.orionVivaBridge;
  window.__TAURI_INTERNALS__ = { invoke: async <T>(command: string, args?: Record<string, unknown>) => await invoked(command, args) as T };
  installTauriBridge();
  return window.orionVivaBridge!;
}

afterEach(() => {
  delete window.orionVivaBridge;
  delete window.__TAURI_INTERNALS__;
  opened.mockReset();
  subscribed.mockReset();
  invoked.mockClear();
});

describe("the host shim", () => {
  it("keeps remembered-vault secrets inside native commands", async () => {
    const transport = install();
    await expect(transport.openRememberedVault?.()).resolves.toEqual({ state: "opened", directory: "/remembered/vault" });
    await transport.rememberVault?.("/chosen/vault", "device secret");

    expect(invoked).toHaveBeenNthCalledWith(1, "open_remembered_vault", undefined);
    expect(invoked).toHaveBeenNthCalledWith(2, "remember_vault", { vaultDirectory: "/chosen/vault", passphrase: "device secret" });
  });

  it("asks the operating system for one document, not for several", async () => {
    opened.mockResolvedValue("/chosen/first.pdf");
    const transport = install();
    await expect(transport.pickDocumentPaths?.()).resolves.toEqual(["/chosen/first.pdf"]);
    expect(opened).toHaveBeenCalledWith({ directory: false, multiple: false, title: "Choose a file" });
  });

  it("hands back nothing when the picker was closed with nothing chosen", async () => {
    opened.mockResolvedValue(null);
    const transport = install();
    await expect(transport.pickDocumentPaths?.()).resolves.toEqual([]);
  });

  it("asks the operating system for one folder when a vault is being opened", async () => {
    opened.mockResolvedValue("/chosen/vault");
    const transport = install();
    await expect(transport.pickVaultDirectory?.()).resolves.toBe("/chosen/vault");
    expect(opened).toHaveBeenCalledWith({ directory: true, multiple: false, title: "Choose an OrionViva vault" });
  });

  it("passes on the paths a drop landed with, and nothing a drag merely passed over", async () => {
    const transport = install();
    const landed: string[][] = [];
    await transport.subscribeToDroppedPaths?.((paths) => { landed.push([...paths]); });
    const handler = subscribed.mock.calls[0][0] as (event: { payload: DragDropEvent }) => void;
    // The cursor position is derived from the published union rather than
    // rebuilt, so nothing here restates a shape it does not read.
    const somewhere = {} as Extract<DragDropEvent, { type: "drop" }>["position"];
    handler({ payload: { type: "enter", paths: ["/hovered/first.pdf"], position: somewhere } });
    handler({ payload: { type: "over", position: somewhere } });
    handler({ payload: { type: "leave" } });
    expect(landed).toEqual([]);
    handler({ payload: { type: "drop", paths: ["/dropped/first.pdf"], position: somewhere } });
    expect(landed).toEqual([["/dropped/first.pdf"]]);
  });
});
