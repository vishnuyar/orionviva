"""A printed restriction disclosure is copied, never inferred or shortened."""
import copy
import json
import pytest
from viva.ingest.registry import extraction_prompt_for,profile_for,doc_type_for_prompt_version
from viva.ingest.prompt_library import resolve
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_read import validate_sources
from viva.ingest import instrument_contracts as c
from viva.normalization_context import ExtractionNormalizationContext,encode_context
from viva.rebuild import _parse_claim
from viva.instrument_claims import CLAIMS
from vivacore.verify.normalize import RULES_VERSION
from test_instrument_contracts import deposit_json,printed

FULL=('Principal and credited interest remain restricted in this term-deposit '
      'account until the sourced maturity redemption transfers them to SAVE-A.')
TOKEN='restricted_until_redemption'


def payload(text=FULL):
    data=deposit_json();data['terms']={'principal':printed('1000'),'opened':printed('2021-01-01'),'maturity':printed('2022-01-01'),'withdrawal_restriction':printed(text) if text is not None else None}
    return data


def test_active_request_prefers_complete_printed_disclosure_and_keeps_source_limits():
    text,version=extraction_prompt_for('term_deposit_statement')
    assert version=='extract:term-deposit-base-v1+term-deposit-v2'
    assert profile_for('term_deposit_statement').profile_version=='term-deposit-v2'
    for rule in ('complete printed withdrawal restriction/disclosure wording',
                 'rather than the short status/code','If only a restriction token is printed',
                 'genuinely competing full clauses','null/omission','Do not summarize',
                 'no independent restriction enum field','never shorten'):
        assert rule in text
    assert profile_for('refinance_settlement').profile_version=='instrument-v1'
    assert profile_for('property_tax_receipt').profile_version=='instrument-v1'


def test_other_fragment_guidance_and_base_schema_remain_unchanged():
    old=resolve('term-deposit-v1');new=resolve('term-deposit-v2')
    assert new.split('- Copy withdrawal restriction',1)[0]==old.split('- Copy withdrawal restriction',1)[0]
    assert new[new.index('- simple_nominal,'):]==old[old.index('- simple_nominal,'):]
    assert '"withdrawal_restriction"' in resolve('term-deposit-base-v1')
    assert 'restriction_status' not in resolve('term-deposit-base-v1')


@pytest.mark.parametrize('version',['extract:term-deposit-base-v1+term-deposit-v1','extract:term-deposit-base-v1+term-deposit-v2'])
@pytest.mark.parametrize('text',[FULL,TOKEN,None,'unreadable',FULL.replace('SAVE-A','SAVE-B'),'x'*300])
def test_recorded_literal_reconstruction_never_expands_or_truncates(version,text):
    ctx=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD')
    body={'prompt_version':version,'response_text':json.dumps(payload(text)),'normalization_context':encode_context(ctx)}
    facts,error,restored=_parse_claim('term_deposit_statement',body,'public-deposit','de-DE','EUR',page_count=1)
    assert error is None and restored==ctx
    value=facts.payload.terms.withdrawal_restriction
    assert (value.value if value else None)==text
    if value:assert value.source==c.Source('public-deposit',1)
    assert doc_type_for_prompt_version(version)=='term_deposit_statement'
    assert len(FULL)==142 and len(TOKEN)==27 and FULL!=TOKEN


def test_missing_ambiguous_optional_source_and_foreign_page_do_not_acquire_authority():
    data=payload(None)
    facts=parse_instrument_json(json.dumps(data),'term_deposit_statement','public-deposit')
    assert facts.terms.withdrawal_restriction is None
    del data['terms']['withdrawal_restriction']
    assert parse_instrument_json(json.dumps(data),'term_deposit_statement','public-deposit').terms.withdrawal_restriction is None
    data=payload();del data['terms']['withdrawal_restriction']['page']
    with pytest.raises(c.ContractError):parse_instrument_json(json.dumps(data),'term_deposit_statement','public-deposit')
    data=payload();data['terms']['withdrawal_restriction']['page']=2
    facts=parse_instrument_json(json.dumps(data),'term_deposit_statement','public-deposit')
    with pytest.raises(c.ContractError):validate_sources(facts,'public-deposit',1)


def test_oversize_disclosure_is_retained_beyond_downstream_assertion_bound():
    text='x'*300
    facts=parse_instrument_json(json.dumps(payload(text)),'term_deposit_statement','public-deposit')
    assert facts.terms.withdrawal_restriction.value==text
    assert len(text.encode())>CLAIMS['deposit_withdrawal_restriction'].max_bytes
    from viva.read_store.instrument_authority_contracts import AuthorityAssertion
    with pytest.raises(ValueError,match='source literal exceeds bound'):
        AuthorityAssertion('public-assertion','deposit_withdrawal_restriction',text,
            'public-account','2021-01-31',('public-anchor',),('public-observation',),(), 'verified')


@pytest.mark.parametrize('version',['extract:term-deposit-base-v1+term-deposit-v1','extract:term-deposit-base-v1+term-deposit-v2'])
@pytest.mark.parametrize('literal',[FULL,TOKEN])
def test_normal_saved_read_rebuild_preserves_old_and_new_literal_proposals(tmp_path,monkeypatch,version,literal):
    from contextlib import closing
    from viva.vault import Vault
    from viva.ingest.pipeline import capture_and_ingest,ReadResult
    from viva.ingest.instrument_read import parser_for
    from viva import rebuild
    from test_rebuild_context import pdf
    data=payload(literal);text=json.dumps(data)
    ctx=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD')
    def saved_reader(_data,doc):
        facts,error=parser_for('term_deposit_statement')(text,doc,'en-US','USD')
        assert error is None
        return ReadResult('term_deposit_statement',1,facts,raw_text=text,model='public-route',prompt_version=version,normalization_context=ctx)
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
    assert all(f.payload.terms.withdrawal_restriction.value==literal for f,_,_ in seen)
    with closing(Vault.open(tmp_path/'destination','synthetic-rebuild-passphrase')) as destination:
        rows=[e for e in destination.ledger.events() if e.event_type=='ReadRecorded']
        assert len(rows)==1 and rows[0].body['prompt_version']==version
        assert rows[0].body['normalization_context']==encode_context(ctx)
        assert rows[0].body['response_text']==text and rows[0].body['input_mode']==original[0].body['input_mode']
