import { useEffect, useRef, useState } from "react";
import type { AccountingView, AccountingLine, AccountingNode, FeatureResult } from "../surface/types";

function Evidence({ lines, onInspectDocument }: { lines: AccountingLine[]; onInspectDocument?: (documentId: string) => void }) {
  return <ul className="accounting-evidence">{lines.map((line, index) => <li key={`${line.id}-${index}`}><strong>{line.label}</strong><span>{line.date} · {line.currency} · {line.display}</span><dl><div><dt>Amount evidence</dt><dd>{line.amountEvidence || "Recorded financial activity"}</dd></div><div><dt>Accounting treatment</dt><dd>{line.classificationEvidence || line.origin || "Derived from the recorded account"}{line.provisional ? " · Provisional interpretation" : ""}{line.classifiedBy ? ` · ${line.classifiedBy}` : ""}</dd></div>{line.existingExplanation ? <div><dt>Your existing explanation</dt><dd>{line.existingExplanation}</dd></div> : null}</dl>{line.supportingComponents?.length ? <div><strong>What the supporting document records</strong><dl className="accounting-totals">{line.supportingComponents.map((component, componentIndex) => <div key={`${component.label}-${componentIndex}`}><dt>{component.label}</dt><dd>{component.display}</dd></div>)}</dl></div> : null}{onInspectDocument ? line.documentIds?.map((documentId, sourceIndex) => <button type="button" className="proof-link" key={documentId} onClick={() => onInspectDocument(documentId)}>View source{line.documentIds!.length > 1 ? ` ${sourceIndex + 1}` : ""}</button>) : null}</li>)}</ul>;
}
function Branch({ node }: { node: AccountingNode }) {
  return <li>{node.children.length ? <details><summary><span>{node.label}</span><strong>{node.display}</strong></summary><ul>{node.children.map((child, index) => <Branch key={`${child.label}-${index}`} node={child} />)}</ul></details> : <div className="accounting-leaf"><span>{node.label}</span><strong>{node.display}</strong></div>}</li>;
}
export type AccountingReader = (start: string, end: string) => Promise<FeatureResult<AccountingView>>;

export function AccountingReports({ report: initialReport, accountingReader, onInspectDocument }: { report: AccountingView; accountingReader?: AccountingReader; onInspectDocument?: (documentId: string) => void }) {
  const [selected, setSelected] = useState<AccountingView | null>(null);
  const [start, setStart] = useState(initialReport.start);
  const [end, setEnd] = useState(initialReport.end);
  const [working, setWorking] = useState(false);
  const [status, setStatus] = useState("");
  const report = selected ?? initialReport;
  const selectedPeriod = useRef<{ start: string; end: string } | null>(null);
  const generation = useRef(0);
  const snapshot = JSON.stringify(initialReport);
  const previousSnapshot = useRef(snapshot);
  useEffect(() => () => { ++generation.current; }, []);
  useEffect(() => {
    if (previousSnapshot.current === snapshot) return;
    previousSnapshot.current = snapshot;
    if (selectedPeriod.current && accountingReader) void readPeriod(selectedPeriod.current);
    else { setStart(initialReport.start); setEnd(initialReport.end); }
  }, [snapshot, accountingReader]);
  async function readPeriod(refreshPeriod?: { start: string; end: string }) {
    if (!accountingReader || (working && !refreshPeriod)) return;
    const period = refreshPeriod ?? { start, end };
    selectedPeriod.current = period;
    const requestGeneration = ++generation.current;
    setWorking(true);
    setStatus("Updating financial statements. The previous period remains visible until the reports are ready.");
    try {
      const result = await accountingReader(period.start, period.end);
      if (requestGeneration !== generation.current) return;
      if (result.state === "ready" || result.state === "partial" || result.state === "needs_input") {
        setSelected(result.data);
        setStatus(result.state === "ready" ? "Financial statements updated." : `Financial statements updated with incomplete coverage. ${result.issues.map((issue) => issue.message).filter(Boolean).join(" ")}`);
      } else {
        const reason = result.state === "failed" && result.reason === "invalid_payload" ? "The report reply could not be read." : result.state === "absent" && result.reason === "locked" ? "Open your vault to update these reports." : result.state === "unavailable" ? "Financial statements are unavailable for this request." : "The financial statement read did not complete.";
        setStatus(`Financial statements could not be updated. ${reason} The previous period remains visible.`);
      }
    } catch { if (requestGeneration === generation.current) setStatus("Financial statements could not be updated. The previous period remains visible."); }
    finally { if (requestGeneration === generation.current) setWorking(false); }
  }
  return <section className="section-block accounting-reports" aria-labelledby="financial-statements-title"><div className="section-heading"><div><div className="section-kicker">Your recorded financial activity</div><h2 id="financial-statements-title">Financial statements</h2></div></div><p>Personal finance reports. Each currency is shown separately.</p>{accountingReader ? <form className="accounting-period" onSubmit={(event) => { event.preventDefault(); void readPeriod(); }}><label>Period start<input type="date" value={start} max={end || undefined} onChange={(event) => setStart(event.target.value)} /></label><label>Period end<input type="date" required value={end} min={start || undefined} onChange={(event) => setEnd(event.target.value)} /></label><button type="submit" className="secondary-button" aria-disabled={working} aria-describedby={working ? "accounting-period-status" : undefined}>{working ? "Updating…" : "Update period"}</button></form> : null}{status ? <p id="accounting-period-status" role="status" aria-live="polite">{status}</p> : null}<div className="accounting-grid"><article className="accounting-card" aria-labelledby="balance-sheet-title"><h3 id="balance-sheet-title">Balance sheet</h3><p>As of {report.asOf}</p>{report.balanceTotals.map((row) => <div key={row.currency}><h4>{row.currency}</h4><dl className="accounting-totals"><div><dt>Assets</dt><dd>{row.values.assets}</dd></div><div><dt>Liabilities</dt><dd>{row.values.liabilities}</dd></div><div><dt>Net worth</dt><dd>{row.values.net}</dd></div></dl></div>)}{!report.balances.length ? <p>Add a statement to establish your account balances.</p> : null}{!report.balanceComplete ? <p>Available balances are shown; the inventory is incomplete.</p> : null}<details><summary>Balance sources and coverage</summary><Evidence onInspectDocument={onInspectDocument} lines={report.balances} />{report.missing.map((item, index) => <p key={`${item.label}-${index}`}><strong>{item.label}</strong> {item.reason || "Balance is not measured."}</p>)}{report.heldCount ? <p>Some documents have not contributed verified activity. Their status is available in Documents.</p> : null}</details></article><article className="accounting-card" aria-labelledby="profit-loss-title"><h3 id="profit-loss-title">Profit and loss</h3><p>{report.start || "Recorded history"} – {report.end}</p>{report.profitTotals.map((row) => <div key={row.currency}><h4>{row.currency}</h4><dl className="accounting-totals"><div><dt>Income</dt><dd>{row.values.income}</dd></div><div><dt>Expenses</dt><dd>{row.values.expenses}</dd></div><div><dt>Net income</dt><dd>{row.values.net}</dd></div></dl><details><summary>Provisional contribution</summary><dl className="accounting-totals"><div><dt>Provisional income</dt><dd>{row.values.provisional_income}</dd></div><div><dt>Provisional expenses</dt><dd>{row.values.provisional_expenses}</dd></div></dl><p>These interpretations are included in working totals. They remain inferred until stronger evidence is available.</p></details></div>)}{!report.lines.length && !report.unresolved.length ? <p>No income or expense activity is recorded for this period.</p> : null}{report.hierarchy.map((group) => <details key={group.currency}><summary>{group.currency} categories and merchants</summary><ul className="accounting-tree">{group.roots.map((root, index) => <Branch key={`${root.label}-${index}`} node={root} />)}</ul></details>)}<details><summary>Transaction amounts and accounting evidence</summary><Evidence onInspectDocument={onInspectDocument} lines={report.lines} /></details>{report.unresolved.length ? <details open><summary>Unresolved payment components</summary><p>Measured payments are preserved. Their missing allocation limits these reports; no component amount has been assumed.</p><Evidence onInspectDocument={onInspectDocument} lines={report.unresolved} /></details> : null}</article></div></section>;
}
