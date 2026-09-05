import { useEffect, useRef, useState } from "react";
import type { FeatureResult, SpendingBreakdownData, SpendingGranularity, SpendingPeriodId, SpendingRequest } from "../surface/types";

const DEFAULT_REQUEST: SpendingRequest = { period: "latest_complete_month", granularity: "category" };

function hasData(result: FeatureResult<SpendingBreakdownData> | null): result is Extract<FeatureResult<SpendingBreakdownData>, { data: SpendingBreakdownData }> {
  return result?.state === "ready" || result?.state === "partial" || result?.state === "needs_input";
}

export function SpendingBreakdown({ read }: { read: (request: SpendingRequest) => Promise<FeatureResult<SpendingBreakdownData>> }) {
  const [request, setRequest] = useState<SpendingRequest>(DEFAULT_REQUEST);
  const [result, setResult] = useState<FeatureResult<SpendingBreakdownData> | null>(null);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const generation = useRef(0);
  const prior = hasData(result) ? result.data : null;

  useEffect(() => {
    const current = ++generation.current;
    setPending(true);
    setFailed(false);
    void read(request).then((next) => {
      if (current !== generation.current) return;
      setPending(false);
      if (next.state === "ready" || next.state === "partial" || next.state === "needs_input") setResult(next);
      else { setFailed(true); if (!prior) setResult(next); }
    }).catch(() => {
      if (current !== generation.current) return;
      setPending(false);
      setFailed(true);
    });
    return () => { generation.current += 1; };
    // `prior` is deliberately not a dependency: the last authored result stays
    // visible while this exact request is in flight or fails.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [read, request]);

  const data = hasData(result) ? result.data : null;
  if (!data) {
    if (pending) return <section className="spending-card" aria-labelledby="spending-title" aria-busy="true"><h2 id="spending-title">Spending breakdown</h2><p role="status">Reading an authored spending breakdown…</p></section>;
    const locked = result?.state === "absent" && ["locked", "denied", "refused", "no_vault"].includes(result.reason);
    return <section className="spending-card" aria-labelledby="spending-title"><h2 id="spending-title">Spending breakdown</h2><div className="empty-state"><strong>{locked ? "Spending breakdown is locked" : "Spending breakdown is unavailable"}</strong><span>{locked ? "Open and authorize this vault to read its spending breakdown." : "No valid authored chart is available from this vault."}</span></div></section>;
  }

  const update = (change: Partial<SpendingRequest>) => setRequest((current) => ({ ...current, ...change }));
  const choosePeriod = (period: SpendingPeriodId) => {
    if (period === "custom") {
      const startDate = customStart || data.period.startDate;
      const endDate = customEnd || data.period.endDate;
      setCustomStart(startDate); setCustomEnd(endDate);
      setRequest((current) => ({ ...current, period, startDate, endDate }));
    } else {
      setRequest((current) => ({ period, granularity: current.granularity, ...(current.accountId ? { accountId: current.accountId } : {}), ...(current.currency ? { currency: current.currency } : {}) }));
    }
  };
  const filtered = request.period !== DEFAULT_REQUEST.period || request.granularity !== DEFAULT_REQUEST.granularity || Boolean(request.accountId || request.currency);
  const describedBy = ["spending-period", "spending-scope", data.coverage.state !== "complete" ? "spending-coverage" : ""].filter(Boolean).join(" ");

  return <section className="spending-card" aria-labelledby="spending-title" aria-busy={pending}>
    <div className="spending-heading"><div><span className="section-kicker">From attested statements</span><h2 id="spending-title">{data.title}</h2></div>{filtered ? <button type="button" className="text-button" onClick={() => setRequest(DEFAULT_REQUEST)}>Reset filters</button> : null}</div>
    <div className="spending-controls" aria-label="Spending breakdown filters" aria-describedby={pending ? "spending-update" : undefined}>
      <label><span>Date</span><select aria-label="Spending date range" aria-disabled={pending} value={request.period} onChange={(event) => { if (!pending) choosePeriod(event.target.value as SpendingPeriodId); }}>{data.controls.periods.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      <label><span>Breakdown</span><select aria-label="Spending breakdown granularity" aria-disabled={pending} value={request.granularity} onChange={(event) => { if (!pending) update({ granularity: event.target.value as SpendingGranularity }); }}>{data.controls.granularities.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
      {data.controls.accounts.length ? <label><span>Scope</span><select aria-label="Spending account scope" aria-disabled={pending} value={request.accountId ?? ""} onChange={(event) => { if (pending) return; setRequest((current) => ({ period: current.period, granularity: current.granularity, ...(current.startDate ? { startDate: current.startDate } : {}), ...(current.endDate ? { endDate: current.endDate } : {}), ...(event.target.value ? { accountId: event.target.value } : {}) })); }}><option value="">All accounts</option>{data.controls.accounts.map((option) => <option key={option.id} value={option.id}>{option.label} · {option.currency}</option>)}</select></label> : null}
      {data.controls.currencies.length > 1 ? <label><span>Currency</span><select aria-label="Spending currency" aria-disabled={pending} value={request.currency ?? ""} onChange={(event) => { if (!pending) update({ currency: event.target.value || undefined }); }}><option value="">Separate totals</option>{data.controls.currencies.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label> : null}
    </div>
    {request.period === "custom" ? <form className="spending-custom-range" onSubmit={(event) => { event.preventDefault(); if (!pending && customStart && customEnd && customStart <= customEnd) update({ startDate: customStart, endDate: customEnd }); }}><label>Start date<input type="date" aria-disabled={pending} value={customStart} max={customEnd || data.asOf} onChange={(event) => { if (!pending) setCustomStart(event.target.value); }} /></label><label>End date<input type="date" aria-disabled={pending} value={customEnd} min={customStart} max={data.asOf} onChange={(event) => { if (!pending) setCustomEnd(event.target.value); }} /></label><button type="submit" className="secondary-button" aria-disabled={pending || !customStart || !customEnd || customStart > customEnd}>Apply dates</button></form> : null}
    <div className="spending-filter-summary" id="spending-period"><strong>{data.period.label}</strong><span id="spending-scope">{data.scopeSummary}</span></div>
    {pending ? <div className="spending-update" id="spending-update" role="status">Updating the breakdown. Filters are unavailable until this authored selection returns; the previous selection remains below.</div> : failed ? <div className="unavailable-callout" role="status">The new breakdown could not be read. The previous authored selection remains below.</div> : null}
    <p className={`spending-coverage spending-coverage-${data.coverage.state}`} id="spending-coverage"><strong>{data.coverage.label}</strong></p>
    {data.coverage.gaps.length || data.coverage.unsupportedAccounts.length ? <div className="spending-coverage-details"><strong>Coverage details</strong><ul>{data.coverage.gaps.map((gap) => <li key={`gap-${gap.order}`}>{gap.sentence}</li>)}{data.coverage.unsupportedAccounts.map((account) => <li key={`unsupported-${account.order}`}>{account.sentence}</li>)}</ul></div> : null}
    <div className="spending-sections">{data.sections.map((section) => <figure className="spending-figure" aria-describedby={describedBy} key={section.currency}>
      <figcaption><div><span>{section.currency}</span><strong>{section.totalDisplay}</strong></div><small>{data.granularity === "category" ? "By category" : "By subcategory"} · {section.includedCount} included movement{section.includedCount === 1 ? "" : "s"}</small></figcaption>
      {section.bars.length ? <ol className="spending-bars" aria-label={`${section.currency} spending, ${section.totalDisplay} total`}>{section.bars.map((bar) => <li key={bar.id} aria-label={`${bar.label}: ${bar.amountDisplay}; ${bar.count} included movement${bar.count === 1 ? "" : "s"}`}>
        <div className="spending-bar-label"><strong>{bar.label}</strong><span>{bar.amountDisplay}</span></div>
        <svg className="spending-bar-track" viewBox="0 0 10000 12" preserveAspectRatio="none" aria-hidden="true"><rect className="spending-bar-ground" x="0" y="0" width="10000" height="12" /><rect className={`spending-bar-fill spending-${bar.colorToken}`} x="0" y="0" width={bar.barBasisPoints} height="12" />{bar.barBasisPoints === 0 ? <line className="spending-zero-marker" x1="1" y1="0" x2="1" y2="12" /> : null}</svg>
        <small>{bar.count} movement{bar.count === 1 ? "" : "s"}</small>
      </li>)}</ol> : <div className="empty-state"><strong>{section.emptyMessage}</strong><span>{data.coverage.label}</span></div>}
    </figure>)}</div>
    {data.exclusions.length ? <details className="spending-disclosures"><summary>{data.coverage.excludedCount} excluded movement{data.coverage.excludedCount === 1 ? "" : "s"}</summary><ul>{data.exclusions.map((item) => <li key={item.kind}>{item.sentence} ({item.count})</li>)}</ul></details> : null}
    <details className="spending-disclosures"><summary>How this chart is counted</summary><ul>{data.notes.map((note) => <li key={note}>{note}</li>)}</ul><p>{data.timezonePolicy}</p></details>
  </section>;
}
