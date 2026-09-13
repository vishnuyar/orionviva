import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(desktop, "..");
const executableName = process.platform === "win32" ? "python.exe" : "python";
const configured = process.env.ORIONVIVA_PYTHON?.trim();
const repositoryPython = join(root, ".venv",
  process.platform === "win32" ? "Scripts" : "bin", executableName);
const python = configured || (existsSync(repositoryPython) ? repositoryPython : executableName);

if (configured && !existsSync(python)) {
  throw new Error(`sidecar build Python from ORIONVIVA_PYTHON does not exist: ${python}`);
}

const result = spawnSync(python, [join(root, "scripts", "build_desktop_sidecar.py"),
  "--output-dir", join(desktop, "src-tauri", "binaries"), ...process.argv.slice(2)], {
  cwd: desktop,
  env: process.env,
  stdio: "inherit",
});
if (result.error) throw result.error;
if (result.signal) {
  throw new Error(`sidecar build Python ended from signal ${result.signal}`);
}
process.exitCode = result.status ?? 1;
