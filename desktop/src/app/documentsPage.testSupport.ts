// Test transport fixture for the explicit Documents contract. No legacy UI
// fallback uses this helper; tests must author IDs and selection truthfully.
export function documentsPageFixture(value: unknown, selectedId?: string) {
  const source = value as { documents: Record<string, unknown>[]; reading_sentence?: string };
  const documents = source.documents;
  const selected = selectedId ? documents.find((row) => row.id === selectedId) : null;
  return { ...source, state: "ready", contract_version: "documents-page-v1", revision: { generation: "test-documents-g1", count: documents.length, head: "test-head", epoch: 1 },
    selected_document: selected ? { state: "ready", reason: null, document: selected } : selectedId ? { state: "missing", reason: "identity_not_captured", document: null } : { state: "none", reason: null, document: null },
    page: { total_documents: documents.length, total_unavailable_reason: null, page_start: documents.length ? 1 : 0, page_end: documents.length, page_count: documents.length, has_more: false, next_cursor: null },
    summary: { scope: "revision", counts: { total_documents: documents.length }, unavailable_reason: null } };
}
