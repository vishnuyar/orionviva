import { expect, it } from "vitest";
import annual from "./fixtures/retirement/annual-actual-wire.json";
import rollovers from "./fixtures/retirement/rollovers-actual-wire.json";
import { adaptTurn } from "./conversation";
it.each([annual,rollovers])("retains every genuine retirement figure with exact subject and source pages",(wire)=>{
 const answer=adaptTurn(wire)!;
 expect(answer.figures).toHaveLength(wire.figures.length);
 for(const [index,figure] of answer.figures.entries()){
  expect(figure.receiptState).toBe("ready");
  expect(figure.numerical).toMatchObject({value:wire.figures[index].value,subject:wire.figures[index].subject,boundary:wire.figures[index].boundary});
  expect(Object.keys(figure.numericalReceipts![0].figureProvenance!)).toEqual([figure.id]);
 }
});
it("retains all genuine per-record typed rollover assertions",()=>{
 const answer=adaptTurn(rollovers)!;expect(answer.sourceAssertions).toHaveLength(8);
 for(const [index,receipt] of answer.sourceAssertions!.entries()){
  expect(receipt.recordAssociation).toBe(rollovers.source_assertions[index].record_association);
  expect(receipt.value).toBe(rollovers.source_assertions[index].value);
 }
});
import { numericalFigure } from "./numerical-receipts";
it.each(["empty members","duplicate","unordered","too many","nontext member","control member","set type","extra subject","foreign scope","missing member","year","invalid date","unknown quantity","bad kind","bad grade","bad currency"])("refuses malformed annual %s",(bad)=>{
 const wire=JSON.parse(JSON.stringify(annual));const figure=wire.figures[0];
 if(bad==="empty members")figure.subject.member_ids=[];
 if(bad==="duplicate")figure.subject.member_ids=["acct:plan-b","acct:plan-b"];
 if(bad==="unordered")figure.subject.member_ids.reverse();
 if(bad==="too many")figure.subject.member_ids=["a","b","c","d"];
 if(bad==="nontext member")figure.subject.member_ids=[true];
 if(bad==="control member")figure.subject.member_ids=["a\n"];
 if(bad==="set type")figure.subject.set_type="all_assets";
 if(bad==="extra subject")figure.subject.account_id="invented";
 if(bad==="foreign scope")figure.subject.member_ids=["acct:foreign"];
 if(bad==="missing member")delete figure.subject.member_ids;
 if(bad==="year")figure.boundary.cut[1].to="2025-12-31";
 if(bad==="invalid date")figure.boundary.cut[1].value="2024-02-30";
 if(bad==="unknown quantity")figure.quantity="employee_retirement_contributions";
 if(bad==="bad kind")figure.kind="hypothetical";
 if(bad==="bad grade")figure.grade="";
 if(bad==="bad currency")figure.currency="";
 expect(numericalFigure(figure)).toBeUndefined();
});
it.each(["same endpoints","foreign endpoint","missing endpoint","wrong scope","oversized period","wrong quantity","unknown relationship","extra relationship","conflicting endpoints","foreign pages","missing provenance","unknown context","member context"])("refuses malformed relationship %s",(bad)=>{
 const wire=JSON.parse(JSON.stringify(rollovers));const figure=wire.figures[0];const receipt=wire.numerical_receipts[0];
 if(bad==="same endpoints")figure.subject.destination_account_id=figure.subject.source_account_id;
 if(bad==="foreign endpoint")figure.subject.source_account_id="foreign";
 if(bad==="missing endpoint")delete figure.subject.source_account_id;
 if(bad==="wrong scope")figure.boundary.selected[0].value='["foreign"]';
 if(bad==="oversized period")figure.boundary.cut[1].to="2035-12-31";
 if(bad==="wrong quantity")figure.quantity="security_units";
 if(bad==="unknown relationship")figure.subject.relationship_id="retirement-rollover:"+"a".repeat(64);
 if(bad==="extra relationship")figure.subject.unreviewed=true;
 if(bad==="conflicting endpoints"){figure.subject.source_account_id="acct:plan-a";figure.subject.destination_account_id="acct:plan-b";}
 if(bad==="foreign pages")receipt.figure_provenance.f1[0].document_id="a".repeat(64);
 if(bad==="missing provenance")delete receipt.figure_provenance;
 if(bad==="unknown context")receipt.context.push({label:"Invented context",value:"foreign"});
 if(bad==="member context")receipt.context.find((row:{label:string})=>row.label==="Selected retirement plans").value="foreign";
 expect(adaptTurn(wire)!.figures.every((figure)=>figure.receiptState==="unavailable")).toBe(true);
});
it.each(["unknown claim","foreign relationship","foreign endpoint","foreign set","foreign source","missing digest","wrong digest","extra field","bad type","missing observation","foreign observation","bad page","duplicate claim","mixed labels"])("refuses corrupted new assertion %s",(bad)=>{
 const wire=JSON.parse(JSON.stringify(rollovers));const item=wire.source_assertions[0];
 if(bad==="unknown claim")item.claim="rollover_guaranteed_tax_free";
 if(bad==="foreign relationship")item.record_association="retirement-rollover:"+"a".repeat(64);
 if(bad==="foreign endpoint")item.source_account_id="acct:plan-a";
 if(bad==="foreign set")item.account="retirement-set:"+"a".repeat(64);
 if(bad==="foreign source")item.anchors[0].document_id="a".repeat(64);
 if(bad==="missing digest")delete item.source_lineage_digest;
 if(bad==="wrong digest")item.source_lineage_digest="a".repeat(64);
 if(bad==="extra field")item.receipt_id="fabricated";
 if(bad==="bad type")item.value_type="literal_text";
 if(bad==="missing observation")item.observation_ids=[];
 if(bad==="foreign observation")item.observation_ids=[wire.source_assertions[1].record_association];
 if(bad==="bad page")item.anchors[0].page=201;
 if(bad==="duplicate claim")wire.source_assertions.push({...item,id:"duplicate"});
 if(bad==="mixed labels")item.association_label="foreign";
 expect(adaptTurn(wire)!.sourceAssertions).toEqual([]);
});
it("keeps each actual association independent of input ordering and saved serialization",()=>{
 const wire=JSON.parse(JSON.stringify(rollovers));wire.figures.reverse();wire.source_assertions.reverse();wire.numerical_receipts[0].figure_ids.reverse();
 const answer=adaptTurn(wire)!;expect(answer.figures.every((figure)=>figure.receiptState==="ready")).toBe(true);expect(answer.sourceAssertions).toHaveLength(8);
 for(const item of answer.sourceAssertions!){const source=rollovers.source_assertions.find((raw)=>raw.id===item.id)!;expect(item.recordAssociation).toBe(source.record_association);expect(item.value).toBe(source.value);expect(item.anchors).toEqual(source.anchors.map((page)=>({documentId:page.document_id,page:page.page})));}
});
it("does not broaden generic figures into account-set scopes",()=>{
 const raw=JSON.parse(JSON.stringify(annual.figures[0]));raw.quantity="balance";raw.subject={account_id:"acct:plan-b"};expect(numericalFigure(raw)).toBeUndefined();
 raw.subject={kind:"account_set",value:"foreign"};expect(numericalFigure(raw)).toBeUndefined();
});
it.each(["receipt_id","effective_date","anchor_id"])("preserves the original instrument %s requirement",(field)=>{
 const legacy={id:"i1",receipt_id:"receipt-1",claim:"deposit_opened",value_type:"date",value:"2024-01-01",written:"Source date",account:"account",effective_date:"2024-01-01",grade:"unverified",anchors:[{document_id:"a".repeat(64),page:1,anchor_id:"a1"}],observation_ids:["observation"]};
 const wire=JSON.parse(JSON.stringify(annual));wire.source_assertions=[legacy];
 if(field==="anchor_id")delete wire.source_assertions[0].anchors[0].anchor_id;else delete wire.source_assertions[0][field];
 expect(adaptTurn(wire)!.sourceAssertions).toEqual([]);
});
