import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { createRef } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, ConversationDialogShell } from "./App";
// The sentences a person is told, read from the pack that ships them.
import moments from "../../../product/viva/persona/pack-v31/moments.json";
// The sample vault as the backend answers for it, produced by running the
// product rather than authored here.
import sampleVault from "../../../product/viva/surface/fixtures/overview-parity-v1.json";

const SAVED_NO_READER = moments.documents_saved_no_reader;
const queryByRoleIn = (root: HTMLElement, role: string) => root.querySelector(`[role="${role}"]`);

function ThrowingConversationBody(): never { throw new Error("bounded conversation render failure"); }

function installResponsiveMatchMedia(initialWidth: number) {
  let width = initialWidth;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const media = {
    media: "(max-width: 760px)",
    get matches() { return width <= 760; },
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => { listeners.add(listener); },
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => { listeners.delete(listener); },
    addListener: (listener: (event: MediaQueryListEvent) => void) => { listeners.add(listener); },
    removeListener: (listener: (event: MediaQueryListEvent) => void) => { listeners.delete(listener); },
    dispatchEvent: () => true,
  };
  window.matchMedia = vi.fn(() => media as unknown as MediaQueryList);
  return {
    resize(nextWidth: number) {
      width = nextWidth;
      const event = { matches: media.matches, media: media.media } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

function installCapturedAnimationFrames() {
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
  const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
  const callbacks: FrameRequestCallback[] = [];
  globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { callbacks.push(callback); return callbacks.length; });
  globalThis.cancelAnimationFrame = vi.fn();
  return {
    runCaptured() { [...callbacks].forEach((callback) => callback(performance.now())); },
    restore() { globalThis.requestAnimationFrame = originalRequestAnimationFrame; globalThis.cancelAnimationFrame = originalCancelAnimationFrame; },
  };
}

// What a live trust read answers with. It is the shape the sidecar sends, so a
// stub that omitted it would make every destination test in this file also a
// test of what happens when Trust cannot be read.
// What a live activity read answers with. A stub that omitted it would make
// every destination test in this file also a test of what happens when Activity
// cannot be read.
const activityPayload = { state: "absent", sentence: moments.activity_empty, beyond: { count: 0 } };
const trustPayload = { state: "ready", notes: [], outbound: { state: "ready", sentence: moments.outbound_none, call_count: 0, phases: [], models: [], model_sentence: "", span: null, cost: null, absences: [{ id: "scope", sentence: moments.outbound_scope }, { id: "anchoring", sentence: moments.outbound_no_anchor }] } };

// The sample vault, as the backend actually answers for it. These are the same
// bytes the parity artifact holds — produced by minting the vault and reading
// it through the real dispatch — so the shell here renders what a person
// meets, rather than rows composed in this file that would agree with
// themselves while disagreeing with the product.
const sampleReads = sampleVault.reads as Record<string, { result: { data: unknown } }>;
const sampleFrame = { title: moments.sample_frame, detail: moments.sample_frame_detail, leave: moments.sample_frame_leave };

// One bridge stub, serving the sample vault's own payloads. Every test here
// enters through the one affordance the sample is entered from, because that
// is how a person enters it and the shell has no other way in.
function installSampleBridge(overrides: Record<string, unknown> = {}) {
  const previous = window.orionVivaBridge;
  window.orionVivaBridge = {
    pickDocumentPaths: async () => [],
    request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
      if (operation === "bridge.open_demo_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened", sample: true, frame: sampleFrame, surfaces: [] } as T };
      if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened", sample: false } as T };
      if (operation === "bridge.handshake") return { protocol: "1.0", request_id: "hand", ok: true, result: { protocol: "2.0", transport: "json-lines", revision: "sample-build" } as T };
      if (operation === "viva.surface.capabilities") return { protocol: "1.0", request_id: "caps", ok: true, result: { protocol: "2.0", capabilities: [], destinations: { overview: true, accounts: true, activity: true, documents: true, review: true, trust: true } } as T };
      if (operation === "viva.settings.read") return { protocol: "1.0", request_id: "set", ok: true, result: { state: "ready", locale: "en-US", currency: "USD", adapter: "", model: "", base_url: "", key_set: false, can_send: false } as T };
      if (operation !== "viva.surface.read") return { protocol: "1.0", request_id: "act", ok: true, result: { kind: "completed", message: "Done.", state: null, reason: null } as T };
      const surface = String(payload.surface);
      const data = surface in overrides ? overrides[surface] : sampleReads[surface]?.result.data;
      return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
    },
  };
  return () => { window.orionVivaBridge = previous; };
}

// Render the shell and go in through the sample vault's one door. Every test
// that used to start inside a fixture starts here instead.
async function openSample(overrides: Record<string, unknown> = {}) {
  const restore = installSampleBridge(overrides);
  const view = render(<App />);
  fireEvent.click(view.getAllByRole("button", { name: "Open the sample vault" })[0]);
  await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
  return { ...view, restore };
}

// A wide window before every test. `installResponsiveMatchMedia` replaces the
// global, and a narrow one installed by one test used to survive into the next
// — where the sidebar is hidden from the accessibility tree and the control
// that opens a vault is unreachable. A test that fails because of the test
// before it is a test nobody can read.

export { act, fireEvent, render, waitFor, createRef, userEvent, afterEach,
  beforeEach, describe, expect, it, vi, App, ConversationDialogShell, moments,
  sampleVault, SAVED_NO_READER, queryByRoleIn, ThrowingConversationBody,
  installResponsiveMatchMedia, installCapturedAnimationFrames, activityPayload,
  trustPayload, sampleReads, sampleFrame, installSampleBridge, openSample };
