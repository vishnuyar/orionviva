import { act, fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OriginalPreview } from "./OriginalPreview";
import type { DocumentPreview } from "../surface/types";
afterEach(cleanup);
const id = "a".repeat(64);
const text = (value: string): DocumentPreview => ({ status: "ready", sourceKind: "text", page: 1, pageCount: 1, text: value, image: null, width: null, height: null });
function pending() { let resolve!: (value: DocumentPreview) => void; const promise = new Promise<DocumentPreview>((finish) => { resolve = finish; }); return { promise, resolve }; }
describe("explicit saved original viewing", () => {
  it("fetches only on explicit open, renders markup literally, closes with Escape and restores focus", async () => {
    const read = vi.fn(async () => text('<script>alert("private")</script><a href="https://example.invalid">link</a>'));
    render(<OriginalPreview documentId={id} name="Statement" read={read} />);
    expect(read).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    expect(await screen.findByText(/<script>/)).toBeInTheDocument();
    expect(document.querySelector("script, a")).toBeNull();
    expect(screen.getByRole("heading", { name: "Saved original: Statement" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("heading"), { key: "Escape" });
    expect(screen.queryByText(/<script>/)).toBeNull();
    expect(screen.getByRole("button", { name: "View saved original" })).toHaveFocus();
    expect(read).toHaveBeenCalledTimes(1);
  });
  it("drops late content after close and prevents duplicate reads while busy", async () => {
    const held = pending(); const read = vi.fn(() => held.promise);
    render(<OriginalPreview documentId={id} name="Statement" read={read} />);
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    fireEvent.click(screen.getByRole("button", { name: "Close original" }));
    await act(async () => held.resolve(text("obsolete private page")));
    expect(screen.queryByText("obsolete private page")).toBeNull(); expect(read).toHaveBeenCalledTimes(1);
  });
  it("clears a ready page at vault-transition start and drops pending content before source replacement", async () => {
    let end!: () => void;
    const held = pending(); const read = vi.fn().mockResolvedValueOnce(text("first vault page")).mockReturnValueOnce(held.promise);
    render(<OriginalPreview documentId={id} name="Statement" read={read} subscribeEnd={(clear) => { end = clear; return () => {}; }} />);
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    expect(await screen.findByText("first vault page")).toBeInTheDocument();
    act(() => end()); expect(screen.queryByText("first vault page")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View saved original" })); expect(read).toHaveBeenCalledTimes(1);
  });
  it("clears the prior page before paging, enforces boundaries and offers zoom and honest text alternative", async () => {
    const ready = (page: number): DocumentPreview => ({ status: "ready", sourceKind: "pdf", page, pageCount: 2, text: null, image: "data:image/png;base64,marker", width: 100, height: 100 });
    const held = pending(); const read = vi.fn().mockResolvedValueOnce(ready(1)).mockReturnValueOnce(held.promise);
    render(<OriginalPreview documentId={id} name="Statement" read={read} />);
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    expect(await screen.findByText("Page 1 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous page" })); expect(read).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" })); expect(screen.getByText("Zoom 200%")).toBeInTheDocument();
    expect(screen.getByText("A text alternative is unavailable for this page.")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("heading"), { key: "ArrowRight" }); expect(screen.queryByRole("img")).toBeNull();
    await act(async () => held.resolve(ready(2)));
    fireEvent.click(screen.getByRole("button", { name: "Next page" })); expect(read).toHaveBeenCalledTimes(2);
    expect(read).toHaveBeenLastCalledWith(id, 2);
  });
  it("drops pending content on unmount, source change or document selection and safely handles older hosts", async () => {
    const held = pending(); const read = vi.fn(() => held.promise);
    const rendered = render(<OriginalPreview key="old" documentId={id} name="Old" read={read} />);
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    rendered.rerender(<OriginalPreview key="new" documentId={"b".repeat(64)} name="New" />);
    await act(async () => held.resolve(text("old original")));
    expect(screen.queryByText("old original")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    expect(await screen.findByText("Local preview is unavailable in this build.")).toBeInTheDocument();
  });
});

it("drops an earlier response after an explicit close and reopen produces a newer page", async () => {
  const first = pending(); const second = pending();
  const read = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  render(<OriginalPreview documentId={id} name="Statement" read={read} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  fireEvent.click(screen.getByRole("button", { name: "Close original" }));
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  await act(async () => second.resolve(text("newer visible page")));
  await act(async () => first.resolve(text("obsolete earlier response")));
  expect(screen.getByText("newer visible page")).toBeInTheDocument();
  expect(screen.queryByText("obsolete earlier response")).toBeNull();
});

it("drops a pending response when a vault transition starts with the same document identity", async () => {
  let end!: () => void; const held = pending();
  render(<OriginalPreview documentId={id} name="Statement" read={() => held.promise} subscribeEnd={(clear) => { end = clear; return () => {}; }} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  act(() => end());
  await act(async () => held.resolve(text("old vault same content ID")));
  expect(screen.queryByText("old vault same content ID")).toBeNull();
  expect(screen.queryByRole("button", { name: "Close original" })).toBeNull();
});

const pdfPage = (page: number): DocumentPreview => ({ status: "ready", sourceKind: "pdf", page, pageCount: 2, text: null, image: "data:image/png;base64,marker", width: 100, height: 100 });
it("keeps keyboard focus in the viewer during page loading and announces the completed page", async () => {
  const held = pending(); const read = vi.fn().mockResolvedValueOnce(pdfPage(1)).mockReturnValueOnce(held.promise);
  render(<OriginalPreview documentId={id} name="Statement" read={read} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  const next = await screen.findByRole("button", { name: "Next page" }); next.focus(); fireEvent.click(next);
  expect(screen.getByRole("heading")).toHaveFocus();
  expect(screen.queryByRole("img")).toBeNull();
  await act(async () => held.resolve(pdfPage(2)));
  expect(screen.getByRole("heading")).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent("Opened page 2 of 2 locally.");
});
it("allows horizontal arrow panning in the zoomed image without requesting another page", async () => {
  const read = vi.fn(async () => pdfPage(1)); render(<OriginalPreview documentId={id} name="Statement" read={read} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  fireEvent.click(await screen.findByRole("button", { name: "Zoom in" }));
  const imageRegion = screen.getByRole("region", { name: "Scrollable saved original page" }); imageRegion.focus();
  expect(fireEvent.keyDown(imageRegion, { key: "ArrowRight" })).toBe(true);
  expect(read).toHaveBeenCalledTimes(1); expect(imageRegion).toHaveFocus();
});
it("retains a keyboard focus target on page refusal and describes the actual retry destination", async () => {
  const held = pending(); const read = vi.fn().mockResolvedValueOnce(pdfPage(1)).mockReturnValueOnce(held.promise);
  render(<OriginalPreview documentId={id} name="Statement" read={read} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  const next = await screen.findByRole("button", { name: "Next page" }); next.focus(); fireEvent.click(next);
  await act(async () => held.resolve({ status: "unavailable", reason: "page_unavailable" }));
  expect(screen.getByRole("heading")).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent("Try opening again to return to page 1");
});

it("supports clearly announced fit, double and quadruple zoom without fetching or changing the page", async () => {
  const read = vi.fn(async () => pdfPage(1)); render(<OriginalPreview documentId={id} name="Statement" read={read} />);
  fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
  const zoomIn = await screen.findByRole("button", { name: "Zoom in" });
  expect(screen.getByText("Zoom 100% (fit width)")).toBeInTheDocument();
  fireEvent.click(zoomIn); expect(screen.getByText("Zoom 200%")).toBeInTheDocument();
  fireEvent.click(zoomIn); expect(screen.getByText("Zoom 400%")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Scrollable saved original page" })).toHaveAttribute("data-preview-zoom", "400");
  expect(zoomIn).toHaveAttribute("aria-disabled", "true"); fireEvent.click(zoomIn);
  fireEvent.click(screen.getByRole("button", { name: "Zoom out" })); expect(screen.getByText("Zoom 200%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Zoom out" })); expect(screen.getByText("Zoom 100% (fit width)")).toBeInTheDocument();
  expect(read).toHaveBeenCalledTimes(1);
});
it("scrolls the opened full-row reading heading into view", async () => {
  const scroll = vi.fn(); Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
  try {
    render(<OriginalPreview documentId={id} name="Statement" read={async () => text("saved text")} />);
    fireEvent.click(screen.getByRole("button", { name: "View saved original" }));
    expect(await screen.findByText("saved text")).toBeInTheDocument();
    expect(screen.getByRole("heading")).toHaveFocus(); expect(scroll).toHaveBeenCalledWith({ block: "start" });
  } finally { Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); }
});
