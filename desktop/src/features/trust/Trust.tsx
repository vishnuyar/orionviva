import { useState, type FormEvent } from "react";
import { CircleSlash, FileQuestion, Info } from "lucide-react";
import { PanelStateView } from "../../components/PanelStateView";
import { UNSPOKEN_REPLY, channelPresentation } from "../../components/actionChannel";
import type { EngineIdentity, FeatureResult, OutboundRecordView, SettingsActionState, SettingsView, TrustActionState, SurfaceMode, TransferActionState, TrustCapabilityGroup, TrustCapabilityState, TrustData, TrustNote, TrustSampleCapability } from "../../surface/types";

// What a screen needs to take a whole vault out and bring one back. A source
// that can do neither carries none of this, so the controls are absent rather
// than present and refusing.
// What a screen needs to say how figures are written and whether a model may
// be reached. A source that carries none of this renders no controls: the
// engine has not offered them, and a form that would have to refuse is worse
// than no form.
// Unattended work, and a file somebody can send. A source that carries neither
// renders no controls: a control that would have to refuse is worse than none.
export type MaintenanceControls = { state: TrustActionState; onRun: (spend: boolean) => void; onDiagnose: (file: string) => void };
export type SettingsControls = {
  settings: FeatureResult<SettingsView>;
  state: SettingsActionState;
  onPropose: (kind: "presentation" | "model", fields: Record<string, string>) => void;
  onConfirm: (kind: "presentation" | "model", fields: Record<string, string>, digest: string, key: string) => void;
};
export type TransferControls = { state: TransferActionState; onExport: (archive: string) => void; onRestore: (archive: string, directory: string, passphrase: string) => void };

// The one sentence this panel says about the last copy. What the vault
// answered stands until the next one is asked for; a reply that never reached
// an answer is said in the words every other screen uses for that channel.
function transferSentence(state: TransferActionState): string {
  if (state.state !== "settled") return "";
  if (state.result.state !== "settled") {
    const said = channelPresentation(state.result);
    return `${said.title}. ${said.detail}`;
  }
  return state.result.outcome.message.trim() || UNSPOKEN_REPLY;
}

// How figures are written, and whether a model may be reached. Two forms, kept
// apart the way the engine keeps them apart: the first sends nothing and says
// so, and the second is the moment bytes become able to leave. The proposal
// between pressing and agreeing is the whole point — the reply describing a
// change is not the change.
function Configuration({ controls }: { controls: SettingsControls }) {
  const [locale, setLocale] = useState("");
  const [currency, setCurrency] = useState("");
  const [adapter, setAdapter] = useState("anthropic");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const working = controls.state.state === "working";
  const proposal = controls.state.state === "proposed" ? controls.state.proposal : null;
  const settled = controls.state.state === "settled" ? controls.state.result : null;
  const said = settled ? (settled.state === "settled" ? settled.outcome.message.trim() || UNSPOKEN_REPLY : `${channelPresentation(settled).title}. ${channelPresentation(settled).detail}`) : "";
  const inForce = controls.settings.state === "ready" ? controls.settings.data : null;
  const presentationFields = { locale: locale.trim(), currency: currency.trim() };
  const modelFields = { adapter, model: model.trim() };
  return <section className="trust-settings" aria-labelledby="trust-settings-title">
    <h3 id="trust-settings-title">What this app has been told to do</h3>
    {inForce ? <dl className="trust-settings-current">
      <div><dt>Figures are written as</dt><dd>{inForce.locale} · {inForce.currency}</dd></div>
      <div><dt>Model</dt><dd>{inForce.canSend ? `${inForce.adapter} · ${inForce.model}` : "None. Nothing can be sent anywhere."}</dd></div>
    </dl> : <p>This source did not say what is in force.</p>}
    <form className="trust-settings-form" onSubmit={(event) => { event.preventDefault(); if (!working) controls.onPropose("presentation", presentationFields); }}>
      <label>Write numbers as<input value={locale} onChange={(event) => setLocale(event.target.value)} placeholder="en-US" autoComplete="off" /></label>
      <label>Label totals<input value={currency} onChange={(event) => setCurrency(event.target.value)} placeholder="USD" autoComplete="off" /></label>
      <button className="secondary-button" type="submit" aria-disabled={working}>Show me what would change</button>
    </form>
    <form className="trust-settings-form" onSubmit={(event) => { event.preventDefault(); if (!working) controls.onPropose("model", modelFields); }}>
      <label>Reach a model through<select value={adapter} onChange={(event) => setAdapter(event.target.value)}><option value="anthropic">anthropic</option><option value="openai-compatible">openai-compatible</option></select></label>
      <label>Named exactly<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="a pinned model id" autoComplete="off" /></label>
      <label>Its key<input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="Paste the key" autoComplete="off" /></label>
      <button className="secondary-button" type="submit" aria-disabled={working}>Show me what would change</button>
    </form>
    {proposal ? <div className={proposal.sends ? "trust-settings-proposal sends" : "trust-settings-proposal"}>
      <p>{proposal.message}</p>
      <dl>{Object.entries(proposal.changes).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value || "nothing"}</dd></div>)}</dl>
      <button className="primary-button" type="button" aria-disabled={working} onClick={() => { if (!working) controls.onConfirm(proposal.kind, proposal.kind === "presentation" ? presentationFields : modelFields, proposal.digest, proposal.kind === "model" ? key : ""); setKey(""); }}>Yes, do that</button>
    </div> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{said}</div>
    {said ? <p className="trust-settings-answer">{said}</p> : null}
  </section>;
}

// Taking a whole vault out, and bringing one back into a folder of its own.
// Nothing here decides what happened: the sentence is the vault's, and the two
// forms only carry what a person typed.
function VaultCopy({ transfer }: { transfer: TransferControls }) {
  const [archive, setArchive] = useState("");
  const [restoreArchive, setRestoreArchive] = useState("");
  const [directory, setDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const working = transfer.state.state === "working";
  const said = transferSentence(transfer.state);
  function takeCopy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working) return;
    transfer.onExport(archive);
  }
  function bringBack(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working) return;
    transfer.onRestore(restoreArchive, directory, passphrase);
    setPassphrase("");
  }
  return <section className="trust-transfer" aria-labelledby="trust-transfer-title">
    <h3 id="trust-transfer-title">A copy of this whole vault</h3>
    <p>A copy is written without decrypting anything, so the file is exactly as private as this vault — and exactly as lost as this vault if you lose the passphrase. Bringing one back writes into an empty folder and never over a vault in use.</p>
    <form className="trust-transfer-form" onSubmit={takeCopy}>
      <label>Write the copy to<input value={archive} onChange={(event) => setArchive(event.target.value)} placeholder="/path/to/copy.orionvault" autoComplete="off" /></label>
      <button className="secondary-button" type="submit" aria-disabled={working} aria-describedby={working ? "trust-transfer-waiting" : undefined}>Take a copy</button>
    </form>
    <form className="trust-transfer-form" onSubmit={bringBack}>
      <label>Bring back the copy at<input value={restoreArchive} onChange={(event) => setRestoreArchive(event.target.value)} placeholder="/path/to/copy.orionvault" autoComplete="off" /></label>
      <label>Into the empty folder<input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="/path/to/new-folder" autoComplete="off" /></label>
      <label>Its passphrase<input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} placeholder="Enter passphrase" autoComplete="off" /></label>
      <button className="secondary-button" type="submit" aria-disabled={working} aria-describedby={working ? "trust-transfer-waiting" : undefined}>Bring it back</button>
    </form>
    {working ? <span className="action-explanation" id="trust-transfer-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{said}</div>
    {said ? <p className="trust-transfer-answer">{said}</p> : null}
  </section>;
}

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

// Everything this vault has ever sent, as the read composed it. Every sentence
// here was written on the other side of the bridge, including both absences:
// what the record does not cover, and that nothing outside this machine holds a
// hash of any of it. A screen that wrote its own caveats would write them out
// of date the day the capability landed, and nothing would go red.
//
// A vault that has sent nothing renders the same panel with the same
// prominence. The emptiness is the record, and hiding it would keep the promise
// by having nothing to show rather than by showing it.
function OutboundRecord({ record }: { record: OutboundRecordView }) {
  return <section className="trust-outbound" aria-labelledby="trust-outbound-title">
    <h3 id="trust-outbound-title">Everything this vault has sent</h3>
    <p className="trust-outbound-lead">{record.sentence}</p>
    {record.phases.length ? <ul className="trust-outbound-phases">{record.phases.map((phase) => <li key={phase.id}>{phase.sentence}</li>)}</ul> : null}
    {record.span ? <p>{record.span.sentence}</p> : null}
    {record.modelSentence ? <p>{record.modelSentence}</p> : null}
    {record.models.length ? <dl className="trust-outbound-models">{record.models.map((model) => <div key={model.name}><dt>{model.name}</dt><dd>{model.count}</dd></div>)}</dl> : null}
    {record.cost ? <p className="trust-outbound-cost">{record.cost.sentence}</p> : null}
    {record.absences.length ? <ul className="trust-outbound-absences">{record.absences.map((absence) => <li key={absence.id}>{absence.sentence}</li>)}</ul> : null}
  </section>;
}

// What nothing on this machine can establish. The sentences are the read's, and
// they are rendered plainly and near the top rather than filed under a
// disclosure: an absence a person has to open something to find is an absence
// they will not find.
function Absences({ absences }: { absences: readonly { id: string; sentence: string }[] }) {
  if (!absences.length) return null;
  return <section className="trust-absences" aria-labelledby="trust-absences-title">
    <h3 id="trust-absences-title">What this cannot establish</h3>
    <ul>{absences.map((absence) => <li key={absence.id}>{absence.sentence}</li>)}</ul>
  </section>;
}

// Unattended work, and a file somebody can send. Planning is what the control
// does; spending is a second control with its own word on it, because the
// difference between the two is money leaving.
function Maintenance({ controls }: { controls: MaintenanceControls }) {
  const [file, setFile] = useState("");
  const working = controls.state.state === "working";
  const settled = controls.state.state === "settled" ? controls.state.result : null;
  const said = settled ? (settled.state === "settled" ? settled.outcome.message.trim() || UNSPOKEN_REPLY : `${channelPresentation(settled).title}. ${channelPresentation(settled).detail}`) : "";
  return <section className="trust-maintenance" aria-labelledby="trust-maintenance-title">
    <h3 id="trust-maintenance-title">Work this app could do on its own</h3>
    <p>Planning shows what it would do and does none of it. Running it spends model calls, and every one of them lands in the record above.</p>
    <div className="trust-maintenance-controls">
      <button className="secondary-button" type="button" aria-disabled={working} onClick={() => { if (!working) controls.onRun(false); }}>Show me what it would do</button>
      <button className="secondary-button" type="button" aria-disabled={working} onClick={() => { if (!working) controls.onRun(true); }}>Run it, and spend</button>
    </div>
    <form className="trust-maintenance-form" onSubmit={(event) => { event.preventDefault(); if (!working) controls.onDiagnose(file); }}>
      <label>Write a file I can send<input value={file} onChange={(event) => setFile(event.target.value)} placeholder="/path/to/diagnostic.json" autoComplete="off" /></label>
      <button className="secondary-button" type="submit" aria-disabled={working}>Write it</button>
    </form>
    <p>That file holds what this build is and what has gone through it as counts. No name, no amount, no document and nothing from your records.</p>
    {working ? <span className="action-explanation" id="trust-maintenance-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}
    <div className="visually-hidden" role="status" aria-live="polite">{said}</div>
    {said ? <p className="trust-maintenance-answer">{said}</p> : null}
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

function TrustReady({ data, mode, identity, transfer, settings, maintenance }: { data: TrustData; mode: SurfaceMode; identity: FeatureResult<EngineIdentity>; transfer: TransferControls | null; settings: SettingsControls | null; maintenance: MaintenanceControls | null }) {
  const capabilities = mode === "demo" ? data.sample?.capabilities ?? [] : [];
  const capabilityRows = identifiedRows(capabilities, "trust-capability");
  // A vault that has sent nothing is not an empty Trust screen: the outbound
  // record is present and says so, which is the whole of what this destination
  // is for.
  const empty = !data.notes.length && !capabilities.length && !data.outbound && !(data.absences ?? []).length;
  return <section className="feature-panel trust-panel"><header className="trust-header"><div className="detail-panel-label">{mode === "demo" ? "Preview-owned explanation" : "Supplied Trust view"}</div><h2>Trust and limitations</h2><p>{mode === "demo" ? "This destination explains what the fictional preview can and cannot establish. It is not a trust report for a private vault." : "These notes are shown exactly as supplied by the Trust view. This interface does not independently verify them or establish a complete outbound, integrity, anchoring, or recovery history."}</p></header><EngineRow identity={identity} /><Absences absences={data.absences ?? []} />{data.outbound ? <OutboundRecord record={data.outbound} /> : null}{maintenance ? <Maintenance controls={maintenance} /> : null}{settings ? <Configuration controls={settings} /> : null}{transfer ? <VaultCopy transfer={transfer} /> : null}{empty ? <div className="empty-state"><strong>{mode === "demo" ? "No sample Trust details" : "No Trust notes supplied"}</strong><span>{mode === "demo" ? "This fictional sample does not include Trust notes or preview capability explanations." : "The supplied Trust view contains no notes. This does not establish zero outbound, model, or maintenance activity, or any integrity or recovery status."}</span></div> : mode === "live" ? <section className="trust-notes" aria-labelledby="trust-notes-title"><h3 id="trust-notes-title">Notes supplied by this Trust view</h3><p>A supplied note is displayed text, not an independently verified guarantee or complete history.</p><NoteRows notes={data.notes} mode={mode} /></section> : <><section className="trust-preview-statements" aria-labelledby="trust-preview-statements-title"><h3 id="trust-preview-statements-title">What this preview can say</h3><ul><li><strong>Fictional source</strong><span>The currently displayed sample names, documents, figures, and Trust rows are fixture-authored. They are not facts about a private vault.</span></li><li><strong>Static interactions</strong><span>Opening and closing these preview rows changes only what is visible. It does not write a vault event, call a model, send data, or change a setting.</span></li><li><strong>No Trust read</strong><span>This sample does not establish what a private vault sent, which models ran, whether maintenance occurred, or whether integrity checks passed.</span></li></ul></section><section className="trust-notes" aria-labelledby="trust-notes-title"><h3 id="trust-notes-title">Preview notes</h3><NoteRows notes={data.notes} mode={mode} /></section><section className="trust-capabilities" aria-label="Preview capability explanations"><CapabilityIdentityRows rows={capabilityRows} />{(["source", "outbound_models", "integrity", "continuity", "build_support"] as const).map((group) => <details key={group} open={group === "source"}><summary>{groupCopy[group]}</summary><CapabilityRows rows={capabilityRows} group={group} /></details>)}</section><section className="trust-final-limitation"><CircleSlash aria-hidden="true" size={20} /><div><h3>No settings are changed here</h3><p>These preview rows are explanatory only. They cannot recover a passphrase, create an anchor, or update the app.</p></div></section></>}</section>;
}

export function Trust({ result, mode, identity, transfer, settings, maintenance }: { result: FeatureResult<TrustData>; mode: SurfaceMode; identity: FeatureResult<EngineIdentity>; transfer: TransferControls | null; settings: SettingsControls | null; maintenance: MaintenanceControls | null }) {
  return <PanelStateView result={result} copy={{ partial: "Some Trust details are unavailable. Supplied notes and preview limitations are shown below.", needsInput: "Some Trust details need more information. Supplied notes and preview limitations are shown below.", unavailable: { title: "Trust details unavailable", detail: "Trust and maintenance details are not connected to this private-vault read." }, failed: { title: "Trust details could not be read", detail: "Trust and maintenance details could not be read. The private vault is still open." } }}>{(data) => <TrustReady data={data} mode={mode} identity={identity} transfer={transfer} settings={settings} maintenance={maintenance} />}</PanelStateView>;
}
