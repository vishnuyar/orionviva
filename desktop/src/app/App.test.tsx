import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { createRef } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App, ConversationDialogShell } from "./App";
// The sentences a person is told, read from the pack that ships them.
import moments from "../../../product/viva/persona/pack-v20/moments.json";

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

describe("minimal shell", () => {
  it("opens on the financial picture", () => {
    const { getByRole, getByText, getAllByText } = render(<App />);
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(getByText("$48,240.18")).toBeInTheDocument();
    expect(getByText("Supported by more than one source or matching record.")).toBeInTheDocument();
    expect(getByText("Sample vault")).toBeInTheDocument();
    expect(getByText("Sample data boundary")).toBeInTheDocument();
    const disclosure = getByRole("complementary", { name: "Vault source" });
    const hero = document.querySelector(".hero-grid");
    expect(disclosure.compareDocumentPosition(hero as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lets the overview spotlight select an account and open its detail", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = render(<App />);

    await user.click(getAllByText("Long view savings").find((node) => node.closest("button")?.classList.contains("account-card-button"))!.closest("button")!);

    expect(getByText("Selected account")).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
    expect(getByText("Long view savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByText("Savings statements, Aug 2022–Jul 2026")).toBeInTheDocument();
  });

  it("pairs every overview account amount with a distinct stable-id source control", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText, getAllByText } = render(<App />);
    const cards = Array.from(container.querySelectorAll<HTMLElement>(".account-card"));

    expect(cards).toHaveLength(5);
    expect(getAllByText("$8,240.18")).toHaveLength(1);
    cards.forEach((card) => {
      const amount = card.querySelector(".account-amount");
      const selection = card.querySelector(".account-card-button");
      const source = card.querySelector(".proof-link");
      expect(amount).not.toBeNull();
      expect(selection).not.toBeNull();
      expect(source).not.toBeNull();
      expect(selection).not.toBe(source);
      expect(selection?.contains(source)).toBe(false);
    });

    const savingsCard = cards[1];
    await user.click(savingsCard.querySelector(".account-card-button") as HTMLElement);
    expect(getByText("Long view savings", { selector: ".coverage-account-title" })).toBeInTheDocument();

    await user.click(savingsCard.querySelector(".proof-link") as HTMLElement);
    expect(getByRole("heading", { name: "north-river-savings-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(getByText("Synthetic PDF · savings statement · page 1")).toBeInTheDocument();
  });

  it("moves through shell destinations without leaving the page", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).toBeInTheDocument();
  });

  it("keeps the sample source before facts with one page heading and one current destination", async () => {
    const user = userEvent.setup();
    const view = render(<App />);
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
    const { container, getByRole } = render(<App />);
    await user.click(getByRole("button", { name: "View sample document journey" }));
    expect(getByRole("status")).toHaveTextContent("Opened the fictional sample document journey. No file was selected, no vault event was written, no model call was made, and nothing was sent.");
    await waitFor(() => expect(getByRole("region", { name: "A sample document journey" })).toHaveFocus());
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("focuses the static capture explanation when already on Documents", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: "View sample document journey" }));
    await waitFor(() => expect(getByRole("region", { name: "A sample document journey" })).toHaveFocus());
  });

  it("does not resurrect capture focus after navigating away and back from another destination", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = render(<App />);
      fireEvent.click(getByRole("button", { name: "View sample document journey" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "A sample document journey" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect capture focus after navigating away and back from Documents", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getByRole } = render(<App />);
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      fireEvent.click(getByRole("button", { name: "View sample document journey" }));
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("region", { name: "A sample document journey" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("shows the demo vault boundary and can reset it", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = render(<App />);

    expect(getByText("Sample vault")).toBeInTheDocument();
    expect(getByText("Fictional sample data")).toBeInTheDocument();
    expect(getAllByText("Every name, document, and figure in this vault is fictional and stored with the app.")).toHaveLength(1);
    expect(getByText("Every name, document, and figure here is fictional.")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /reset sample vault/i }));
    expect(getByRole("status")).toHaveTextContent("Sample vault reset to the fictional data stored with the app.");
    expect(getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
  });

  it.each([
    ["Overview", "OverviewYour picture"],
    ["Accounts", "AccountsWhere money sits"],
    ["Activity", "ActivityWhat moved"],
    ["Documents", "DocumentsWhat supports it"],
    ["Review", "ReviewWhat needs you"],
    ["Trust", "TrustHow it works"],
  ] as const)("resets a fresh %s destination to one mature Overview selection", async (destination, navigationName) => {
    const user = userEvent.setup();
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    const view = render(<App />);
    await user.click(view.getByRole("button", { name: navigationName }));

    if (destination === "Overview") fireEvent.click(view.container.querySelectorAll(".account-card-button")[1]);
    if (destination === "Accounts") fireEvent.click(view.container.querySelectorAll(".detail-row-button")[1]);
    if (destination === "Activity") await user.type(view.getByLabelText("Search fictional activity"), "paycheck");
    if (destination === "Documents") fireEvent.click(view.container.querySelectorAll(".document-list .detail-row-button")[1]);
    if (destination === "Review") fireEvent.click(view.container.querySelectorAll(".review-question-row")[1]);
    if (destination === "Trust") fireEvent.click(view.container.querySelector(".trust-capabilities details:not([open]) summary") as HTMLElement);

    await user.click(view.getByRole("button", { name: "Reset sample vault" }));
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.container.querySelectorAll("h1")).toHaveLength(1);
    expect(view.container.querySelectorAll('#primary-navigation [aria-current="page"]')).toHaveLength(1);
    expect(view.getByRole("button", { name: "OverviewYour picture" })).toHaveAttribute("aria-current", "page");
    expect(view.getByText("Sample vault · Fictional sample data")).toBeInTheDocument();
    expect(view.getByText("$48,240.18")).toBeInTheDocument();
    expect(view.getByRole("status")).toHaveTextContent("Sample vault reset to the fictional data stored with the app.");
    expect(view.queryAllByRole("dialog")).toHaveLength(0);
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(view.container.querySelectorAll('.account-card-button[aria-pressed="true"]')).toHaveLength(1);
  });

  it.each(["Evidence", "Viva"] as const)("does not resurrect explicitly closed %s after a sample reset", async (overlay) => {
    const user = userEvent.setup();
    const view = render(<App />);
    if (overlay === "Evidence") {
      await user.click(view.getByRole("button", { description: "View evidence for Net worth" }));
      expect(view.getByRole("dialog", { name: "Evidence for Net worth" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close evidence" }));
    } else {
      await user.click(view.getByRole("button", { name: "Ask Viva" }));
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      await user.click(view.getByRole("button", { name: "Close Viva conversation" }));
    }
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(view.getByRole("button", { name: "Reset sample vault" }));
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
    expect(view.getByRole("status")).toHaveTextContent("Sample vault reset to the fictional data stored with the app.");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it.each(["Evidence", "Viva"] as const)("cancels captured stale %s restoration before a reset transition", (overlay) => {
    const frames = installCapturedAnimationFrames();
    try {
      const view = render(<App />);
      if (overlay === "Evidence") {
        const opener = view.getByRole("button", { description: "View evidence for Net worth" });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      } else {
        const opener = view.getByRole("button", { name: "Ask Viva" });
        opener.focus();
        fireEvent.click(opener);
        fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      }
      const reset = view.getByRole("button", { name: "Reset sample vault" });
      reset.focus();
      fireEvent.click(reset);
      frames.runCaptured();
      expect(view.queryByRole("dialog")).not.toBeInTheDocument();
      expect(view.getByRole("heading", { name: "Your financial picture" })).toBeInTheDocument();
      expect(view.getByText("Sample vault · Fictional sample data")).toBeInTheDocument();
      expect(view.getByText("$48,240.18")).toBeInTheDocument();
      expect(view.getByRole("button", { name: "Ask Viva" })).not.toHaveFocus();
      expect(reset.isConnected ? reset : view.getByRole("heading", { name: "Your financial picture" })).toHaveFocus();
      expect(document.documentElement.style.overflow).toBe("");
      expect(document.body.style.overflow).toBe("");
    } finally {
      frames.restore();
    }
  });

  it("shows the supplied review total without adding a navigation count", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    expect(getByRole("heading", { name: "Sample review queue" })).toBeInTheDocument();
    expect(getByText("Open-question total from this read")).toBeInTheDocument();
    expect(getByText("4", { selector: ".review-summary > strong" })).toBeInTheDocument();
    expect(container.querySelector(".nav-count")).toBeNull();
  });

  it("opens the Viva conversation drawer with cited turns and refusal states", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByRole } = render(<App />);

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    expect(getByText("Selecting a sample prompt changes only the displayed detail. It does not send a prompt, call a model, write a vault event, create an outbound action, or make a durable change.")).toBeInTheDocument();
    expect(getByText("The sample includes July figures, and one brokerage statement page still needs a human decision.")).toBeInTheDocument();
    expect(getByText("Fictional citation text: Taxable Brokerage statement, pages 1–2")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("picture is complete");
    expect(document.body).not.toHaveTextContent("Brokerage statement, page 4");
    expect(getByText("I can point to the question and the evidence, but the category still needs your answer.")).toBeInTheDocument();
    expect(getByRole("button", { name: /what changed this month\?/i })).toBeInTheDocument();

    await user.click(getAllByRole("button", { name: /show the evidence/i })[0]);
    expect(getByRole("button", { name: /show the evidence/i })).toHaveClass("active");

    await user.click(getByRole("button", { name: /close viva conversation/i }));
    expect(getByRole("button", { name: /ask viva/i })).toBeInTheDocument();
  });

  it("moves keyboard focus into the Viva dialog when it opens", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<App />);

    await user.click(getByRole("button", { name: /ask viva/i }));

    expect(getByRole("dialog", { name: "Viva conversation" })).toContainElement(document.activeElement as HTMLElement | null);
  });

  it("lets a keyboard user dismiss the Viva dialog with Escape", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = render(<App />);

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
      const { getByRole } = render(<App />);
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
    const { container, getByRole } = render(<App />);
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
    const { getByRole, queryByRole } = render(<App />);
    const opener = getByRole("button", { name: "Ask Viva" });
    await user.click(opener);
    fireEvent.click(getByRole("button", { name: "Reset sample vault", hidden: true }));
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    expect(document.querySelector("main")).not.toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).not.toHaveAttribute("inert");
  });

  it("keeps the Viva shell dismissible when its body throws and recovers on reset", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const dismiss = vi.fn();
    const drawer = createRef<HTMLElement>();
    const close = createRef<HTMLButtonElement>();
    try {
      const view = render(<ConversationDialogShell mode="demo" resetKey="request-1-demo" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><ThrowingConversationBody /></ConversationDialogShell>);
      expect(view.getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
      expect(view.getByText("This surface could not be shown")).toBeInTheDocument();
      fireEvent.click(view.getByRole("button", { name: "Close Viva conversation" }));
      expect(dismiss).toHaveBeenCalledTimes(1);
      view.rerender(<ConversationDialogShell mode="live" resetKey="request-2-live" drawerRef={drawer} closeRef={close} onDismiss={dismiss}><div>Recovered supplied body</div></ConversationDialogShell>);
      expect(view.getByText("Recovered supplied body")).toBeInTheDocument();
      expect(view.getByText("This read-only drawer shows only conversation fields supplied to the interface. It cannot accept or send a prompt.")).toBeInTheDocument();
    } finally {
      error.mockRestore();
    }
  });

  it("keeps the overview selected account spotlight in sync with selection", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = render(<App />);

    expect(getByText("Everyday checking", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByText("Checking statements, Aug 2022–Jul 2026")).toBeInTheDocument();

    await user.click(container.querySelectorAll(".account-card-button")[4] as HTMLElement);

    expect(getByText("Taxable Brokerage", { selector: ".coverage-account-title" })).toBeInTheDocument();
    expect(getByText("Brokerage statements, Aug 2022–Jul 2026")).toBeInTheDocument();
    expect(getByRole("button", { name: /open accounts/i })).toBeInTheDocument();
  });

  it("shows the selected document detail inside documents", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, getAllByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Sample lifecycle" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Sample documents" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: /northgate-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByText("2 pages")).toBeInTheDocument();
    expect(getAllByText("Waiting for a reader").length).toBeGreaterThan(0);
    expect(getByText("Synthetic PDF · brokerage statement · pages 1–2")).toBeInTheDocument();
  });

  it("navigates from a document to related evidence without losing provenance", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "DocumentsWhat supports it" }));
    await user.click(getByRole("button", { name: /northgate-brokerage-2026-05-to-2026-07\.pdf/i }));
    await user.click(getByRole("button", { name: /north river savings statement/i }));
    expect(getByRole("heading", { name: "north-river-savings-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(getByText("Synthetic PDF · savings statement · page 1")).toBeInTheDocument();
    expect(getByRole("button", { name: /Taxable Brokerage statementcorroborates.*pages 1–2/i })).toBeInTheDocument();
  });

  it("routes sample figure, account, and activity proof links to exact document ids", async () => {
    const user = userEvent.setup();
    const { container, getByRole, getByText } = render(<App />);

    // The picture's figure carries one evidence control and no proof-link row:
    // a citation the read gave no label becomes a button announcing the word
    // "unavailable", and a stack of them under one number reads as broken
    // links where the product claimed a receipt. Its route to a document runs
    // through the drawer, and the case above this one drives it.
    await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
    expect(getByText("Supporting documents")).toBeInTheDocument();
    await user.click(container.querySelector(".detail-panel .proof-link") as HTMLElement);
    expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(container.querySelector(".signal-row .proof-link") as HTMLElement);
    expect(getByRole("heading", { name: "silverline-checking-2026-06.pdf" })).toBeInTheDocument();
    expect(getByText("Synthetic PDF · checking statement · June 2026 · page 1")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /activity.*what moved/i }));
    await user.click(container.querySelector(".activity-detail .proof-link") as HTMLElement);
    expect(getByRole("heading", { name: "silverline-checking-2026-06.pdf" })).toBeInTheDocument();
    expect(getByText("Synthetic PDF · checking statement · June 2026 · page 1")).toBeInTheDocument();
  });

  it("opens the fictional Activity explorer without a Review action", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = render(<App />);
    await user.click(getByRole("button", { name: /activity.*what moved/i }));
    expect(getByText("Movements, their supplied context, and the evidence behind each displayed figure.")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Sample activity" })).toBeInTheDocument();
    expect(getByRole("textbox", { name: "Search fictional activity" })).toBeInTheDocument();
    expect(queryByRole("button", { name: /go to review queue/i })).not.toBeInTheDocument();
  });

  it("discards a pending document-heading focus when the source request changes", () => {
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
      const { container, getByRole } = render(<App />);
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).not.toHaveFocus();

      fireEvent.click(getByRole("button", { name: "Reset sample vault" }));
      expect(cancelAnimationFrame).toHaveBeenCalled();
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();

      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).not.toHaveFocus();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("discards pending capture focus when the source request changes", () => {
    const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    let frameId = 0;
    globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { frameId += 1; pendingFrames.set(frameId, callback); return frameId; });
    globalThis.cancelAnimationFrame = vi.fn((id: number) => pendingFrames.delete(id));

    try {
      const { getByRole } = render(<App />);
      fireEvent.click(getByRole("button", { name: "View sample document journey" }));
      expect(getByRole("region", { name: "A sample document journey" })).not.toHaveFocus();
      fireEvent.click(getByRole("button", { name: "Reset sample vault" }));
      pendingFrames.forEach((callback) => callback(performance.now()));
      pendingFrames.clear();
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      expect(getByRole("region", { name: "A sample document journey" })).not.toHaveFocus();
    } finally {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    }
  });

  it("does not resurrect document-title focus after leaving and returning to Documents", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = render(<App />);
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: "AccountsWhere money sits" }));
      fireEvent.click(getByRole("button", { name: "DocumentsWhat supports it" }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect document-title focus after selection diverges and returns", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { container, getByRole } = render(<App />);
      fireEvent.click(container.querySelector(".account-card .proof-link") as HTMLElement);
      fireEvent.click(getByRole("button", { name: /northgate-brokerage-2026-05-to-2026-07\.pdf/i }));
      fireEvent.click(getByRole("button", { name: /silverline-checking-2026-07\.pdf/i }));
      getByRole("heading", { name: "Documents" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("opens fresh figure evidence and routes its exact source to the selected document heading", async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = render(<App />);
    const trigger = getByRole("button", { description: "View evidence for Net worth" });

    await user.click(trigger);
    expect(getByRole("dialog", { name: "Evidence for Net worth" })).toBeInTheDocument();
    expect(getByRole("button", { name: "Close evidence" })).toHaveFocus();
    expect(document.querySelector("main")).toHaveAttribute("inert");
    expect(document.getElementById("primary-navigation-drawer")).toHaveAttribute("inert");
    await user.click(getByRole("button", { name: "Open silverline-checking-2026-07.pdf" }));

    expect(queryByRole("dialog", { name: "Evidence for Net worth" })).not.toBeInTheDocument();
    await waitFor(() => expect(getByRole("heading", { name: "silverline-checking-2026-07.pdf" })).toHaveFocus());
  });

  it("keeps Evidence, Viva, and narrow navigation mutually exclusive", async () => {
    installResponsiveMatchMedia(390);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = render(<App />);

    await user.click(getByRole("button", { description: "View evidence for Net worth" }));
    expect(getByRole("dialog", { name: "Evidence for Net worth" })).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Ask Viva", hidden: true }));
    expect(queryByRole("dialog", { name: "Evidence for Net worth" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();

    fireEvent.click(getByRole("button", { name: "Open navigation" }));
    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
    installResponsiveMatchMedia(1440);
  });

  it("shows the selected queue item inside review", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);
    await user.click(getByRole("button", { name: "ReviewWhat needs you" }));
    await user.click(getByRole("button", { name: /duplicate subscription/i }));
    expect(getByRole("heading", { name: "Duplicate subscription" })).toBeInTheDocument();
    expect(getByText("Set-aside boundary")).toBeInTheDocument();
    expect(getByText("Card statement, page 1")).toBeInTheDocument();
    expect(getByRole("button", { name: /harborline signature card statement.*page 1/i })).toBeInTheDocument();
  });

  it("opens and focuses an exact review question from Overview", async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole, queryByRole } = render(<App />);
    await user.click(getAllByRole("button", { name: "View question" })[1]);
    await waitFor(() => expect(getByRole("heading", { name: "Duplicate subscription" })).toHaveFocus());
    expect(queryByRole("button", { name: /^Answer$/i })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /^Confirm$/i })).not.toBeInTheDocument();
  });

  it("does not resurrect Overview review focus after leaving Review", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = render(<App />);
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /trust.*how it works/i }));
      fireEvent.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "Duplicate subscription" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the selected identity changes", () => {
    const frames = installCapturedAnimationFrames();
    try {
      const { getAllByRole, getByRole } = render(<App />);
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      fireEvent.click(getByRole("button", { name: /held statement page/i }));
      fireEvent.click(getByRole("button", { name: /duplicate subscription/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "Duplicate subscription" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not resurrect Overview review focus after the vault request and mode change", async () => {
    const frames = installCapturedAnimationFrames();
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = {
      request: async <T,>({ operation, payload }: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
        if (operation === "bridge.open_vault") return { protocol: "1.0", request_id: "open", ok: true, result: { state: "opened" } as T };
        const data = payload.surface === "overview" ? { accounts: [] } : payload.surface === "documents" ? { documents: [] } : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };
    try {
      const user = userEvent.setup();
      const { getAllByRole, getByLabelText, getByRole } = render(<App />);
      fireEvent.click(getAllByRole("button", { name: "View question" })[1]);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      await waitFor(() => expect(getByRole("heading", { name: "Review queue" })).toBeInTheDocument());
      await user.click(getByRole("button", { name: "Open sample vault" }));
      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      getByRole("heading", { name: "Review" }).focus();
      frames.runCaptured();
      expect(getByRole("heading", { name: "Merchant category" })).not.toHaveFocus();
    } finally {
      window.orionVivaBridge = previousBridge;
      frames.restore();
    }
  });

  it("keeps the selected document when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, queryByRole } = render(<App />);

    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    await user.click(getByRole("button", { name: /northgate-brokerage-2026-05-to-2026-07\.pdf/i }));
    expect(getByRole("heading", { name: "northgate-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    await user.click(getByRole("button", { name: /documents.*what supports it/i }));
    expect(getByRole("heading", { name: "northgate-brokerage-2026-05-to-2026-07.pdf" })).toBeInTheDocument();
    expect(queryByRole("button", { name: /open page review/i })).not.toBeInTheDocument();
    expect(getByText("Page and source-region review are not connected.")).toBeInTheDocument();
  });

  it("keeps the selected account when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = render(<App />);

    await user.click(container.querySelectorAll(".account-card-button")[1] as HTMLElement);
    await user.click(getByRole("button", { name: /open accounts/i }));
    expect(getByRole("heading", { name: "Sample accounts" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Long view savings" })).toBeInTheDocument();
    expect(getByText("Savings statements, Aug 2022–Jul 2026")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /overview.*your picture/i }));
    expect(getByText("Long view savings", { selector: ".coverage-account-title" })).toBeInTheDocument();
  });

  it("keeps the selected review question when navigation moves away and back", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText } = render(<App />);

    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    await user.click(getByRole("button", { name: /merchant category/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    await user.click(getByRole("button", { name: /review.*what needs you/i }));
    expect(getByText("Card purchase on Jun 24")).toBeInTheDocument();
    expect(getByRole("button", { name: /everyday checking june statement.*page 1/i })).toBeInTheDocument();
  });

  it("keeps the accounts detail panel focused on the selected account", async () => {
    const user = userEvent.setup();
    const { getByRole, getByText, container } = render(<App />);

    await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
    expect(getByRole("heading", { name: "Sample accounts" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Everyday checking" })).toBeInTheDocument();
    expect(getByText("Checking statements, Aug 2022–Jul 2026")).toBeInTheDocument();
    expect(getByText("Grade")).toBeInTheDocument();

    await user.click(container.querySelectorAll(".detail-row-button")[4] as HTMLElement);

    expect(getByRole("heading", { name: "Taxable Brokerage" })).toBeInTheDocument();
    expect(getByText("Brokerage statements, Aug 2022–Jul 2026")).toBeInTheDocument();
    expect(getByText("Quarterly statements with holdings")).toBeInTheDocument();
  });

  it("lets the local capture notice be dismissed", async () => {
    const { getByRole, queryByRole } = render(<App />);

    fireEvent.click(getByRole("button", { name: "View sample document journey" }));
    expect(getByRole("status")).toHaveTextContent("Opened the fictional sample document journey. No file was selected, no vault event was written, no model call was made, and nothing was sent.");

    fireEvent.click(getByRole("button", { name: /dismiss notice/i }));
    expect(queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the Trust destination as preview-owned explanation", async () => {
    const user = userEvent.setup();
    const { getAllByText, getByRole, getByText, queryByRole } = render(<App />);

    await user.click(getByRole("button", { name: /trust.*how it works/i }));
    expect(getByRole("heading", { name: "Trust" })).toBeInTheDocument();
    expect(getByText("Preview boundary", { selector: "strong" })).toBeInTheDocument();
    expect(getAllByText("Static interactions", { selector: "strong" })).toHaveLength(2);
    expect(getByText("This Trust destination describes the fictional sample and this interface’s current limitations. It is not a report about a private vault.")).toBeInTheDocument();
    expect(getByText("What this preview can establish, what is unavailable, and which capabilities are not connected.")).toBeInTheDocument();
    expect(getByText("Fictional sample", { selector: ".privacy-lock span" })).toBeInTheDocument();
    expect(getByText("This fictional sample is bundled with the app. Complete outbound history is not available.")).toBeInTheDocument();
    expect(queryByRole("button", { name: "View sample document journey" })).not.toBeInTheDocument();
    const source = getByRole("complementary", { name: "Vault source" });
    const trustHeader = getByRole("heading", { name: "Trust and limitations" });
    expect(source.compareDocumentPosition(trustHeader) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("states the fictional sample boundary", () => {
    const { getByRole, getByText } = render(<App />);
    expect(getByRole("complementary", { name: "Vault source" })).toBeInTheDocument();
    expect(getByText("Every name, document, and figure here is fictional.")).toBeInTheDocument();
  });

  it("keeps fixture preview usable when no host bridge is injected", () => {
    const { getByText, queryByPlaceholderText } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByPlaceholderText("/path/to/vault")).not.toBeInTheDocument();
  });

  it("keeps manual directory entry as the browser fallback", () => {
    const { getByText, queryByLabelText, queryByRole } = render(<App />);

    expect(getByText(/Preview mode. A desktop host bridge will enable local vault opening/i)).toBeInTheDocument();
    expect(queryByRole("button", { name: /choose folder/i })).not.toBeInTheDocument();
    expect(queryByLabelText("Vault directory")).not.toBeInTheDocument();
  });

  it("exposes the collapsed and expanded state of narrow navigation", async () => {
    installResponsiveMatchMedia(760);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = render(<App />);
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
    installResponsiveMatchMedia(759);
    document.body.style.overflow = "clip";
    document.documentElement.style.overflow = "scroll";
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
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
    installResponsiveMatchMedia(760);
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
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
    installResponsiveMatchMedia(759);
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
    const trigger = getByRole("button", { name: "Open navigation" });

    await user.click(trigger);
    const dialog = getByRole("dialog", { name: "Main navigation" });
    const close = getByRole("button", { name: "Close navigation" });
    close.setAttribute("disabled", "");
    trigger.focus();
    const skipDisabled = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(skipDisabled);
    expect(skipDisabled.defaultPrevented).toBe(true);
    expect(getByRole("button", { name: "Reset sample vault" })).toHaveFocus();

    dialog.querySelectorAll("button, input, select, textarea").forEach((element) => element.setAttribute("disabled", ""));
    trigger.focus();
    const empty = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    document.dispatchEvent(empty);
    expect(empty.defaultPrevented).toBe(true);
    expect(dialog).toHaveFocus();
  });

  it("closes narrow navigation for the current destination and focuses the page title", async () => {
    installResponsiveMatchMedia(760);
    const user = userEvent.setup();
    const { getByRole } = render(<App />);

    await user.click(getByRole("button", { name: "Open navigation" }));
    await user.click(getByRole("button", { name: "OverviewYour picture" }));

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  });

  it("closes an open Viva drawer before opening narrow navigation", async () => {
    installResponsiveMatchMedia(390);
    const user = userEvent.setup();
    const { getByRole, queryByRole } = render(<App />);

    await user.click(getByRole("button", { name: /ask viva/i }));
    expect(getByRole("dialog", { name: "Viva conversation" })).toBeInTheDocument();
    await user.click(getByRole("button", { name: "Open navigation" }));

    expect(queryByRole("dialog", { name: "Viva conversation" })).not.toBeInTheDocument();
    expect(getByRole("dialog", { name: "Main navigation" })).toBeInTheDocument();
  });

  it("keeps desktop navigation persistent and cleans up an open mobile modal at the breakpoint", async () => {
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "auto";
    const responsive = installResponsiveMatchMedia(760);
    const user = userEvent.setup();
    const { getByRole } = render(<App />);
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
    const responsive = installResponsiveMatchMedia(760);
    const user = userEvent.setup();
    const { getByRole } = render(<App />);

    await user.click(getByRole("button", { name: "Open navigation" }));
    getByRole("button", { name: "OverviewYour picture" }).removeAttribute("aria-current");
    responsive.resize(761);

    await waitFor(() => expect(getByRole("heading", { name: "Your financial picture" })).toHaveFocus());
    expect(getByRole("button", { name: "Close navigation" })).not.toHaveFocus();
    expect(getByRole("button", { name: "Open navigation" })).not.toHaveFocus();
  });

  it("restores exact root and body overflow values when an open narrow drawer unmounts", async () => {
    installResponsiveMatchMedia(320);
    document.documentElement.style.overflow = "clip";
    document.body.style.overflow = "visible";
    const user = userEvent.setup();
    const { getByRole, unmount } = render(<App />);

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
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/manual/vault");

      await user.click(getByRole("button", { name: /choose folder/i }));

      expect(getByRole("status")).toHaveTextContent(/folder picker could not be opened/i);
      expect(getByRole("status")).not.toHaveTextContent(hostFailure);
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
          : { surface: payload.surface, job_id: "job-1", data: payload.surface === "overview" ? { accounts: [], as_of: "August 1, 2026" } : payload.surface === "documents" ? { documents: [] } : { questions: [], total: 0 } }) as T,
      }),
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
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
      expect(queryByText("$48,240.18")).not.toBeInTheDocument();
      expect(queryByText("Everyday checking")).not.toBeInTheDocument();
      releaseReads();
      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(queryByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("keeps the sample vault after reset even when an earlier private read resolves later", async () => {
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
      const { getByLabelText, getByRole, getByText, queryByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));
      expect(getByText("Reading available surfaces from this device…", { selector: ".empty-state span" })).toBeInTheDocument();

      await user.click(getByRole("button", { name: "Open sample vault" }));
      expect(getByText("Sample vault")).toBeInTheDocument();
      expect(getByText("$48,240.18")).toBeInTheDocument();
      expect(queryByText("Late private account")).not.toBeInTheDocument();

      releaseReads();
      await waitFor(() => expect(getByText("Sample vault")).toBeInTheDocument());
      expect(getByText("$48,240.18")).toBeInTheDocument();
      expect(queryByText("Late private account")).not.toBeInTheDocument();
      expect(queryByText("late-private-document")).not.toBeInTheDocument();
    } finally {
      releaseReads();
      window.orionVivaBridge = previousBridge;
    }
  });

  it("renders combined live surfaces without sample facts and keeps unconnected features honest", async () => {
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
      const { getByLabelText, getByRole, getByText, getAllByText, queryByRole, queryByText } = render(<App />);
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
      expect(queryByText("$48,240.18")).not.toBeInTheDocument();
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
      expect(getByText("Setting a question aside is connected. Answering one in your own words is not, and neither is proposing a change, confirming one, or correcting a document.")).toBeInTheDocument();
      // The read supplies an invitation to answer in a sentence. Nothing here
      // can take one, so a real vault's invitation is never put to a person.
      expect(queryByText("Write an answer")).not.toBeInTheDocument();
      expect(queryByText(/invites an answer in a sentence/)).not.toBeInTheDocument();

      await user.click(getByRole("button", { name: "Open sample vault" }));
      expect(getByText("Sample vault")).toBeInTheDocument();
      expect(getByText("$48,240.18")).toBeInTheDocument();
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
          : payload.surface === "documents" ? { documents: [] } : { questions: [], total: 0 };
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
            : { questions: [], total: 0 };
        return { protocol: "1.0", request_id: "read", ok: true, result: { surface: payload.surface, job_id: "job", data } as T };
      },
    };

    try {
      const { getByLabelText, getByRole, getByText, queryByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument());
      expect(getByText("Local source", { selector: ".privacy-lock span" })).toBeInTheDocument();
      expect(getByText("This vault was opened through the local desktop host. Complete outbound history is not available.")).toBeInTheDocument();
      expect(getByRole("button", { name: "Explore fictional sample data" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      expect(getByText("No accounts yet", { selector: "strong" })).toBeInTheDocument();
      expect(getByRole("button", { name: "Explore fictional sample data" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /documents.*what supports it/i }));
      expect(getByText("No documents yet", { selector: "strong" })).toBeInTheDocument();
      expect(getByRole("button", { name: "Explore fictional sample data" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /review.*what needs you/i }));
      expect(getByText("Nothing needs you right now", { selector: "strong" })).toBeInTheDocument();
      expect(queryByRole("button", { name: "Explore fictional sample data" })).not.toBeInTheDocument();
      await user.click(getByRole("button", { name: /activity.*what moved/i }));
      expect(getByText("Activity unavailable", { selector: "strong" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /trust.*how it works/i }));
      expect(getByText("Trust details unavailable", { selector: "strong" })).toBeInTheDocument();
      await user.click(getByRole("button", { name: /accounts.*where money sits/i }));
      await user.click(getByRole("button", { name: "Explore fictional sample data" }));
      expect(getByText("$48,240.18")).toBeInTheDocument();
      expect(getByText("Sample vault · Fictional sample data")).toBeInTheDocument();
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
      const { getByLabelText, getByRole, getByText, getAllByText } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), "secret");
      await user.click(getByRole("button", { name: "Open local vault" }));

      await waitFor(() => expect(getByRole("status")).toHaveTextContent("The private vault opened, but some surfaces could not be read. Your vault was not changed."));
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
      expect(control).toHaveAccessibleDescription("This opens a vault in the folder you name, and creates one there if none exists. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it. Your vault is answering the last request. Pressing again does nothing until it has.");
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
      const { getByLabelText, getByRole } = render(<App />);
      await user.type(getByLabelText("Vault directory"), "/vault");
      await user.type(getByLabelText("Passphrase"), secret);
      await user.click(getByRole("button", { name: "Open local vault" }));

      expect(getByRole("status")).toHaveTextContent("The local vault could not be opened.");
      expect(getByRole("status")).not.toHaveTextContent(secret);
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
      const { getByLabelText, getByRole } = render(<App />);
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
      expect(getByRole("status")).toHaveTextContent("Set aside until something changes.");
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
      const { getByLabelText, getByRole } = render(<App />);
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
      await waitFor(() => expect(getByRole("status")).toHaveTextContent("Setting this question aside"));
      expect(control).not.toBeDisabled();
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveFocus();

      answerDecline();

      // Nothing moved, so the control the person must use again is still under
      // their hands and the screen does not take focus off it.
      await waitFor(() => expect(getByRole("status")).toHaveTextContent("That question is no longer open."));
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
      const { getByLabelText, getByRole, getByText } = render(<App />);
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
      expect(getByRole("status")).toHaveTextContent("Set aside until something changes.");
      expect(getByRole("status")).toHaveTextContent("This screen could not read the queue afterwards, so it no longer knows what is still open.");
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
      expect(getByText("Nothing has been added to this vault yet. Choose a file to add one.")).toBeInTheDocument();

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

  it("names what a lost passphrase costs to the field and the control beside it", () => {
    const previousBridge = window.orionVivaBridge;
    window.orionVivaBridge = { request: async <T,>(frame: { requestId: string }) => ({ protocol: "1.0", request_id: frame.requestId, ok: true, result: {} as T }) };
    const consequence = "This opens a vault in the folder you name, and creates one there if none exists. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it.";
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
