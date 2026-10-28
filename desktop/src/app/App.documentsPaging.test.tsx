import { act, fireEvent, render, waitFor, beforeEach, afterEach, describe, expect, it, App, moments, sampleReads, installSampleBridge, installResponsiveMatchMedia } from "./App.testSupport";
import { documentsPageFixture } from "./documentsPage.testSupport";
const all = (sampleReads.documents.result.data as { documents: Record<string, unknown>[] }).documents;
const rows = Array.from({ length: 50 }, (_, n) => ({ id: (n + 1).toString(16).padStart(64, "0"), filename: `page-row-${n + 1}.pdf`, doc_type: "statement", raw_available: false }));
const payload = () => ({ ...documentsPageFixture({ documents: rows }), page: { total_documents: 794, total_unavailable_reason: null, page_start: 1, page_end: 50, page_count: 50, has_more: true, next_cursor: "opaque-next" } });
beforeEach(() => installResponsiveMatchMedia(1440));
afterEach(() => { window.orionVivaBridge = undefined; });
async function opened() {
  const restore = installSampleBridge();
  const base = window.orionVivaBridge!;
  let release: (() => void) | null = null;
  const requests: { operation: string; payload: Record<string, unknown> }[] = [];
  let selected = "";
  window.orionVivaBridge = { ...base, request: async <T,>(request: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
    requests.push(request);
    if (request.operation === "viva.documents.preview.read") return { protocol: "2.1", request_id: request.requestId, ok: true, result: { schema_version: 1, document_id: request.payload.document_id, status: "unavailable", reason: "original_unavailable" } as T };
    if (request.operation === "viva.surface.read" && request.payload.surface === "documents") {
      const data = payload(); const params = request.payload.parameters as Record<string, string>;
      if (params.selected_document_id) {
        selected = params.selected_document_id;
        const document = all.find((row) => row.id === selected);
        await new Promise<void>((resolve) => { release = resolve; });
        data.selected_document = { state: "ready", reason: null, document: document! };
      }
      return { protocol: "2.1", request_id: request.requestId, ok: true, result: { surface: "documents", job_id: "documents", data } as T };
    }
    return base.request<T>(request);
  } };
  const view = render(<App />);
  fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
  await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
  await waitFor(() => expect(view.container.querySelector('[data-read-revision="sample-fixture"]')).not.toBeNull());
  fireEvent.click(view.getByRole("button", { description: "View the evidence for net worth in USD." }));
  await waitFor(() => expect(view.getAllByRole("button", { name: /^Find / }).length).toBeGreaterThan(0));
  return { ...view, restore, requests, release: () => release?.(), selected: () => selected };
}

describe("off-page source through actual App evidence caller", () => {
  it("resolves selected detail asynchronously and previews only after the separate action", async () => {
    const view = await opened();
    fireEvent.click(view.getAllByRole("button", { name: /^Find / })[0]);
    await waitFor(() => expect(view.getByRole("button", { name: "Finding source…" })).toHaveAttribute("aria-disabled", "true"));
    expect(view.getByRole("dialog", { name: "Net worth in USD" })).toBeInTheDocument();
    expect(view.requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(0);
    const expected = all.find((row) => row.id === view.selected())!;
    await act(async () => { view.release(); });
    await waitFor(() => expect(view.getByRole("heading", { name: String(expected.filename) })).toBeInTheDocument());
    expect(view.container.querySelectorAll(".document-list-item")).toHaveLength(50);
    expect(view.getByText("Statements 1–50 of 794")).toBeInTheDocument();
    expect(view.requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(0);
    fireEvent.click(view.getByRole("button", { name: "View saved original" }));
    await waitFor(() => expect(view.requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(1));
    expect(view.requests.find((request) => request.operation === "viva.documents.preview.read")?.payload).toEqual({ document_id: view.selected(), page: 1 });
    view.restore();
  });
  it("keeps a late selected response from reopening a closed vault", async () => {
    const view = await opened();
    fireEvent.click(view.getAllByRole("button", { name: /^Find / })[0]);
    await waitFor(() => expect(view.getByRole("button", { name: "Finding source…" })).toBeInTheDocument());
    fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
    fireEvent.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    await act(async () => { view.release(); });
    expect(view.queryByRole("heading", { name: "Statements & documents" })).not.toBeInTheDocument();
    expect(view.container.querySelector("#selected-document-title")).toBeNull();
    expect(view.requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(0);
    view.restore();
  });
});

it("opens a held Review source component through independent detail and previews its exact page", async () => {
  const restore = installSampleBridge(); const base = window.orionVivaBridge!;
  const source = all[0]; const id = String(source.id);
  const component = { component: "payment:PAY-X", kind: "payment", label: "Payment PAY-X", disposition: "held", reason_code: "unmatched_counterpart", reason: "A unique compatible counterpart source has not been established.", effective_date: "2026-01-31", source_pages: [{ document_id: id, page: 2, label: "Payment source page 2" }] };
  const requests: { operation: string; payload: Record<string, unknown> }[] = [];
  window.orionVivaBridge = { ...base, request: async <T,>(request: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
    requests.push(request);
    if (request.operation === "viva.documents.preview.read") return { protocol: "2.1", request_id: request.requestId, ok: true, result: { schema_version: 1, document_id: id, status: "unavailable", reason: "original_unavailable" } as T };
    if (request.operation === "viva.surface.read" && request.payload.surface === "documents") {
      const data = payload(); const params = request.payload.parameters as Record<string, string>;
      if (params.selected_document_id) data.selected_document = { state: "ready", reason: null, document: { ...source, resolved: false, component_statuses: [component], observation_sections: [] } };
      return { protocol: "2.1", request_id: request.requestId, ok: true, result: { surface: "documents", job_id: "documents", data } as T };
    }
    const reply = await base.request<T>(request);
    if (request.operation === "viva.surface.read" && request.payload.surface === "review" && reply.ok) {
      const result = reply.result as Record<string, unknown>;
      result.data = { ...(result.data as Record<string, unknown>), document_attention: { contract_version: "instrument-document-review-v1", scope: "revision", state: "ready", total_documents: 1, shown_count: 1, remaining_count: 0, unavailable_reason: null, documents: [{ document_id: id, filename: source.filename, components: [component] }] } };
    }
    return reply;
  } };
  const view = render(<App />);
  fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
  await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
  fireEvent.click(view.getByRole("button", { name: /^Review,/ }));
  await waitFor(() => expect(view.getByText("Source sections needing review")).toBeInTheDocument());
  expect(requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(0);
  fireEvent.click(view.getByRole("button", { name: "Payment source page 2" }));
  await waitFor(() => expect(view.container.querySelector("#selected-document-title")).toHaveTextContent(String(source.filename)));
  await waitFor(() => expect(requests.filter((request) => request.operation === "viva.documents.preview.read")).toHaveLength(1));
  expect(requests.find((request) => request.operation === "viva.documents.preview.read")?.payload).toEqual({ document_id: id, page: 2 });
  expect(view.getByText("Needs review")).toBeInTheDocument();
  restore();
});
