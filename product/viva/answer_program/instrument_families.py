"""Closed instrument read families and deterministic claim-preserving lowering."""
from ..instrument_claims import CLAIMS,CLAIM_RELATIONSHIPS

VIEW_CLAIMS={
 "terms":tuple(c for c in CLAIMS if c.startswith(("deposit_","loan_","disclosure_apr_")) and c not in {"deposit_opening_balance","deposit_closing_balance","deposit_credited_interest","deposit_funding","deposit_redemption"})+("availability_restriction",),
 "period_components":("deposit_opening_balance","deposit_closing_balance","deposit_credited_interest","deposit_funding","deposit_redemption","loan_opening_principal","loan_closing_principal","principal_repayment","principal_payoff","payment_total","payment_interest","payment_fees","payment_net_unallocated","escrow_funding","escrow_opening_balance","escrow_closing_balance","tax_paid"),
 "maturities":("deposit_maturity","deposit_contract_principal","deposit_closing_balance","deposit_redemption","redemption_date","redemption_reference","availability_restriction"),
 "refinances":tuple(c for c in CLAIMS if c.startswith("refinance_"))+("settlement_date","settlement_reference"),
 "tax_payments":("tax_paid","tax_payment_date","tax_payment_reference","property_identity"),
 "allocation":tuple(c for c in CLAIMS if c.startswith("allocation_") and c!="allocation_percentage_points"),
}

FIXED_COMPONENT_FAMILIES={
 "instrument_monthly_loan_principal":("loan_principal","month",("loan_opening_principal","loan_closing_principal","principal_repayment","principal_payoff")),
 "instrument_monthly_payment_escrow":("payment_escrow","month",("payment_total","payment_interest","payment_fees","payment_net_unallocated","escrow_funding","escrow_opening_balance","escrow_closing_balance","tax_paid")),
 "instrument_annual_summary":("annual_summary","year",VIEW_CLAIMS["period_components"]),
 "instrument_deposit_annual_components":("deposit","year",("deposit_credited_interest","deposit_funding","deposit_redemption","deposit_opening_balance","deposit_closing_balance")),
 "instrument_deposit_transactions":("deposit","none",("deposit_credited_interest","deposit_funding","deposit_redemption","deposit_opening_balance","deposit_closing_balance")),
}

def families():
    from .intents import SemanticFamily,_object,_STRING,_DATE
    output={}
    for view,claims in VIEW_CLAIMS.items():
        properties={"account_phrase":_STRING};required=["account_phrase"]
        if view in {"terms","maturities","allocation"}:properties["as_of"]=_DATE;required.append("as_of")
        else:properties.update({"from":_DATE,"to":_DATE});required.extend(("from","to"))
        if view in {"period_components","tax_payments"}:
            properties["grouping"]={"type":"string","enum":["none","year"] if view=="tax_payments" else ["none","month","year"]};required.append("grouping")
        if view=="period_components":properties["component_set"]={"type":"string","enum":["deposit","loan_principal","payment_escrow","annual_summary"]};required.append("component_set")
        if view=="allocation":properties["axis"]={"type":"string","enum":["exposure","vehicle"]};required.append("axis")
        name="instrument_"+view
        output[name]=SemanticFamily(name,_object(properties,required),claims,_build,
            user_label="source-bound instrument "+view.replace("_"," "),
            user_example="read retained "+view.replace("_"," ")+" for one explicitly selected account and date or finite period; preserve each requested field identity")
    for name,(component,group,claims) in FIXED_COMPONENT_FAMILIES.items():
        output[name]=SemanticFamily(name,_object({"account_phrase":_STRING,"from":_DATE,"to":_DATE},("account_phrase","from","to")),claims,_build,
            user_label="source-bound "+name.removeprefix("instrument_").replace("_"," "),
            user_example="read the selected account's "+component.replace("_"," ")+" over explicit inclusive dates with "+group+" grouping; component and grouping are fixed by this family, never typed by the person")
    output["instrument_monthly_loan_payments"]=SemanticFamily("instrument_monthly_loan_payments",_object({"account_phrase":_STRING,"from":_DATE,"to":_DATE},("account_phrase","from","to")),
        ("principal_repayment","payment_total","payment_interest","escrow_funding"),_build_monthly_payments,
        user_label="monthly loan payments with principal, interest and escrow",
        user_example="show monthly mortgage payments, principal repaid, interest and escrow for one selected loan over explicit inclusive dates; account and period are grounded, component and month grouping are code-owned")
    output["instrument_allocation_target"]=SemanticFamily("instrument_allocation_target",_object({
        "exposure":{"type":"string","enum":["bond","equity","cash","other"]},"target_percent":_STRING,
        "account_phrase":_STRING,"as_of":_DATE,"continuation_receipt_id":_STRING},("exposure","target_percent")),
        ("actual_allocation","user_target","percentage_point_difference"),_build_target,
        user_label="compare actual allocation with the current question's stated target",
        user_example="positive allocation-target sentence; target_percent source quote must be the full my/the N% target role; use only an issued continuation ID from current QuestionContext when account/date are omitted")
    return output

def _build(request,manifest,*,source="instrument",offset=0):
    from .intents import _program,_read
    p=request.parameters;view=request.family.removeprefix("instrument_")
    if request.family in FIXED_COMPONENT_FAMILIES:
        component,group,_=FIXED_COMPONENT_FAMILIES[request.family]
        p={**p,"component_set":component,"grouping":group};view="period_components"
    args={"view":view,"account":p["account_phrase"],"currency":p["currency"]}
    for name in ("as_of","from","to","grouping","component_set","axis"):
        if name in p:args[name]=p[name]
    clauses=[];bindings=[]
    for i,claim in enumerate(request.requested_claims):
        contract=CLAIMS[claim];hole="field"+_letters(i+offset)
        period_flow=(view=="period_components" and contract.quantity not in {"balance","owed"}) or (view=="tax_payments" and args.get("grouping")=="year")
        scope=["account"]+(["period"] if period_flow and contract.quantity else [])
        many=view in {"period_components","refinances","tax_payments"}
        slot={"name":hole,"type":"rows" if many else contract.render_type}
        selector={"cardinality":"all" if many else "one","claim":claim,"entity_ref":({"role":CLAIM_RELATIONSHIPS[claim]} if claim in CLAIM_RELATIONSHIPS else {"id":p["account_phrase"]})}
        if contract.quantity:
            if not many:slot.update(quantity=contract.quantity,scope=scope)
            selector.update(quantity=contract.quantity,scope=scope)
        if contract.render_type=="money":selector["currency"]=p["currency"]
        clauses.append({"id":hole,"text":claim.replace("_"," ")+": {"+hole+"}.","slots":[slot]})
        bindings.append({"hole":hole,"source":source,"reference_kind":"read_figures" if many and contract.value_type=="number" else contract.reference_kind,"selector":selector})
    return _program(manifest,request.family,clauses,[_read(source,"read_instrument_details",args)],bindings,required=[clause["id"] for clause,claim in zip(clauses,request.requested_claims) if claim!="payment_fees" or len(request.requested_claims)==1],
        allow_partial='payment_fees' in request.requested_claims and len(request.requested_claims)>1)

def _build_monthly_payments(request,manifest):
    from dataclasses import replace
    from .intents import _program
    clauses=[];nodes=[];bindings=[]
    for family,claims,source in (
        ("instrument_monthly_loan_principal",("principal_repayment",),"principal"),
        ("instrument_monthly_payment_escrow",("payment_total","payment_interest","escrow_funding"),"payments")):
        selected=tuple(claim for claim in request.requested_claims if claim in claims)
        if not selected:continue
        part=_build(replace(request,family=family,requested_claims=selected),manifest,source=source,offset=len(clauses)).to_dict()
        clauses.extend(part["shape"]["clauses"]);nodes.extend(part["nodes"]);bindings.extend(part["bindings"])
    return _program(manifest,request.family,clauses,nodes,bindings,required=[clause["id"] for clause in clauses])

def _letters(n):
    out=""
    while True:
        out=chr(97+n%26)+out;n=n//26-1
        if n<0:return out

def _build_target(request,manifest):
    from .intents import _program,_read
    p=request.parameters;account=p["account_phrase"];actual="allocation_exposure_"+p["exposure"]+"_weight"
    args={"view":"allocation","account":account,"currency":p["currency"],"as_of":p["as_of"],"axis":"exposure","target_premise_ref":p["target_premise_ref"]}
    clauses=[{"id":"comparison","text":"The actual allocation is {actual}; compared with your stated target of {target}, the difference is {difference}.","slots":[
        {"name":"actual","type":"rate","quantity":"ratio_of_balance","scope":["account"]},
        {"name":"target","type":"supposed","quantity":"ratio"},
        {"name":"difference","type":"percentage_points","quantity":"allocation_percentage_points","scope":["account"]}]}]
    bindings=[]
    for hole,claim,qty,kind in (("actual",actual,"ratio_of_balance","figure"),("target","allocation_target","ratio","allocation_target"),("difference","allocation_percentage_points","allocation_percentage_points","figure")):
        selector={"cardinality":"one","claim":claim,"quantity":qty,"entity_ref":{"id":account}}
        if hole!="target":selector["scope"]=["account"]
        bindings.append({"hole":hole,"source":"instrument","reference_kind":kind,"selector":selector})
    return _program(manifest,request.family,clauses,[_read("instrument","read_instrument_details",args)],bindings,required=["comparison"])


def samples():
    output={}
    for view in VIEW_CLAIMS:
        params={"account_phrase":"account-held"}
        if view in {"terms","maturities","allocation"}:params["as_of"]="2000-01-31"
        else:params.update({"from":"2000-01-01","to":"2000-01-31"})
        if view in {"period_components","tax_payments"}:params["grouping"]="none"
        if view=="period_components":params["component_set"]="deposit"
        if view=="allocation":params["axis"]="exposure"
        output["instrument_"+view]=params
    for name in FIXED_COMPONENT_FAMILIES:
        output[name]={"account_phrase":"account-held","from":"2000-01-01","to":"2000-01-31"}
    output["instrument_monthly_loan_payments"]={"account_phrase":"account-held","from":"2000-01-01","to":"2000-01-31"}
    # Static admission lowering probe only. This is not a runtime premise seal.
    output["instrument_allocation_target"]={"account_phrase":"account-held","currency":"USD","as_of":"2000-01-31","exposure":"bond","target_premise_ref":"admission-static-unissued-premise"}
    return output
