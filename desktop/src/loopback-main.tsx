import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { App } from "./app/App";
import { installLoopbackBridge } from "./bridge/loopback-transport";

if (!installLoopbackBridge()) throw new Error("The OrionViva loopback bridge is unavailable");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
