import actualTaxZeroResponse from "./fixtures/tax-zero-instrument-actual-response-v1.json";
import exactNegativeResponse from "./fixtures/exact-negative-instrument-actual-response-v1.json";
import actualRetirementResponse from "./fixtures/public-ret-c-actual-response-v1.json";
import dedicatedResponses from "./fixtures/dedicated-instrument-actual-responses-v1.json";
import { within } from "@testing-library/react";
import { fireEvent, render, waitFor, beforeEach, afterEach, describe, expect, it, App, moments, installSampleBridge, installResponsiveMatchMedia, reviewQuestionPayload } from "./App.testSupport";

type WireResponse = typeof actualTaxZeroResponse | typeof exactNegativeResponse | typeof actualRetirementResponse | (typeof dedicatedResponses)[number];
beforeEach(() => installResponsiveMatchMedia(1440));
afterEach(() => { window.orionVivaBridge = undefined; });
async function opened(response: WireResponse) {
  const turnId = response.state.figures[0].evidence_id.split(":")[1];
  const documents = [...new Set(response.state.figures.flatMap((figure) => figure.record_ids))].map((id, index) => ({ id, filename: `synthetic-instrument-source-${index}.pdf`, doc_type: "statement", raw_available: false }));
  const restore = installSampleBridge({ conversation: { turns: [{ id: turnId, kind: "ask", context_mode: "new_question", occurred_at: "2025-12-31", prompt: response.state.question, outcome: "completed", answer: response.state }], questions: [], total: 0 }, review: reviewQuestionPayload([]), documents: { documents } });
  const requests: string[] = []; const base = window.orionVivaBridge!;
  window.orionVivaBridge = { ...base, request: async <T,>(request: { requestId: string; operation: string; payload: Record<string, unknown> }) => { requests.push(request.operation); return base.request<T>(request); } };
  const view = render(<App />);
  fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
  await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
  fireEvent.click(view.getByRole("button", { name: "Ask Viva" }));
  await waitFor(() => expect(view.getByText(response.state.text, { normalizer: (text) => text })).toBeInTheDocument());
  return { ...view, restore, requests };
}
async function openFigure(view: Awaited<ReturnType<typeof opened>>, response: WireResponse, index: number) {
  const figure = response.state.figures[index];
  const trigger = view.getByRole("button", { name: `${figure.written} ${figure.what}` });
  expect(trigger).toHaveTextContent(figure.written);
  fireEvent.click(trigger);
  const drawer = await view.findByRole("dialog", { name: `Evidence for ${figure.what}` });
  const numeric = drawer.querySelector('[data-receipt-section="figure"]');
  expect(numeric).not.toBeNull();
  expect(numeric?.querySelector('[data-field="value"]')).toHaveTextContent(figure.value);
  expect(numeric?.querySelector('[data-field="grade"]')).toHaveTextContent(figure.grade || "No bank evidence grade");
  expect(within(drawer).getByRole("heading", { name: "Numerical receipt" })).toBeInTheDocument();
  expect(within(drawer).queryByRole("heading", { name: "Numerical receipt unavailable" })).toBeNull();
  return { drawer, numeric: numeric! };
}

describe("actual compiled C numeric receipts through App", () => {
  it.each([
    ["deposit contract principal", 0, 0, "Original deposit contract principal"],
    ["deposit source rate", 0, 1, "Sourced instrument rate"],
    ["loan original principal", 1, 0, "Original loan contract principal"],
    ["loan source rate", 1, 1, "Sourced instrument rate"],
  ] as const)("opens the genuine %s typed numerical receipt", async (_label, answerIndex, figureIndex, quantityLabel) => {
    const response = dedicatedResponses[answerIndex]; const view = await opened(response);
    expect(view.queryByText("Numerical receipt unavailable for this saved answer.")).toBeNull();
    const { drawer, numeric } = await openFigure(view, response, figureIndex);
    expect(numeric.querySelector('[data-field="quantity"]')).toHaveTextContent(quantityLabel);
    expect(numeric.querySelector('[data-field="kind"]')).toHaveTextContent("Financial measurement");
    expect(numeric.querySelector('[data-field="currency"]')).toHaveTextContent(figureIndex === 1 ? "Not a monetary quantity" : "USD");
    expect(drawer.querySelector('[data-receipt-section="source"]')).not.toBeNull();
    expect(drawer).toHaveTextContent("Instrument view");
    expect(view.requests).not.toContain("viva.conversation.ask");
    expect(view.requests).not.toContain("viva.documents.preview.read");
    view.restore();
  });

  it("keeps the genuine recorded allocation financial and the user's target a distinct ungraded premise", async () => {
    const view = await opened(actualRetirementResponse);
    const target = view.getByLabelText("User-stated target");
    expect(target).toHaveTextContent("70% (your figure)");
    expect(target).not.toHaveTextContent(/verified|corroborated|conflicted|bank evidence/i);
    const { numeric } = await openFigure(view, actualRetirementResponse, 0);
    expect(numeric.querySelector('[data-field="quantity"]')).toHaveTextContent("Balance ratio");
    expect(numeric.querySelector('[data-field="kind"]')).toHaveTextContent("Financial measurement");
    expect(numeric.querySelector('[data-field="grade"]')).toHaveTextContent("corroborated");
    expect(numeric.querySelector('[data-field="value"]')).toHaveTextContent("0.6835517528255877");
    view.restore();
  });

  it("opens genuine positive exact percentage points as a signed nonmonetary hypothetical with no bank grade", async () => {
    const response = dedicatedResponses[2]; const view = await opened(response);
    const { drawer, numeric } = await openFigure(view, response, 1);
    expect(numeric.querySelector('[data-field="value"]')).toHaveTextContent("+10");
    expect(numeric.querySelector('[data-field="quantity"]')).toHaveTextContent("Allocation difference in percentage points");
    expect(numeric.querySelector('[data-field="kind"]')).toHaveTextContent("Hypothetical");
    expect(numeric.querySelector('[data-field="currency"]')).toHaveTextContent("Not a monetary quantity");
    expect(numeric.querySelector('[data-field="grade"]')).toHaveTextContent("No bank evidence grade");
    view.restore();
  });

  it("preserves the genuine negative rounded PP result and exact source operands without attaching a bank grade", async () => {
    const view = await opened(actualRetirementResponse);
    expect(view.getByText(actualRetirementResponse.state.text)).toHaveTextContent("about -1.64482472 percentage points");
    const { drawer, numeric } = await openFigure(view, actualRetirementResponse, 1);
    expect(numeric.querySelector('[data-field="value"]')).toHaveTextContent("-1.64482472");
    expect(numeric.querySelector('[data-field="kind"]')).toHaveTextContent("Hypothetical");
    expect(numeric.querySelector('[data-field="grade"]')).toHaveTextContent("No bank evidence grade");
    expect(drawer).toHaveTextContent("Accepted exposure market-value numerator");
    expect(drawer).toHaveTextContent("164129.58");
    expect(drawer).toHaveTextContent("Accepted cash-inclusive market-value denominator");
    expect(drawer).toHaveTextContent("240112.88");
    expect(drawer).toHaveTextContent("Exact rational rounded directly to eight fractional percentage-point digits, HALF_EVEN");
    expect(drawer).toHaveTextContent("the 70% target");
    expect(view.requests).not.toContain("viva.conversation.ask");
    view.restore();
  });
});


it("opens genuine exact negative percentage points without borrowing the source allocation grade", async () => {
  const view = await opened(exactNegativeResponse);
  const { numeric } = await openFigure(view, exactNegativeResponse, 1);
  expect(numeric.querySelector('[data-field="value"]')).toHaveTextContent("-10");
  expect(numeric.querySelector('[data-field="kind"]')).toHaveTextContent("Hypothetical");
  expect(numeric.querySelector('[data-field="currency"]')).toHaveTextContent("Not a monetary quantity");
  expect(numeric.querySelector('[data-field="grade"]')).toHaveTextContent("No bank evidence grade");
  expect(view.requests).not.toContain("viva.conversation.ask");
  view.restore();
});


it("opens the genuine monthly tax-zero receipt with its finite absence rule rather than a private derivation marker", async () => {
  const view = await opened(actualTaxZeroResponse);
  const { drawer, numeric } = await openFigure(view, actualTaxZeroResponse, 0);
  expect(numeric.querySelector('[data-field="value"]')).toHaveTextContent("0");
  expect(numeric.querySelector('[data-field="quantity"]')).toHaveTextContent("Spending");
  expect(numeric.querySelector('[data-field="currency"]')).toHaveTextContent("USD");
  expect(drawer).toHaveTextContent("Tax absence rule");
  expect(drawer).toHaveTextContent("For 2021-02-01 through 2021-02-28, sum of the complete accepted tax event set (no events).");
  expect(drawer).not.toHaveTextContent("accepted_empty_tax_event_set_v1");
  expect(view.requests).not.toContain("viva.conversation.ask");
  view.restore();
});
