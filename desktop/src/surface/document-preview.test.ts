import { describe, it, expect } from "vitest";
import { decodeDocumentPreview } from "./document-preview";
const id = "a".repeat(64);
describe("saved original boundary", () => {
  it("rejects a response belonging to a different document", async () => {
    await expect(decodeDocumentPreview({ schema_version: 1, status: "unavailable", document_id: "b".repeat(64), reason: "original_unavailable" }, id, 1)).rejects.toThrow();
  });
  it("rejects unknown refusals and unexpected response content", async () => {
    await expect(decodeDocumentPreview({ schema_version: 1, status: "unavailable", document_id: id, reason: "secret path" }, id, 1)).rejects.toThrow();
    await expect(decodeDocumentPreview({ schema_version: 1, status: "unavailable", document_id: id, reason: "original_unavailable", text: "private" }, id, 1)).rejects.toThrow();
  });
});
const textHash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
function ready(overrides: object = {}) { return { schema_version: 1, status: "ready", document_id: id, original_sha256: id, source_kind: "text", page: 1, page_count: 1, rendition_sha256: textHash, text: "abc", png_base64: null, width: null, height: null, ...overrides }; }
describe("rendition verification", () => {
  it("accepts a faithfully hashed plain text rendition", async () => {
    await expect(decodeDocumentPreview(ready(), id, 1)).resolves.toMatchObject({ status: "ready", sourceKind: "text", text: "abc" });
  });
  it("rejects wrong hashes, page identities, unknown keys, missing nulls and over-limit content", async () => {
    for (const changed of [{ rendition_sha256: id }, { original_sha256: "b".repeat(64) }, { page: 2 }, { page_count: 0 }, { source_kind: "html" }, { width: 1 }, { text: "a".repeat(256 * 1024 + 1) }, { text: "a\u0000b" }, { extra: "not permitted" }, { png_base64: undefined }]) await expect(decodeDocumentPreview(ready(changed), id, 1)).rejects.toThrow();
  });
  it("rejects forged PNG headers, dimensions, MIME data, excessive pixels and invalid base64", async () => {
    const image = ready({ source_kind: "pdf", text: null, png_base64: "not PNG", width: 100, height: 100 });
    for (const changed of [{}, { width: 2001 }, { height: 0 }, { png_base64: "data:image/svg+xml,malicious" }, { png_base64: "AAAA" }]) await expect(decodeDocumentPreview({ ...image, ...changed }, id, 1)).rejects.toThrow();
  });
});

it("accepts a bounded PNG and rejects a rendition whose declared dimensions or hash differ", async () => {
  const png = ready({ source_kind: "pdf", text: "faithful text", png_base64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aLe0AAAAASUVORK5CYII=", width: 1, height: 1, rendition_sha256: "e8224d7cd73556bdbdb3da4c81b73290ab1e0928bb434ba6c97b8a041e19bebc" });
  await expect(decodeDocumentPreview(png, id, 1)).resolves.toMatchObject({ status: "ready", sourceKind: "pdf", width: 1, height: 1, text: "faithful text" });
  await expect(decodeDocumentPreview({ ...png, width: 2 }, id, 1)).rejects.toThrow();
  await expect(decodeDocumentPreview({ ...png, rendition_sha256: id }, id, 1)).rejects.toThrow();
});
