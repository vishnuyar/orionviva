import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { narrowNavigationQuery, useResponsiveNavigation } from "./useResponsiveNavigation";

function installMatchMedia(width: number, legacy = false) {
  let listener: ((event: MediaQueryListEvent) => void) | null = null;
  const matches = () => width <= 760;
  const media = {
    media: narrowNavigationQuery,
    matches: matches(),
    onchange: null,
    addEventListener: legacy ? undefined : vi.fn((_type: string, next: (event: MediaQueryListEvent) => void) => { listener = next; }),
    removeEventListener: legacy ? undefined : vi.fn((_type: string, next: (event: MediaQueryListEvent) => void) => { if (listener === next) listener = null; }),
    addListener: vi.fn((next: (event: MediaQueryListEvent) => void) => { listener = next; }),
    removeListener: vi.fn((next: (event: MediaQueryListEvent) => void) => { if (listener === next) listener = null; }),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList;
  window.matchMedia = vi.fn(() => media);
  return { media, resize(nextWidth: number) { width = nextWidth; Object.defineProperty(media, "matches", { configurable: true, value: matches() }); listener?.({ matches: matches(), media: narrowNavigationQuery } as MediaQueryListEvent); } };
}

describe("responsive navigation query", () => {
  afterEach(() => { delete (window as { matchMedia?: typeof window.matchMedia }).matchMedia; });

  it.each([[1440, false], [761, false], [760, true], [759, true]])("maps width %i to narrow=%s", (width, expected) => {
    installMatchMedia(width);
    const renders: boolean[] = [];
    const { result } = renderHook(() => {
      const isNarrow = useResponsiveNavigation();
      renders.push(isNarrow);
      return isNarrow;
    });
    expect(window.matchMedia).toHaveBeenCalledWith(narrowNavigationQuery);
    expect(renders[0]).toBe(expected);
    expect(renders.every((value) => value === expected)).toBe(true);
    expect(result.current).toBe(expected);
  });

  it("responds to breakpoint changes and removes the modern listener", () => {
    const control = installMatchMedia(761);
    const { result, unmount } = renderHook(() => useResponsiveNavigation());
    act(() => control.resize(760));
    expect(result.current).toBe(true);
    act(() => control.resize(1440));
    expect(result.current).toBe(false);
    unmount();
    expect(control.media.removeEventListener).toHaveBeenCalledOnce();
  });

  it("supports and cleans up the legacy listener API", () => {
    const control = installMatchMedia(759, true);
    const { result, unmount } = renderHook(() => useResponsiveNavigation());
    expect(result.current).toBe(true);
    unmount();
    expect(control.media.removeListener).toHaveBeenCalledOnce();
  });

  it("defaults to persistent desktop navigation when matchMedia is missing", () => {
    delete (window as { matchMedia?: typeof window.matchMedia }).matchMedia;
    const { result } = renderHook(() => useResponsiveNavigation());
    expect(result.current).toBe(false);
  });
});
