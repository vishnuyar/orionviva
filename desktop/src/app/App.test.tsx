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
beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("minimal shell", () => {
  it("opens on the financial picture", async () => {
    const { getByRole, getByText, getAllByText } = await openSample();
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("USD 17,486.45")).toBeInTheDocument();
    expect(getAllByText("Sample vault")[0]).toBeInTheDocument();
    expect(getByText(moments.sample_frame)).toBeInTheDocument();
    const disclosure = getByRole("complementary", { name: "Vault source" });
    const hero = document.querySelector(".hero-grid");
    expect(disclosure.compareDocumentPosition(hero as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lets the overview spotlight select an account and open its detail", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = await openSample();

    await user.click(getAllByText("Rainy Day Savings").find((node) => node.closest("button")?.classList.contains("account-card-button"))!.closest("button")!);

    expect(getByText("Selected account")).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
    expect(getByText("Rainy Day Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByText("This figure is over Rainy Day Savings alone. It is good as of 2026-06-01.")).toBeInTheDocument();
  });

  it("pairs every overview account amount with a distinct stable-id source control", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText, getAllByText } = await openSample();
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".account-card"));

    expect(cards).toHaveLength(8);
    expect(getAllByText("USD 3,081.45")).toHaveLength(1);
    cards.forEach((card) => {
      const amount = card.querySelector(".account-amount");
      const selection = card.querySelector(".account-card-button");
      // The amount a card shows and the control that selects it are separate
      // elements, so pressing the row never reads as pressing the figure. The
      // proof link that used to sit beside them was a field only the fixture
      // filled; the vault read supplies none, and this no longer looks for one.
      expect(amount).not.toBeNull();
      expect(selection).not.toBeNull();
      expect(selection?.contains(amount)).toBe(false);
    });

    const savingsCard = cards.find((card) => card.textContent?.includes("Rainy Day Savings")) as HTMLElement;
    await user.click(savingsCard.querySelector(".account-card-button") as HTMLElement);
    expect(getByText("Rainy Day Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();

    // The proof link beside a figure is the read's own citation, and it is a
    // separate control from the one that selects the row: pressing the row
    // never reads as pressing the figure.
    const proof = savingsCard.querySelector(".proof-link");
    expect(proof).not.toBeNull();
    expect(savingsCard.querySelector(".account-card-button")?.contains(proof as Node)).toBe(false);
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
  });

  it("keeps the sample source before facts with one page heading and one current destination", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    const destinations = [
      ["OverviewYour picture", ".hero-grid"],
      ["AccountsWhere money sits", ".feature-panel"],
      ["ActivityWhat moved", ".activity-panel"],
      ["DocumentsWhat supports it", ".documents-surface"],
      ["ReviewWhat needs you", ".review-inspection"],
      ["TrustHow it works", ".trust-panel"],
    ] as const;
    for (const [name, selector] of destinations) {
      await user.click(view.getByRole("button", { name }));
      const source = view.getByRole("complementary", { name: "Vault source" });
      const facts = view.container.querySelector(selector);
      expect(facts).not.toBeNull();
      expect(source.compareDocumentPosition(facts as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(view.container.querySelectorAll("h1")).toHaveLength(1);
      expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    }
  });

  it("acknowledges document capture as local-only", async () => {
    const user = userEvent.setup();
    const { getAllByRole, container, getByRole } = await openSample();
    await user.click(getByRole("button", { name: "Go to documents" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a document" })).toHaveFocus());
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("focuses the static capture explanation when already on Documents", async () => {
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: "Go to documents" }));
    await waitFor(() => expect(getByRole("region", { name: "Add a document" })).toHaveFocus());
  });

  it("does not resurrect capture focus after navigating away and back from another destination", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a document" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect capture focus after navigating away and back from Documents", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "Add a document" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("puts one frame around the sample vault, and leaves it in one action", async () => {
    const user = userEvent.setup();
    const { queryByText, getAllByRole, getByRole, getByText, getAllByText } = await openSample();

    expect(getAllByText("Sample vault")[0]).toBeInTheDocument();
    // One frame, said once, in the pack's own words — not a qualifier repeated
    // beside every figure inside it.
    expect(getAllByText(moments.sample_frame)).toHaveLength(1);
    expect(getByText(moments.sample_frame_detail)).toBeInTheDocument();

    await user.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    expect(getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(queryByText(moments.sample_frame)).not.toBeInTheDocument();
  });

  it.each([
    ["Overview", "OverviewYour picture"],
    ["Accounts", "AccountsWhere money sits"],
    ["Activity", "ActivityWhat moved"],
    ["Documents", "DocumentsWhat supports it"],
    ["Review", "ReviewWhat needs you"],
    ["Trust", "TrustHow it works"],
  ] as const)("leaves the sample vault from %s and takes the whole session with it", async (destination, navigationName) => {
    // Leaving is one action, and nothing from the vault survives it: not the
    // screen a person was on, not what they had selected there, not an open
    // overlay, and not the vault itself. The session is rebuilt from nothing
    // rather than cleared field by field, so a field added later cannot be the
    // one that survives.
    const user = userEvent.setup();
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    const view = await openSample();
    await user.click(view.getByRole("button", { name: navigationName }));

    if (destination === "Overview") fireEvent.click(view.container.querySelectorAll(".account-card-button")[1]);
    if (destination === "Accounts") fireEvent.click(view.container.querySelectorAll(".detail-row-button")[1]);
    if (destination === "Documents") fireEvent.click(view.container.querySelectorAll(".document-list .detail-row-button")[1]);
    if (destination === "Review") fireEvent.click(view.container.querySelectorAll(".review-question-row")[1]);

    await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);

    expect(view.queryByText(moments.sample_frame)).not.toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.container.querySelectorAll("h1")).toHaveLength(1);
    expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    expect(view.getByRole("button", { name: "OverviewYour picture" })).toHaveAttribute("aria-current", "page");
    expect(view.queryByText("USD 17,486.45")).not.toBeInTheDocument();
    expect(view.getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(view.queryAllByRole("dialog")).toHaveLength(0);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(view.getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
  });

  it.each(["Evidence", "Viva"] as const)("does not resurrect explicitly closed %s after a sample reset", async (overlay) => {
    const user = userEvent.setup();
    const view = await openSample();
    if (overlay === "Evidence") {
      await user.click(view.getByRole("button", { description: "View the evidence for net worth in USD." }));
      expect(view.getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close evidence" }));
    } else {
      await user.click(view.getByRole("button", { name: "Ask Viva" }));
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close Viva conversation" }));
    }
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it.each(["Evidence", "Viva"] as const)("cancels captured stale %s restoration before a reset transition", async (overlay) => {
    const frames = installCapturedAnimationFrames();
    try {
      const view = await openSample();
      if (overlay === "Evidence") {
        const opener = view.getByRole("button", { description: "View the evidence for net worth in USD." });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      } else {
        const opener = view.getByRole("button", { name: "Ask Viva" });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      }
      const reset = view.getAllByRole("button", { name: moments.sample_frame_leave })[0];
      reset.focus();
      fireEvent.click(reset);
      frames.runCaptured();
      expect(view.queryByRole("dialog")).not.toBeInTheDocument();
      expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
      expect(view.queryByText(moments.sample_frame)).not.toBeInTheDocument();
      expect(view.getByRole("button", { name: "Ask Viva" })).not.toHaveFocus();
      expect(document.documentElement.style.overflow).toBe("");
      expect(document.body.style.overflow).toBe("");
    } finally {
      frames.restore();
    }
  });

  it("shows the supplied review total without adding a navigation count", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    expect(getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(getByText("Open-question total from this read")).toBeInTheDocument();
    expect(getByText("13", { selector: ".review-summary > strong" })).toBeInTheDocument();
    expect(container.querySelector(".nav-count")).toBeNull();
  });

  it("opens the Viva conversation drawer with cited turns and refusal states", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    // Viva is not connected to a vault read, so the drawer says so rather than
    // showing turns from somewhere else. What it does carry is the box that
    // takes a question, which is not a read and does not wait for one.
    expect(getByText("Conversation isn’t connected yet")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("picture is complete");
    expect(document.body).not.toHaveTextContent("Brokerage statement, page 4");
    // The box that takes a question is outside the read's gate, so a person
    // can ask even where nothing has been answered yet.
    expect(getByRole("button", { name: /^Ask$/i })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /close viva conversation/i }));
    expect(getByRole("button", { name: /ask viva/i })).toBeInTheDocument();
  });

  it("moves keyboard focus into the Viva dialog when it opens", async () => {
    const user = userEvent.setup();
    const { getByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toContainElement(document.activeElement as HTMLElement | null);
  });

  it("lets a keyboard user dismiss the Viva dialog with Escape", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /ask viva/i }));
    await user.keyboard("{Escape}");

    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
  });

  it("locks and inerts the shell while Viva is open, then Close restores its opener and exact overflow", async () => {
    const user = userEvent.setup();
    const priorRoot = document.documentElement.style.overflow;
    const priorBody = document.body.style.overflow;
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "visible";
    try {
      const { getByRole } = await openSample();
      const opener = getByRole("button", { name: "Ask Viva" });
      await user.click(opener);
      expect(getByRole("button", { name: "Close Viva conversation" })).toHaveFocus();
      expect(document.querySelector("main")).toHaveAttribute("inert");
      expect(document.getElementById("primary-navigation-drawer")).toHaveAttribute("inert");
      expect(document.documentElement.style.overflow).toBe("hidden");
      expect(document.body.style.overflow).toBe("hidden");
      await user.click(getByRole("button", { name: "Close Viva conversation" }));
      await waitFor(() => expect(opener).toHaveFocus());
      expect(document.documentElement.style.overflow).toBe("clip");
      expect(document.body.style.overflow).toBe("visible");
    } finally {
      document.documentElement.style.overflow = priorRoot;
      document.body.style.overflow = priorBody;
    }
  });

  it("traps both Viva tab boundaries, recaptures outside focus, and restores from the backdrop", async () => {
    const user = userEvent.setup();
    const { container, getByRole } = await openSample();
    const opener = getByRole("button", { name: "Ask Viva" });
    await user.click(opener);
    const dialog = getByRole("dialog", { name: "Viva conversation" });
    const close = getByRole("button", { name: "Close Viva conversation" });
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(close).not.toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();
    fireEvent.focus(getByRole("heading", { name: "Your financial picture" }));
    expect(close).toHaveFocus();
    fireEvent.click(container.querySelector(".conversation-backdrop") as HTMLElement);
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("closes a stale conversation scope without restoring its opener", async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole, queryByRole } = await openSample();
    const opener = getByRole("button", { name: "Ask Viva" });
    await user.click(opener);
    fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave, hidden: true })[0]);
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    expect(document.querySelector("main")).not.toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("inert");
  });

  it("keeps the Viva shell dismissible when its body throws and recovers on reset", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const dismiss = vi.fn();
    const drawer = createRef<HTMLElement>();
    const close = createRef<HTMLButtonElement>();
    try {
      const view = render(<ConversationDialogShell resetKey="request-1-demo" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><ThrowingConversationBody /></ConversationDialogShell>);
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      expect(view.getByText("This surface could not be shown")).toBeInTheDocument();
      fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      expect(dismiss).toHaveBeenCalledTimes(1);
      view.rerender(<ConversationDialogShell resetKey="request-2-live" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><div>Recovered supplied body</div></ConversationDialogShell>);
      expect(view.getByText("Recovered supplied body")).toBeInTheDocument();
      expect(view.getByText("This drawer shows the turns this vault recorded, and takes a question of your own.")).toBeInTheDocument();
    } finally {
      error.mockRestore();
    }
  });

  it("keeps the overview selected account spotlight in sync with selection", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    expect(getByText("Abroad Current", { selector: ".coverage-account-title" })).toBeInTheDocument();

    await user.click(container.querySelectorAll(".account-card-button")[4] as HTMLElement);

    expect(getByText("Household Card", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
  });

  it("shows the selected document detail inside documents", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = await openSample();
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "What this read can show" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
    // The read supplies identity, filename, kind, resolution and what the
    // document put on the books. Pages, source regions and provenance are not
    // supplied by any vault read, and this screen says so rather than showing
    // a field it filled in itself.
    expect(getAllByText("Page details are not supplied by this vault read.").length).toBeGreaterThan(0);
    expect(getByText("Related evidence is not supplied by this vault read.")).toBeInTheDocument();
  });



  it("opens Activity on the vault own movements, with no second implementation", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = await openSample();
    await user.click(getByRole("button", { name: /activity.*what moved/i }));
    expect(getByRole("heading", { name: "What moved" })).toBeInTheDocument();
    // One implementation, and no search box: the facet explorer this screen
    // used to carry existed only for rows composed in the shell.
    expect(queryByRole("searchbox")).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /go to review queue/i })).not.toBeInTheDocument();
  });

  it("discards a pending document-heading focus when the source request changes", async () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    const cancelAnimationFrame = vi.fn((id: number) => pendingFrames.delete(id));
    globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
      frameId += 1;
      pendingFrames.set(frameId, callback);
      return frameId;
    });
    globalThis.cancelAnimationFrame = cancelAnimationFrame;

    try {
      const { queryByRole, getAllByRole, container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      expect(document.querySelector("#selected-document-title")).not.toHaveFocus();

      fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      expect(cancelAnimationFrame).toHaveBeenCalled();
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();

      fireEvent.click(getAllByRole("button", { name: "DocumentsWhat supports it" })[0]);
      expect(document.querySelector("#selected-document-title")).toBeNull();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("discards pending capture focus when the source request changes", async () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { frameId += 1; pendingFrames.set(frameId, callback); return frameId; });
    globalThis.cancelAnimationFrame = vi.fn((id: number) => pendingFrames.delete(id));

    try {
      const { queryByRole, getAllByRole, getByRole } = await openSample();
      fireEvent.click(getByRole("button", { name: "Go to documents" }));
      expect(document.getElementById("document-capture-status")).not.toHaveFocus();
      fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();
      fireEvent.click(getAllByRole("button", { name: "DocumentsWhat supports it" })[0]);
      expect(document.getElementById("document-capture-status")).toBeNull();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("does not resurrect document-title focus after leaving and returning to Documents", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "bank_statement" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect document-title focus after selection diverges and returns", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = await openSample();
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
      fireEvent.click(getByRole("button", { name: /everyday-checking-2026-06\.pdf/i }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "bank_statement" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("opens fresh figure evidence and routes its exact source to the selected document heading", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    const trigger = getByRole("button", { description: "View the evidence for net worth in USD." });

    await user.click(trigger);
    expect(getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
    expect(getByRole("button", { name: "Close evidence" })).toHaveFocus();
    expect(document.querySelector("main")).toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).toHaveAttribute("inert");
    await user.click(getByRole("button", { name: "Open everyday-checking-2026-06.pdf" }));

    expect(queryByRole("dialog", { name: "Net worth in USD" })).not.toBeInTheDocument();
    await waitFor(() => expect(getByRole("heading", { name: "bank_statement" })).toHaveFocus());
  });

  it("keeps Evidence, Viva, and narrow navigation mutually exclusive", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { description: "View the evidence for net worth in USD." }));
    expect(getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Ask Viva", hidden: true }));
    expect(queryByRole("dialog", { name: "Net worth in USD" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();

    fireEvent.click(getByRole("button", { name: "Open navigation" }));
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    installResponsiveMatchMedia(1440);
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText } = await openSample();
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    await user.click(getByRole("button", { name: /May I ask what annual fee is/i }));
    expect(getByRole("heading", { name: /May I ask what/ })).toBeInTheDocument();
    expect(getByText("Set this question aside")).toBeInTheDocument();
    expect(getAllByText("160.00").length).toBeGreaterThan(0);
  });

  it("opens and focuses an exact review question from Overview", async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole, queryByRole } = await openSample();
    await user.click(getAllByRole("button", { name: "View question" })[1]);
    await waitFor(() => expect(getByRole("heading", { name: /May I ask what/ })).toHaveFocus());
    expect(queryByRole("button", { name: /^Answer$/i })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /^Confirm$/i })).not.toBeInTheDocument();
  });

  it("does not resurrect Overview review focus after leaving Review", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = await openSample();
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /trust.*how it works/i }));
      fireEvent.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: /May I ask what/ })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the selected identity changes", async () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = await openSample();
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /Your acct:everyday-checking statement/i }));
      fireEvent.click(getByRole("button", { name: /May I ask what annual fee is/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: /May I ask what/ })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the vault is closed", async () => {
    const frames = installCapturedAnimationFrames();
    const restore = installSampleBridge();
    try {
      const user = userEvent.setup();
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument());
      // A question opened from Overview asks for focus one frame later. The
      // vault is closed before that frame runs, so the focus it captured names
      // a question on a screen nobody is looking at any more.
      fireEvent.click(getAllByRole("button", { name: "View question" })[0]);
      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(document.querySelector("#selected-question-title")).toBeNull();
      expect(getByRole("heading", { name: "Review" })).toHaveFocus();
    } finally {
      restore();
      frames.restore();
    }
  });

  it("keeps the selected document when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    await user.click(getByRole("button", { name: /growth-portfolio-2026-06\.pdf/i }));
    expect(getByRole("heading", { name: "brokerage_statement" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    expect(getByRole("heading", { name: "brokerage_statement" })).toBeInTheDocument();
    expect(queryByRole("button", { name: /open page review/i })).not.toBeInTheDocument();
    expect(getByText("Page and source-region review are not connected.")).toBeInTheDocument();
  });

  it("keeps the selected account when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    await user.click(container.querySelectorAll(".account-card-button")[1] as HTMLElement);
    await user.click(getByRole("button", { name: /open accounts/i }));
    expect(getByRole("heading", { name: "Accounts in this read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Dormant Savings" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    expect(getByText("Dormant Savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
  });

  it("keeps the selected review question when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText } = await openSample();

    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    await user.click(getByRole("button", { name: /May I ask what annual fee is/i }));
    expect(getAllByText("160.00").length).toBeGreaterThan(0);

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    expect(getAllByText("160.00").length).toBeGreaterThan(0);
  });

  it("keeps the accounts detail panel focused on the selected account", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = await openSample();

    await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
    expect(getByRole("heading", { name: "Accounts in this read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Abroad Current" })).toBeInTheDocument();
    expect(getByText("Grade")).toBeInTheDocument();

    await user.click(container.querySelectorAll(".detail-row-button")[4] as HTMLElement);

    expect(getByRole("heading", { name: "Household Card" })).toBeInTheDocument();
  });

  it("lets the local capture notice be dismissed", async () => {
    const { getAllByRole, getByRole, queryByRole } = await openSample();

    fireEvent.click(getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    expect(getAllByRole("status")[0]).toHaveTextContent("Closed. Nothing from that vault is on this screen.");

    fireEvent.click(getByRole("button", { name: /dismiss notice/i }));
    expect(queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the Trust destination from what the vault read said", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText, queryByRole } = await openSample();

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    expect(getByRole("heading", { name: "Trust" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Trust and limitations" })).toBeInTheDocument();
    // The outbound record, and what nothing on this machine can establish.
    // Both are the read's; neither is a row this screen authored.
    expect(getAllByText(moments.trust_no_anchoring).length).toBeGreaterThan(0);
    expect(getByText("Local source", { selector: ".privacy-lock span" })).toBeInTheDocument();
    expect(getByText("Every vault this app opens, the sample one included, is opened through the local desktop host on this machine.")).toBeInTheDocument();
    expect(queryByRole("button", { name: "Go to documents" })).not.toBeInTheDocument();
    const source = getByRole("complementary", { name: "Vault source" });
    const trustHeader = getByRole("heading", { name: "Trust and limitations" });
    expect(source.compareDocumentPosition(trustHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("states the fictional sample boundary", async () => {
    const { getByRole, getByText } = await openSample();
    expect(getByRole("complementary", { name: "Vault source" })).toBeInTheDocument();
    expect(getByText(moments.sample_frame_detail)).toBeInTheDocument();
  });

  it("says a vault cannot be opened here when no host bridge is injected", async () => {
    const { getByText, queryByPlaceholderText } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByPlaceholderText("/path/to/vault")).not.toBeInTheDocument();
  });

  it("keeps manual directory entry as the browser fallback", async () => {
    const { getByText, queryByLabelText, queryByRole } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByRole("button", { name: /choose folder/i })).not.toBeInTheDocument();
    expect(queryByLabelText("Vault directory")).not.toBeInTheDocument();
  });

  it("exposes the collapsed and expanded state of narrow navigation", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));
    const openNavigation = getByRole("button", { name: "Open navigation" });
    const drawer = document.getElementById("primary-navigation-drawer");

    expect(openNavigation).toHaveAttribute("aria-expanded", "false");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(drawer).toHaveAttribute("inert");
    await user.click(openNavigation);
    expect(openNavigation).toHaveAttribute("aria-expanded", "true");
    expect(getByRole("dialog", { name: "Main navigation" })).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector("main")).toHaveAttribute("inert");
    expect(getByRole("button", { name: "Close navigation" })).toHaveFocus();
    const backdrop = document.querySelector<HTMLElement>(".navigation-backdrop");
    expect(backdrop).toHaveAttribute("aria-hidden", "true");
    expect(backdrop?.tabIndex).toBe(-1);
    expect(queryByRole("button", { name: /dismiss navigation/i })).not.toBeInTheDocument();
    fireEvent.click(backdrop as HTMLElement);
    await waitFor(() => expect(openNavigation).toHaveFocus());
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it("traps focus in narrow navigation and restores the trigger after Escape", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    document.body.style.overflow = "clip";
    document.documentElement.style.overflow = "scroll";
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");
    const close = getByRole("button", { name: "Close navigation" });
    const navButtons = document.querySelectorAll<HTMLElement>("#primary-navigation button");
    const last = navButtons[navButtons.length - 1];
    close.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(last).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.overflow).toBe("clip");
    expect(document.documentElement.style.overflow).toBe("scroll");
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  });

  it("moves outside focus into the open narrow dialog in either Tab direction", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    const dialog = getByRole("dialog", { name: "Main navigation" });
    const close = getByRole("button", { name: "Close navigation" });
    const currentPage = getByRole("button", { name: "OverviewYour picture" });
    expect(document.querySelector("main")).toHaveAttribute("inert");

    trigger.focus();
    const forward = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(close).toHaveFocus();

    document.getElementById("page-title")?.focus();
    const backward = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
    document.dispatchEvent(backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(getByRole("button", { name: "TrustHow it works" })).toHaveFocus();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(currentPage).toHaveAttribute("aria-current", "page");
  });

  it("skips disabled controls and falls back to the drawer when none remain", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getAllByRole, getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    const dialog = getByRole("dialog", { name: "Main navigation" });
    const close = getByRole("button", { name: "Close navigation" });
    close.setAttribute("disabled", "");
    trigger.focus();
    const skipDisabled = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(skipDisabled);
    expect(skipDisabled.defaultPrevented).toBe(true);
    expect(getAllByRole("button", { name: moments.sample_frame_leave }).some((control) => control === document.activeElement)).toBe(true);

    dialog.querySelectorAll("button, input, select, textarea").forEach((element) => element.setAttribute("disabled", ""));
    trigger.focus();
    const empty = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(empty);
    expect(empty.defaultPrevented).toBe(true);
    expect(dialog).toHaveFocus();
  });

  it("closes narrow navigation for the current destination and focuses the page title", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    await user.click(getByRole("button", { name: "OverviewYour picture" }));

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes an open Viva drawer before opening narrow navigation", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: /ask viva/i }));
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: "Open navigation" }));

    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("keeps desktop navigation persistent and cleans up an open mobile modal at the breakpoint", async () => {
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "auto";
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("hidden");
    responsive.resize(761);

    await waitFor(() => expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("role"));
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("aria-hidden");
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("inert");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(getByRole("button", { name: "OverviewYour picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Close navigation" })).not.toHaveFocus();
    expect(trigger).not.toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.style.overflow).toBe("auto");
    document.documentElement.style.overflow = "";
  });

  it("focuses the page title after desktop resize when no current navigation item is available", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const { getByRole } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    getByRole("button", { name: "OverviewYour picture" }).removeAttribute("aria-current");
    responsive.resize(761);

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Close navigation" })).not.toHaveFocus();
    expect(getByRole("button", { name: "Open navigation" })).not.toHaveFocus();
  });

  it("restores exact root and body overflow values when an open narrow drawer unmounts", async () => {
    const responsive = installResponsiveMatchMedia(1440);
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "visible";
    const user = userEvent.setup();
    const { getByRole, unmount } = await openSample();
    act(() => responsive.resize(390));

    await user.click(getByRole("button", { name: "Open navigation" }));
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.documentElement.style.overflow).toBe("clip");
    expect(document.body.style.overflow).toBe("visible");
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    installResponsiveMatchMedia(1440);
  });

  it("asks the native host to choose a vault directory and copies the selection into the manual field", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => "/chosen/local-vault");
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/chosen/local-vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("treats a cancelled native picker as a no-op and keeps the manual path", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const pickVaultDirectory = vi.fn(async () => null);
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory,
    };

    try {
      const { getByLabelText, getByRole, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(pickVaultDirectory).toHaveBeenCalledTimes(1);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
      expect(queryByRole("status")).toBeNull();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps picker failures bounded and leaves manual entry available", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const hostFailure = "dialog failed while reading /private/vault";
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "1.0", request_id: "req", ok: true, result: {} as T }),
      pickVaultDirectory: async () => { throw new Error(hostFailure); },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(getAllByRole("status")[0]).toHaveTextContent(/folder picker could not be opened/i);
      expect(getAllByRole("status")[0]).not.toHaveTextContent(hostFailure);
      expect(getByLabelText("Vault directory")).toHaveValue("/manual/vault");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("opens a local vault through the injected host bridge", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => ({
        protocol: "1.0",
        request_id: "req",
        ok: true,
        result: (operation === "bridge.open_vault"
          ? { state: "opened" }
          : { surface: payload.surface, job_id: "job-1", data: payload.surface === "overview" ? { accounts: [], as_of: "August 1, 2026" } : payload.surface === "documents" ? { documents: [] } : payload.surface === "trust" ? trustPayload : payload.surface === "activity" ? activityPayload : { questions: [], total: 0 } }) as T,
      }),
    };

    try {
      const { getAllByText, getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByText("Private vault")).toBeInTheDocument());
      expect(getByText("Opened on this device")).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("hides the sample surface as soon as a private vault opens, while live reads are still pending", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let releaseReads: () => void = () => {};
    const readsCanFinish = new Promise<void>((resolve) => {
      releaseReads = resolve;
    });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        await readsCanFinish;
        const data = payload.surface === "overview"
          ? { accounts: [] }
          : payload.surface === "documents"
            ? { documents: [] }
            : payload.surface === "trust"
              ? trustPayload
              : payload.surface === "activity"
                ? activityPayload
              : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Private vault")).toBeInTheDocument();
      expect(getByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).toBeInTheDocument();
      expect(queryByText("USD 17,486.45")).not.toBeInTheDocument();
      expect(queryByText("Everyday Checking")).not.toBeInTheDocument();
      releaseReads();
      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(queryByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps a closed vault closed even when its read resolves later", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let releaseReads: () => void = () => {};
    const readsCanFinish = new Promise<void>((resolve) => {
      releaseReads = resolve;
    });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        await readsCanFinish;
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "late-private", name: "Late private account", balance: { amount: "999.99", grade: "verified" } }] }
          : payload.surface === "documents"
            ? { documents: [{ id: "late-private-document", doc_type: "statement" }] }
            : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByText, getAllByRole, getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      expect(getByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).toBeInTheDocument();

      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
      expect(queryByText("Late private account")).not.toBeInTheDocument();

      // The read that was still in flight when the vault was closed lands on a
      // session that has moved on. It changes nothing: a row from a vault
      // nobody has open any more is a row about somebody's money on a screen
      // that says no vault is open.
      releaseReads();
      await waitFor(() => expect(getAllByText("No vault open")[0]).toBeInTheDocument());
      expect(queryByText("Late private account")).not.toBeInTheDocument();
      expect(queryByText("late-private-document")).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders combined live surfaces, and closing takes every one of them away", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview"
          ? { as_of: "2026-08-18", accounts: [{ account: "live-account", name: "Private checking", kind: "deposit", currency: "USD", balance: { amount: "101.25", grade: "conflicted", dated: "2026-08-18" } }] }
          : surface === "documents"
            ? { documents: [{ id: "live-document", doc_type: "statement", resolved: false, raw_available: true }] }
            : { questions: [{ id: "live-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, tail: { count: 0, amount: "0" }, pending: { count: 0 }, invite: "Write an answer", answered_by_document: "A document answers this" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText, getAllByText, queryByRole, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      // Twice on the screen: the account card and the selected-account panel. A
      // figure carries its subject in text a reader hears and a screen does not
      // show, and this counts what is shown.
      await waitFor(() => expect(getAllByText("Private checking", { ignore: "script, style, .figure-invitation" })).toHaveLength(2));
      expect(getByText("Private vault")).toBeInTheDocument();
      expect(getByText("Opened on this device")).toBeInTheDocument();
      expect(getByText("Private vault · Opened on this device")).toBeInTheDocument();
      expect(getByRole("complementary", { name: "Vault source" })).toHaveTextContent("The surfaces below are read from this vault. Features that are not connected stay hidden or say so.");
      expect(getAllByText("Conflicting evidence").length).toBeGreaterThan(0);
      expect(queryByText("101.25")).not.toBeInTheDocument();
      expect(getAllByText("Amount unavailable from this preview read.").length).toBeGreaterThan(0);
      expect(queryByText("USD 17,486.45")).not.toBeInTheDocument();
      expect(queryByText(/silverline-checking/i)).not.toBeInTheDocument();
      expect(queryByText("Every figure carries its date, scope, and evidence. Uncertainty stays visible.")).not.toBeInTheDocument();
      expect(queryByText("Document capture is not connected for this vault.")).not.toBeInTheDocument();
      expect(queryByRole("button", { name: /add document/i })).not.toBeInTheDocument();

      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(queryByText("101.25")).not.toBeInTheDocument();
      expect(getAllByText("Amount unavailable from this preview read.").length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /overview.*your picture/i }));

      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByText("Viva is not connected to this vault in this preview. Opening this drawer does not send a prompt or call a model. This unavailable view does not establish whether earlier model activity occurred.")).toBeInTheDocument();
      expect(queryByText("What changed this month?")).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /close viva conversation/i }));

      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByRole("heading", { name: "statement" })).toBeInTheDocument();
      expect(getAllByText(/live-document/).length).toBeGreaterThan(0);
      expect(queryByText("Capture queue")).not.toBeInTheDocument();
      expect(queryByRole("button", { name: /choose a/i })).not.toBeInTheDocument();
      expect(queryByText("Document capture unavailable")).not.toBeInTheDocument();

      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      expect(getByRole("heading", { name: "Is this your account?" })).toBeInTheDocument();
      expect(queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
      expect(getByRole("button", { name: "Set aside for now" })).toBeInTheDocument();
      expect(getByText("Setting a question aside is connected, and so is answering one in your own words. Proposing a change, confirming one, and correcting a document are not.")).toBeInTheDocument();
      // The read supplies an invitation to answer in a sentence. Nothing here
      // can take one, so a real vault's invitation is never put to a person.
      expect(queryByText("Write an answer")).not.toBeInTheDocument();
      expect(queryByText(/invites an answer in a sentence/)).not.toBeInTheDocument();

      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
      expect(queryByText("Private checking")).not.toBeInTheDocument();
      expect(queryByText("live-document")).not.toBeInTheDocument();
      expect(queryByText("Is this your account?")).not.toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders a complete backend canonical account display byte-for-byte", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const canonicalDisplay = "Canonical backend display — USD 202.50";
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "complete-account", name: "Complete account", balance: { amount: "202.50", display: canonicalDisplay, measure: "balance", currency: "USD", dated: "2026-08-18", coverage: "Statement period ending 2026-08-18", provenance: "document live-doc, page 7", grade: "verified" } }] }
          : payload.surface === "documents" ? { documents: [] } : payload.surface === "trust" ? trustPayload : payload.surface === "activity" ? activityPayload : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getByLabelText, getByRole, getAllByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getAllByText(canonicalDisplay).length).toBeGreaterThan(0));
      expect(queryByText("202.50")).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(getAllByText(canonicalDisplay).length).toBeGreaterThan(0);
      expect(queryByText("202.50")).not.toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders an explicit empty state for every private-vault destination", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        const data = payload.surface === "overview"
          ? { accounts: [] }
          : payload.surface === "documents"
            ? { documents: [] }
            : payload.surface === "trust"
              ? trustPayload
              : payload.surface === "activity"
                ? activityPayload
              : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getAllByText, getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(getByText("Local source", { selector: ".privacy-lock span" })).toBeInTheDocument();
      expect(getByText("Every vault this app opens, the sample one included, is opened through the local desktop host on this machine.")).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("No documents yet", { selector: "strong" })).toBeInTheDocument();
      expect(getAllByRole("button", { name: "Open the sample vault" })[0]).toBeInTheDocument();
      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      expect(getByText("Nothing needs you right now", { selector: "strong" })).toBeInTheDocument();
      expect(queryByRole("button", { name: "Open the sample vault" })).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /activity.*what moved/i }));
      // Activity is a read now. A vault that knows of nothing moving says so,
      // which is not the same as nothing having moved.
      expect(getAllByText(moments.activity_empty).length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /trust.*how it works/i }));
      // Trust is a read now, and a vault that has sent nothing says so with the
      // same prominence as one that has. That emptiness is the record.
      expect(getAllByText(moments.outbound_none).length).toBeGreaterThan(0);
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      await user.click(getAllByRole("button", { name: "Close this vault" })[0]);
      expect(getAllByText("No vault open")[0]).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("reports a partial private-vault read without discarding successful surfaces", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") {
          return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        }
        if (payload.surface === "documents") {
          throw new Error("private path must stay bounded");
        }
        const data = payload.surface === "overview"
          ? { accounts: [{ account: "kept-account", name: "Kept account", balance: { amount: "1", grade: "unverified" } }] }
          : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText, getAllByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getAllByRole("status")[0]).toHaveTextContent("The private vault opened, but some surfaces could not be read. Your vault was not changed."));
      expect(getAllByText("Kept account", { ignore: "script, style, .figure-invitation" })).toHaveLength(2);
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("validates the vault-open form before calling the host", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let calls = 0;
    window.orionVivaBridge = {
      request: async <T,>() => {
        calls += 1;
        return { protocol: "1.0", request_id: "req", ok: true, result: { state: "opened" } as T };
      },
    };

    try {
      const { getByRole, getByText } = render(<App />);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByText("Enter a vault directory and passphrase to open a local vault.")).toBeInTheDocument();
      expect(calls).toBe(0);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows an opening state while the host request is pending", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let resolveRequest: (() => void) | undefined;
    window.orionVivaBridge = {
      request: <T,>() => new Promise<{ protocol: string; request_id: string; ok: boolean; result: T }>((resolve) => {
        resolveRequest = () => resolve({
          protocol: "1.0",
          request_id: "req",
          ok: true,
          result: {} as T,
        });
      }),
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      const control = getByRole("button", { name: "Opening vault..." });
      expect(control).not.toHaveAttribute("disabled");
      expect(control).toHaveAttribute("aria-disabled", "true");
      // Both sentences reach the control: what a lost passphrase costs, which
      // is what this form is for, and why pressing again does nothing.
      expect(control).toHaveAccessibleDescription("This opens the vault in the folder you name. If there is none there, nothing is made unless you say so above — a folder named by mistake would otherwise look like an empty vault. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it. Your vault is answering the last request. Pressing again does nothing until it has.");
      resolveRequest?.();
      await waitFor(() => expect(getByRole("button", { name: "Open local vault" })).not.toHaveAttribute("aria-disabled", "true"));
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("shows a bounded open error and clears the passphrase", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const secret = "correct horse battery staple";
    window.orionVivaBridge = {
      request: async <T,>() => ({
        protocol: "1.0",
        request_id: "req",
        ok: false,
        error: { code: "vault_open_failed", message: "internal details must not reach the UI" },
      } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T }),
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), secret);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getAllByRole("status")[0]).toHaveTextContent("The local vault could not be opened.");
      expect(getAllByRole("status")[0]).not.toHaveTextContent(secret);
      expect(getByLabelText("Passphrase")).toHaveValue("");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("says what became of a question set aside and moves focus once the write has settled", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let setAside = false;
    const questions = () => (setAside
      ? [{ id: "second-question", kind: "merchant", text: "What is this payment for?", why: "The merchant is unknown." }]
      : [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." },
         { id: "second-question", kind: "merchant", text: "What is this payment for?", why: "The merchant is unknown." }]);
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.review.decline") {
          setAside = true;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "completed", message: "Set aside until something changes.", state: null, reason: null } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : { questions: questions(), total: setAside ? 1 : 2, invite: "Write an answer", answered_by_document: "A document answers this" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /review.*what needs you/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /review.*what needs you/i }));

      await user.click(getByRole("button", { name: "Set aside for now" }));

      // The question leaves the queue and the control that was pressed goes
      // with it, so what happened is said where it can still be read and focus
      // lands on the question the queue moved to.
      await waitFor(() => expect(getByRole("heading", { name: "What is this payment for?" })).toBeInTheDocument());
      await waitFor(() => expect(document.getElementById("selected-question-title")).toHaveFocus());
      expect(getAllByRole("status")[0]).toHaveTextContent("Set aside until something changes.");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("never disables the pressed control, so a refusal leaves it under the person's hands", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let answerDecline: () => void = () => {};
    const declineAnswered = new Promise<void>((resolve) => { answerDecline = resolve; });
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.review.decline") {
          await declineAnswered;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "refused", message: "That question is no longer open.", state: null, reason: "not_open" } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : { questions: [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, invite: "Write an answer", answered_by_document: "A document answers this" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /review.*what needs you/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /review.*what needs you/i }));

      const control = getByRole("button", { name: "Set aside for now" });
      await user.click(control);

      // The vault has not answered yet. A focused element that becomes disabled
      // is blurred to the document body by the browser this ships in, and this
      // test environment does not implement that blur — so what is asserted
      // through the whole in-flight window is that the control was never
      // disabled, which is observable in both.
      await waitFor(() => expect(getAllByRole("status")[0]).toHaveTextContent("Setting this question aside"));
      expect(control).not.toBeDisabled();
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveFocus();

      answerDecline();

      // Nothing moved, so the control the person must use again is still under
      // their hands and the screen does not take focus off it.
      await waitFor(() => expect(getAllByRole("status")[0]).toHaveTextContent("That question is no longer open."));
      expect(control).not.toBeDisabled();
      expect(control).toHaveFocus();
    } finally {
      answerDecline();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("gives focus somewhere to land when the read after a write fails, and says the queue is unread", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let setAside = false;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.review.decline") {
          setAside = true;
          return { protocol: "1.0", request_id: "decline", ok: true, result: { kind: "completed", message: "Set aside until something changes.", state: null, reason: null } as T };
        }
        const surface = payload.surface;
        if (surface === "review" && setAside) throw new Error("bounded read failure");
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? { documents: [] }
            : { questions: [{ id: "first-question", kind: "identity", text: "Is this your account?", why: "Account identity is unresolved." }], total: 1, invite: "Write an answer", answered_by_document: "A document answers this" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getAllByRole, getByLabelText, getByRole, getByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /review.*what needs you/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /review.*what needs you/i }));

      await user.click(getByRole("button", { name: "Set aside for now" }));

      // The write took and the read that followed did not, so the panel and the
      // control are both gone. What happened is still said, it says the queue
      // was not read again, and focus lands on it rather than on the body.
      await waitFor(() => expect(getByText("Review could not be read")).toBeInTheDocument());
      expect(getAllByRole("status")[0]).toHaveTextContent("Set aside until something changes.");
      expect(getAllByRole("status")[0]).toHaveTextContent("This screen could not read the queue afterwards, so it no longer knows what is still open.");
      await waitFor(() => expect(document.getElementById("review-outcome-title")).toHaveFocus());
      expect(document.activeElement).not.toBe(document.body);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("sends one document per gesture, reads the vault again, and says only what the vault said", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: Array<{ operation: string; payload: Record<string, unknown> }> = [];
    let captured = false;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        operations.push({ operation, payload });
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") {
          captured = true;
          return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        }
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] }
          : surface === "documents" ? (captured
            ? { documents: [{ id: "captured-identity", doc_type: "statement", filename: "quarter-close.pdf", resolved: false, raw_available: true, reading: "never_read" }], reading_sentence: SAVED_NO_READER }
            : { documents: [], reading_sentence: "" })
            : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      pickDocumentPaths: async () => ["/chosen/first.pdf"],
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { container, getAllByText, getByLabelText, getByRole, getByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /documents.*what supports it/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("Nothing has been added to this vault yet. Choose a file to add one, or open the sample vault to see what a full one looks like.")).toBeInTheDocument();

      operations.length = 0;
      await user.click(getByRole("button", { name: "Choose a file" }));

      // One frame carrying the path and nothing else. The read that follows
      // asks for documents alone.
      await waitFor(() => expect(container.querySelector(".document-library")).toHaveTextContent("quarter-close.pdf"));
      expect(operations.map((frame) => frame.operation)).toEqual(["viva.documents.upload", "viva.surface.read"]);
      expect(operations[0].payload).toEqual({ path: "/chosen/first.pdf" });
      expect(operations[1].payload.surface).toBe("documents");
      expect(getAllByText(SAVED_NO_READER).length).toBeGreaterThan(0);

      // A dropped path is the same request from the same screen: a path
      // crosses, and nothing about the file's contents does.
      operations.length = 0;
      expect(listen).not.toBeNull();
      await act(async () => { listen?.(["/dropped/second.pdf"]); });
      await waitFor(() => expect(operations.map((frame) => frame.operation)).toEqual(["viva.documents.upload", "viva.surface.read"]));
      expect(operations[0].payload).toEqual({ path: "/dropped/second.pdf" });

      // More than one document in one gesture is refused in this window,
      // before anything is sealed, and nothing is sent.
      operations.length = 0;
      await act(async () => { listen?.(["/dropped/third.pdf", "/dropped/fourth.pdf"]); });
      expect(operations).toEqual([]);
      const refusal = container.querySelector(".notice");
      expect(refusal).toHaveTextContent("This takes one document at a time. Nothing was added.");
      expect(refusal).toHaveAttribute("data-kind", "refused");
      expect(refusal).toHaveClass("notice-refused");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("names what a lost passphrase costs to the field and the control beside it", async () => {
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = { request: async <T,>(frame: { requestId: string }) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) };
    const consequence = "This opens the vault in the folder you name. If there is none there, nothing is made unless you say so above — a folder named by mistake would otherwise look like an empty vault. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it.";
    try {
      const { container, getByLabelText, getByRole, getByText } = render(<App />);
      expect(getByText(consequence)).toBeInTheDocument();
      expect(getByLabelText("Passphrase")).toHaveAccessibleDescription(consequence);
      expect(getByRole("button", { name: "Open local vault" })).toHaveAccessibleDescription(consequence);
      // The nesting the capture stylesheet is written against.
      expect(container.querySelector(".vault-open-form .vault-passphrase-consequence")).not.toBeNull();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("says so when the file picker could not be opened, and stays quiet when it was closed with nothing chosen", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let picker: () => Promise<readonly string[]> = async () => [];
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      pickDocumentPaths: () => picker(),
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /documents.*what supports it/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));

      // Closed with nothing chosen is a person changing their mind.
      await user.click(getByRole("button", { name: "Choose a file" }));
      expect(queryByText("The file picker could not be opened, so nothing was chosen and nothing was added to this vault.")).not.toBeInTheDocument();

      // A picker that could not be opened is a control that did not work.
      picker = async () => { throw new Error("the dialog never opened"); };
      await user.click(getByRole("button", { name: "Choose a file" }));
      await waitFor(() => expect(getByText("The file picker could not be opened, so nothing was chosen and nothing was added to this vault.")).toBeInTheDocument());
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("takes a person to the receipt when a file is dropped on another screen, and keeps it there afterwards", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { getAllByText, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /overview.*your picture/i })).toBeInTheDocument());
      expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();

      // The drop lands while another screen is open. Something durable happens,
      // so the screen that can say what became of it is what the person sees.
      await act(async () => { listen?.(["/dropped/first.pdf"]); });
      await waitFor(() => expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument());
      await waitFor(() => expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1));

      // What was written is the session's, not the panel's: leaving the screen
      // and returning does not discard the receipt for it.
      await user.click(getByRole("button", { name: /overview.*your picture/i }));
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("refuses a picker that hands back more than one document, and seals none of them", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: string[] = [];
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        operations.push(operation);
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      // A shim that lost its cap. The refusal is at the door both gestures
      // pass through, so nothing is sealed here either.
      pickDocumentPaths: async () => ["/chosen/first.pdf", "/chosen/second.pdf"],
    };

    try {
      const { container, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /documents.*what supports it/i })).toBeInTheDocument());
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));

      operations.length = 0;
      await user.click(getByRole("button", { name: "Choose a file" }));

      await waitFor(() => expect(container.querySelector(".notice")).toHaveTextContent("This takes one document at a time. Nothing was added."));
      expect(operations).toEqual([]);
      expect(container.querySelector(".notice")).toHaveAttribute("data-kind", "refused");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("sends one vault-open request however many times the control is pressed", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const operations: string[] = [];
    let release: (() => void) | undefined;
    window.orionVivaBridge = {
      request: <T,>({ operation }: { requestId: string; operation: string }) => {
        operations.push(operation);
        return new Promise<{ protocol: string; request_id: string; ok: boolean; result: T }>((resolve) => {
          release = () => resolve({ protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T });
        });
      },
    };

    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");

      // The form that creates a vault, on a transport that answers one request
      // before it reads the next. Pressing again while it waits sends nothing.
      await user.click(getByRole("button", { name: "Open local vault" }));
      const waiting = getByRole("button", { name: "Opening vault..." });
      await user.click(waiting);
      await user.click(waiting);
      expect(operations).toEqual(["bridge.open_vault"]);

      release?.();
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("announces the move when a dropped file changes the screen from under a person", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    let listen: ((paths: readonly string[]) => void) | null = null;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        if (operation === "viva.documents.upload") return { protocol: "1.0", request_id: "upload", ok: true, result: { kind: "completed", message: SAVED_NO_READER, state: null, reason: null } as T };
        const surface = payload.surface;
        const data = surface === "overview" ? { as_of: "2026-08-18", accounts: [] } : surface === "documents" ? { documents: [], reading_sentence: "" } : { questions: [], total: 0, invite: "", answered_by_document: "" };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface, job_id: "job", data } as T };
      },
      subscribeToDroppedPaths: async (handler: (paths: readonly string[]) => void) => { listen = handler; return () => { listen = null; }; },
    };

    try {
      const { container, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("button", { name: /overview.*your picture/i })).toBeInTheDocument());

      // A drawer is open, so the screen under it is inert and anything landing
      // there would be announced to nobody and painted behind the drawer.
      await user.click(getByRole("button", { name: /ask viva/i }));
      expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();

      await act(async () => { listen?.(["/dropped/first.pdf"]); });

      await waitFor(() => expect(container.querySelector("main")).not.toHaveAttribute("inert"));
      expect(queryByRoleIn(container, "dialog")).toBeNull();
      await waitFor(() => expect(document.getElementById("page-title")).toHaveTextContent("Documents"));
      await waitFor(() => expect(document.getElementById("page-title")).toHaveFocus());
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});

describe("naming a folder", () => {
  it("makes no vault unless a person said to, and repeats the vault's own sentence", async () => {
    // A path typed with a letter wrong used to answer as an opened, brand-new
    // empty vault, which reads to somebody as their records having vanished.
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const sent: Array<Record<string, unknown>> = [];
    window.orionVivaBridge = {
      request: async <T,>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        sent.push(frame.payload);
        return { protocol: "2.0", request_id: frame.requestId, ok: false, error: { code: "vault_absent", message: moments.vault_absent } } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T };
      },
    };
    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/typo");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(sent[0].create).toBe(false);
      expect(getAllByRole("status")[0]).toHaveTextContent(moments.vault_absent);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("asks for a vault to be made only when the box is ticked, and says so on the control", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    const sent: Array<Record<string, unknown>> = [];
    window.orionVivaBridge = {
      request: async <T,>(frame: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (frame.operation === "bridge.open_vault") sent.push(frame.payload);
        const data = frame.payload.surface === "overview" ? { accounts: [] } : frame.payload.surface === "documents" ? { documents: [] } : frame.payload.surface === "trust" ? trustPayload : frame.payload.surface === "activity" ? activityPayload : { questions: [], total: 0 };
        return { protocol: "2.0", request_id: frame.requestId, ok: true, result: (frame.operation === "bridge.open_vault" ? { state: "created" } : { surface: frame.payload.surface, job_id: "job", data }) as T };
      },
    };
    try {
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/new");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByLabelText("Make a new vault in that folder"));
      expect(getByRole("button", { name: "Make and open vault" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: "Make and open vault" }));

      expect(sent[0].create).toBe(true);
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });

  it("never repeats machine text from a code whose message is not a reviewed sentence", async () => {
    const user = userEvent.setup();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>() => ({ protocol: "2.0", request_id: "r", ok: false, error: { code: "handler_failed", message: "Everyday Checking has 1200.00" } } as { protocol: string; request_id: string; ok: boolean; error: { code: string; message: string }; result?: T }),
    };
    try {
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getAllByRole("status")[0]).not.toHaveTextContent("Everyday Checking");
      expect(getAllByRole("status")[0]).toHaveTextContent("The local vault could not be opened.");
    } finally {
      window.orionVivaBridge = previousBridge;
    }
  });
});
