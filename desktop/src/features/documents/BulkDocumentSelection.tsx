import { useLayoutEffect, useRef, useState } from "react";
import type { BulkDocumentSession } from "../../surface/types";
import uploadCopy from "./bulk-upload-v1.json";
import retainedCopy from "./bulk-retained-reading-v1.json";

export type BulkDocumentControls = { session: BulkDocumentSession | null; working: boolean; onChoose: (() => void) | null; onStop: () => void };
function BulkStopButton({ stopping, onStop, removedWhileFocused, label }: { label: string; stopping: boolean; onStop: () => void; removedWhileFocused: { current: boolean } }) {
  const button = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => () => {
    const element = button.current;
    if (element && element.ownerDocument.activeElement === element) removedWhileFocused.current = true;
  }, [removedWhileFocused]);
  return <button ref={button} className="secondary-button" type="button" aria-describedby="bulk-document-status" aria-disabled={stopping} onClick={() => { if (!stopping) onStop(); }}>{label}</button>;
}

export function BulkDocumentSelection({ controls, unavailable }: { controls: BulkDocumentControls; unavailable: boolean }) {
  const [page, setPage] = useState(0);
  const progress = useRef<HTMLDivElement>(null);
  const removedWhileFocused = useRef(false);
  useLayoutEffect(() => {
    if (!removedWhileFocused.current) return;
    removedWhileFocused.current = false;
    const target = progress.current;
    if (target && target.ownerDocument.activeElement === target.ownerDocument.body) target.focus();
  });
  const selection = controls.session;
  const copy = selection?.mode === "retained" ? retainedCopy : uploadCopy;
  const total = selection?.rows.length ?? 0;
  const selectedPage = Math.min(page, Math.max(0, Math.ceil(total / 25) - 1));
  const start = selectedPage * 25;
  const terminal = selection?.rows.filter((row) => !["queued", "working", "uncertain", "not_started"].includes(row.status)).length ?? 0;
  const active = selection?.state === "running" || selection?.state === "stopping";
  return <section className="document-capture-status document-bulk-selection" aria-labelledby="bulk-document-title">
    <h2 id="bulk-document-title">{copy.title}</h2><p id="bulk-document-consent">{copy.detail}</p><p id="bulk-document-session">{copy.session}</p>
    {selection?.mode === "retained" && controls.onChoose ? <div><p id="bulk-new-upload-consent">{uploadCopy.detail}</p><button className="secondary-button" type="button" aria-describedby="bulk-new-upload-consent" aria-disabled={controls.working || unavailable} onClick={() => { if (!controls.working && !unavailable) { setPage(0); controls.onChoose?.(); } }}>{uploadCopy.choose}</button></div> : null}
    {controls.onChoose && selection?.mode !== "retained" ? <button className="secondary-button" type="button" aria-describedby="bulk-document-consent bulk-document-session bulk-document-status" aria-disabled={controls.working || unavailable} onClick={() => { if (!controls.working && !unavailable) { setPage(0); controls.onChoose?.(); } }}>{copy.choose}</button> : null}
    <div ref={progress} tabIndex={-1} id="bulk-document-status" role="status" aria-label={copy.progressLabel} aria-live="polite" aria-atomic="true">{selection ? <><p>{copy[selection.state].replace("{remaining}", String(total - terminal)).replace("{documentNoun}", total - terminal === 1 ? copy.documentSingular : copy.documentPlural).replace("{remainVerb}", total - terminal === 1 ? "remains" : "remain")}</p><p>{copy.counts.replace("{terminal}", String(terminal)).replace("{total}", String(total)).replace("{resultNoun}", terminal === 1 ? copy.resultSingular : copy.resultPlural).replace("{documentNoun}", total === 1 ? copy.documentSingular : copy.documentPlural)}</p></> : null}</div>
    {active ? <BulkStopButton label={copy.stop} stopping={selection?.state === "stopping"} onStop={controls.onStop} removedWhileFocused={removedWhileFocused} /> : null}
    {selection ? <>
      <p role="status" aria-label={copy.pageLabel} aria-live="polite" aria-atomic="true">{copy.pageCounts.replace("{first}", String(total ? start + 1 : 0)).replace("{last}", String(Math.min(start + 25, total))).replace("{total}", String(total))}</p>
      <ol start={start + 1}>{selection.rows.slice(start, start + 25).map((row, index) => <li key={start + index}>
        <strong className="bulk-document-name">{row.path.split(/[\\/]/).at(-1) || row.path}</strong><p>{copy.labels[row.status]}</p>
        {row.status === "refused" && !row.outcome ? <p>{copy.requestRefused}</p> : null}
        {row.documentId || row.outcome?.documentId ? <p>{copy.savedOriginal}: <code>{row.documentId || row.outcome?.documentId}</code></p> : null}
        {row.outcome?.disposition ? <p>{copy.readings[row.outcome.disposition]}</p> : null}
        {row.outcome?.reason ? <p>{copy.reason}: {({ ...uploadCopy.reasons, ...retainedCopy.reasons })[row.outcome.reason as keyof typeof retainedCopy.reasons]}</p> : null}
      </li>)}</ol>
      <nav aria-label="Selected document pages"><button className="secondary-button" type="button" aria-disabled={selectedPage === 0} onClick={() => { if (selectedPage > 0) setPage(selectedPage - 1); }}>{copy.previous}</button><button className="secondary-button" type="button" aria-disabled={start + 25 >= total} onClick={() => { if (start + 25 < total) setPage(selectedPage + 1); }}>{copy.next}</button></nav>
    </> : null}
  </section>;
}
