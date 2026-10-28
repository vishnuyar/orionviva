import { describe, expect, it } from "vitest";
import positions from "./fixtures/investment/positions-actual-wire.json";
import activity from "./fixtures/investment/activity-actual-wire.json";
import unavailable from "./fixtures/investment/basis-unavailable-actual-wire.json";
import { adaptTurn } from "./conversation";
// Exact public source-reader→post→SQL→tool→Binder→surface outputs; no authored positives.
describe("genuine investment numerical receipt wire", () => {
  it.each([positions, activity, unavailable])("retains every actual figure and receipt for $question", (wire) => {
    const answer = adaptTurn(wire)!;
    expect(answer.figures).toHaveLength(wire.figures.length);
    for (const [index, figure] of answer.figures.entries()) {
      const raw = wire.figures[index];
      expect(figure.receiptState).toBe("ready");
      expect(figure.numerical).toMatchObject({ value: raw.value, quantity: raw.quantity, kind: raw.kind, currency: raw.currency, grade: raw.grade, subject: raw.subject, boundary: raw.boundary });
      expect(figure.evidenceLinks[0].page).toBe("1");
    }
  });
});
import maximum from "./fixtures/investment/max-fractional-actual-wire.json";
import { numericalFigure } from "./numerical-receipts";
it("preserves the genuine eighteen-integer/twelve-fraction units without numeric conversion",()=>{
 const answer=adaptTurn(maximum)!;const figure=answer.figures.find((f)=>f.numerical?.quantity==="security_units")!;
 expect(figure.receiptState).toBe("ready");expect(figure.numerical?.value).toBe("123456789012345678.123456789012");
 expect(figure.written).toBe("123,456,789,012,345,678.123456789012");
});
it("retains only this figure's provenance/derivation and never invents unknown basis",()=>{
 const answer=adaptTurn(activity)!;
 const derived=answer.figures.find((f)=>f.numerical?.quantity==="disposed_cost_basis")!;
 expect(derived.numericalReceipts?.[0].investmentDerivations?.[0].rows[0]).toMatchObject({proceeds:"30.00",reportedRealizedGain:"-5.00"});
 for(const figure of answer.figures){expect(Object.keys(figure.numericalReceipts![0].figureProvenance!)).toEqual([figure.id]);if(figure!==derived)expect(figure.numericalReceipts![0].investmentDerivations).toEqual([]);}
 expect(adaptTurn(unavailable)!.figures.some((f)=>f.numerical?.quantity==="holding_cost_basis")).toBe(false);
});
it.each(["-1","-0","+1","1e3","NaN","Infinity","1000000000000000000","1.1234567890123",true,1.25])("refuses invalid units %s",(value)=>{
 expect(numericalFigure({...positions.figures[0],value})).toBeUndefined();
});
it.each(["currency","grade","kind","account","security","missing security","extra subject","duplicate scope","missing date"])("refuses a broken investment %s",(broken)=>{
 const raw=structuredClone(positions.figures[0]);
 if(broken==="currency")raw.currency="USD";
 if(broken==="grade")raw.grade="";
 if(broken==="kind")raw.kind="computed";
 if(broken==="account")raw.subject.account_id="another-account";
 if(broken==="security")raw.subject.security_id="another-security";
 if(broken==="missing security")delete (raw.subject as Partial<typeof raw.subject>).security_id;
 if(broken==="extra subject")Object.assign(raw.subject,{merchant:"invented"});
 if(broken==="duplicate scope")raw.boundary.cut.push(raw.boundary.cut[0]);
 if(broken==="missing date")raw.dated="";
 expect(numericalFigure(raw)).toBeUndefined();
});
it.each(["unknown quantity","unknown context","extra receipt","missing provenance","foreign provenance figure","foreign page","bad page","source substitution","missing derivation","foreign derivation figure","unknown operation","bad operand","foreign operand page","currency mismatch"])("fails closed for %s",(broken)=>{
 const wire=structuredClone(activity);const receipt=wire.numerical_receipts[0];
 if(broken==="unknown quantity")wire.figures[0].quantity="investment_contribution_v2";
 if(broken==="unknown context")receipt.context.push({label:"Invented context",value:"unsupported"});
 if(broken==="extra receipt")Object.assign(receipt,{unreviewed:true});
 if(broken==="missing provenance")delete (receipt as Partial<typeof receipt>).figure_provenance;
 if(broken==="foreign provenance figure")Object.assign(receipt.figure_provenance,{foreign:receipt.figure_provenance.f1});
 if(broken==="foreign page")receipt.figure_provenance.f1[0].document_id="a".repeat(64);
 if(broken==="bad page")receipt.figure_provenance.f1[0].page=201;
 if(broken==="source substitution")receipt.source_records[0].document_id="a".repeat(64);
 if(broken==="missing derivation")receipt.investment_derivations=[];
 if(broken==="foreign derivation figure")receipt.investment_derivations[0].figure_id="f1";
 if(broken==="unknown operation")receipt.investment_derivations[0].operation="fifo";
 if(broken==="bad operand")receipt.investment_derivations[0].rows[0].proceeds="1e3";
 if(broken==="foreign operand page")receipt.investment_derivations[0].rows[0].source_pages[0].page=2;
 if(broken==="currency mismatch")wire.figures[0].currency="EUR";
 const answer=adaptTurn(wire)!;
 expect(answer.figures.every((figure)=>figure.receiptState==="unavailable")).toBe(true);
});
it.each(["security_units","holding_cost_basis","investment_contribution","investment_dividend","sale_proceeds","disposed_cost_basis","realized_gain"])("does not admit %s as a scenario starting measurement",(quantity)=>{
 const wire=structuredClone(activity);
 (wire.numerical_receipts[0].observed_inputs as unknown[]).push({account_id:activity.figures[0].subject.account_id,value:"1",modeled_value:"1",quantity,kind:"financial",currency:"USD",dated:"2025-01-31",grade:"unverified",measurement_view:"recorded_cash",record_ids:[activity.figures[0].record_ids[0]],carry_forward_hypothetical:true});
 expect(adaptTurn(wire)!.figures.every((figure)=>figure.receiptState==="unavailable")).toBe(true);
});

it("refuses oversized units display and economic-row lists without truncating",()=>{
 expect(numericalFigure({...positions.figures[0],written:"1".repeat(41)})).toBeUndefined();
 const wire=structuredClone(activity);const source=wire.numerical_receipts[0].investment_derivations[0].rows[0];
 wire.numerical_receipts[0].investment_derivations[0].rows=Array.from({length:1001},(_,index)=>({...source,row_id:`${source.row_id}-${index}`}));
 expect(adaptTurn(wire)!.figures.every((figure)=>figure.receiptState==="unavailable")).toBe(true);
});

it("honors independently optional empty derivations without dropping required source pages",()=>{
 const wire=structuredClone(positions);delete (wire.numerical_receipts[0] as Partial<typeof wire.numerical_receipts[0]>).investment_derivations;
 expect(adaptTurn(wire)!.figures.every((figure)=>figure.receiptState==="ready")).toBe(true);
 delete (wire.numerical_receipts[0] as Partial<typeof wire.numerical_receipts[0]>).figure_provenance;
 expect(adaptTurn(wire)!.figures.every((figure)=>figure.receiptState==="unavailable")).toBe(true);
});

import count from "./fixtures/investment/legacy-count-actual-wire.json";
it("retains actual legacy COUNT separately from fractional security units",()=>{
 const figure=adaptTurn(count)!.figures[0];
 expect(figure.receiptState).toBe("ready");expect(figure.numerical).toMatchObject({quantity:"count",value:"1",subject:count.figures[0].subject});
 expect(figure.written).toBe("1");expect(adaptTurn(positions)!.figures[0].numerical?.value).toBe("1.25");
});
