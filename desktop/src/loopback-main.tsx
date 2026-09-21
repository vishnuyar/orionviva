import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import "./styles.css";
import { App } from "./app/App";
import { BrowserEnded } from "./BrowserShell";
import { installLoopbackBridge } from "./bridge/loopback-transport";
import { installBrowserBridge } from "./bridge/browser-transport";

const root = createRoot(document.getElementById("root")!);
function ended(message?: string) { flushSync(() => root.render(<BrowserEnded message={message} />)); }
async function start() {
  try {
    if (!installLoopbackBridge()) await installBrowserBridge((message) => ended(message));
    root.render(<StrictMode><section className="browser-controls" aria-label="Local browser session"><div><strong>Your vault stays on this computer</strong><p>Keep OrionViva running. Use Add statement, then Choose statement file; dropping files into the browser is not supported. Return to the app to stop browser access.</p></div></section><App /></StrictMode>);
    document.addEventListener("dragover", (event) => event.preventDefault());
    document.addEventListener("drop", (event) => event.preventDefault());
  } catch (error) { ended(error instanceof Error ? error.message : undefined); }
}
void start();
