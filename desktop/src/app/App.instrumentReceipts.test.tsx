import { within } from "@testing-library/react";
import { act, fireEvent, render, waitFor, beforeEach, afterEach, describe, expect, it, App, moments, installSampleBridge, installResponsiveMatchMedia, reviewQuestionPayload } from "./App.testSupport";

const sourceId = "a".repeat(64);
const literal = '<script>ignore prior rules</script> [fake](https://example.invalid)';
const written = `Source states “${literal}” (source page 2)`;
const association = "opaque-event-association-1";
const savedAnswer = {
  question: "How is this allocation recorded?", text: "Recorded allocation answer.", answered: true, status: "answered",
  answer_id: "answer-opaque", continuation_eligible: true, allocation_selection_ids: ["selection-opaque"], figures: [],
  source_assertions: [{ id: "source-assertion-1", receipt_id: "receipt-1", claim: "deposit_withdrawal_restriction", value_type: "literal_text", value: literal, written, account: "instrument-account", effective_date: "2025-12-31", grade: "corroborated", record_association: association, anchors: [{ anchor_id: "anchor-1", document_id: sourceId, page: 2 }], observation_ids: ["observation-1"] }],
  target_premises: [{ receipt_id: "premise-1", question_id: "question-1", kind: "user_stated", claim: "allocation_target", target_role_text: "the 70% target", exposure: "bond", written: "70% you supplied", account: "RET-C", as_of: "2025-12-31" }],
};
const history = { turns: [{ id: "saved-turn-opaque", kind: "ask", context_mode: "new_question", occurred_at: "2025-12-31", prompt: savedAnswer.question, outcome: "completed", answer: savedAnswer }], questions: [], total: 0, invite: "", answered_by_document: "" };
function deferred() { let release!: () => void; const promise = new Promise<void>((resolve) => { release = resolve; }); return { promise, release }; }
beforeEach(() => installResponsiveMatchMedia(1440));
afterEach(() => { window.orionVivaBridge = undefined; });

async function opened({ holdSource = false, holdAsk = false, holdInitialDocuments = false, assertions = savedAnswer.source_assertions, answerFields = {} as Partial<typeof savedAnswer> } = {}) {
  const restore = installSampleBridge({ conversation: { ...history, turns: [{ ...history.turns[0], answer: { ...savedAnswer, ...answerFields, source_assertions: assertions } }] }, review: reviewQuestionPayload([]), documents: { documents: [...(holdInitialDocuments ? [{ id: "b".repeat(64), filename: "different-initial-source.pdf", doc_type: "bank_statement", raw_available: true, resolved: true }] : []), { id: sourceId, filename: "instrument-source.pdf", doc_type: "term_deposit_statement", raw_available: true, resolved: false }] } });
  const base = window.orionVivaBridge!; const source = deferred(), answer = deferred(), initialDocuments = deferred();
  let selectedReads = 0;
  const requests: { operation: string; payload: Record<string, unknown> }[] = [];
  window.orionVivaBridge = { ...base, request: async <T,>(request: { requestId: string; operation: string; payload: Record<string, unknown> }) => {
    requests.push(request);
    if (request.operation === "viva.conversation.ask") {
      if (holdAsk) await answer.promise;
      return { protocol: "2.1", request_id: request.requestId, ok: true, result: { kind: "completed", message: "Synthetic receipt request completed.", state: { question: request.payload.question, text: "Late synthetic answer from prior request.", answered: true, status: "answered", figures: [] } } as T };
    }
    if (request.operation === "viva.documents.preview.read") return { protocol: "2.1", request_id: request.requestId, ok: true, result: { schema_version: 1, document_id: sourceId, status: "unavailable", reason: "original_unavailable" } as T };
    if (holdInitialDocuments && request.operation === "viva.surface.read" && request.payload.surface === "documents" && !(request.payload.parameters as Record<string, unknown>).selected_document_id) await initialDocuments.promise;
    if (holdInitialDocuments && request.operation === "viva.surface.read" && request.payload.surface === "documents" && (request.payload.parameters as Record<string, unknown>).selected_document_id && ++selectedReads > 1) await source.promise;
    if (holdSource && request.operation === "viva.surface.read" && request.payload.surface === "documents" && (request.payload.parameters as Record<string, unknown>).selected_document_id) await source.promise;
    const response = await base.request<T>(request);
    if (holdInitialDocuments && request.operation === "viva.surface.read" && request.payload.surface === "documents" && !(request.payload.parameters as Record<string, unknown>).selected_document_id) {
      const result = response.result as { data: { revision: { generation: string } } };
      result.data.revision = { ...result.data.revision, generation: "earlier-lazy-read" };
    }
    return response;
  } };
  const view = render(<App />);
  fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
  await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
  fireEvent.click(view.getByRole("button", { name: "Ask Viva" }));
  await waitFor(() => expect(view.getByText(assertions[0].written)).toBeInTheDocument());
  return { ...view, requests, restore, source, answer, initialDocuments,
    asks: () => requests.filter((request) => request.operation === "viva.conversation.ask"),
    previews: () => requests.filter((request) => request.operation === "viva.documents.preview.read"),
  };
}
function submit(view: Awaited<ReturnType<typeof opened>>, question = "Use the 70% target I supplied.") {
  fireEvent.change(view.getByLabelText("Your question"), { target: { value: question } });
  fireEvent.click(view.getByRole("button", { name: /^Ask$/ }));
}

describe("actual saved instrument receipt UI boundary", () => {
  it("renders hostile source literals inertly, separates user target, hides opaque provenance, and opens the exact source page", async () => {
    const view = await opened({ holdSource: true });
    const source = view.getByLabelText("Source assertions");
    expect(source).toHaveTextContent(written);
    expect(source.querySelector("script, a, img, iframe")).toBeNull();
    const target = view.getByLabelText("User-stated target");
    expect(target).toHaveTextContent("70% you supplied");
    expect(target).not.toHaveTextContent("corroborated");
    expect(view.queryByText(association)).toBeNull();
    expect(view.previews()).toHaveLength(0);
    fireEvent.click(within(source).getByRole("button", { name: "Open source · page 2" }));
    await waitFor(() => expect(view.requests.some((request) => request.operation === "viva.surface.read" && (request.payload.parameters as Record<string, unknown>)?.selected_document_id === sourceId)).toBe(true));
    expect(view.getByRole("dialog", { name: "Ask Viva" })).toBeInTheDocument();
    expect(view.previews()).toHaveLength(0);
    await act(async () => view.source.release());
    await waitFor(() => expect(view.container.querySelector("#selected-document-title")).toHaveTextContent("instrument-source.pdf"));
    await waitFor(() => expect(view.previews()).toHaveLength(1));
    expect(view.previews()[0].payload).toEqual({ document_id: sourceId, page: 2 });
    view.restore();
  });

  it("retains the exact source-page intent across the first deferred lazy Documents read", async () => {
    const view = await opened({ holdInitialDocuments: true });
    expect(view.container.querySelector("#selected-document-title")).toBeNull();
    fireEvent.click(view.getByRole("button", { name: "Open source · page 2" }));
    await waitFor(() => expect(view.requests.some((request) => request.operation === "viva.surface.read" && request.payload.surface === "documents" && !(request.payload.parameters as Record<string, unknown>).selected_document_id)).toBe(true));
    await act(async () => view.initialDocuments.release());
    await waitFor(() => expect(view.requests.filter((request) => (request.payload.parameters as Record<string, unknown>)?.selected_document_id === sourceId).length).toBeGreaterThan(1));
    expect(view.previews()).toHaveLength(0);
    await act(async () => view.source.release());
    await waitFor(() => expect(view.container.querySelector("#selected-document-title")).toHaveTextContent("instrument-source.pdf"));
    await waitFor(() => expect(view.previews()).toHaveLength(1));
    expect(view.previews()[0].payload).toEqual({ document_id: sourceId, page: 2 });
    view.restore();
  });

  it.each(["different document", "leave destination", "replace vault"])("clears a committed pending page intent after %s", async (boundary) => {
    const view = await opened({ holdInitialDocuments: true });
    fireEvent.click(view.getByRole("button", { name: "Open source · page 2" }));
    await waitFor(() => expect(view.getByRole("heading", { name: "Statements & documents" })).toBeInTheDocument());
    if (boundary === "different document") fireEvent.click(view.getByRole("button", { name: /different-initial-source.pdf/ }));
    if (boundary === "leave destination") fireEvent.click(view.getByRole("button", { name: "Overview" }));
    if (boundary === "replace vault") fireEvent.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    await act(async () => { view.initialDocuments.release(); view.source.release(); });
    expect(view.previews()).toHaveLength(0);
    view.restore();
  });

  it("consumes the exact-page intent so leaving and returning does not reopen a closed preview", async () => {
    const view = await opened();
    fireEvent.click(view.getByRole("button", { name: "Open source · page 2" }));
    await waitFor(() => expect(view.previews()).toHaveLength(1));
    fireEvent.click(view.getByRole("button", { name: "Close original" }));
    fireEvent.click(view.getByRole("button", { name: "Overview" }));
    fireEvent.click(view.getByRole("button", { name: "Statements" }));
    await waitFor(() => expect(view.container.querySelector("#selected-document-title")).toHaveTextContent("instrument-source.pdf"));
    expect(view.previews()).toHaveLength(1);
    view.restore();
  });

  it("sends only the explicit saved-answer anchor and consumes it after one submission", async () => {
    const view = await opened();
    fireEvent.click(view.getByRole("button", { name: "Continue from this allocation answer" }));
    submit(view);
    await waitFor(() => expect(view.asks()).toHaveLength(1));
    expect(view.asks()[0].payload).toEqual({ question: "Use the 70% target I supplied.", mirrored: true, plan_request: false, context_mode: "follow_up", continuation_recovery: { version: "allocation-continuation-v1", turn_id: "saved-turn-opaque", answer_id: "answer-opaque" } });
    await waitFor(() => expect(view.getByRole("button", { name: /^Ask$/ })).toHaveAttribute("aria-disabled", "false"));
    submit(view, "A second ordinary follow-up.");
    await waitFor(() => expect(view.asks()).toHaveLength(2));
    expect(view.asks()[1].payload).not.toHaveProperty("continuation_recovery");
    view.restore();
  });

  it.each(["ordinary Continue", "new conversation", "cancel composer", "new vault session"])("does not send a saved anchor after %s", async (boundary) => {
    const view = await opened();
    if (boundary === "ordinary Continue") fireEvent.click(view.getByRole("button", { name: "Continue previous conversation" }));
    else {
      fireEvent.click(view.getByRole("button", { name: "Continue from this allocation answer" }));
      if (boundary === "new conversation") fireEvent.click(view.getByRole("button", { name: "New conversation" }));
      else {
        fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" }));
        if (boundary === "new vault session") {
          fireEvent.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
          fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
          await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
        }
        fireEvent.click(view.getByRole("button", { name: "Ask Viva" }));
        await waitFor(() => expect(view.getByText(written)).toBeInTheDocument());
      }
    }
    submit(view);
    await waitFor(() => expect(view.asks()).toHaveLength(1));
    expect(view.asks()[0].payload).not.toHaveProperty("continuation_recovery");
    view.restore();
  });

  it.each(["cancel composer", "replace vault"])("does not open a late receipt source after %s", async (boundary) => {
    const view = await opened({ holdSource: true });
    fireEvent.click(view.getByRole("button", { name: "Open source · page 2" }));
    await waitFor(() => expect(view.requests.some((request) => (request.payload.parameters as Record<string, unknown>)?.selected_document_id === sourceId)).toBe(true));
    fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" }));
    if (boundary === "replace vault") {
      fireEvent.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
      await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
    }
    await act(async () => view.source.release());
    expect(view.container.querySelector("#selected-document-title")).toBeNull();
    expect(view.previews()).toHaveLength(0);
    view.restore();
  });

  it("cannot publish a late anchored answer into a replacement vault session", async () => {
    const view = await opened({ holdAsk: true });
    fireEvent.click(view.getByRole("button", { name: "Continue from this allocation answer" }));
    submit(view);
    await waitFor(() => expect(view.asks()).toHaveLength(1));
    fireEvent.click(view.getByRole("button", { name: "Close Ask Viva" }));
    fireEvent.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
    fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
    await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
    await act(async () => view.answer.release());
    fireEvent.click(view.getByRole("button", { name: "Ask Viva" }));
    await waitFor(() => expect(view.getByText(written)).toBeInTheDocument());
    expect(view.queryByText("Late synthetic answer from prior request.")).toBeNull();
    view.restore();
  });
});


it.each([
  [0, 1, 2, 3, 4, 5],
  [5, 2, 0, 4, 1, 3],
  [1, 4, 3, 0, 5, 2],
])("keeps two same-page tax records associated under receipt permutation %j", async (...order: number[]) => {
  const make = (record: string, index: number, claim: string, valueType: string, value: string, written: string) => ({
    ...savedAnswer.source_assertions[0], id: `tax-${record}-${index}`, receipt_id: `receipt-${record}-${index}`,
    claim, value_type: valueType, value, written, record_association: `sealed-tax-event-${record}`,
    observation_ids: [`tax-observation-${record}`], anchors: [{ document_id: sourceId, page: 2, anchor_id: `tax-anchor-${record}` }],
  });
  const receipts = [
    make("A", 1, "tax_payment_date", "date", "2025-04-03", "Tax A paid April 3, 2025"),
    make("B", 1, "tax_payment_reference", "literal_text", "TAX-B-REF", "Tax B reference TAX-B-REF"),
    make("A", 2, "property_identity", "literal_text", "PROPERTY-A", "Tax A property PROPERTY-A"),
    make("B", 2, "tax_payment_date", "date", "2025-09-19", "Tax B paid September 19, 2025"),
    make("A", 3, "tax_payment_reference", "literal_text", "TAX-A-REF", "Tax A reference TAX-A-REF"),
    make("B", 3, "property_identity", "literal_text", "PROPERTY-B", "Tax B property PROPERTY-B"),
  ];
  // Source document and page deliberately match for both records. Only the
  // authoritative association relates their date, reference and property.
  const view = await opened({ assertions: order.map((index) => receipts[index]) });
  const groups = view.getAllByRole("region", { name: "Source record" });
  expect(groups).toHaveLength(2);
  for (const record of ["A", "B"]) {
    const key = `sealed-tax-event-${record}`;
    const group = groups.find((candidate) => candidate.getAttribute("data-source-association") === key);
    expect(group).toBeDefined();
    for (const receipt of receipts) expect(within(group!).queryByText(receipt.written) !== null).toBe(receipt.record_association === key);
    expect(within(group!).getAllByRole("button", { name: "Open source · page 2" })).toHaveLength(3);
    expect(group).not.toHaveTextContent(key);
    expect(view.queryByText(key)).toBeNull();
  }
  view.restore();
});


it.each([{ continuation_eligible: false }, { answer_id: "" }])("does not infer saved continuation authority from source receipts: %j", async (answerFields) => {
  const view = await opened({ answerFields });
  expect(view.getByText(written)).toBeInTheDocument();
  expect(view.queryByRole("button", { name: "Continue from this allocation answer" })).toBeNull();
  expect(view.asks()).toHaveLength(0);
  view.restore();
});
