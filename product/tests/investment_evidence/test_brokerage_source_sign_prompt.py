"""Printed cash literals remain distinct from local magnitude interpretation."""
import copy
import json
from decimal import Decimal
import pytest
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.registry import extraction_prompt_for, profile_for
from viva.ingest.prompt_library import resolve
from viva.rebuild import _parse_claim
from viva.normalization_context import ExtractionNormalizationContext, encode_context
from vivacore.verify.normalize import RULES_VERSION
from test_extraction import fixture, legacy


def packet(ordinary='-25.00', typed='-25.00'):
    data=legacy();data['doc_type']='brokerage_statement'
    data['activity']=[dict(date_raw='01/25/2025',kind='buy',amount_raw=ordinary,instrument='TEST-SEC',description='Printed buy',realized_gain_raw='-2.12345678')]
    data['investment_source']=fixture()
    row=data['investment_source']['rows'][0]
    row['amount']['raw']=typed
    row['printed_row_reference']={'raw':'PRINTED-ROW-A','page':1}
    row['reported_realized_gain']={'raw':'-2.12345678','page':1}
    return data


def test_active_request_copies_both_cash_effect_literals_without_sign_inference():
    text,version=extraction_prompt_for('brokerage_statement')
    assert version=='extract:brokerage-base-v7+brokerage-v2'
    assert 'the POSITIVE cash amount AS PRINTED' not in text
    for rule in ('Both activity[].amount_raw and investment_source.rows[].amount.raw',
                 'same settled row', 'If the source prints no sign, preserve that unsigned text',
                 'Do not remove printed minus signs or parentheses',
                 'do not synthesize a negative sign', 'realized gain/loss signs'):
        assert rule in text
    assert profile_for('401k_statement') is profile_for('brokerage_statement')
    assert profile_for('brokerage_statement').profile_version=='brk-v7'


def test_new_request_preserves_entire_row_local_security_and_source_tail():
    old=resolve('brokerage-base-v6');new=resolve('brokerage-base-v7')
    marker='Printed security correspondence is ROW-LOCAL.'
    assert new[new.index(marker):]==old[old.index(marker):]
    assert new[new.index('Provide one source positions entry'):new.index(marker)]==old[old.index('Provide one source positions entry'):old.index(marker)]
    assert 'source\'s dates, quantities, amounts, signs and' in new


@pytest.mark.parametrize('ordinary',['25.00','-25.00'])
@pytest.mark.parametrize('typed',['25.00','-25.00'])
def test_four_historical_sign_combinations_keep_magnitude_and_exact_source(ordinary,typed):
    facts,error=from_brokerage_json(json.dumps(packet(ordinary,typed)),'public-sign','en-US','USD')
    assert error is None
    assert facts.activity[0].amount==Decimal('25.00')
    row=dict(facts.investment_source.rows[0])
    assert row['amount'].raw==typed
    assert row['printed_row_reference'].raw=='PRINTED-ROW-A'
    assert facts.activity[0].realized_gain==Decimal('-2.12345678')
    assert row['reported_realized_gain'].raw=='-2.12345678'


@pytest.mark.parametrize('version',['extract:brokerage-base-v4+brokerage-v2','extract:brokerage-base-v6+brokerage-v2','extract:brokerage-base-v7+brokerage-v2'])
def test_recorded_reconstruction_preserves_context_signs_and_ids(version):
    ctx=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD')
    body={'prompt_version':version,'response_text':json.dumps(packet()),'normalization_context':encode_context(ctx)}
    facts,error,restored=_parse_claim('brokerage_statement',body,'public-sign','de-DE','EUR',page_count=1)
    assert error is None and restored==ctx
    assert facts.currency=='USD' and facts.activity[0].amount==Decimal('25.00')
    assert dict(facts.investment_source.rows[0])['amount'].raw=='-25.00'
    assert dict(facts.investment_source.rows[0])['printed_row_reference'].raw=='PRINTED-ROW-A'


def test_unsigned_precision_duplicate_order_and_unreadable_source_are_not_rewritten():
    data=packet('25.00000001','25.00000001')
    data['activity']*=2;data['investment_source']['rows']*=2
    facts,error=from_brokerage_json(json.dumps(data),'public-sign','en-US','USD')
    assert error is None and len(facts.activity)==2
    assert [dict(r)['amount'].raw for r in facts.investment_source.rows]==['25.00000001']*2
    assert facts.activity[0].amount==Decimal('25.00000001')
    data['investment_source']['rows'][0]=copy.deepcopy(data['investment_source']['rows'][0])
    data['investment_source']['rows'][0]['amount']={'raw':'unreadable','page':None}
    facts,error=from_brokerage_json(json.dumps(data),'public-sign','en-US','USD')
    assert error is None and dict(facts.investment_source.rows[0])['amount'].raw=='unreadable'
    assert dict(facts.investment_source.rows[0])['amount'].page is None
    data.pop('investment_source')
    facts,error=from_brokerage_json(json.dumps(data),'public-sign','en-US','USD')
    assert error is None and facts.investment_source is None


@pytest.mark.parametrize('version',['extract:brokerage-base-v6+brokerage-v2','extract:brokerage-base-v7+brokerage-v2'])
@pytest.mark.parametrize('ordinary',['25.00','-25.00'])
def test_normal_saved_read_rebuild_keeps_recorded_context_and_source_signs(tmp_path,monkeypatch,version,ordinary):
    from contextlib import closing
    from viva.vault import Vault
    from viva.ingest.pipeline import capture_and_ingest,ReadResult
    from viva import rebuild
    from test_rebuild_context import pdf
    data=packet(ordinary,'-25.00');text=json.dumps(data)
    ctx=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD')
    def saved_reader(_data,doc):
        facts,error=from_brokerage_json(text,doc,'en-US','USD')
        assert error is None
        return ReadResult('brokerage_statement',1,facts,raw_text=text,model='public-route',prompt_version=version,normalization_context=ctx)
    with closing(Vault.open(tmp_path/'source','synthetic-rebuild-passphrase')) as source:
        capture_and_ingest(source.raw,source.ledger,pdf(data),saved_reader)
        original=[e for e in source.ledger.events() if e.event_type=='ReadRecorded']
        assert len(original)==1 and original[0].body['normalization_context']==encode_context(ctx)
    seen=[];parse=rebuild._parse_claim
    def tracked(*args,**kwargs):
        result=parse(*args,**kwargs);seen.append(result);return result
    monkeypatch.setattr(rebuild,'_parse_claim',tracked)
    rebuild.rebuild(tmp_path/'source',tmp_path/'destination','synthetic-rebuild-passphrase',locale='de-DE',currency='EUR',by_date=False,log=lambda *a:None)
    assert seen and all(error is None for _,error,_ in seen)
    facts=seen[0][0]
    assert facts.currency=='USD' and facts.activity[0].amount==Decimal('25.00')
    assert dict(facts.investment_source.rows[0])['amount'].raw=='-25.00'
    with closing(Vault.open(tmp_path/'destination','synthetic-rebuild-passphrase')) as destination:
        rows=[e for e in destination.ledger.events() if e.event_type=='ReadRecorded']
        assert len(rows)==1 and rows[0].body['prompt_version']==version
        assert rows[0].body['normalization_context']==encode_context(ctx)
        assert rows[0].body['response_text']==text and rows[0].body['input_mode']==original[0].body['input_mode']
