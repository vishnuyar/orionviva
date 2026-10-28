import annual from "./fixtures/retirement/annual-actual-wire.json";
import rollovers from "./fixtures/retirement/rollovers-actual-wire.json";
import { within } from "@testing-library/react";
import { fireEvent, render, waitFor, beforeEach, afterEach, expect, it, App, installSampleBridge, installResponsiveMatchMedia, reviewQuestionPayload } from "./App.testSupport";
type Wire = typeof annual | typeof rollovers;
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
it("opens the genuine annual employee total as an explicit selected set",async()=>{
 const view=await opened(annual);const figure=annual.figures[0];
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(within(drawer).getByRole("heading",{name:"Numerical receipt"})).toBeInTheDocument();
 expect(drawer.querySelector('[data-field="account_set_id"]')).toHaveTextContent(figure.subject.account_set_id);
 expect(drawer.querySelectorAll('[data-field="member_id"]')).toHaveLength(2);
 expect(drawer.querySelector('[data-field="account_id"]')).toBeNull();
 expect(drawer.querySelector('[data-field="value"]')).toHaveTextContent("12000");view.restore();
});
it.each(rollovers.figures.filter((figure)=>figure.quantity==="investment_contribution"))("opens the actual rollover $value with its own endpoints",async(figure)=>{
 const view=await opened(rollovers);
 fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(within(drawer).getByRole("heading",{name:"Numerical receipt"})).toBeInTheDocument();
 expect(drawer.querySelector('[data-field="relationship_id"]')).toHaveTextContent(figure.subject.relationship_id);
 expect(drawer.querySelector('[data-field="source_account_id"]')).toHaveTextContent(figure.subject.source_account_id);
 expect(drawer.querySelector('[data-field="destination_account_id"]')).toHaveTextContent(figure.subject.destination_account_id);view.restore();
});
it("keeps genuine source assertions in their own association groups",async()=>{
 const view=await opened(rollovers);const labels=[...new Set(rollovers.source_assertions.map((item)=>item.association_label))];expect(labels).toHaveLength(2);const groups=labels.map((name)=>view.getByRole("region",{name}));expect(groups).toHaveLength(2);
 for(const group of groups){const association=group.getAttribute("data-source-association");const expected=rollovers.source_assertions.filter((item)=>item.record_association===association);expect(expected).toHaveLength(4);for(const item of expected)expect(group).toHaveTextContent(item.written);}
 view.restore();
});
it.each(rollovers.figures.filter((figure)=>figure.value==="0"))("shows actual scoped $what as exact zero with its source grade",async(figure)=>{
 const view=await opened(rollovers);fireEvent.click(view.getByRole("button",{name:`${figure.written} ${figure.what}`}));
 const drawer=await view.findByRole("dialog",{name:`Evidence for ${figure.what}`});
 expect(drawer.querySelector('[data-field="value"]')).toHaveTextContent("0");
 expect(drawer.querySelector('[data-field="grade"]')).toHaveTextContent("unverified");
 expect(drawer.querySelector('[data-field="relationship_id"]')).toHaveTextContent(figure.subject.relationship_id);
 expect(drawer.querySelector('[data-field="source_account_id"]')).toHaveTextContent(figure.subject.source_account_id);
 expect(drawer.querySelector('[data-field="destination_account_id"]')).toHaveTextContent(figure.subject.destination_account_id);
 const other=rollovers.figures.find((item)=>item.subject.relationship_id!==figure.subject.relationship_id)!;
 expect(drawer).not.toHaveTextContent(other.subject.relationship_id);
 expect(drawer.querySelector('[data-field="source_page"]')).toHaveTextContent("1");view.restore();
});
it("restores genuine record group identity after permutation and serialized saved history",async()=>{
 const wire=JSON.parse(JSON.stringify(rollovers)) as typeof rollovers;wire.source_assertions.reverse();wire.figures.reverse();
 const first=await opened(wire);first.unmount();first.restore();const view=await opened(JSON.parse(JSON.stringify(wire)) as typeof rollovers);
 const labels=[...new Set(wire.source_assertions.map((item)=>item.association_label))];expect(labels).toHaveLength(2);const groups=labels.map((name)=>view.getByRole("region",{name}));expect(groups).toHaveLength(2);
 for(const group of groups){const association=group.getAttribute("data-source-association");const expected=wire.source_assertions.filter((item)=>item.record_association===association);expect(expected).toHaveLength(4);for(const item of expected)expect(group).toHaveTextContent(item.written);for(const item of wire.source_assertions.filter((item)=>item.record_association!==association))expect(group).not.toHaveTextContent(item.written);}
 const expected=wire.source_assertions[0];const group=groups.find((item)=>item.getAttribute("data-source-association")===expected.record_association)!;
 const claimLabels:Record<string,string>={rollover_date:"Rollover date",rollover_reference:"Rollover reference",rollover_source_account:"Source account",rollover_destination_account:"Destination account"};
 fireEvent.click(within(group).getByRole("button",{name:`${expected.association_label} · ${claimLabels[expected.claim]} · page ${expected.anchors[0].page} · ${expected.anchors[0].document_id}`}));
 await waitFor(()=>expect(view.requests.some((request)=>(request.payload.parameters as Record<string,unknown>)?.selected_document_id===expected.anchors[0].document_id)).toBe(true));view.restore();
});
