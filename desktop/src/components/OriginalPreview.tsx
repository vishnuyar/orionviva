import { useLayoutEffect, useRef, useState } from "react";
import type { DocumentPreview, DocumentPreviewReader } from "../surface/types";
const messages = {
  invalid_request: "This page cannot be opened.", original_unavailable: "The saved original is unavailable in this vault.", identity_unverifiable: "The saved original's identity could not be verified.", unsupported_type: "This file type cannot be previewed here.", unsupported_encoding: "This text encoding cannot be previewed here.", over_limit: "This original exceeds the local preview limits. It remains saved in your vault.", encrypted_pdf: "Password-protected PDFs cannot be previewed here.", damaged_original: "The saved original could not be verified or rendered.", page_unavailable: "This page is unavailable. Try opening again to return to page 1, or choose another document.", timed_out: "Opening the local preview took too long.", renderer_unavailable: "Local preview is unavailable in this build.",
};
type Props = { documentId: string; name: string; read?: DocumentPreviewReader; subscribeEnd?: (clear: () => void) => () => void };
// Only the explicit action fetches content. This component retains one page.
export function OriginalPreview({ documentId, name, read, subscribeEnd }: Props) {
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [zoom, setZoom] = useState<100 | 200 | 400>(100);
  const generation = useRef(0);
  const ended = useRef(false);
  const busy = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const close = (focus = true) => { ++generation.current; busy.current = false; setOpen(false); setWorking(false); setPreview(null); setZoom(100); if (focus) trigger.current?.focus(); };
  useLayoutEffect(() => {
    close(false);
    ended.current = false;
    const unsubscribe = subscribeEnd?.(() => { ended.current = true; close(false); });
    return () => { ended.current = true; ++generation.current; unsubscribe?.(); };
  }, [documentId, read, subscribeEnd]);
  useLayoutEffect(() => { if (open) { heading.current?.focus(); heading.current?.scrollIntoView?.({ block: "start" }); } }, [open]);
  async function load(page: number) {
    if (ended.current || busy.current) return;
    busy.current = true;
    const request = ++generation.current;
    // Keep focus on a persistent target before the previous page controls leave.
    if (open) heading.current?.focus();
    setOpen(true); setWorking(true); setPreview(null);
    let result: DocumentPreview;
    try { result = read ? await read(documentId, page) : { status: "unavailable", reason: "renderer_unavailable" }; }
    catch { result = { status: "unavailable", reason: "renderer_unavailable" }; }
    if (ended.current || generation.current !== request) return;
    busy.current = false; setWorking(false); setPreview(result);
  }
  const ready = preview?.status === "ready" ? preview : null;
  const page = (offset: number) => { if (!working && ready && ready.page + offset >= 1 && ready.page + offset <= ready.pageCount) void load(ready.page + offset); };
  return <section className="original-source">
    <p>Saved original: <strong>{name}</strong></p>
    <button ref={trigger} className="secondary-button" type="button" onClick={() => { if (!open) void load(1); }} aria-expanded={open}>View saved original</button>
    {open ? <section className="original-preview" aria-labelledby="original-preview-title" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); close(); } if (event.target !== heading.current) return; if (event.key === "ArrowLeft") { event.preventDefault(); page(-1); } if (event.key === "ArrowRight") { event.preventDefault(); page(1); } }}>
      <div className="original-preview-toolbar"><h3 ref={heading} tabIndex={-1} id="original-preview-title">Saved original: {name}</h3><button className="secondary-button" type="button" onClick={() => close()}>Close original</button></div>
      <p>This preview is made on this computer from your encrypted saved original. Opening it does not use your document reader.</p>
      <div role="status" aria-live="polite">{working ? "Opening locally…" : preview?.status === "unavailable" ? messages[preview.reason] : ready ? `Opened page ${ready.page} of ${ready.pageCount} locally.` : ""}</div>
      {preview?.status === "unavailable" ? <button className="secondary-button" type="button" onClick={() => void load(1)}>Try opening again</button> : null}
      {ready ? <>
        <div className="original-preview-toolbar"><span>Page {ready.page} of {ready.pageCount}</span>{ready.sourceKind === "pdf" ? <><button className="secondary-button" type="button" aria-disabled={ready.page === 1 || working} onClick={() => page(-1)}>Previous page</button><button className="secondary-button" type="button" aria-disabled={ready.page === ready.pageCount || working} onClick={() => page(1)}>Next page</button></> : null}{ready.image ? <><span aria-live="polite">{zoom === 100 ? "Zoom 100% (fit width)" : `Zoom ${zoom}%`}</span><button className="secondary-button" type="button" aria-disabled={zoom === 100} onClick={() => { if (zoom !== 100) setZoom(zoom === 400 ? 200 : 100); }}>Zoom out</button><button className="secondary-button" type="button" aria-disabled={zoom === 400} onClick={() => { if (zoom !== 400) setZoom(zoom === 100 ? 200 : 400); }}>Zoom in</button></> : null}</div>
        {ready.image ? <><p>Local preview of the saved original</p><div className={`original-preview-image original-preview-image-${zoom}`} data-preview-zoom={zoom} tabIndex={0} role="region" aria-label="Scrollable saved original page"><img src={ready.image} width={ready.width ?? undefined} height={ready.height ?? undefined} alt={`Local preview, page ${ready.page} of ${name}`} /></div>{ready.text !== null ? <details><summary>Extracted text alternative</summary><pre className="original-preview-text">{ready.text}</pre></details> : <p>A text alternative is unavailable for this page.</p>}</> : <pre className="original-preview-text" tabIndex={0}>{ready.text}</pre>}
      </> : null}
    </section> : null}
  </section>;
}
