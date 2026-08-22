import { CircleSlash, FileQuestion, Info } from "lucide-react";
import { PanelStateView } from "../../components/PanelStateView";
import type { EngineIdentity, FeatureResult, SurfaceMode, TrustCapabilityGroup, TrustCapabilityState, TrustData, TrustNote, TrustSampleCapability } from "../../surface/types";

type IdentityRow<T> =
  | { state: "ready"; item: T; key: string }
  | { state: "missing_identity"; key: string }
  | { state: "conflicted_identity"; id: string; key: string };

function identifiedRows<T extends { readonly id: string }>(items: readonly T[], namespace: string): IdentityRow<T>[] {
  const counts = new Map<string, number>();
  for (const item of items) if (item.id.trim()) counts.set(item.id, (counts.get(item.id) ?? 0) + 1);
  const rows: IdentityRow<T>[] = [];
  const seen = new Set<string>();
  let missingIdentityShown = false;
  for (const item of items) {
    if (!item.id.trim()) {
      if (!missingIdentityShown) rows.push({ state: "missing_identity", key: `${namespace}:missing` });
      missingIdentityShown = true;
      continue;
    }
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    if (counts.get(item.id) === 1) rows.push({ state: "ready", item, key: `${namespace}:ready:${item.id}` });
    else rows.push({ state: "conflicted_identity", id: item.id, key: `${namespace}:conflict:${item.id}` });
  }
  return rows;
}

const groupCopy: Record<TrustCapabilityGroup, string> = {
  source: "Source and scope",
  outbound_models: "Outbound, models, and maintenance",
  integrity: "Integrity and anchoring",
  continuity: "Continuity and settings",
  build_support: "Build and support",
};

const capabilityStateCopy: Record<TrustCapabilityState, string> = {
  fictional_sample: "Fictional sample",
  preview_limitation: "Preview limitation",
  not_connected: "Not connected",
  not_supplied: "Not supplied",
  not_implemented: "Not implemented",
};

function capabilityStateLabel(state: string): string | null {
  switch (state) {
    case "fictional_sample": return capabilityStateCopy.fictional_sample;
    case "preview_limitation": return capabilityStateCopy.preview_limitation;
    case "not_connected": return capabilityStateCopy.not_connected;
    case "not_supplied": return capabilityStateCopy.not_supplied;
    case "not_implemented": return capabilityStateCopy.not_implemented;
    default: return null;
  }
}

// Which build answered, said where a person looking for it would look. It is
// the sidecar's own word for itself, including its word for not knowing — this
// screen never fills that in, because a plausible-looking revision is worse
// than a stated absence.
function EngineRow({ identity }: { identity: FeatureResult<EngineIdentity> }) {
  if (identity.state !== "ready") return <section className="trust-engine" aria-labelledby="trust-engine-title"><h3 id="trust-engine-title">The engine behind this vault</h3><p>This source did not say which build answered.</p></section>;
  const { protocol, revision } = identity.data;
  return <section className="trust-engine" aria-labelledby="trust-engine-title">
    <h3 id="trust-engine-title">The engine behind this vault</h3>
    <p>Shown as the engine reported itself when this vault was opened. It is not independently checked here.</p>
    <dl>
      <div><dt>Build</dt><dd>{revision.trim() ? revision : "The engine's reply carried no build at all."}</dd></div>
      <div><dt>Protocol</dt><dd>{protocol}</dd></div>
    </dl>
  </section>;
}

function NoteRows({ notes, mode }: { notes: readonly TrustNote[]; mode: SurfaceMode }) {
  return <ul className="trust-note-list">{identifiedRows(notes, "trust-note").map((row) => {
    if (row.state === "missing_identity") return <li className="trust-identity-state" key={row.key}><FileQuestion aria-hidden="true" size={18} /><div><strong>Trust note identity unavailable</strong><p>A supplied note has no stable ID, so it is not presented as an identified Trust record.</p></div></li>;
    if (row.state === "conflicted_identity") return <li className="trust-identity-state" key={row.key}><FileQuestion aria-hidden="true" size={18} /><div><strong>Trust note identity conflicted</strong><p>More than one supplied note uses this Trust ID. The interface will not merge them.</p><dl><div><dt>Note ID</dt><dd>{row.id}</dd></div></dl></div></li>;
    return <li className="trust-note" key={row.key}><div className="trust-note-heading"><span className="trust-state-label">{mode === "demo" ? "Preview note" : "Supplied note"}</span><Info aria-hidden="true" size={18} /></div><strong>{row.item.title.trim() ? row.item.title : "Note title was not supplied by this Trust view."}</strong><p>{row.item.detail.trim() ? row.item.detail : "Note detail was not supplied by this Trust view."}</p><dl><div><dt>Note ID</dt><dd>{row.item.id}</dd></div></dl></li>;
  })}</ul>;
}

function CapabilityRow({ capability }: { capability: TrustSampleCapability }) {
  const suppliedState = capability.state as string;
  const stateLabel = capabilityStateLabel(suppliedState);
  return <li className="trust-capability-row"><div className="trust-capability-heading"><strong>{capability.label.trim() ? capability.label : "Capability label was not authored for this preview row."}</strong><span className={stateLabel ? "trust-state-label" : "trust-state-label unavailable"}>{stateLabel ?? "Status unavailable"}</span></div><p>{stateLabel ? (capability.detail.trim() ? capability.detail : "Capability detail was not authored for this preview row.") : "This preview row supplied an unrecognized availability state. No capability claim is made."}</p>{!stateLabel && <dl><div><dt>Unrecognized supplied status value</dt><dd>{suppliedState.trim() ? suppliedState : "Status value was not supplied."}</dd></div></dl>}<dl><div><dt>Capability ID</dt><dd>{capability.id}</dd></div></dl></li>;
}

function CapabilityIdentityRows({ rows }: { rows: readonly IdentityRow<TrustSampleCapability>[] }) {
  const boundedRows = rows.filter((row) => row.state !== "ready");
  if (!boundedRows.length) return null;
  return <ul className="trust-capability-list trust-capability-identities">{boundedRows.map((row) => row.state === "missing_identity" ? <li className="trust-identity-state" key={row.key}><FileQuestion aria-hidden="true" size={18} /><div><strong>Capability identity unavailable</strong><p>A preview capability has no stable ID, so it is not presented as an identified capability row.</p></div></li> : <li className="trust-identity-state" key={row.key}><FileQuestion aria-hidden="true" size={18} /><div><strong>Capability identity conflicted</strong><p>More than one preview capability uses this Capability ID. The interface will not merge them.</p><dl><div><dt>Capability ID</dt><dd>{row.id}</dd></div></dl></div></li>)}</ul>;
}

function CapabilityRows({ rows, group }: { rows: readonly IdentityRow<TrustSampleCapability>[]; group: TrustCapabilityGroup }) {
  const grouped = rows.filter((row): row is Extract<IdentityRow<TrustSampleCapability>, { state: "ready" }> => row.state === "ready" && row.item.group === group);
  return <ul className="trust-capability-list">{grouped.map((row) => <CapabilityRow capability={row.item} key={row.key} />)}</ul>;
}

function TrustReady({ data, mode, identity }: { data: TrustData; mode: SurfaceMode; identity: FeatureResult<EngineIdentity> }) {
  const capabilities = mode === "demo" ? data.sample?.capabilities ?? [] : [];
  const capabilityRows = identifiedRows(capabilities, "trust-capability");
  const empty = !data.notes.length && !capabilities.length;
  return <section className="feature-panel trust-panel"><header className="trust-header"><div className="detail-panel-label">{mode === "demo" ? "Preview-owned explanation" : "Supplied Trust view"}</div><h2>Trust and limitations</h2><p>{mode === "demo" ? "This destination explains what the fictional preview can and cannot establish. It is not a trust report for a private vault." : "These notes are shown exactly as supplied by the Trust view. This interface does not independently verify them or establish a complete outbound, integrity, anchoring, or recovery history."}</p></header><EngineRow identity={identity} />{empty ? <div className="empty-state"><strong>{mode === "demo" ? "No sample Trust details" : "No Trust notes supplied"}</strong><span>{mode === "demo" ? "This fictional sample does not include Trust notes or preview capability explanations." : "The supplied Trust view contains no notes. This does not establish zero outbound, model, or maintenance activity, or any integrity or recovery status."}</span></div> : mode === "live" ? <section className="trust-notes" aria-labelledby="trust-notes-title"><h3 id="trust-notes-title">Notes supplied by this Trust view</h3><p>A supplied note is displayed text, not an independently verified guarantee or complete history.</p><NoteRows notes={data.notes} mode={mode} /></section> : <><section className="trust-preview-statements" aria-labelledby="trust-preview-statements-title"><h3 id="trust-preview-statements-title">What this preview can say</h3><ul><li><strong>Fictional source</strong><span>The currently displayed sample names, documents, figures, and Trust rows are fixture-authored. They are not facts about a private vault.</span></li><li><strong>Static interactions</strong><span>Opening and closing these preview rows changes only what is visible. It does not write a vault event, call a model, send data, or change a setting.</span></li><li><strong>No Trust read</strong><span>This sample does not establish what a private vault sent, which models ran, whether maintenance occurred, or whether integrity checks passed.</span></li></ul></section><section className="trust-notes" aria-labelledby="trust-notes-title"><h3 id="trust-notes-title">Preview notes</h3><NoteRows notes={data.notes} mode={mode} /></section><section className="trust-capabilities" aria-label="Preview capability explanations"><CapabilityIdentityRows rows={capabilityRows} />{(["source", "outbound_models", "integrity", "continuity", "build_support"] as const).map((group) => <details key={group} open={group === "source"}><summary>{groupCopy[group]}</summary><CapabilityRows rows={capabilityRows} group={group} /></details>)}</section><section className="trust-final-limitation"><CircleSlash aria-hidden="true" size={20} /><div><h3>No settings are changed here</h3><p>This destination is explanatory only. It cannot change provider or network permission, locale or currency display, export or back up a vault, recover a passphrase, run maintenance, create an anchor, update the app, or produce a diagnostic file.</p></div></section></>}</section>;
}

export function Trust({ result, mode, identity }: { result: FeatureResult<TrustData>; mode: SurfaceMode; identity: FeatureResult<EngineIdentity> }) {
  return <PanelStateView result={result} copy={{ partial: "Some Trust details are unavailable. Supplied notes and preview limitations are shown below.", needsInput: "Some Trust details need more information. Supplied notes and preview limitations are shown below.", unavailable: { title: "Trust details unavailable", detail: "Trust and maintenance details are not connected to this private-vault read." }, failed: { title: "Trust details could not be read", detail: "Trust and maintenance details could not be read. The private vault is still open." } }}>{(data) => <TrustReady data={data} mode={mode} identity={identity} />}</PanelStateView>;
}
