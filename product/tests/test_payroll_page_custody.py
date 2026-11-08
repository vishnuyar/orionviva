"""Payroll page counts come from the renderer, including acknowledged resumes."""
import json
from types import SimpleNamespace
from test_cash_source_page_provenance import payroll_facts
from test_bulk_upload import setup_bulk, spec
from vivacore.models.base import ModelResult,PageImage
from viva.ingest import reader


def packet():
    return {'doc_type':'pay_stub','doc_type_confidence':0.98,'employer':'Synthetic employer','currency':'USD',
        'pay_date_raw':'2025-01-31','period_start_raw':'2025-01-01','period_end_raw':'2025-01-31',
        'gross_raw':'100.00','net_raw':'80.00','deductions':[{'label':'Synthetic withholding','amount_raw':'20.00','category':'tax'}],
        'payroll_source':payroll_facts().payroll_source.to_dict(),'validated_source_page_count':199}


def pages():
    return (PageImage(1,b'synthetic-page-one','synthetic-one'),PageImage(2,b'synthetic-page-two','synthetic-two'))


def test_real_reader_assigns_rendered_count_after_source_validation(monkeypatch):
    calls=[]
    class Adapter:
        def extract(self,*args):
            calls.append(args)
            reply={'doc_type':'pay_stub','doc_type_confidence':0.98} if len(calls)==1 else packet()
            return ModelResult(json.dumps(reply),'synthetic-model',0,0,0,0,{}, {'usage':{'input_tokens':0,'output_tokens':0}})
    monkeypatch.setattr(reader,'_render_and_read_text',lambda data:(pages(),'synthetic text'))
    monkeypatch.setattr(reader,'adapter_for',lambda selected:Adapter())
    result=reader.read_statement(b'synthetic-render-fixture','d'*64,SimpleNamespace(model='synthetic-only',json_mode=True),'en-US','USD')
    assert result.facts is not None,result.error
    assert len(calls)==2 and result.facts.validated_source_page_count==2


def test_acknowledged_payroll_resume_keeps_renderer_bound_without_new_request(setup_bulk,monkeypatch):
    from vivacore.models import OpenAICompatAdapter
    from test_extraction_responses import wire
    from viva.desktop_bridge.bulk_documents import BulkDocuments
    from viva.desktop_bridge.import_checkpoints import ImportCheckpoints
    from viva.desktop_bridge.jobs import JobRegistry
    sample=setup_bulk;calls=[]
    def build():
        def unused(*args):raise AssertionError('unexpected ordinary extraction')
        unused.prepare=lambda data,checkpoint=None:(pages(),'synthetic text')
        unused.read_prepared=lambda images,text,doc_id,**kw:reader.read_prepared_statement(images,text,doc_id,spec(),'en-US','USD',**kw)
        return unused,True
    monkeypatch.setattr(reader,'build_reader',build)
    monkeypatch.setattr(reader,'adapter_for',lambda selected:OpenAICompatAdapter(spec()))
    def transport(self,body,headers):
        calls.append(body)
        return wire('openai-compatible',json.dumps({'doc_type':'pay_stub','doc_type_confidence':0.98} if len(calls)==1 else packet()))
    monkeypatch.setattr(OpenAICompatAdapter,'_post',transport)
    complete=ImportCheckpoints.complete
    def interrupted(*args):raise RuntimeError('synthetic interruption after acknowledged extraction')
    monkeypatch.setattr(ImportCheckpoints,'complete',interrupted)
    first=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    assert first['rows'][0]['reason']=='outcome_unknown'
    assert len(calls)==2
    monkeypatch.setattr(ImportCheckpoints,'complete',complete)
    monkeypatch.setattr(reader,'_render_and_read_text',lambda data:(pages(),'synthetic text'))
    def forbidden(*args):raise AssertionError('acknowledged extraction must not be requested again')
    monkeypatch.setattr(reader,'adapter_for',forbidden)
    resume=ImportCheckpoints.resume;counts=[]
    def observed(self,owner,body):
        result=resume(self,owner,body);counts.append(result.facts.validated_source_page_count);return result
    monkeypatch.setattr(ImportCheckpoints,'resume',observed)
    second=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    assert counts==[2],second
    assert len(calls)==2
    assert second['rows'][0].get('action')=='awaiting',second


def _population_read():
    from viva.ingest.paystub import from_paystub_json
    from viva.ledger.events import read_recorded
    raw = packet()
    # This descriptor in a model response must never become render authority.
    facts, error = from_paystub_json(json.dumps(raw), 'c' * 64, 'en-US', 'USD')
    assert error is None and facts.validated_source_page_count is None
    event = read_recorded(facts.doc_id, 'synthetic-only', 'synthetic-v1', 'text',
                          json.dumps(raw), 0, 0, 0, True, None, '2025-01-31')
    return facts, event


def test_population_reparse_preserves_backend_page_descriptor_without_requiring_raw_copy():
    from dataclasses import replace
    from viva.retirement_funding.population import source_from_facts
    facts, event = _population_read()
    for count in (2, 3):
        trusted = replace(facts, validated_source_page_count=count)
        before = trusted.to_dict()
        source = source_from_facts(trusted, (event,))
        assert source.reading_id == event.event_id
        assert trusted.to_dict() == before
        assert trusted.validated_source_page_count == count
        assert source.source.gross.value == '100.00'


def test_population_reparse_still_rejects_financial_period_and_page_tampering():
    from dataclasses import replace
    from decimal import Decimal
    import pytest
    from viva.investment.contracts import EvidenceError
    from viva.retirement_funding.population import source_from_facts
    facts, event = _population_read()
    for changes in ({'gross': Decimal('101.00')}, {'net': Decimal('79.00')},
                    {'period_start': '2025-01-02'}, {'period_end': '2025-01-30'},
                    {'gross_page': 1}, {'net_page': 1},
                    {'payroll_source': None}):
        changed = replace(facts, validated_source_page_count=2, **changes)
        with pytest.raises(EvidenceError, match='authenticated payroll reading unavailable'):
            source_from_facts(changed, (event,))
