import { useEffect, useRef, useState } from "react";
import { App } from "./app/App";

type Controls = {
  status: () => Promise<boolean>;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  returnToDesktop: () => Promise<void>;
  subscribe: (changed: (active: boolean) => void) => Promise<() => void>;
};

export function DesktopShell({ controls }: { controls: Controls | null }) {
  const [active, setActive] = useState(false);
  const [ready, setReady] = useState(!controls);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const previousActive = useRef(false);
  useEffect(() => { if (previousActive.current !== active) heading.current?.focus(); previousActive.current = active; }, [active]);
  useEffect(() => {
    if (!controls) return;
    let gone = false;
    let unsubscribe: (() => void) | undefined;
    void controls.subscribe((value) => { if (!gone) setActive(value); }).then((stop) => { if (gone) stop(); else unsubscribe = stop; }).catch(() => undefined);
    void controls.status().then((value) => { if (!gone) { setActive(value); setReady(true); } }).catch(() => { if (!gone) setNotice("OrionViva could not check which view is active. Restart the app to continue."); });
    const timer = setInterval(() => { void controls.status().then((value) => { if (!gone) setActive(value); }).catch(() => undefined); }, 500);
    return () => { gone = true; clearInterval(timer); unsubscribe?.(); };
  }, [controls]);
  async function change(toBrowser: boolean) {
    if (!controls || busy) return;
    setBusy(true); setNotice("");
    try { if (toBrowser) await controls.start(); else await controls.returnToDesktop(); setActive(toBrowser); }
    catch (error) {
      const said = String(error);
      if (toBrowser && said === "This build is missing its browser interface. Build or reinstall OrionViva before trying again.") setNotice("This build is missing its browser interface. Reinstall OrionViva with a build that includes browser access.");
      else setNotice(toBrowser ? "The browser could not be opened. Wait for any current work to finish, check your default browser, then try again." : "OrionViva is still finishing a request. Wait for it to finish, then try again."); }
    finally { setBusy(false); }
  }
  async function revoke() {
    if (!controls || busy) return;
    setBusy(true);
    try {
      await controls.stop();
      const waiting = await controls.status();
      setActive(waiting);
      setNotice(waiting ? "Browser access has ended. OrionViva is finishing the current request before returning to desktop." : "Browser access has ended.");
    } catch { setNotice("Browser access could not be stopped. Quit OrionViva to close the local connection."); }
    finally { setBusy(false); }
  }
  if (!controls) return <App />;
  return <>
    <section className="browser-controls" aria-label="Browser access">
      <div><h2 ref={heading} tabIndex={-1}>{active ? "OrionViva is open in your browser" : "Use OrionViva in your browser"}</h2><p>{active ? "Keep this app running. Your vault stays on this computer. Returning here ends browser access." : "Create or open your vault and add files in your browser on this computer."}</p></div>
      {ready && <div className="browser-actions">{active ? <><button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? "browser-waiting" : undefined} onClick={() => { void change(false); }}>Return to desktop</button><button className="text-button" aria-disabled={busy} aria-describedby={busy ? "browser-waiting" : undefined} onClick={() => { void revoke(); }}>Stop browser access</button></> : <button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? "browser-waiting" : undefined} onClick={() => { void change(true); }}>{busy ? "Opening browser…" : "Open in browser"}</button>}</div>}
      {busy && <p id="browser-waiting" role="status">{active ? "Ending browser access. Wait for OrionViva to finish this request." : "Opening your browser. Keep OrionViva running."}</p>}
      {notice && <p role="alert">{notice}</p>}
    </section>
    {ready && !active && <App />}
  </>;
}

export function BrowserEnded({ message }: { message?: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <main className="browser-controls"><div><h1 ref={heading} tabIndex={-1}>Open OrionViva from the app</h1><p role="status">{message || "Browser access has ended or the connection was interrupted. Return to the OrionViva app to reopen it. If a file or other change was in progress, check the vault before trying again."}</p><p>Your vault remains on this computer.</p></div></main>;
}
