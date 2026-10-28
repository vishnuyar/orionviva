import { useRef, useState, type ReactNode, type CSSProperties } from "react";
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

function DisclosureHarness({children, closeHidden=false}: {children:ReactNode; closeHidden?:boolean}) {
 const drawer=useRef<HTMLElement>(null);const close=useRef<HTMLButtonElement>(null);const title=useRef<HTMLHeadingElement>(null);
 useEvidenceDialog({open:true,drawerRef:drawer,initialFocusRef:close,pageTitleRef:title,onDismiss:vi.fn()});
 return <><h1 ref={title} tabIndex={-1}>Disclosure page</h1><aside ref={drawer} role="dialog" aria-label="Disclosure evidence" tabIndex={-1}><button ref={close} hidden={closeHidden}>Disclosure close</button>{children}</aside></>;
}
function pressTab(element:HTMLElement,shiftKey=false){element.focus();const event=new KeyboardEvent("keydown",{key:"Tab",shiftKey,bubbles:true,cancelable:true});element.dispatchEvent(event);return event;}
describe("native evidence disclosures",()=>{
 it.each([false,true])("allows native forward traversal from first summary when open=%s",(open)=>{
  const view=render(<DisclosureHarness><details open={open}><summary>Source collection</summary><button>Disclosure source</button></details><button>Following action</button></DisclosureHarness>);
  const summary=view.getByText("Source collection");const event=pressTab(summary);expect(event.defaultPrevented).toBe(false);expect(summary).toHaveFocus();
 });
 it("wraps backward to closed summary rather than its hidden descendant",()=>{
  const view=render(<DisclosureHarness><details><summary>Source collection</summary><button>Hidden final source</button></details></DisclosureHarness>);
  const close=view.getByRole("button",{name:"Disclosure close"});const summary=view.getByText("Source collection");const event=pressTab(close,true);expect(event.defaultPrevented).toBe(true);expect(summary).toHaveFocus();expect(view.getByText("Hidden final source")).not.toHaveFocus();
 });
});
describe("native disclosure boundaries",()=>{
 it("leaves default movement between ordinary controls and a summary to the browser",()=>{
  const view=render(<DisclosureHarness><button>Before collection</button><details><summary>Collection summary</summary><button>Closed content</button></details><button>After collection</button></DisclosureHarness>);
  for(const name of ["Before collection","Collection summary","After collection"]){const node=view.getByText(name);const event=pressTab(node,name==="After collection");expect(event.defaultPrevented).toBe(false);expect(node).toHaveFocus();}
  const event=pressTab(view.getByText("After collection"));expect(event.defaultPrevented).toBe(true);expect(view.getByText("Disclosure close")).toHaveFocus();
 });
 it("recomputes boundary targets when a disclosure opens and closes",()=>{
  const view=render(<DisclosureHarness><details><summary>Dynamic collection</summary><button>Dynamic source</button></details></DisclosureHarness>);
  const close=view.getByText("Disclosure close");const summary=view.getByText("Dynamic collection");const details=summary.parentElement!;const source=view.getByText("Dynamic source");
  pressTab(close,true);expect(summary).toHaveFocus();details.setAttribute("open","");pressTab(close,true);expect(source).toHaveFocus();
  const forward=pressTab(source);expect(forward.defaultPrevented).toBe(true);expect(close).toHaveFocus();details.removeAttribute("open");pressTab(close,true);expect(summary).toHaveFocus();
  const summaryForward=pressTab(summary);expect(summaryForward.defaultPrevented).toBe(true);expect(close).toHaveFocus();
 });
 it("excludes descendants hidden by every closed details ancestor",()=>{
  const view=render(<DisclosureHarness><details><summary>Outer summary</summary><details open><summary>Inner summary</summary><button>Nested source</button></details></details></DisclosureHarness>);
  const close=view.getByText("Disclosure close");const outer=view.getByText("Outer summary").parentElement!;const inner=view.getByText("Inner summary").parentElement!;
  pressTab(close,true);expect(view.getByText("Outer summary")).toHaveFocus();outer.setAttribute("open","");pressTab(close,true);expect(view.getByText("Nested source")).toHaveFocus();
  inner.removeAttribute("open");pressTab(close,true);expect(view.getByText("Inner summary")).toHaveFocus();outer.removeAttribute("open");pressTab(close,true);expect(view.getByText("Outer summary")).toHaveFocus();
 });
 it("retains exposed controls inside the first summary subtree of a closed ancestor",()=>{
  const view=render(<DisclosureHarness><details><summary>Linked summary <a href="#source">Summary link</a></summary><button>Unexposed source</button></details></DisclosureHarness>);
  pressTab(view.getByText("Disclosure close"),true);expect(view.getByRole("link",{name:"Summary link"})).toHaveFocus();
 });
 it("uses the first direct summary even when another child precedes it and ignores later default summaries",()=>{
  const view=render(<DisclosureHarness><details><span>Introduction</span><summary>First native summary</summary><summary>Later summary</summary><button>Closed source</button></details></DisclosureHarness>);
  pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("First native summary")).toHaveFocus();
  view.getByText("First native summary").parentElement!.setAttribute("open","");view.getByText("Closed source").setAttribute("hidden","");pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("First native summary")).toHaveFocus();
 });
 it.each(["-1","-2"," -3 "])("does not target a native summary with negative tabindex %s",(tabIndex)=>{
  const view=render(<DisclosureHarness><button>Prior eligible action</button><details><summary>Excluded summary</summary><button>Closed source</button></details></DisclosureHarness>);
  view.getByText("Excluded summary").setAttribute("tabindex",tabIndex);pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("Prior eligible action")).toHaveFocus();
 });
 it.each(["hidden","inert","aria-hidden","display","visibility","disabled"])("retains %s exclusion on native summaries",(reason)=>{
  const view=render(<DisclosureHarness><button>Prior eligible action</button><details><summary>Excluded summary</summary><button>Closed source</button></details></DisclosureHarness>);
  const summary=view.getByText("Excluded summary");
  if(reason==="display")summary.style.display="none";else if(reason==="visibility")summary.style.visibility="hidden";else summary.setAttribute(reason,reason==="aria-hidden"?"true":"");
  pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("Prior eligible action")).toHaveFocus();
 });
 it("falls back to the dialog when all summaries and actions are ineligible and recaptures outside focus",()=>{
  const view=render(<DisclosureHarness closeHidden><details><summary tabIndex={-2}>Excluded first summary</summary><summary>Later default summary</summary><button>Hidden source</button></details></DisclosureHarness>);
  const drawer=view.getByRole("dialog",{name:"Disclosure evidence"});expect(drawer).toHaveFocus();const event=pressTab(drawer);expect(event.defaultPrevented).toBe(true);expect(drawer).toHaveFocus();fireEvent.focus(view.getByText("Disclosure page"));expect(drawer).toHaveFocus();
 });
 it("does not invent a stop for summary-less details or a standalone summary",()=>{
  const view=render(<DisclosureHarness><button>Prior eligible action</button><details><button>Hidden source</button></details><summary>Standalone summary</summary></DisclosureHarness>);
  pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("Prior eligible action")).toHaveFocus();
 });
 it("preserves explicit sequential tabindex on a later summary without changing ordinary native-control policy",()=>{
  const view=render(<DisclosureHarness><details open><summary>First native summary</summary><summary tabIndex={0}>Explicit later summary</summary></details><button tabIndex={-2}>Ordinary native action</button></DisclosureHarness>);
  pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("Ordinary native action")).toHaveFocus();view.getByText("Ordinary native action").setAttribute("hidden","");pressTab(view.getByText("Disclosure close"),true);expect(view.getByText("Explicit later summary")).toHaveFocus();
 });
});
