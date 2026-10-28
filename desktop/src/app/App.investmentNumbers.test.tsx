import count from "./fixtures/investment/legacy-count-actual-wire.json";
import maximum from "./fixtures/investment/max-fractional-actual-wire.json";
import positions from "./fixtures/investment/positions-actual-wire.json";
import activity from "./fixtures/investment/activity-actual-wire.json";
import unavailable from "./fixtures/investment/basis-unavailable-actual-wire.json";
import { within } from "@testing-library/react";
import { fireEvent, render, waitFor, beforeEach, afterEach, describe, expect, it, App, installSampleBridge, installResponsiveMatchMedia, reviewQuestionPayload } from "./App.testSupport";
type Wire = typeof positions | typeof activity | typeof unavailable | typeof maximum | typeof count;
beforeEach(() => installResponsiveMatchMedia(1440));
afterEach(() => { window.orionVivaBridge = undefined; });
async function opened(wire: Wire) {
 const links = wire.figures.flatMap((figure) => figure.evidence_links);
 const documents = [...new Map(links.map((link) => [link.document_id, link])).values()].map((link) => ({ id: link.document_id, filename: link.label, doc_type: "statement", raw_available: false }));
 const restore = installSampleBridge({ conversation: { turns: [{ id: wire.figures[0].evidence_id.split(":")[1], kind: "ask", context_mode: "new_question", occurred_at: "2025-01-31", prompt: wire.question, outcome: "completed", answer: wire }], questions: [], total: 0 }, review: reviewQuestionPayload([]), documents: { documents } });
 const base = window.orionVivaBridge!;const requests: {operation:string;payload:Record<string,unknown>}[]=[];
 window.orionVivaBridge={...base,request:async <T,>(request:{requestId:string;operation:string;payload:Record<string,unknown>})=>{requests.push(request);return base.request<T>(request);}};
 const view = render(<App />);fireEvent.click(view.getAllByRole("button", { name: "Try sample data" })[0]);
 await waitFor(() => expect(view.getByRole("button", { name: "Ask Viva" })).toBeInTheDocument());
 fireEvent.click(view.getByRole("button", { name: "Ask Viva" }));
 await waitFor(() => expect(view.getByText(wire.text, { normalizer: (text) => text })).toBeInTheDocument());
 return { ...view, restore, requests };
}
describe("genuine investment receipts through saved history and App", () => {
 it.each([...positions.figures.map((figure) => ({wire:positions,figure})), ...activity.figures.map((figure) => ({wire:activity,figure}))])("opens the actual $figure.quantity receipt", async ({wire,figure}) => {
  const view=await opened(wire);fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
  const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
  expect(within(drawer).getByRole("heading",{name:"Numerical receipt"})).toBeInTheDocument();
  expect(drawer.querySelector('[data-field="value"]')).toHaveTextContent(figure.value);
  expect(drawer.querySelector('[data-field="grade"]')).toHaveTextContent("unverified");
  expect(drawer.querySelector('[data-field="currency"]')).toHaveTextContent(figure.currency || "Not a monetary quantity");
  expect(drawer.querySelector('[data-field="account_id"]')).toHaveTextContent(figure.subject.account_id);
  if("security_id" in figure.subject) expect(drawer.querySelector('[data-field="security_id"]')).toHaveTextContent(figure.subject.security_id);
  expect(drawer.querySelector('[data-field="source_page"]')).toHaveTextContent("1");
  if(figure.quantity==="disposed_cost_basis") {
   expect(drawer).toHaveTextContent("Derived disposed cost basis");
   expect(drawer.querySelector('[data-field="sale_proceeds"]')).toHaveTextContent("30.00");
   expect(drawer.querySelector('[data-field="reported_realized_gain"]')).toHaveTextContent("-5.00");
  }
  view.restore();
 });
 it("keeps missing basis unavailable instead of displaying a zero basis",async()=>{
  const view=await opened(unavailable);
  expect(view.queryByRole("button",{name:new RegExp("holding cost basis")})).toBeNull();
  const figure=unavailable.figures[0];fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
  const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
  expect(drawer).toHaveTextContent("holding cost basis: unavailable.");
  expect(drawer).not.toHaveTextContent("USD 0.00");view.restore();
 });
});

it("shows genuine maximum precision without scientific notation or lost digits",async()=>{
 const view=await opened(maximum);const figure=maximum.figures[0];
 expect(figure.written).toBe("123,456,789,012,345,678.123456789012");
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(drawer.querySelector('[data-field="value"]')).toHaveTextContent("123456789012345678.123456789012");
 expect(drawer.querySelector('[data-field="quantity"]')).toHaveTextContent("Security units");
 expect(drawer.querySelector('[data-field="currency"]')).toHaveTextContent("Not a monetary quantity");view.restore();
});
it("retains source page/account/security and resolves the genuine captured source through App",async()=>{
 const view=await opened(positions);const figure=positions.figures[0];
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(drawer.querySelector('[data-field="source_document"]')).toHaveTextContent(figure.evidence_links[0].document_id);
 expect(drawer.querySelector('[data-field="source_page"]')).toHaveTextContent("1");
 const sourceButtons=await within(drawer).findAllByRole("button",{name:new RegExp("^(Find|Open) synthetic-investment-source.pdf$")});
 fireEvent.click(sourceButtons[0]);
 await waitFor(()=>expect(view.container.querySelector("#selected-document-title")).toHaveTextContent("synthetic-investment-source.pdf"));
 expect(view.requests.some((request)=>(request.payload.parameters as Record<string,unknown>)?.selected_document_id===figure.evidence_links[0].document_id)).toBe(true);
 expect(view.requests.some((request)=>request.operation==="viva.documents.upload"||request.operation==="viva.conversation.ask")).toBe(false);view.restore();
});
it("restores exact serialized genuine saved receipts including signed loss and derived operands",async()=>{
 const first=await opened(activity);first.unmount();first.restore();
 const restored=JSON.parse(JSON.stringify(activity)) as typeof activity;
 const view=await opened(restored);const figure=restored.figures[3];
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(drawer.querySelector('[data-field="sale_proceeds"]')).toHaveTextContent("30.00");
 expect(drawer.querySelector('[data-field="reported_realized_gain"]')).toHaveTextContent("-5.00");
 expect(drawer).toHaveTextContent("Source sale proceeds minus source reported realized gain; no lot method is asserted.");
 expect(drawer).not.toHaveTextContent("FIFO");view.restore();
});

it("keeps the actual legacy holding count whole and account-scoped",async()=>{
 const view=await opened(count);const figure=count.figures[0];
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(drawer.querySelector('[data-field="quantity"]')).toHaveTextContent("Count");
 expect(drawer.querySelector('[data-field="value"]')).toHaveTextContent("1");
 expect(drawer.querySelector('[data-field="security_id"]')).toBeNull();
 expect(drawer.querySelector('[data-field="source_page"]')).toHaveTextContent("1");view.restore();
});
