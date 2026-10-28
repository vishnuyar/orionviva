import json
from pathlib import Path
from test_instrument_c_continuation import opened,actions,allocation_step,source
from test_instrument_projector_b import ingest,mortgage
from test_instrument_contracts import deposit_json,printed
from viva.ledger.instruments import reference_accounts

def test_actual_compiled_dedicated_quantities_and_positive_points_wire(opened):
    deposit=deposit_json();deposit["terms"]={"principal":printed("1000"),"opened":printed("2021-01-01"),"maturity":printed("2022-01-01"),"rate":printed("5.25"),"rate_basis":"simple_nominal","rate_basis_source":{"page":1},"day_count":"actual_365","day_count_source":{"page":1},"compounding":printed("No compounding"),"withdrawal_restriction":printed("Restricted until maturity")}
    ingest(opened.raw,opened.ledger,"deposit-wire-source",deposit,"term_deposit_statement")
    loan=mortgage();loan["terms"]={"original_principal":printed("630000"),"originated":printed("2021-01-01"),"note_rate":printed("5.25"),"fixed_rate":True,"fixed_rate_source":{"page":1},"note_rate_basis":"simple_nominal","note_rate_basis_source":{"page":1}}
    ingest(opened.raw,opened.ledger,"loan-wire-source",loan,"mortgage_statement")
    accounts=[reference_accounts(opened.ledger.projection(),ref)[0] for ref in ("CD-A","LOAN-A")]
    def terms(account,claims):return ("instrument_terms",{"account_phrase":account,"as_of":"2021-01-31"},{"account_phrase":source(account,"catalog_selection"),"as_of":source("2021-01-31")},claims)
    target=("instrument_allocation_target",{"exposure":"bond","target_percent":"50"},{"exposure":source("bond"),"target_percent":source("my 50% target")},["actual_allocation","user_target","percentage_point_difference"])
    bridge=actions(opened,[terms(accounts[0],["deposit_contract_principal","deposit_nominal_rate"]),terms(accounts[1],["loan_original_principal","loan_note_rate"]),allocation_step(),target])
    answers=[]
    for account in accounts:answers.append(bridge.ask({"question":f"Give {account} terms as of 2021-01-31","context_mode":"new_question"}))
    base=bridge.ask({"question":"Show PLAN exposure allocation as of 2025-12-31","context_mode":"new_question"});assert base["kind"]=="completed"
    answers.append(bridge.ask({"question":"How far is my bond allocation from my 50% target?","context_mode":"follow_up"}))
    assert all(answer["kind"]=="completed" for answer in answers),answers
    quantities={f["quantity"] for answer in answers for f in answer["state"]["figures"]}
    assert {"deposit_contract_principal","loan_original_principal","instrument_rate","allocation_percentage_points"}<=quantities
    assert next(f for f in answers[-1]["state"]["figures"] if f["quantity"]=="allocation_percentage_points")["value"]=="+10"
    assert all(answer["state"]["numerical_receipts"] for answer in answers)
    Path("/private/tmp/instrument-c-dedicated-numeric-responses.json").write_text(json.dumps(answers,indent=2)+"\n")


def test_actual_monthly_tax_zero_receipt_explains_accepted_empty_event_set(opened):
    from test_instrument_authority_views import two_accepted_months
    two_accepted_months(opened.raw,opened.ledger)
    account=reference_accounts(opened.ledger.projection(),"LOAN-A")[0]
    step=("instrument_monthly_payment_escrow",{"account_phrase":account,"from":"2021-01-01","to":"2021-02-28"},
        {"account_phrase":source(account,"catalog_selection"),"from":source("2021-01-01"),"to":source("2021-02-28")},["tax_paid"])
    answer=actions(opened,[step]).ask({"question":f"Give monthly property tax disbursements for {account} from 2021-01-01 to 2021-02-28.","context_mode":"new_question"})
    assert answer["kind"]=="completed",answer
    taxes=answer["state"]["figures"];assert {f["value"] for f in taxes}=={"100","0"}
    zeros=[f for f in taxes if f["value"]=="0"]
    assert len(zeros)==1
    contexts=[item for receipt in answer["state"]["numerical_receipts"] for item in receipt["context"]]
    assert [c["value"] for c in contexts if c["label"]=="Tax absence rule"]==["For 2021-02-01 through 2021-02-28, sum of the complete accepted tax event set (no events)."]
    assert zeros[0]["record_ids"] and zeros[0]["grade"]
    Path("/private/tmp/instrument-c-tax-zero-actual-response.json").write_text(json.dumps(answer,indent=2)+"\n")
