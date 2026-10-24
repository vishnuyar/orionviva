import { BridgeTimeout } from "../bridge/contracts";
import type { BridgeClient } from "../bridge/contracts";
import type { DocumentPreview, DocumentPreviewReader, DocumentPreviewReason } from "./types";
const reasons: readonly DocumentPreviewReason[] = ["invalid_request", "original_unavailable", "identity_unverifiable", "unsupported_type", "unsupported_encoding", "over_limit", "encrypted_pdf", "damaged_original", "page_unavailable", "timed_out", "renderer_unavailable"];
const hashPattern = new RegExp("^[a-f0-9]{64}$");
const encoder = new TextEncoder();
function fail(): never { throw new Error("Saved original response unavailable"); }
function exact(value: Record<string, unknown>, keys: string[]) { if (Object.keys(value).sort().join() !== keys.sort().join()) fail(); }
function positive(value: unknown, max: number): value is number { return typeof value === "number" && Number.isInteger(value) && value > 0 && value <= max; }
async function digest(bytes: Uint8Array): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
// The original identity and the displayed rendition have different hashes.
export async function decodeDocumentPreview(raw: unknown, documentId: string, page: number): Promise<DocumentPreview> {
  if (!hashPattern.test(documentId) || !positive(page, 200) || !raw || typeof raw !== "object" || Array.isArray(raw)) fail();
  const value = raw as Record<string, unknown>;
  if (encoder.encode(JSON.stringify(raw)).length > 1.5 * 1024 * 1024 || value.schema_version !== 1 || value.document_id !== documentId) fail();
  if (value.status === "unavailable") {
    exact(value, ["schema_version", "status", "document_id", "reason"]);
    if (!reasons.includes(value.reason as DocumentPreviewReason)) fail();
    return { status: "unavailable", reason: value.reason as DocumentPreviewReason };
  }
  exact(value, ["schema_version", "status", "document_id", "original_sha256", "source_kind", "page", "page_count", "rendition_sha256", "text", "png_base64", "width", "height"]);
  if (value.status !== "ready" || value.original_sha256 !== documentId || typeof value.rendition_sha256 !== "string" || !hashPattern.test(value.rendition_sha256) || value.page !== page || !positive(value.page_count, 200) || page > value.page_count) fail();
  if (value.text !== null && (typeof value.text !== "string" || encoder.encode(value.text).length > 256 * 1024 || new RegExp("[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]").test(value.text))) fail();
  if (value.source_kind === "text") {
    if (page !== 1 || value.page_count !== 1 || typeof value.text !== "string" || value.png_base64 !== null || value.width !== null || value.height !== null || await digest(encoder.encode(value.text)) !== value.rendition_sha256) fail();
    return { status: "ready", sourceKind: "text", page, pageCount: 1, text: value.text, image: null, width: null, height: null };
  }
  if (value.source_kind !== "pdf" && value.source_kind !== "image") fail();
  if (value.source_kind === "image" && (page !== 1 || value.page_count !== 1)) fail();
  if (!positive(value.width, 2000) || !positive(value.height, 2000) || value.width * value.height > 4_000_000 || typeof value.png_base64 !== "string" || value.png_base64.length > 1_398_104 || !new RegExp("^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$").test(value.png_base64)) fail();
  const bytes = Uint8Array.from(atob(value.png_base64), (char) => char.charCodeAt(0));
  if (bytes.length > 1024 * 1024 || bytes.length < 45 || [137,80,78,71,13,10,26,10].some((byte, index) => bytes[index] !== byte)) fail();
  const view = new DataView(bytes.buffer);
  if (view.getUint32(8) !== 13 || String.fromCharCode(...bytes.slice(12, 16)) !== "IHDR" || view.getUint32(16) !== value.width || view.getUint32(20) !== value.height || String.fromCharCode(...bytes.slice(-8, -4)) !== "IEND" || await digest(bytes) !== value.rendition_sha256) fail();
  return { status: "ready", sourceKind: value.source_kind, page, pageCount: value.page_count, text: value.text as string | null, image: `data:image/png;base64,${value.png_base64}`, width: value.width, height: value.height };
}
export function documentPreviewReader(client: BridgeClient): DocumentPreviewReader {
  return async (documentId, page) => {
    if (!client.readDocumentPreview) return { status: "unavailable", reason: "renderer_unavailable" };
    try { return await decodeDocumentPreview(await client.readDocumentPreview(documentId, page), documentId, page); }
    catch (failure) { return { status: "unavailable", reason: failure instanceof BridgeTimeout ? "timed_out" : "renderer_unavailable" }; }
  };
}
