import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { DesktopShell } from "./BrowserShell";
import { installTauriBridge, desktopBrowserControls } from "./tauri-host";

installTauriBridge();
const controls = desktopBrowserControls();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DesktopShell controls={controls} />
  </StrictMode>,
);
