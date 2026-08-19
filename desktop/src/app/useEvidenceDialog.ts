import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";

type EvidenceDialogOptions = { open: boolean; drawerRef: RefObject<HTMLElement | null>; initialFocusRef: RefObject<HTMLElement | null>; pageTitleRef: RefObject<HTMLElement | null>; onDismiss: () => void };
const focusableSelector = 'button, input, a[href], select, textarea, [tabindex]:not([tabindex="-1"])';

function eligibleFocusable(element: HTMLElement | null): element is HTMLElement {
  if (!element?.isConnected || element.hasAttribute("disabled") || element.matches(":disabled") || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
  if (typeof globalThis.getComputedStyle !== "function") return true;
  let current: HTMLElement | null = element;
  while (current) {
    const style = globalThis.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return false;
    current = current.parentElement;
  }
  return true;
}

function eligibleFocusables(drawer: HTMLElement | null): HTMLElement[] {
  return Array.from(drawer?.querySelectorAll<HTMLElement>(focusableSelector) ?? []).filter(eligibleFocusable);
}

function focusEntryTarget(drawer: HTMLElement | null, initial: HTMLElement | null): HTMLElement | null {
  if (drawer?.contains(initial) && eligibleFocusable(initial)) return initial;
  return eligibleFocusables(drawer)[0] ?? drawer;
}

function canRestore(element: HTMLElement | null) {
  return eligibleFocusable(element);
}

export function useEvidenceDialog({ open, drawerRef, initialFocusRef, pageTitleRef, onDismiss }: EvidenceDialogOptions) {
  const openerRef = useRef<HTMLElement | null>(null);
  const restoreFrameRef = useRef<number | null>(null);
  const restoreGenerationRef = useRef(0);
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;
  const cancelPendingRestore = useCallback(() => {
    restoreGenerationRef.current += 1;
    if (restoreFrameRef.current !== null) cancelAnimationFrame(restoreFrameRef.current);
    restoreFrameRef.current = null;
  }, []);
  const scheduleRestore = useCallback(() => {
    cancelPendingRestore();
    const generation = restoreGenerationRef.current;
    restoreFrameRef.current = requestAnimationFrame(() => {
      if (restoreGenerationRef.current !== generation) return;
      restoreFrameRef.current = null;
      (canRestore(openerRef.current) ? openerRef.current : pageTitleRef.current)?.focus();
    });
  }, [cancelPendingRestore, pageTitleRef]);
  useEffect(() => () => cancelPendingRestore(), [cancelPendingRestore]);
  useLayoutEffect(() => {
    if (!open) return undefined;
    cancelPendingRestore();
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const priorRootOverflow = document.documentElement.style.overflow;
    const priorBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    focusEntryTarget(drawerRef.current, initialFocusRef.current)?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); dismissRef.current(); scheduleRestore(); return; }
      if (event.key !== "Tab") return;
      const available = eligibleFocusables(drawerRef.current);
      if (!available.length) { event.preventDefault(); drawerRef.current?.focus(); return; }
      const first = available[0]; const last = available[available.length - 1];
      if (!available.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); return; }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const onFocusIn = (event: FocusEvent) => { if (drawerRef.current && event.target instanceof Node && !drawerRef.current.contains(event.target)) focusEntryTarget(drawerRef.current, initialFocusRef.current)?.focus(); };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => { document.removeEventListener("keydown", onKeyDown); document.removeEventListener("focusin", onFocusIn); document.documentElement.style.overflow = priorRootOverflow; document.body.style.overflow = priorBodyOverflow; };
  }, [cancelPendingRestore, drawerRef, initialFocusRef, open, scheduleRestore]);

  const dismissAndRestore = useCallback(() => { dismissRef.current(); scheduleRestore(); }, [scheduleRestore]);
  const closeWithoutRestore = useCallback(() => { cancelPendingRestore(); dismissRef.current(); }, [cancelPendingRestore]);
  return { dismissAndRestore, closeWithoutRestore, cancelPendingRestore };
}
