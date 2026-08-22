import { useEffect, useRef, useState } from "react";
import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { activityEvidenceFigure } from "../../surface/evidence";
import type { ActivityData, ActivityView, EvidenceLink, FeatureResult, SampleActivityFacet, SurfaceMode } from "../../surface/types";
import { emptySampleActivityFilters, filterSampleActivity, firstUniqueActivityId, resolveActivitySelection, resolveRelatedActivity, retainVisibleActivitySelection, type SampleActivityFilters } from "./activityPresentation";

type ActivityProps = { result: FeatureResult<ActivityData>; mode: SurfaceMode; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void };

function Header({ mode }: { mode: SurfaceMode }) {
  return <header className="activity-header"><div className="detail-panel-label">{mode === "demo" ? "Fictional sample" : "Current Activity view"}</div><h2>{mode === "demo" ? "Sample activity" : "Activity"}</h2><p>{mode === "demo" ? "These movements and organization labels are fictional and stored with the app. Searching, filtering, and selecting change only this view. No vault event, categorization, tag, correction, transfer ruling, model call, outbound action, or durable state change occurs." : "These movement rows are shown from the supplied Activity view. This screen does not calculate totals, direction, categories, nature, or transfer relationships."}</p></header>;
}

function FacetSelect({ label, allLabel, value, options, onChange }: { label: string; allLabel: string; value: string; options: readonly SampleActivityFacet[]; onChange: (value: string) => void }) {
  return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">{allLabel}</option>{options.map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select></label>;
}

function DemoControls({ data, query, filters, visibleCount, onQuery, onFilter, onClear }: { data: ActivityData; query: string; filters: SampleActivityFilters; visibleCount: number; onQuery: (value: string) => void; onFilter: (next: SampleActivityFilters) => void; onClear: () => void }) {
  const catalog = data.sample?.filters;
  if (!catalog) return <section className="activity-controls"><div className="empty-state"><strong>Sample filters unavailable</strong><span>This fictional sample does not include authored filter choices.</span></div></section>;
  return <section className="activity-controls" aria-labelledby="activity-controls-title"><h3 id="activity-controls-title">Explore fictional activity</h3><p>Literal matching only across authored sample text and identities.</p><label className="activity-search">Search fictional activity<input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search authored names and details" /></label><details><summary>Refine fictional sample</summary><div className="activity-filter-grid">
    <FacetSelect label="Sample date" allLabel="All sample dates" value={filters.date} options={catalog.dates} onChange={(date) => onFilter({ ...filters, date })} />
    <FacetSelect label="Sample account" allLabel="All sample accounts" value={filters.account} options={catalog.accounts} onChange={(account) => onFilter({ ...filters, account })} />
    <FacetSelect label="Sample merchant" allLabel="All sample merchants" value={filters.merchant} options={catalog.merchants} onChange={(merchant) => onFilter({ ...filters, merchant })} />
    <FacetSelect label="Sample category" allLabel="All sample categories" value={filters.category} options={catalog.categories} onChange={(category) => onFilter({ ...filters, category })} />
    <FacetSelect label="Sample tag" allLabel="All sample tags" value={filters.tag} options={catalog.tags} onChange={(tag) => onFilter({ ...filters, tag })} />
    <FacetSelect label="Sample nature" allLabel="All sample natures" value={filters.nature} options={catalog.natures} onChange={(nature) => onFilter({ ...filters, nature })} />
    <FacetSelect label="Sample direction" allLabel="All sample directions" value={filters.direction} options={catalog.directions} onChange={(direction) => onFilter({ ...filters, direction })} />
  </div></details><button className="secondary-button" type="button" onClick={onClear}>Clear sample view</button><p className="activity-result-count" aria-live="polite">{visibleCount === 1 ? "1 fictional sample movement shown." : `${visibleCount} fictional sample movements shown.`}</p></section>;
}

function MovementList({ items, allItems, mode, selectedId, onSelect, onOpenFigure }: { items: readonly ActivityView[]; allItems: readonly ActivityView[]; mode: SurfaceMode; selectedId: string; onSelect: (id: string) => void; onOpenFigure: (figureId: string) => void }) {
  return <section className="activity-list" aria-labelledby="activity-list-title"><h3 id="activity-list-title">Movement list</h3><p>{mode === "demo" ? "Select a fictional movement to inspect its authored details." : "Select a supplied movement to inspect its available details."}</p><ul>{items.map((item, occurrence) => {
    const identityCount = item.id.trim() ? allItems.filter((candidate) => candidate.id === item.id).length : 0;
    const selectable = Boolean(item.id.trim()) && identityCount === 1;
    return <li className="activity-list-row" key={`${item.id || "blank-activity"}-${occurrence}`}>{selectable ? <button type="button" className={selectedId === item.id ? "activity-select active" : "activity-select"} aria-pressed={selectedId === item.id} onClick={() => onSelect(item.id)}><span><strong>{item.label || (mode === "demo" ? "Sample movement label unavailable" : "Movement label was not supplied by this view.")}</strong><small>{item.id}</small></span><span className="activity-row-badge">{mode === "demo" ? "Fictional sample" : "Supplied movement"}</span></button> : <div className="activity-select activity-identity-state"><span><strong>{item.id.trim() ? "Activity identity conflicted" : "Activity identity unavailable"}</strong><small>{item.id.trim() ? "More than one row uses this activity ID. No row with this identity can be selected." : "This row has no stable activity ID, so it cannot be selected."}</small></span></div>}<Figure figure={activityEvidenceFigure(item)} onOpenEvidence={onOpenFigure} className="activity-list-figure" /></li>;
  })}</ul></section>;
}

function RecordIdentities({ item }: { item: ActivityView }) {
  return <section className="activity-records"><h4>Record identities</h4>{item.recordIds?.length ? <ul>{item.recordIds.map((recordId) => <li key={recordId}>{recordId}</li>)}</ul> : <p>Record identities were not supplied for this movement.</p>}</section>;
}

function CommonDetail({ item, mode, onOpenEvidence, onOpenFigure }: { item: ActivityView; mode: SurfaceMode; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void }) {
  return <><Figure figure={activityEvidenceFigure(item)} onOpenEvidence={onOpenFigure} className="activity-detail-figure" /><div className="activity-detail-grid"><div><span>Activity ID</span><strong>{item.id}</strong><small>An activity ID is the stable identity used for selection. It is not a list position, record ID, or document ID.</small></div><div><span>Movement detail</span><strong>{item.detail || (mode === "demo" ? "Sample movement detail was not authored for this movement." : "Movement detail was not supplied by this view.")}</strong></div><div><span>Supplied measure</span><strong>{item.measure}</strong><small>This measure is not used as proof of direction or category.</small></div><div><span>Supplied state</span><strong>{item.state}</strong></div></div><section className="activity-provenance"><h4>Provenance</h4><p>{item.provenance || "Provenance was not supplied for this movement."}</p></section><RecordIdentities item={item} />{item.evidenceLinks.length ? <ProofLinks label={mode === "demo" ? "View fictional source" : "View source"} links={item.evidenceLinks} onOpen={onOpenEvidence} /> : <p>{mode === "demo" ? "No fictional source document link was authored for this movement." : "No source document link was supplied for this movement."}</p>}</>;
}

function Organization({ item }: { item: ActivityView }) {
  const sample = item.sample;
  const values = [
    ["Sample date", sample?.date?.label || "Sample date was not authored for this movement."],
    ["Sample account", sample?.account?.label || "Sample account was not authored for this movement."],
    ["Sample merchant", sample?.merchant?.label || "Sample merchant was not authored for this movement."],
    ["Sample category", sample?.category?.label || "Sample category was not authored for this movement."],
    ["Sample tags", sample?.tags?.length ? sample.tags.map((tag) => tag.label).join(", ") : "Sample tags were not authored for this movement."],
    ["Sample nature", sample?.nature?.label || "Sample nature was not authored for this movement."],
    ["Sample direction", sample?.direction?.label || "Sample direction was not authored for this movement."],
  ];
  return <section className="activity-organization"><h4>Fictional organization details</h4><p>These labels were authored for the sample. They are not inferred from the amount, sign, measure, or description.</p><div className="activity-organization-grid">{values.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>;
}

function Relationships({ item, items, onOpenRelated }: { item: ActivityView; items: readonly ActivityView[]; onOpenRelated: (targetId: string) => void }) {
  const relationships = item.sample?.relationships ?? [];
  return <section className="activity-relationships"><h4>Fictional relationship anatomy</h4><p>This authored sample points to another fictional movement by activity ID. It does not assert or create a live transfer link.</p>{relationships.length ? relationships.map((relationship, occurrence) => {
    const target = resolveRelatedActivity(items, relationship.targetActivityId);
    if (target.state === "ready") return <div className="activity-relationship" key={`${relationship.targetActivityId}-${occurrence}`}><button type="button" className="secondary-button" onClick={() => onOpenRelated(target.item.id)}>View related fictional movement: {relationship.label}</button><span>Opening a related sample movement clears the local sample filters so the exact target can be shown. Nothing is written.</span></div>;
    const detail = target.state === "missing_identity" ? "This fictional relationship does not include an activity identity." : target.state === "missing_activity" ? "The related fictional movement is not present in this sample." : "More than one fictional movement uses the related activity ID. No related movement was opened.";
    return <p key={`${relationship.targetActivityId}-${occurrence}`}>{detail}</p>;
  }) : <p>No fictional relationship was authored for this movement.</p>}</section>;
}

function SelectionDetail({ selection, mode, allItems, onOpenEvidence, onOpenFigure, onOpenRelated }: { selection: ReturnType<typeof resolveActivitySelection>; mode: SurfaceMode; allItems: readonly ActivityView[]; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void; onOpenRelated: (targetId: string) => void }) {
  if (selection.state === "ready") {
    const item = selection.item;
    return <aside className="activity-detail" aria-labelledby="selected-activity-title"><div className="detail-panel-label">Selected movement</div><h3 id="selected-activity-title" data-activity-id={item.id} tabIndex={-1}>{item.label || (mode === "demo" ? "Sample movement label unavailable" : "Movement label was not supplied by this view.")}</h3><CommonDetail item={item} mode={mode} onOpenEvidence={onOpenEvidence} onOpenFigure={onOpenFigure} />{mode === "demo" && <><Organization item={item} /><Relationships item={item} items={allItems} onOpenRelated={onOpenRelated} /></>}<section className="activity-limitations"><h4>{mode === "demo" ? "Organization is view-only" : "Organization actions are not connected"}</h4><p>{mode === "demo" ? "Categories, tags, nature, direction, and relationships in this sample are fictional descriptions. This screen cannot categorize, tag, correct, link, unlink, confirm a transfer, write a vault event, call a model, or send anything." : "This screen cannot categorize, tag, correct, link, unlink, or confirm a transfer for private-vault activity."}</p></section></aside>;
  }
  let title = "No movement selected";
  let detail = "Choose a visible movement to inspect its supplied details.";
  let requestedId = "";
  if (selection.state === "missing") { title = "Selected movement unavailable"; detail = "The selected movement is no longer present in the current Activity view."; requestedId = selection.requestedId; }
  if (selection.state === "conflicted_identity") { title = "Movement selection unavailable"; detail = "More than one movement uses the selected activity identity, so the interface will not choose between them."; requestedId = selection.requestedId; }
  if (selection.state === "empty" && selection.reason === "no_selectable_identity") { title = "Movement selection unavailable"; detail = "The current Activity view contains rows, but none has a unique nonblank activity ID."; }
  return <aside className="activity-detail" aria-labelledby="selected-activity-title"><div className="detail-panel-label">Selected movement</div><h3 id="selected-activity-title" tabIndex={-1}>{title}</h3><div className="empty-state"><span>{detail}</span>{requestedId && <span>Requested activity ID: {requestedId}</span>}</div></aside>;
}

function ActivityReady({ data, mode, onOpenEvidence, onOpenFigure }: { data: ActivityData; mode: SurfaceMode; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void }) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SampleActivityFilters>(emptySampleActivityFilters);
  const [selectedId, setSelectedId] = useState(() => firstUniqueActivityId(data.items));
  const focusFrame = useRef<number | null>(null);
  const focusToken = useRef<object | null>(null);
  const instance = useRef({});
  const panelRef = useRef<HTMLElement>(null);
  const modeRef = useRef(mode);
  const itemsRef = useRef(data.items);
  const selectedIdRef = useRef(selectedId);
  modeRef.current = mode;
  itemsRef.current = data.items;
  selectedIdRef.current = selectedId;
  const visibleItems = mode === "demo" ? filterSampleActivity(data.items, query, filters) : data.items;
  const selection = resolveActivitySelection(data.items, selectedId);

  useEffect(() => () => { focusToken.current = null; if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current); }, []);

  function cancelRelatedFocus() { focusToken.current = null; if (focusFrame.current !== null) cancelAnimationFrame(focusFrame.current); focusFrame.current = null; }
  function updateQuery(next: string) { cancelRelatedFocus(); const visible = filterSampleActivity(data.items, next, filters); setQuery(next); setSelectedId((current) => retainVisibleActivitySelection(data.items, visible, current)); }
  function updateFilters(next: SampleActivityFilters) { cancelRelatedFocus(); const visible = filterSampleActivity(data.items, query, next); setFilters(next); setSelectedId((current) => retainVisibleActivitySelection(data.items, visible, current)); }
  function clearView() { cancelRelatedFocus(); setQuery(""); setFilters(emptySampleActivityFilters); setSelectedId((current) => retainVisibleActivitySelection(data.items, data.items, current)); }
  function select(id: string) { cancelRelatedFocus(); setSelectedId(id); }
  function openRelated(targetId: string) {
    cancelRelatedFocus();
    const token = {};
    const owner = instance.current;
    focusToken.current = token;
    selectedIdRef.current = targetId;
    setQuery(""); setFilters(emptySampleActivityFilters); setSelectedId(targetId);
    focusFrame.current = requestAnimationFrame(() => {
      const latestTarget = resolveRelatedActivity(itemsRef.current, targetId);
      const title = panelRef.current?.querySelector<HTMLElement>("#selected-activity-title");
      if (focusToken.current !== token || instance.current !== owner || modeRef.current !== "demo" || selectedIdRef.current !== targetId || latestTarget.state !== "ready" || title?.dataset.activityId !== targetId) {
        if (focusToken.current === token) { focusToken.current = null; focusFrame.current = null; }
        return;
      }
      focusToken.current = null; focusFrame.current = null;
      title.focus();
    });
  }

  // A live read composes its own rows, its own direction and its own sentence
  // about each of them. It is rendered by itself rather than through the demo
  // path: the two are different models, and merging them would let a fixture
  // field arrive on a row about real money.
  if (mode === "live") return <LiveMovements data={data} />;
  return <section ref={panelRef} className="feature-panel activity-panel"><Header mode={mode} />{!data.items.length ? <div className="empty-state"><strong>{mode === "demo" ? "No sample activity" : "No activity yet"}</strong><span>{mode === "demo" ? "This fictional sample does not include any movements." : "The supplied Activity view does not contain any movement rows."}</span></div> : <>{mode === "demo" && <DemoControls data={data} query={query} filters={filters} visibleCount={visibleItems.length} onQuery={updateQuery} onFilter={updateFilters} onClear={clearView} />}{mode === "demo" && !visibleItems.length ? <div className="empty-state"><strong>No fictional sample movements match this view</strong><span>Try clearing the literal search or one of the authored sample filters.</span><button type="button" className="secondary-button" onClick={clearView}>Clear sample view</button></div> : <div className="activity-layout"><MovementList items={visibleItems} allItems={data.items} mode={mode} selectedId={selectedId} onSelect={select} onOpenFigure={onOpenFigure} /><SelectionDetail selection={selection} mode={mode} allItems={data.items} onOpenEvidence={onOpenEvidence} onOpenFigure={onOpenFigure} onOpenRelated={openRelated} /></div>}</>}</section>;
}

// What moved, as the read composed it. Every word here is the backend's: the
// direction, the sentence saying what a row is where it is not plain spending,
// and the panel's own line about where the rows came from and where direction
// is read from. Nothing here counts, signs or names anything.
function LiveMovements({ data }: { data: ActivityData }) {
  const movements = data.movements ?? [];
  return <section className="feature-panel activity-panel">
    <header className="activity-header"><div className="detail-panel-label">Current vault read</div><h2>What moved</h2><p>{data.sentence}</p></header>
    {!movements.length ? <div className="empty-state"><strong>No movements in this read</strong><span>{data.sentence}</span></div> : <>
      <ul className="activity-movements">{movements.map((movement) => <li key={movement.id} className={movement.direction === "in" ? "activity-movement inflow" : "activity-movement outflow"}>
        <span className="activity-movement-when">{movement.date}</span>
        <span className="activity-movement-what"><strong>{movement.description || "No description was recorded for this movement."}</strong><small>{movement.account}</small></span>
        <span className="activity-movement-amount"><strong>{movement.display}</strong><small>{movement.direction === "in" ? "in" : "out"}</small></span>
        {movement.sentence ? <p className="activity-movement-note">{movement.sentence}</p> : null}
      </li>)}</ul>
      {data.beyond && data.beyond.count > 0 ? <p className="activity-beyond">{data.beyond.count} more are in this vault and not in this list.</p> : null}
    </>}
  </section>;
}

export function Activity({ result, mode, onOpenEvidence, onOpenFigure }: ActivityProps) {
  return <PanelStateView result={result} copy={{ partial: "Some activity details are unavailable. Available movements are shown below.", needsInput: "Some activity details need more information. Available movements are shown below.", unavailable: { title: "Activity unavailable", detail: "Activity is not connected to this private-vault read." }, failed: { title: "Activity could not be read", detail: "Activity could not be read. The private vault is still open." } }}>{(data) => <ActivityReady data={data} mode={mode} onOpenEvidence={onOpenEvidence} onOpenFigure={onOpenFigure} />}</PanelStateView>;
}
