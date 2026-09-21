import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, writeFile, readFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
const desktop = resolve(fileURLToPath(new URL("..", import.meta.url)));
const evaluator = process.env.ORIONVIVA_ACCEPTANCE_ROOT || resolve(desktop, "../../orionviva-acceptance");
const require = createRequire(join(evaluator, "package.json"));
const { remote } = await import(require.resolve("webdriverio"));
const root = await mkdtemp(join(tmpdir(), "orionviva-browser-host-"));
await writeFile(join(root, "empty.env"), "# Synthetic browser test: no model provider\n", { mode: 0o600 });
// Isolate configuration in the engine and its read-store subprocess alike.
await writeFile(join(root, "sitecustomize.py"), "from pathlib import Path\nimport viva.env\nviva.env.CONFIG_HOME = Path(__file__).parent / 'config'\n", { mode: 0o600 });
await writeFile(join(root, "synthetic.txt"), "Synthetic browser import fixture. No personal financial data.\n", { mode: 0o600 });
const engine = join(root, "isolated-engine");
await writeFile(engine, `#!${join(desktop, "../.venv/bin/python")}
import os, sys
os.environ.clear()
os.environ['PYTHONPATH'] = ${JSON.stringify([root, join(desktop, "../product"), join(desktop, "../core"), join(desktop, "../merchant")].join(":"))}
os.environ['VIVA_ENV_FILE'] = ${JSON.stringify(join(root, "empty.env"))}
os.execv(sys.executable, [sys.executable, '-m', 'viva.desktop_bridge'])
`, { mode: 0o700 });
const host = spawn("cargo", ["test", "--offline", "production_browser_routes_with_synthetic_vault", "--", "--ignored", "--nocapture"], { cwd: join(desktop, "src-tauri"), env: { ...process.env, ORIONVIVA_BROWSER_PROBE_ROOT: root, ORIONVIVA_SIDECAR: engine }, stdio: ["ignore", "pipe", "pipe"] });
let hostOutput = "";
host.stdout.on("data", (chunk) => { hostOutput += chunk; });
host.stderr.on("data", (chunk) => { hostOutput += chunk; });
let driver, browser;
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(check, timeout = 45_000) { const deadline = Date.now() + timeout; while (Date.now() < deadline) { if (await check()) return; await delay(100); } throw new Error("Timed out waiting for browser test prerequisite"); }
try {
  await until(async () => { if (host.exitCode !== null) throw new Error(hostOutput); try { await access(join(root, "ready.json")); return true; } catch { return false; } });
  const { url } = JSON.parse(await readFile(join(root, "ready.json"), "utf8"));
  const port = await new Promise((done) => { const s = createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => done(p)); }); });
  driver = spawn(process.env.EVALUATOR_CHROMEDRIVER || "chromedriver", [`--port=${port}`, "--allowed-ips=127.0.0.1"], { stdio: "ignore" });
  await until(async () => { try { return (await fetch(`http://127.0.0.1:${port}/status`)).ok; } catch { return false; } });
  browser = await remote({ hostname: "127.0.0.1", port, logLevel: "error", capabilities: { browserName: "chrome", "goog:chromeOptions": { args: ["--headless=new", "--no-first-run", "--window-size=1440,1100"] } } });
  await browser.url(url);
  const text = () => browser.$("body").getText();
  await browser.waitUntil(async () => (await text()).includes("Open local vault"), { timeout: 30_000 });
  assert.equal(new URL(await browser.getUrl()).hash, "");
  const observeErrors = () => browser.execute(() => {
    const originalFetch = globalThis.fetch;
    globalThis.__browserChecks = [];
    globalThis.fetch = async (...args) => {
      const result = await originalFetch(...args);
      const copy = await result.clone().json().catch(() => ({}));
      if (!result.ok || copy.response?.ok === false) globalThis.__browserChecks.push({ path: args[0], status: result.status, error: copy.response?.error || copy.error });
      return result;
    };
  });
  await observeErrors();
  await browser.$('input[value=""][placeholder="/path/to/vault"]').setValue(join(root, "vault"));
  await browser.$('aria/Make a new vault in that folder').click();
  await browser.$('input[type="password"]').setValue("synthetic browser phrase");
  await browser.$('aria/Make and open vault').click();
  await browser.waitUntil(async () => !(await text()).includes("Opening vault...") && (await text()).includes("Vault open"), { timeout: 45_000 });
  await browser.$('aria/Add statement').click();
  await browser.$('aria/Choose statement file').waitForClickable({ timeout: 30_000 });
  await browser.$('aria/Choose statement file').click();
  await browser.waitUntil(async () => {
    if ((await text()).includes("synthetic.txt")) return true;
    const retry = await browser.$('aria/Retry this screen');
    if (await retry.isExisting() && await retry.isClickable()) await retry.click();
    return false;
  }, { timeout: 30_000, interval: 1000 });
  await browser.saveScreenshot(join(root, "browser-import.png"));
  assert.equal(await readFile(join(root, "synthetic.txt"), "utf8"), "Synthetic browser import fixture. No personal financial data.\n");
  await browser.$('aria/Close this vault').click();
  await browser.waitUntil(async () => (await text()).includes("No vault open"), { timeout: 10_000 });
  await browser.refresh();
  await browser.waitUntil(async () => (await text()).includes("Open local vault"), { timeout: 10_000 });
  assert(!(await text()).includes("Vault open"), "Reload must not reopen an explicitly closed vault");
  await observeErrors();
  await browser.$('aria/Open an existing vault').click();
  await browser.$('aria/Choose folder').click();
  assert.equal(await browser.$('input[placeholder="/path/to/vault"]').getValue(), join(root, "vault"));
  await browser.$('input[type="password"]').setValue("incorrect synthetic phrase");
  await browser.$('aria/Open local vault').click();
  await browser.waitUntil(async () => browser.execute(() => globalThis.__browserChecks.some((entry) => entry.error?.code === "vault_wrong_passphrase")), { timeout: 15_000 });
  await browser.$('input[type="password"]').setValue("synthetic browser phrase");
  await browser.$('aria/Open local vault').click();
  await browser.waitUntil(async () => (await text()).includes("Vault open"), { timeout: 30_000 });
  const inspected = spawnSync(join(desktop, "../.venv/bin/python"), ["-c", "from pathlib import Path; import sys; from viva.ingest.raw_store import RawStore; root=Path(sys.argv[1]); data=(root/'synthetic.txt').read_bytes(); raw=RawStore.open(root/'vault'/'raw', 'synthetic browser phrase'); ids=raw.doc_ids(); assert len(ids)==1; assert raw.get(ids[0])==data; assert all(data not in p.read_bytes() for p in (root/'vault').rglob('*') if p.is_file())", root], { env: { PYTHONPATH: [root, join(desktop, "../product"), join(desktop, "../core"), join(desktop, "../merchant")].join(process.platform === "win32" ? ";" : ":"), VIVA_ENV_FILE: join(root, "empty.env") }, encoding: "utf8" });
  assert.equal(inspected.status, 0, "Synthetic original must reopen from encrypted storage without a plaintext vault copy");
  const original = await browser.getWindowHandle();
  // Opening with an opener clones sessionStorage, matching a duplicated tab.
  await browser.execute(() => { window.open(location.href, "_blank"); });
  const handles = await browser.getWindowHandles();
  assert.equal(handles.length, 2);
  await browser.switchToWindow(handles.find((handle) => handle !== original));
  await browser.refresh();
  await browser.waitUntil(async () => (await text()).includes("Another browser tab is active"), { timeout: 10_000 });
  await browser.closeWindow();
  await browser.switchToWindow(original);
  await browser.refresh();
  await browser.waitUntil(async () => (await text()).includes("Vault open"), { timeout: 30_000 });
  await writeFile(join(root, "revoke"), "revoke\n");
  await browser.waitUntil(async () => (await text()).includes("Browser access has ended"), { timeout: 10_000 });
  await browser.saveScreenshot(join(root, "browser-revoked.png"));
  console.log(JSON.stringify({ status: "pass", evidence: root, cases: ["production-assets", "create-real-vault", "synthetic-file-import", "original-unchanged", "closed-vault-stays-closed-after-reload", "wrong-phrase-refused", "reopen-vault", "encrypted-original-roundtrip", "duplicate-tab-reload-refused", "authorized-reload", "revocation"] }));
} catch (error) {
  if (browser) {
    await browser.saveScreenshot(join(root, "failure.png")).catch(() => {});
    await writeFile(join(root, "browser-errors.json"), JSON.stringify(await browser.execute(() => globalThis.__browserChecks).catch(() => [])), { mode: 0o600 });
  }
  console.error(`Browser host check failed. Synthetic evidence: ${root}`);
  throw error;
} finally {
  if (browser) await browser.deleteSession().catch(() => {});
  driver?.kill("SIGTERM");
  await writeFile(join(root, "stop"), "stop\n");
  await until(async () => host.exitCode !== null, 10_000).catch(() => host.kill("SIGTERM"));
  await writeFile(join(root, "host.log"), hostOutput, { mode: 0o600 });
  if (host.exitCode !== 0) {
    console.error("The native browser test host did not finish successfully.");
    process.exitCode = 1;
  }
}
