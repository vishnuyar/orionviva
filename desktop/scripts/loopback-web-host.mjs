import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import { chmod, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer as createViteServer } from "vite";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const productRoot = resolve(desktopRoot, "..");
const readyFlag = process.argv.indexOf("--ready-file");
if (readyFlag < 0 || !process.argv[readyFlag + 1]) {
  throw new Error("usage: node scripts/loopback-web-host.mjs --ready-file <path>");
}
const readyFile = resolve(process.argv[readyFlag + 1]);
const evidenceRoot = resolve(process.env.ORIONVIVA_LOOPBACK_EVIDENCE ?? dirname(readyFile));
await mkdir(evidenceRoot, { recursive: true, mode: 0o700 });

const token = randomBytes(32).toString("hex");
const python = process.env.ORIONVIVA_PYTHON || "python3";
const stderrPath = resolve(evidenceRoot, "sidecar.stderr.log");
const sidecar = spawn(python, ["-m", "viva.desktop_bridge"], {
  cwd: resolve(productRoot, "product"),
  env: process.env,
  stdio: ["pipe", "pipe", "pipe"],
});
sidecar.stderr.pipe(createWriteStream(stderrPath, { mode: 0o600 }));

let buffer = "";
const pending = new Map();
sidecar.stdout.setEncoding("utf8");
sidecar.stdout.on("data", (chunk) => {
  buffer += chunk;
  while (buffer.includes("\n")) {
    const newline = buffer.indexOf("\n");
    const line = buffer.slice(0, newline);
    buffer = buffer.slice(newline + 1);
    if (!line.trim()) continue;
    let frame;
    try { frame = JSON.parse(line); } catch { continue; }
    if (frame.event) continue;
    const waiting = pending.get(frame.request_id);
    if (waiting) {
      pending.delete(frame.request_id);
      waiting.resolve(frame);
    }
  }
});
sidecar.on("exit", (code, signal) => {
  for (const waiting of pending.values()) waiting.reject(new Error(`loopback sidecar exited (${code ?? signal})`));
  pending.clear();
});

function requestSidecar(frame) {
  return new Promise((resolveRequest, rejectRequest) => {
    const timeout = setTimeout(() => {
      pending.delete(frame.request_id);
      rejectRequest(new Error("loopback sidecar request timed out"));
    }, 120_000);
    pending.set(frame.request_id, {
      resolve: (value) => { clearTimeout(timeout); resolveRequest(value); },
      reject: (error) => { clearTimeout(timeout); rejectRequest(error); },
    });
    sidecar.stdin.write(`${JSON.stringify(frame)}\n`, (error) => {
      if (!error) return;
      clearTimeout(timeout);
      pending.delete(frame.request_id);
      rejectRequest(error);
    });
  });
}

const vite = await createViteServer({
  root: desktopRoot,
  server: { host: "127.0.0.1", port: 0, strictPort: false },
  plugins: [{
    name: "orionviva-loopback-bridge",
    configureServer(server) {
      server.middlewares.use("/__orionviva/bridge", async (request, response) => {
        if (request.method !== "POST") {
          response.writeHead(405).end();
          return;
        }
        if (request.headers.authorization !== `Bearer ${token}`) {
          response.writeHead(403).end();
          return;
        }
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        try {
          const frame = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          const result = await requestSidecar(frame);
          response.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
          response.end(JSON.stringify(result));
        } catch {
          response.writeHead(502, { "content-type": "application/json", "cache-control": "no-store" });
          response.end(JSON.stringify({ error: "loopback bridge request failed" }));
        }
      });
    },
  }],
});
await vite.listen();
const address = vite.httpServer.address();
const port = typeof address === "object" && address ? address.port : 0;
const ready = { url: `http://127.0.0.1:${port}/loopback.html#token=${token}`, host: "127.0.0.1", functional_surface: "loopback-web" };
await writeFile(readyFile, `${JSON.stringify(ready)}\n`, { mode: 0o600 });
await chmod(readyFile, 0o600);

async function close() {
  await vite.close();
  sidecar.stdin.end();
  setTimeout(() => sidecar.kill("SIGTERM"), 1_000).unref();
}
process.once("SIGINT", () => { void close().finally(() => process.exit(0)); });
process.once("SIGTERM", () => { void close().finally(() => process.exit(0)); });
await new Promise(() => {});
