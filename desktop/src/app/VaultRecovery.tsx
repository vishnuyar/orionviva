import { useEffect, useRef, useState, type FormEvent } from "react";
import { channelPresentation, UNSPOKEN_REPLY } from "../components/actionChannel";
import type { ActionResult } from "../surface/types";

type Props = {
  restore: (archive: string, directory: string, passphrase: string) => Promise<ActionResult>;
  pickArchive?: () => Promise<string | null>;
  pickDirectory?: () => Promise<string | null>;
  onBack: () => void;
  onOpen: (directory: string) => void;
};

export function VaultRecovery({ restore, pickArchive, pickDirectory, onBack, onOpen }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [archive, setArchive] = useState("");
  const [directory, setDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [result, setResult] = useState<ActionResult | null>(null);
  const [restoredDirectory, setRestoredDirectory] = useState("");
  const [pickerError, setPickerError] = useState("");
  useEffect(() => { heading.current?.focus(); }, []);
  function changed() { setResult(null); setRestoredDirectory(""); }
  async function choose(picker: () => Promise<string | null>, set: (value: string) => void) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setChoosing(true); setPickerError("");
    try { const path = await picker(); if (path !== null) { changed(); set(path); } }
    catch { setPickerError("The chooser could not select one path. Try again or enter the path below."); }
    finally { inFlight.current = false; setBusy(false); setChoosing(false); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || !archive.trim() || !directory.trim() || !passphrase) return;
    inFlight.current = true; setBusy(true); setResult(null); setPickerError("");
    const target = directory;
    const phrase = passphrase;
    setPassphrase(""); setRestoredDirectory("");
    try {
      const reply = await restore(archive, target, phrase);
      setResult(reply);
      if (reply.state === "settled" && reply.outcome.kind === "completed") setRestoredDirectory(target);
    } catch {
      setResult({ state: "interrupted", message: "The restore did not return a result. Inspect the destination before trying again; it may already contain your restored vault. OrionViva did not retry it." });
    } finally { inFlight.current = false; setBusy(false); setChoosing(false); }
  }
  const channel = result && result.state !== "settled" ? channelPresentation(result) : null;
  return <div className="welcome-setup">
    <button className="text-button" type="button" aria-disabled={busy} aria-describedby={busy ? "recovery-waiting" : undefined} onClick={() => { if (!inFlight.current) onBack(); }}>Back to getting started</button>
    <h2 ref={heading} tabIndex={-1}>Restore your backup</h2>
    <p>Choose an encrypted .orionvault backup and an empty folder. You need the backup’s passphrase. Restoring checks its records and original documents before making the recovered vault available.</p>
    <form className="vault-open-form" onSubmit={(event) => void submit(event)} aria-busy={busy}>
      <fieldset aria-disabled={busy} className="vault-recovery-fields">
        <legend className="visually-hidden">Backup and destination</legend>
        <label>Backup file<span className="vault-directory-control"><input required readOnly={busy} value={archive} onChange={(event) => { changed(); setArchive(event.target.value); }} placeholder="/path/to/copy.orionvault" autoComplete="off" />{pickArchive ? <button className="vault-picker-button" type="button" aria-disabled={busy} aria-describedby={busy ? "recovery-waiting" : undefined} onClick={() => void choose(pickArchive, setArchive)}>Choose backup file</button> : null}</span></label>
        <label>Empty destination folder<span className="vault-directory-control"><input required readOnly={busy} value={directory} onChange={(event) => { changed(); setDirectory(event.target.value); }} placeholder="/path/to/restored-vault" autoComplete="off" />{pickDirectory ? <button className="vault-picker-button" type="button" aria-disabled={busy} aria-describedby={busy ? "recovery-waiting" : undefined} onClick={() => void choose(pickDirectory, setDirectory)}>Choose restore folder</button> : null}</span></label>
        <label>Backup passphrase<input required readOnly={busy} type="password" value={passphrase} onChange={(event) => { changed(); setPassphrase(event.target.value); }} autoComplete="off" aria-describedby="restore-consequence" /></label>
        <p id="restore-consequence">Existing files are never replaced. Restoring verifies the backup but does not open it in this app or save its passphrase on this device.</p>
        <button className="primary-button" type="submit" aria-disabled={busy} aria-describedby={busy ? "recovery-waiting" : undefined}>Restore backup</button>
      </fieldset>
    </form>
    <div role="status" aria-live="polite" aria-atomic="true">
      {busy ? <p id="recovery-waiting">{choosing ? "Waiting for the chooser… Select one path or cancel to continue." : "Restoring your backup… Wait for the result before starting another restore."}</p> : null}
      {pickerError ? <p>{pickerError}</p> : null}
      {result?.state === "settled" ? <p>{result.outcome.message || UNSPOKEN_REPLY}</p> : null}
      {channel ? <p><strong>{channel.title}</strong> {channel.detail}</p> : null}
    </div>
    {restoredDirectory ? <div><p>Your recovered vault is ready. Open it separately with its passphrase to view your records.</p><button className="secondary-button" type="button" onClick={() => onOpen(restoredDirectory)}>Open restored vault</button></div> : null}
  </div>;
}
