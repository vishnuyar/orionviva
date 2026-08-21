import { useRef, useState, type CSSProperties } from "react";
import { fireEvent, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useEvidenceDialog } from "./useEvidenceDialog";

type CloseState = "eligible" | "aria-hidden" | "disabled" | "hidden";
type CssHidden = "display" | "visibility" | null;

function hiddenStyle(value: CssHidden): CSSProperties | undefined {
  if (value === "display") return { display: "none" };
  if (value === "visibility") return { visibility: "hidden" };
  return undefined;
}

function Harness({
  closeState = "eligible",
  closeCss = null,
  closeAncestorCss = null,
  lastCss = null,
  allActionsIneligible = false,
}: {
  closeState?: CloseState;
  closeCss?: CssHidden;
  closeAncestorCss?: CssHidden;
  lastCss?: CssHidden;
  allActionsIneligible?: boolean;
}) {
  const [open, setOpen] = useState(false); const drawer = useRef<HTMLElement>(null); const close = useRef<HTMLButtonElement>(null); const title = useRef<HTMLHeadingElement>(null);
  const dialog = useEvidenceDialog({ open, drawerRef: drawer, initialFocusRef: close, pageTitleRef: title, onDismiss: () => setOpen(false) });
  return <><button onClick={() => setOpen(true)}>Open evidence</button><button onClick={dialog.cancelPendingRestore}>Cancel restore</button><button onClick={dialog.dismissAndRestore}>Schedule restore</button><button onClick={dialog.closeWithoutRestore}>Close without restore</button><h1 ref={title} tabIndex={-1}>Page</h1>{open && <aside ref={drawer} role="dialog" aria-label="Evidence" tabIndex={-1}><span style={hiddenStyle(closeAncestorCss)}><button ref={(node) => { close.current = node; if (node && closeState === "disabled") node.setAttribute("disabled", ""); }} style={hiddenStyle(closeCss)} aria-hidden={closeState === "aria-hidden" ? "true" : undefined} hidden={closeState === "hidden"} onClick={dialog.dismissAndRestore}>Close evidence</button></span><button style={hiddenStyle(lastCss)} hidden={allActionsIneligible}>Last action</button><button ref={(node) => node?.setAttribute("disabled", "")}>Disabled</button></aside>}</>;
}

function captureAnimationFrames() {
  const originalRequest = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  const callbacks: FrameRequestCallback[] = [];
  globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { callbacks.push(callback); return callbacks.length; });
  globalThis.cancelAnimationFrame = vi.fn();
  return {
    flush() { [...callbacks].forEach((callback) => callback(performance.now())); },
    restore() { globalThis.requestAnimationFrame = originalRequest; globalThis.cancelAnimationFrame = originalCancel; },
  };
}

describe("evidence dialog behavior", () => {
  it("focuses Close, traps both boundaries, and restores its opener", async () => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness />); const opener = getByRole("button", { name: "Open evidence" });
    document.documentElement.style.overflow = "clip"; document.body.style.overflow = "visible";
    await user.click(opener); expect(getByRole("button", { name: "Close evidence" })).toHaveFocus(); expect(document.documentElement.style.overflow).toBe("hidden");
    await user.keyboard("{Shift>}{Tab}{/Shift}"); expect(getByRole("button", { name: "Last action" })).toHaveFocus();
    await user.keyboard("{Tab}"); expect(getByRole("button", { name: "Close evidence" })).toHaveFocus();
    await user.click(getByRole("button", { name: "Close evidence" })); await waitFor(() => expect(opener).toHaveFocus());
    expect(document.documentElement.style.overflow).toBe("clip"); expect(document.body.style.overflow).toBe("visible"); document.documentElement.style.overflow = ""; document.body.style.overflow = "";
  });

  it("recaptures outside focus and restores with Escape", async () => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness />); const opener = getByRole("button", { name: "Open evidence" }); await user.click(opener);
    fireEvent.focus(getByRole("heading", { name: "Page" })); expect(getByRole("button", { name: "Close evidence" })).toHaveFocus();
    await user.keyboard("{Escape}"); await waitFor(() => expect(opener).toHaveFocus());
  });

  it("consumes Escape and falls back when the opener becomes disabled or hidden", async () => {
    const user = userEvent.setup();
    const escaped = vi.fn();
    window.addEventListener("keydown", escaped);
    try {
      const { getByRole } = render(<Harness />);
      const opener = getByRole("button", { name: "Open evidence" });
      await user.click(opener);
      opener.setAttribute("disabled", "");
      const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      document.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      expect(escaped).not.toHaveBeenCalled();
      await waitFor(() => expect(getByRole("heading", { name: "Page" })).toHaveFocus());
    } finally {
      window.removeEventListener("keydown", escaped);
    }
  });

  it.each(["display", "visibility"] as const)("rejects an opener hidden by CSS %s when restoring from Close", async (property) => {
    const user = userEvent.setup();
    const { getByRole } = render(<Harness />);
    const opener = getByRole("button", { name: "Open evidence" });
    await user.click(opener);
    opener.style[property] = property === "display" ? "none" : "hidden";
    await user.click(getByRole("button", { name: "Close evidence" }));
    await waitFor(() => expect(getByRole("heading", { name: "Page" })).toHaveFocus());
  });

  it.each(["aria-hidden", "disabled", "hidden"] as const)("skips an initially %s Close control", async (closeState) => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness closeState={closeState} />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    expect(getByRole("button", { name: "Last action" })).toHaveFocus();
  });

  it.each([
    ["self display none", "display", null],
    ["self visibility hidden", "visibility", null],
    ["ancestor display none", null, "display"],
    ["ancestor visibility hidden", null, "visibility"],
  ] as const)("skips an initially CSS-hidden Close control: %s", async (_label, closeCss, closeAncestorCss) => {
    const user = userEvent.setup();
    const { getByRole } = render(<Harness closeCss={closeCss} closeAncestorCss={closeAncestorCss} />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    expect(getByRole("button", { name: "Last action" })).toHaveFocus();
  });

  it.each(["display", "visibility"] as const)("excludes a CSS-hidden %s action from Tab wrapping", async (lastCss) => {
    const user = userEvent.setup();
    const { getByRole } = render(<Harness lastCss={lastCss} />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    const close = getByRole("button", { name: "Close evidence" });
    expect(close).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(close).toHaveFocus();
  });

  it("recaptures on the first remaining action when Close becomes ineligible", async () => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    getByRole("button", { name: "Close evidence" }).setAttribute("aria-hidden", "true");
    fireEvent.focus(getByRole("heading", { name: "Page" }));
    expect(getByRole("button", { name: "Last action" })).toHaveFocus();
  });

  it.each(["display", "visibility"] as const)("recaptures on the first remaining action when Close becomes CSS %s hidden", async (property) => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    getByRole("button", { name: "Close evidence" }).style[property] = property === "display" ? "none" : "hidden";
    fireEvent.focus(getByRole("heading", { name: "Page" }));
    expect(getByRole("button", { name: "Last action" })).toHaveFocus();
  });

  it("uses the drawer for initial focus and recapture when every action is ineligible", async () => {
    const user = userEvent.setup(); const { getByRole } = render(<Harness closeState="disabled" allActionsIneligible />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    const drawer = getByRole("dialog", { name: "Evidence" });
    expect(drawer).toHaveFocus();
    fireEvent.focus(getByRole("heading", { name: "Page" }));
    expect(drawer).toHaveFocus();
  });

  it("uses the drawer for entry and recapture when actions are CSS-hidden or disabled", async () => {
    const user = userEvent.setup();
    const { getByRole } = render(<Harness closeCss="display" lastCss="visibility" />);
    await user.click(getByRole("button", { name: "Open evidence" }));
    const drawer = getByRole("dialog", { name: "Evidence" });
    expect(drawer).toHaveFocus();
    fireEvent.focus(getByRole("heading", { name: "Page" }));
    expect(drawer).toHaveFocus();
  });

  it("invalidates a captured restore even when cancelAnimationFrame cannot remove its callback", () => {
    const frames = captureAnimationFrames();
    try {
      const view = render(<Harness />);
      const opener = view.getByRole("button", { name: "Open evidence" });
      opener.focus();
      fireEvent.click(opener);
      fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      const cancel = view.getByRole("button", { name: "Cancel restore" });
      cancel.focus();
      fireEvent.click(cancel);
      frames.flush();
      expect(cancel).toHaveFocus();
      expect(opener).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("lets only the newest pending restore focus its opener", () => {
    const frames = captureAnimationFrames();
    try {
      const view = render(<Harness />);
      const opener = view.getByRole("button", { name: "Open evidence" });
      opener.focus();
      fireEvent.click(opener);
      const focus = vi.spyOn(opener, "focus");
      fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      fireEvent.click(view.getByRole("button", { name: "Schedule restore" }));
      frames.flush();
      expect(focus).toHaveBeenCalledOnce();
      expect(opener).toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("invalidates pending restore work on unmount", () => {
    const frames = captureAnimationFrames();
    try {
      const view = render(<Harness />);
      const opener = view.getByRole("button", { name: "Open evidence" });
      const title = view.getByRole("heading", { name: "Page" });
      opener.focus();
      fireEvent.click(opener);
      const openerFocus = vi.spyOn(opener, "focus");
      const titleFocus = vi.spyOn(title, "focus");
      fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      view.unmount();
      frames.flush();
      expect(openerFocus).not.toHaveBeenCalled();
      expect(titleFocus).not.toHaveBeenCalled();
    } finally {
      frames.restore();
    }
  });

  it("invalidates an old restore when the dialog opens again", () => {
    const frames = captureAnimationFrames();
    try {
      const view = render(<Harness />);
      const opener = view.getByRole("button", { name: "Open evidence" });
      opener.focus();
      fireEvent.click(opener);
      fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      fireEvent.click(opener);
      const close = view.getByRole("button", { name: "Close evidence" });
      expect(close).toHaveFocus();
      frames.flush();
      expect(close).toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("closeWithoutRestore invalidates older restore work without moving focus", () => {
    const frames = captureAnimationFrames();
    try {
      const view = render(<Harness />);
      const opener = view.getByRole("button", { name: "Open evidence" });
      opener.focus();
      fireEvent.click(opener);
      fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
      const withoutRestore = view.getByRole("button", { name: "Close without restore" });
      withoutRestore.focus();
      fireEvent.click(withoutRestore);
      frames.flush();
      expect(withoutRestore).toHaveFocus();
    } finally {
      frames.restore();
    }
  });
});
