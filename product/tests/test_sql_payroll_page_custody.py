"""Ordinary SQL payroll uses physical PDF extent and captured parser context."""
from decimal import Decimal
import hashlib,json,secrets
from io import BytesIO
from reportlab.pdfgen.canvas import Canvas
import pytest
from viva.ingest.paystub import from_paystub_json
from viva.ingest.pipeline_models import ReadResult
from viva.normalization_context import ExtractionNormalizationContext
from viva.sql_authority import SQLAuthority
from vivacore.verify.normalize import RULES_VERSION
from test_payroll_page_custody import packet
from test_sql_authority_bank import ingest

pytestmark=pytest.mark.production_kdf

def pdf_bytes(count=2):
    output=BytesIO();pdf=Canvas(output,pagesize=(612,792),pageCompression=0)
    for index in range(count):
        pdf.drawString(72,720,'Synthetic payroll source: USD gross 100.00 net 80.00 withholding 20.00')
        pdf.showPage()
    pdf.save();return output.getvalue()

def payroll_read(data,raw=None,*,count=2,context=True):
    raw=packet() if raw is None else raw
    text=json.dumps(raw);doc=hashlib.sha256(data).hexdigest()
    facts,error=from_paystub_json(text,doc,'en-US','USD')
    assert error is None,error
    assert facts.validated_source_page_count is None
    from viva.retirement_funding.payroll_v2 import invalidate_period_pages
    from viva.investment.payroll_extraction import validate_pages
    facts=invalidate_period_pages(facts,count);validate_pages(facts.payroll_source,count)
    facts.validated_source_page_count=count
    descriptor=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD') if context else None
    return ReadResult('pay_stub',0.98,facts=facts,raw_text=text,source_locale='en-US',normalization_context=descriptor)

def deposit(store):
    bank=ingest(store,b'synthetic payroll custody deposit',opening='0',closing='80',movement='80',
        start='2025-01-31',end='2025-01-31',number='45123456',institution='Synthetic issuer',currency='USD')
    assert bank.status=='accepted'
    return bank

def test_ordinary_sql_accepts_physically_bound_payroll_and_reopens(tmp_path):
    data=pdf_bytes();reading=payroll_read(data);doc=reading.facts.doc_id;secret=secrets.token_urlsafe(48)
    root=tmp_path.resolve()/'authority'
    with SQLAuthority.create(root,secret,verification='complete') as store:
        bank=deposit(store);before=store.transactions(bank.account_id)
        result=store.ingest(data,lambda original,identity:reading,contract='synthetic-physical-payroll-v1')
        assert result.status=='accepted',result
        assert store.receipt(doc)['raw_reading']['normalization_context']['instrument_source_contract'] is None
        legs=store.payroll_postings(doc)
        assert [(p['account'],Decimal(p['amount']))for p in legs]==[('Income:Salary',Decimal('-100')),('Income:Uncategorized',Decimal('80')),('Expenses:Tax',Decimal('20'))]
        assert [p['provenance']['page']for p in legs]==[2,2,2]
        assert store.transactions(bank.account_id)==before
        assert store.verify()['verified']
        assert store.resume(doc).status=='accepted'
    with SQLAuthority.open(root,secret,verification='complete') as store:
        assert store.payroll_postings(doc)==legs
        assert store.verify()['verified']


def source_packet(page=2,version=1,period_page=None):
    raw=packet()
    source=raw['payroll_source']
    for record in [source['headers'],*source['deductions']]:
        for value in record.values():
            if type(value) is dict and 'page' in value:value['page']=page
    raw['gross_page']=page;raw['net_page']=page
    if version==2:
        source['schema']='payroll-source-v2'
        for name in ('period_start','period_end'):
            source['headers'][name]={'raw':raw[name+'_raw'],'page':page if period_page is None else period_page}
    return raw


@pytest.mark.parametrize('application',[False,True])
@pytest.mark.parametrize('pages,version',[(1,1),(2,1),(1,2),(2,2)])
def test_real_pdf_v1_v2_counts_and_source_citations(tmp_path,pages,version,application):
    data=pdf_bytes(pages);reading=payroll_read(data,source_packet(pages,version),count=pages)
    with SQLAuthority.create(tmp_path.resolve()/'authority',secrets.token_urlsafe(48),verification='complete',application=application) as store:
        bank=deposit(store);before=store.transactions(bank.account_id)
        result=store.ingest(data,lambda *_:reading,contract='synthetic-payroll-page-contract')
        assert result.status=='accepted',result
        assert store.payroll_facts(result.doc_id)==reading.facts.to_dict()
        assert [p['provenance']['page']for p in store.payroll_postings(result.doc_id)]==[pages]*3
        assert store.transactions(bank.account_id)==before and store.account(bank.account_id)['running_balance']=='80'
        assert store.verify()['verified']


def test_invalid_v2_period_anchors_remain_absent_without_losing_money(tmp_path):
    from viva.retirement_funding.payroll_v2 import periods
    data=pdf_bytes();raw=source_packet(2,2,period_page=3);reading=payroll_read(data,raw)
    assert dict(reading.facts.payroll_source.headers)['period_start'] is None
    assert dict(reading.facts.payroll_source.headers)['period_end'] is None
    assert all(field.status!='accepted' for field in periods(reading.facts))
    with SQLAuthority.create(tmp_path.resolve()/'authority',secrets.token_urlsafe(48),verification='complete') as store:
        deposit(store);result=store.ingest(data,lambda *_:reading,contract='synthetic-invalid-period-anchor')
        assert result.status=='accepted',result
        retained=store.payroll_facts(result.doc_id)
        assert retained['payroll_source']['headers']['period_start'] is None
        assert json.loads(store.receipt(result.doc_id)['raw_reading']['raw_text'])['payroll_source']['headers']['period_start']['page']==3
        assert all(p['provenance']['page']==2 for p in store.payroll_postings(result.doc_id))
        assert store.verify()['verified']


@pytest.mark.parametrize('fault',[
    'count-mismatch','boolean-count','missing-context','locale-context','currency-context',
    'rules-context','unknown-context-field','missing-raw','gross-page','net-page','typed-header-page',
    'typed-deduction-page','raw-money-disagreement','raw-employer-disagreement','non-pdf','over-page-bound',
])
def test_physically_unbound_payroll_never_books_money(tmp_path,fault):
    from copy import deepcopy
    data=b'synthetic non-PDF payroll input' if fault=='non-pdf' else pdf_bytes(201 if fault=='over-page-bound' else 2)
    reading=payroll_read(data,source_packet())
    if fault=='count-mismatch':reading.facts.validated_source_page_count=3
    elif fault=='boolean-count':reading.facts.validated_source_page_count=True
    elif fault=='missing-context':reading.normalization_context=None
    elif fault=='locale-context':reading.normalization_context=ExtractionNormalizationContext(1,RULES_VERSION,'fr-FR','USD')
    elif fault=='currency-context':reading.normalization_context=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','EUR')
    elif fault in ('rules-context','unknown-context-field'):
        from viva.normalization_context import encode_context
        reading.normalization_context=encode_context(reading.normalization_context)
        if fault=='rules-context':reading.normalization_context['normalization_rules_version']='synthetic-unrecognized-rules'
        else:reading.normalization_context['unexpected_backend_field']=True
    elif fault=='missing-raw':reading.raw_text=''
    elif fault in ('gross-page','net-page','typed-header-page','typed-deduction-page'):
        raw=json.loads(reading.raw_text)
        if fault in ('gross-page','net-page'):raw[fault.replace('-','_')]=3
        elif fault=='typed-header-page':raw['payroll_source']['headers']['gross']['page']=3
        else:raw['payroll_source']['deductions'][0]['amount']['page']=3
        reading.raw_text=json.dumps(raw)
        reading.facts,error=from_paystub_json(reading.raw_text,hashlib.sha256(data).hexdigest(),'en-US','USD')
        assert error is None,error
        reading.facts.validated_source_page_count=2
    elif fault=='raw-money-disagreement':
        from dataclasses import replace
        from vivacore.verify.arithmetic import check_paystub_identity
        reading.facts.gross=Decimal('101')
        reading.facts.deductions[0]=replace(reading.facts.deductions[0],amount=Decimal('21'))
        assert check_paystub_identity(reading.facts.gross,[d.amount for d in reading.facts.deductions],reading.facts.net).passed
    elif fault=='raw-employer-disagreement':reading.facts.employer='Synthetic different employer'
    with SQLAuthority.create(tmp_path.resolve()/'authority',secrets.token_urlsafe(48),verification='complete') as store:
        bank=deposit(store);before=store.transactions(bank.account_id)
        result=store.ingest(data,lambda *_:reading,contract='synthetic-physical-payroll-negative')
        assert result.status=='pending',result
        assert store.payroll_postings(result.doc_id)==[]
        assert store.transactions(bank.account_id)==before and store.account(bank.account_id)['running_balance']=='80'
        assert store.verify()['verified']


@pytest.mark.parametrize('fault',['count','context','citation'])
def test_independent_auditor_rejects_consistently_written_page_or_context_faults(tmp_path,monkeypatch,fault):
    from viva.sql_authority import IntegrityError,reading as reading_module,payroll_source_custody as custody
    data=pdf_bytes();reading=payroll_read(data,source_packet());physical=[]
    if fault=='count':reading.facts.validated_source_page_count=3
    if fault=='context':reading.normalization_context=ExtractionNormalizationContext(1,RULES_VERSION,'en-US','EUR')
    actual_count=custody._physical_page_count
    def observed(store,doc):
        count=actual_count(store,doc);physical.append(count);return count
    monkeypatch.setattr(custody,'_physical_page_count',observed)
    with SQLAuthority.create(tmp_path.resolve()/'authority',secrets.token_urlsafe(48),verification='complete') as store:
        deposit(store);interpret=reading_module.interpret;put=store._put
        def dishonest_interpret(owner,receipt):
            with monkeypatch.context() as writer_only:
                if fault=='count':writer_only.setattr(custody,'_physical_page_count',lambda owner,doc:(observed(owner,doc),3)[1])
                if fault=='context':writer_only.setattr(custody,'_parser_context',lambda *_:ExtractionNormalizationContext(1,RULES_VERSION,'en-US','USD'))
                return interpret(owner,receipt)
        def dishonest_put(table,row):
            if fault=='citation' and table=='payroll_legs':row=dict(row,page=3)
            return put(table,row)
        monkeypatch.setattr(reading_module,'interpret',dishonest_interpret)
        monkeypatch.setattr(store,'_put',dishonest_put)
        with pytest.raises(IntegrityError,match='payroll semantic mismatch'):
            store.ingest(data,lambda *_:reading,contract='synthetic-known-key-page-control')
        assert len(physical)>=2 and set(physical)=={2}


def test_physical_original_is_reauthenticated_after_an_earlier_call():
    from viva.sql_authority.payroll_source_custody import _physical_page_count
    data=pdf_bytes();doc=hashlib.sha256(data).hexdigest()
    class Original:
        value=data
        def _original_with_commitment(self,identity):
            assert identity==doc
            return self.value,'synthetic-authenticated-commitment'
    owner=Original();assert _physical_page_count(owner,doc)==2
    owner.value=pdf_bytes(1)
    with pytest.raises(ValueError,match='authenticated address'):_physical_page_count(owner,doc)


@pytest.mark.parametrize('extent',[0,201])
def test_out_of_range_native_extent_is_closed_and_refused(monkeypatch,extent):
    from viva.sql_authority.payroll_source_custody import _physical_page_count
    import pypdfium2 as pdfium
    data=pdf_bytes();doc=hashlib.sha256(data).hexdigest();closed=[]
    class NativeExtent:
        def __init__(self,original):assert original==data
        def __len__(self):return extent
        def close(self):closed.append(True)
    class Original:
        def _original_with_commitment(self,identity):return data,'synthetic-authenticated-commitment'
    monkeypatch.setattr(pdfium,'PdfDocument',NativeExtent)
    with pytest.raises(ValueError,match='physical PDF extent'):_physical_page_count(Original(),doc)
    assert closed==[True]


def test_sql_source_closure_includes_and_detects_both_page_helpers(monkeypatch):
    from pathlib import Path
    from viva.sql_authority.reading import implementation_identity
    from viva.sql_authority import payroll_source_custody
    base=implementation_identity()
    assert 'viva.sql_authority.payroll_source_custody' in base['files']
    assert 'viva.ingest.cash_source_pages' in base['files']
    subject=Path(payroll_source_custody.__file__);original=Path.read_bytes
    def changed(path):
        data=original(path)
        return data+b'\n# synthetic source-closure fault\n' if path==subject else data
    monkeypatch.setattr(Path,'read_bytes',changed)
    assert implementation_identity()['sha256']!=base['sha256']


def test_closed_four_field_encoded_context_is_the_same_contract(tmp_path):
    from viva.normalization_context import encode_context
    data=pdf_bytes();reading=payroll_read(data,source_packet())
    reading.normalization_context=encode_context(reading.normalization_context)
    assert len(reading.normalization_context)==4
    with SQLAuthority.create(tmp_path.resolve()/'authority',secrets.token_urlsafe(48),verification='complete') as store:
        deposit(store);result=store.ingest(data,lambda *_:reading,contract='synthetic-encoded-context')
        assert result.status=='accepted',result
        assert all(p['provenance']['page']==2 for p in store.payroll_postings(result.doc_id))
        assert store.verify()['verified']
