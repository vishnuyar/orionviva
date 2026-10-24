import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, writeFile, readFile, access } from "node:fs/promises";
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
const engineEnvironment = {
  PATH: "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
  HOME: join(root, "home"),
  PYTHONPATH: [root, join(desktop, "../product"), join(desktop, "../core"), join(desktop, "../merchant")].join(process.platform === "win32" ? ";" : ":"),
  VIVA_ENV_FILE: join(root, "empty.env"),
  MERCHANTCORE_HOME: join(root, "merchant"),
  VIVA_DEMO_HOME: join(root, "sample-vault"),
};
await mkdir(engineEnvironment.HOME);
const engine = join(root, "isolated-engine");
await writeFile(engine, `#!${join(desktop, "../.venv/bin/python")}
import os, sys
os.environ.clear()
os.environ.update(${JSON.stringify(engineEnvironment)})
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
  const measuredViewports = [];
  const viewport = async (width, height) => {
    await browser.setWindowSize(Math.max(600, width), height);
    await browser.sendCommandAndGetResult("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    const actual = await browser.execute(() => ({ width: innerWidth, height: innerHeight }));
    assert.deepEqual(actual, { width, height }, "Responsive evidence requires the requested CSS viewport, not merely the outer window");
    measuredViewports.push(actual);
  };
  await browser.url(url);
  const text = () => browser.$("body").getText();
  await browser.waitUntil(async () => (await text()).includes("Set up my vault"), { timeout: 30_000 });
  await browser.saveScreenshot(join(root, "welcome.png"));
  await browser.$("aria/Set up my vault").click();
  assert.equal(new URL(await browser.getUrl()).hash, "");
  const observeErrors = () => browser.execute(() => {
    const originalFetch = globalThis.fetch;
    globalThis.__browserChecks = [];
    globalThis.__previewRequestCount ??= 0;
    globalThis.fetch = async (...args) => {
      if (typeof args[1]?.body === "string" && args[1].body.includes('"viva.documents.preview.read"')) globalThis.__previewRequestCount++;
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
    if (await browser.$(".document-list").isExisting() && (await browser.$(".document-list").getText()).includes("synthetic.txt") && !(await text()).includes("could not be refreshed")) return true;
    return false;
  }, { timeout: 30_000, interval: 1000 });
  await browser.$(".document-list").scrollIntoView();
  await browser.saveScreenshot(join(root, "browser-import.png"));
  for (const width of [836, 390]) {
    await viewport(width, 1000);
    await browser.$(".document-library").scrollIntoView();
    const library = await browser.$(".document-library").getSize();
    assert.ok(library.width >= 160, `Statement list is squeezed at ${width}px`);
    const fields = await browser.$$(".document-status-grid .document-detail-field:not(.document-detail-field-wide)");
    for (const field of fields) assert.ok((await field.getSize()).width >= 100, `Statement status field is squeezed at ${width}px`);
    assert.equal(await browser.execute(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Statements overflow at ${width}px`);
    await browser.saveScreenshot(join(root, `statements-${width}.png`));
  }
  await viewport(1440, 1100);
  assert.equal(await readFile(join(root, "synthetic.txt"), "utf8"), "Synthetic browser import fixture. No personal financial data.\n");
  assert.equal(await browser.execute(() => globalThis.__previewRequestCount), 0, "Metadata selection must not request original content");
  await browser.$('aria/View saved original').click();
  await browser.waitUntil(async () => (await browser.$('.original-preview-text').getText()).includes("Synthetic browser import fixture."), { timeout: 20_000 });
  assert.equal(await browser.execute(() => globalThis.__previewRequestCount), 1);
  await browser.$('aria/Close original').click();
  assert.equal(await browser.$('.original-preview').isExisting(), false);
  assert.equal(await browser.execute(() => document.activeElement?.textContent), "View saved original");
  await browser.$('aria/Close this vault').click();
  await browser.waitUntil(async () => (await text()).includes("Set up my vault"), { timeout: 10_000 });
  await browser.refresh();
  await browser.waitUntil(async () => (await text()).includes("Open existing vault"), { timeout: 10_000 });
  await browser.$("aria/Open existing vault").click();
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
  const prepared = spawnSync(join(desktop, "../.venv/bin/python"), [join(desktop, "scripts/source-preview-fixtures.py"), root], {
    env: engineEnvironment, encoding: "utf8",
  });
  assert.equal(prepared.status, 0, `Synthetic originals must be prepared: ${prepared.stderr}`);
  const previewFixture = JSON.parse(prepared.stdout);
  await browser.$('aria/Close this vault').click();
  await browser.$('aria/Open existing vault').waitForClickable({ timeout: 15_000 });
  await browser.$('aria/Open existing vault').click();
  await browser.$('input[placeholder="/path/to/vault"]').setValue(previewFixture.vault);
  await browser.$('input[type="password"]').setValue("synthetic browser phrase");
  await browser.$('aria/Open local vault').click();
  await browser.waitUntil(async () => (await text()).includes("Vault open"), { timeout: 30_000 });
  await browser.$('aria/Add statement').click();
  const selectOriginal = async (filename) => {
    const buttons = await browser.$$('.document-list button');
    for (const button of buttons) if ((await button.getText()).includes(filename)) { await button.click(); return; }
    throw new Error(`Synthetic original is missing from the statement list: ${filename}`);
  };
  await browser.$('.document-list').waitForDisplayed({ timeout: 20_000 });
  await selectOriginal("preview-source.pdf");
  assert.equal(await browser.$('.original-preview').isExisting(), false);
  await browser.$('aria/View saved original').click();
  await browser.$('.original-preview-image img').waitForDisplayed({ timeout: 20_000 });
  assert((await text()).includes("Page 1 of 2"));
  await browser.$('summary=Extracted text alternative').click();
  assert((await browser.$('.original-preview-text').getText()).includes("SOURCE ALPHA PAGE ONE"));
  const firstImage = await browser.$('.original-preview-image img').getAttribute("src");
  assert(firstImage.startsWith("data:image/png;base64,"));
  await browser.saveScreenshot(join(root, "source-pdf-page-1.png"));
  await browser.$('aria/Next page').click();
  await browser.waitUntil(async () => (await text()).includes("Page 2 of 2"), { timeout: 20_000 });
  await browser.$('summary=Extracted text alternative').click();
  const secondText = await browser.$('.original-preview-text').getText();
  assert(secondText.includes("SOURCE BETA PAGE TWO") && !secondText.includes("SOURCE ALPHA PAGE ONE"));
  assert.notEqual(await browser.$('.original-preview-image img').getAttribute("src"), firstImage);
  await viewport(390, 1000);
  await browser.$('.original-preview').scrollIntoView();
  assert.equal(await browser.execute(() => document.documentElement.scrollWidth <= innerWidth), true, "Original preview must fit a narrow viewport");
  await browser.saveScreenshot(join(root, "source-pdf-390.png"));
  await browser.$('aria/Zoom in').click();
  assert.equal(await browser.$('[data-preview-zoom="200"]').isExisting(), true);
  await browser.saveScreenshot(join(root, "source-pdf-390-zoomed.png"));
  await browser.$('aria/Zoom in').click();
  assert.equal(await browser.$('[data-preview-zoom="400"]').isExisting(), true);
  await browser.saveScreenshot(join(root, "source-pdf-390-400.png"));
  await browser.$('aria/Close original').click();
  await viewport(1440, 1100);
  await selectOriginal("preview-text.txt");
  await browser.$('aria/View saved original').click();
  await browser.waitUntil(async () => (await browser.$('.original-preview-text').getText()).includes("LOCAL TEXT ORIGINAL"), { timeout: 20_000 });
  assert((await browser.$('.original-preview-text').getText()).includes("<script>globalThis.__previewInjection=true</script>"));
  assert.equal(await browser.execute(() => typeof globalThis.__previewInjection), "undefined");
  await browser.saveScreenshot(join(root, "source-text.png"));
  await selectOriginal("preview-image.png");
  assert.equal(await browser.$('.original-preview').isExisting(), false, "Changing documents must discard previous original content");
  await browser.$('aria/View saved original').click();
  await browser.$('.original-preview-image img').waitForDisplayed({ timeout: 20_000 });
  assert((await text()).includes("A text alternative is unavailable"));
  await browser.$('aria/Close this vault').click();
  await browser.waitUntil(async () => (await text()).includes("Open existing vault"), { timeout: 15_000 });
  assert.equal(await browser.$('.original-preview').isExisting(), false);
  await browser.$('aria/Open existing vault').click();
  await browser.$('input[placeholder="/path/to/vault"]').setValue(previewFixture.vault);
  await browser.$('input[type="password"]').setValue("synthetic browser phrase");
  await browser.$('aria/Open local vault').click();
  await browser.waitUntil(async () => (await text()).includes("Vault open"), { timeout: 30_000 });
  await browser.$('aria/Add statement').click();
  await browser.$('.document-list').waitForDisplayed({ timeout: 20_000 });
  await selectOriginal("preview-source.pdf");
  await browser.$('aria/View saved original').click();
  await browser.$('.original-preview-image img').waitForDisplayed({ timeout: 20_000 });
  assert((await text()).includes("Page 1 of 2"));
  const inspected = spawnSync(join(desktop, "../.venv/bin/python"), ["-c", "from pathlib import Path; import sys; from viva.ingest.raw_store import RawStore; root=Path(sys.argv[1]); data=(root/'synthetic.txt').read_bytes(); raw=RawStore.open(root/'vault'/'raw', 'synthetic browser phrase'); ids=raw.doc_ids(); assert len(ids)==1; assert raw.get(ids[0])==data; assert all(data not in p.read_bytes() for p in (root/'vault').rglob('*') if p.is_file())", root], { env: engineEnvironment, encoding: "utf8" });
  assert.equal(inspected.status, 0, "Synthetic original must reopen from encrypted storage without a plaintext vault copy");
  await browser.$('aria/Trust & settings').click();
  await browser.$('aria/Choose backup location').waitForClickable({ timeout: 30_000 });
  await assert.rejects(access(join(root, "copy.orionvault")), "No backup exists before choosing");
  await browser.$('aria/Choose backup location').click();
  assert.equal(await browser.$('aria/Write the copy to').getValue(), join(root, "copy.orionvault"));
  await assert.rejects(access(join(root, "copy.orionvault")), "Choosing a location must not export a backup");
  await viewport(390, 1000);
  await browser.$('.trust-transfer').scrollIntoView();
  assert.equal(await browser.execute(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Backup controls must fit a narrow viewport");
  await browser.saveScreenshot(join(root, "backup-390.png"));
  await viewport(1440, 1100);
  await browser.$('aria/Take a copy').click();
  await browser.waitUntil(async () => { try { await access(join(root, "copy.orionvault")); return (await browser.$('aria/Take a copy').getAttribute("aria-disabled")) === "false"; } catch { return false; } }, { timeout: 30_000 });
  await browser.$('aria/Close this vault').click();
  await browser.$('aria/Restore a backup').waitForClickable({ timeout: 15_000 });
  await browser.$('aria/Restore a backup').click();
  await browser.$('aria/Backup file').setValue(join(root, "copy.orionvault"));
  await browser.$('aria/Empty destination folder').setValue(join(root, "recovered"));
  await browser.$('aria/Backup passphrase').setValue("wrong synthetic phrase");
  await browser.$('aria/Restore backup').click();
  await browser.waitUntil(async () => (await browser.$('aria/Restore backup').getAttribute("aria-disabled")) === "false" && (await browser.$('[role="status"]').getText()).length > 0, { timeout: 30_000 });
  assert.equal(await browser.$('aria/Open restored vault').isExisting(), false, "Refusal must not offer a recovered vault");
  await assert.rejects(access(join(root, "recovered")), "Wrong phrase must leave destination absent");
  await browser.$('aria/Backup passphrase').setValue("synthetic browser phrase");
  await browser.$('aria/Restore backup').click();
  await browser.$('aria/Open restored vault').waitForClickable({ timeout: 30_000 });
  assert.equal(await browser.$('aria/Backup passphrase').getValue(), "", "Submitted recovery phrase must clear");
  assert(!(await text()).includes("Vault open"), "Restoring must not open the vault automatically");
  await viewport(390, 1000);
  assert.equal(await browser.execute(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Recovery must fit a narrow viewport");
  await browser.saveScreenshot(join(root, "recovery-390.png"));
  await browser.$('aria/Open restored vault').scrollIntoView();
  await browser.saveScreenshot(join(root, "recovery-receipt-390.png"));
  await viewport(1440, 1100);
  await browser.$('aria/Open restored vault').scrollIntoView();
  await browser.saveScreenshot(join(root, "recovery-completed.png"));
  await browser.$('aria/Open restored vault').click();
  assert.equal(await browser.$('input[placeholder="/path/to/vault"]').getValue(), join(root, "recovered"));
  await browser.$('input[type="password"]').setValue("synthetic browser phrase");
  await browser.$('aria/Open local vault').click();
  await browser.waitUntil(async () => (await text()).includes("Vault open"), { timeout: 30_000 });
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
  console.log(JSON.stringify({ status: "pass", evidence: root, measured_viewports: measuredViewports, cases: ["production-assets", "responsive-statements", "create-real-vault", "synthetic-file-import", "original-unchanged", "explicit-local-text-preview", "preview-close-focus", "closed-vault-stays-closed-after-reload", "wrong-phrase-refused", "reopen-vault", "encrypted-original-roundtrip", "backup-chooser-does-not-write", "explicit-browser-backup-export", "responsive-backup-controls", "restore-without-open-vault", "wrong-backup-phrase-retry", "explicit-restored-vault-open", "responsive-recovery", "genuine-pdf-page-content", "pdf-page-navigation", "responsive-source-preview", "source-preview-zoom", "original-markup-is-literal", "source-change-clears-preview", "original-preview-after-reopen", "duplicate-tab-reload-refused", "authorized-reload", "revocation"] }));
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
