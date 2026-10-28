"""The shipped sample is source bound and never represents a model execution."""
import pytest

def test_installed_resource_closure():
    from viva.sample.resources import load_pack
    pack = load_pack()
    assert len(pack.documents) == 794
    assert sum(doc['page_count'] for doc in pack.documents) == 913
    assert pack.source_event_count == 3531

@pytest.mark.parametrize('change', ['kind', 'sample_version', 'reading_contract', 'document_sha256', 'extra'])
def test_unknown_or_corrupt_acquisition_refused(change):
    from viva.acquisition import validate
    value = dict(kind='local-curation-v1', sample_version='five-year-life-v1',
                 reading_contract='curated-source-reading-v1',
                 corpus_manifest_sha256='a'*64, readings_sha256='b'*64,
                 document_sha256='c'*64, reading_sha256='d'*64)
    value[change] = 'invalid'
    with pytest.raises(ValueError): validate(value)

def test_original_model_event_keeps_exact_body():
    from viva.ledger.events import read_recorded
    event=read_recorded('doc','route','prompt','text','{}',.25,10,20,True,None,'2026-01-01')
    assert event.body == {'doc_id':'doc','model':'route','model_role':'configured_route',
        'prompt_version':'prompt','input_mode':'text','response_text':'{}','cost_usd':.25,
        'parse_ok':True,'parse_error':None,'phase':'extract','input_tokens':10,
        'output_tokens':20,'usage_reported':True}

def test_every_source_occurrence_and_raw_field_keeps_physical_page():
    import pypdfium2 as pdfium
    from viva.sample.resources import load_pack
    pack=load_pack(); occurrences=set()
    for doc in pack.documents:
        row=pack.readings[doc['sha256']];occurrences.update(row['source_event_ids'])
        pdf=pdfium.PdfDocument(pack.original(doc));text=[]
        try:
            for number in range(len(pdf)):
                page=pdf[number]
                try:
                    source=page.get_textpage()
                    try: text.append(' '.join(source.get_text_range().split()))
                    finally: source.close()
                finally: page.close()
        finally:pdf.close()
        def check(value):
            if isinstance(value,dict):
                if set(value)>={'raw','page'}:
                    raw=' '.join(value['raw'].split())
                    assert raw in text[value['page']-1],(doc['id'],value)
                for item in value.values():check(item)
            elif isinstance(value,list):
                for item in value:check(item)
        check(row['envelope']['parser_input'])
    assert len(occurrences)==3531


def test_model_reply_cannot_claim_local_curation():
    import json
    from viva.ingest.statement import from_model_json
    from viva.ingest.pipeline_models import ReadResult
    text=json.dumps({'acquisition':{'kind':'local-curation-v1'},
        'opening':{'amount_raw':'10','date_raw':'2025-01-01'},
        'closing':{'amount_raw':'10','date_raw':'2025-01-31'},'transactions':[]})
    facts,error=from_model_json(text,'model-document','en-US','USD')
    assert error is None
    reading=ReadResult('checking_statement',.9,facts,raw_text=text,model='real-model',cost_usd=.12)
    assert reading.acquisition is None and reading.cost_usd==.12


def test_local_variant_does_not_hide_real_model_cost():
    from viva.acquisition import local_read
    value=dict(kind='local-curation-v1',sample_version='five-year-life-v1',
        reading_contract='curated-source-reading-v1',corpus_manifest_sha256='a'*64,
        readings_sha256='b'*64,document_sha256='c'*64,reading_sha256='d'*64)
    with pytest.raises(ValueError):local_read({'acquisition':value,'model':'real','cost_usd':.5})

@pytest.mark.parametrize('document_id',['D0001','D0002','D0007','D0010'])
def test_local_snapshot_preserves_unavailable_confidence(document_id):
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    pack=load_pack();doc=next(item for item in pack.documents if item['id']==document_id)
    result=CuratedReader(pack)(pack.original(doc),doc['sha256'])
    snapshot=result.facts.to_dict()
    assert snapshot['doc_type_confidence'] is None
    assert snapshot['acquisition']==result.acquisition
    restored=type(result.facts).from_dict(snapshot)
    assert restored.to_dict()==snapshot


def test_model_and_local_reads_remain_separate_in_trust():
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ledger.events import curated_read_recorded,read_recorded
    from viva.surface.outbound import outbound
    pack=load_pack();doc=pack.documents[0];reading=CuratedReader(pack)(pack.original(doc),doc['sha256'])
    curated=curated_read_recorded(doc['sha256'],reading.doc_type,reading.raw_text,True,None,'2026-10-25',reading.acquisition)
    model=read_recorded('real-document','actual-route','actual-prompt','text','{}',.25,5,10,True,None,'2026-10-25')
    assert outbound([curated])['call_count']==0
    assert outbound([curated])['cost'] is None
    visible=outbound([curated,model])
    assert visible['call_count']==1
    assert visible['models']==[{'name':'actual-route','count':1}]

@pytest.mark.parametrize('field',['corpus_manifest_sha256','readings_sha256','document_sha256','reading_sha256'])
def test_curated_read_corruption_cannot_hide_in_trust(field):
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ledger.events import curated_read_recorded
    from viva.surface.outbound import outbound
    pack=load_pack();doc=pack.documents[0];rr=CuratedReader(pack)(pack.original(doc),doc['sha256'])
    event=curated_read_recorded(doc['sha256'],rr.doc_type,rr.raw_text,True,None,'2026-10-25',rr.acquisition)
    event.body['acquisition']=dict(event.body['acquisition']);event.body['acquisition'][field]='0'*64
    with pytest.raises(ValueError):outbound([event])


def test_instrument_none_needs_valid_local_acquisition():
    from dataclasses import replace
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    pack=load_pack();doc=next(item for item in pack.documents if item['id']=='D0010')
    facts=CuratedReader(pack)(pack.original(doc),doc['sha256']).facts
    with pytest.raises(ValueError):replace(facts,acquisition=None)
    with pytest.raises(ValueError):replace(facts,doc_type_confidence=0.0)
    changed=dict(facts.acquisition);changed['document_sha256']='0'*64
    with pytest.raises(ValueError):replace(facts,acquisition=changed)


def test_held_snapshot_and_capture_have_local_not_model_metadata(tmp_path):
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ledger import Ledger
    from viva.ingest.raw_store import RawStore
    from viva.ingest import capture_and_ingest
    pack=load_pack();doc=pack.documents[0];reader=CuratedReader(pack)
    ledger=Ledger.open(tmp_path/'events.jsonl','public-synthetic-test')
    raw=RawStore.open(tmp_path/'raw','public-synthetic-test')
    result=capture_and_ingest(raw,ledger,pack.original(doc),reader,filename=doc['file'],captured_at='2026-10-25')
    assert result.action=='awaiting'
    events=list(ledger.events());read=next(e for e in events if e.event_type=='ReadRecorded')
    capture=next(e for e in events if e.event_type=='DocumentCaptured')
    held=next(e for e in events if e.event_type=='StatementHeld')
    assert 'doc_type_confidence' not in capture.body
    assert held.body['facts']['doc_type_confidence'] is None
    assert held.body['facts']['acquisition']==read.body['acquisition']==capture.body['acquisition']
    assert not set(read.body)&{'model','cost_usd','prompt_version','input_tokens','output_tokens'}

@pytest.mark.parametrize('limit',[0,794,True,-1,'1'])
def test_invalid_engineering_limit_cannot_publish_an_empty_ready_sample(tmp_path,limit):
    from viva.sample.instances import build_instance,SampleBuildError
    base=tmp_path/'unmodified'
    with pytest.raises(SampleBuildError):build_instance(base,engineering_document_limit=limit)
    assert not base.exists()


def test_intermediate_symlink_cannot_redirect_sample_mutation(tmp_path):
    from viva.sample.instances import build_instance,SampleBuildError
    outside=tmp_path/'retained';outside.mkdir(mode=0o700)
    marker=outside/'user-edits.txt';marker.write_text('retain all edits')
    base=tmp_path/'sample';base.mkdir(mode=0o700)
    (base/'sample-vaults').symlink_to(outside,target_is_directory=True)
    with pytest.raises(SampleBuildError):build_instance(base,engineering_document_limit=1)
    assert list(outside.iterdir())==[marker]
    assert marker.read_text()=='retain all edits'


def test_simultaneous_preparation_is_bounded_busy(tmp_path):
    import fcntl,os
    from viva.sample.instances import build_instance,SampleBuildError
    parent=tmp_path/'sample-vaults';parent.mkdir(mode=0o700)
    root=parent/'five-year-life-v1';root.mkdir(mode=0o700)
    descriptor=os.open(root/'preparation.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(SampleBuildError,match='busy'):build_instance(tmp_path,engineering_document_limit=1)
        assert {x.name for x in root.iterdir()}=={'preparation.lock'}
    finally:os.close(descriptor)

def test_retained_curated_rebuild_does_not_require_installed_bundle(tmp_path,monkeypatch):
    from viva.sample import resources
    from viva.sample.curation import CuratedReader
    from viva.ingest import capture_and_ingest
    from viva.vault import Vault
    from viva.rebuild import rebuild
    pack=resources.load_pack();doc=next(item for item in pack.documents if item['id']=='D0002')
    source=tmp_path/'source';destination=tmp_path/'reconstructed'
    vault=Vault.open(source,'public-synthetic-test')
    try:
        outcome=capture_and_ingest(vault.raw,vault.ledger,pack.original(doc),CuratedReader(pack),
            filename=doc['file'],captured_at='2026-10-25')
        assert outcome.action=='posted'
        original=[event for event in vault.events() if event.event_type=='ReadRecorded'][0]
    finally:vault.close()
    def unavailable(*args,**kwargs):raise AssertionError('old bundle is unavailable')
    monkeypatch.setattr(resources,'load_pack',unavailable)
    counts=rebuild(source,destination,'public-synthetic-test',log=lambda text:None)
    assert counts=={'posted':1}
    rebuilt=Vault.open(destination,'public-synthetic-test',create=False)
    try:
        event=next(event for event in rebuilt.events() if event.event_type=='ReadRecorded')
        assert event.body['acquisition']==original.body['acquisition']
        assert event.body['response_text']==original.body['response_text']
        assert 'model' not in event.body and 'cost_usd' not in event.body
        assert rebuilt.raw.get(doc['sha256'])==pack.original(doc)
    finally:rebuilt.close()

def test_forged_local_metadata_cannot_suppress_actual_model_receipt(tmp_path):
    from dataclasses import replace
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ingest import capture_and_ingest
    from viva.ingest.raw_store import RawStore
    from viva.ledger import Ledger
    from viva.surface.outbound import outbound
    pack=load_pack();doc=pack.documents[0];local=CuratedReader(pack)(pack.original(doc),doc['sha256'])
    attempted=replace(local,model='actual-configured-route',prompt_version='real-prompt',
                      cost_usd=.25,input_tokens=5,output_tokens=10,usage_reported=True)
    ledger=Ledger.open(tmp_path/'events.jsonl','public-synthetic-test')
    raw=RawStore.open(tmp_path/'raw','public-synthetic-test')
    result=capture_and_ingest(raw,ledger,pack.original(doc),lambda data,doc_id:attempted,
                              filename=doc['file'],captured_at='2026-10-25')
    assert result.action=='parked'
    events=list(ledger.events());reading=next(e for e in events if e.event_type=='ReadRecorded')
    assert 'acquisition' not in reading.body
    assert reading.body['model']=='actual-configured-route' and reading.body['cost_usd']==.25
    assert outbound(events)['call_count']==1

@pytest.mark.parametrize('damage',['missing','foreign','wrong_pdf','wrong_reading','wrong_closure','symlink'])
def test_incomplete_or_corrupt_pack_is_refused_before_capture(tmp_path,damage):
    import shutil,json
    from pathlib import Path
    from viva.sample.resources import load_pack,SampleResourceError
    original=load_pack();destination=tmp_path/'resources';shutil.copytree(Path(original.root),destination)
    doc=original.documents[0];member=destination/doc['file']
    if damage=='missing':member.unlink()
    elif damage=='foreign':(destination/'foreign.pdf').write_bytes(b'foreign')
    elif damage=='wrong_pdf':member.write_bytes(b'%PDF-wrong')
    elif damage=='wrong_reading':(destination/'readings.json').write_text('{}')
    elif damage=='wrong_closure':(destination/'closure.json').write_text('{}')
    else:
        member.unlink();member.symlink_to(Path(original.root)/doc['file'])
    with pytest.raises(SampleResourceError):load_pack(destination)
    assert not (tmp_path/'vault').exists()

def test_curated_payroll_retains_actual_v2_population_without_a_fake_prompt(tmp_path):
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ingest import capture_and_ingest
    from viva.ingest.raw_store import RawStore
    from viva.ledger import Ledger
    pack=load_pack();doc=pack.documents[0]
    ledger=Ledger.open(tmp_path/'events.jsonl','public-synthetic-test');raw=RawStore.open(tmp_path/'raw','public-synthetic-test')
    capture_and_ingest(raw,ledger,pack.original(doc),CuratedReader(pack),filename=doc['file'],captured_at='2026-10-25')
    population=[e for e in ledger.events() if e.event_type=='RetirementPayrollPopulationObserved']
    assert len(population)==1
    assert population[0].body['population']['version']=='payroll-source-v2'
    assert population[0].body['population']['disposition']=='accepted'
    reading=next(e for e in ledger.events() if e.event_type=='ReadRecorded')
    assert 'prompt_version' not in reading.body and 'model' not in reading.body

def test_investment_source_amount_keeps_the_exact_printed_sign():
    import re,pypdfium2 as pdfium
    from viva.sample.resources import load_pack
    pack=load_pack();checked=0
    for doc in pack.documents:
        source=pack.readings[doc['sha256']]['envelope']['parser_input'].get('investment_source')
        if source is None:continue
        pdf=pdfium.PdfDocument(pack.original(doc));texts=[]
        try:
            for number in range(len(pdf)):
                page=pdf[number]
                try:
                    text=page.get_textpage()
                    try:texts.append(text.get_text_range())
                    finally:text.close()
                finally:page.close()
        finally:pdf.close()
        for row in source['rows']:
            reference=row['printed_row_reference'];text=texts[reference['page']-1]
            start=text.index(reference['raw']);tail=text[start:]
            next_row=re.search(r'\bE\d{6}\s*/\s*\d{4}-\d{2}-\d{2}',tail[len(reference['raw']):])
            if next_row:tail=tail[:len(reference['raw'])+next_row.start()]
            values=re.findall(r'(?<![\d.])([+-]?\d+\.\d{2})(?![\d.])',tail)
            assert values,(doc['id'],reference)
            assert row['amount']['raw']==values[-1],(doc['id'],reference['raw'],row['amount']['raw'],values[-1])
            checked+=1
    assert checked>1000

@pytest.mark.parametrize('document_id',['D0002','D0007','D0009','D0010','D0011','D0012','D0013','D0014','D0168','D0311'])
@pytest.mark.parametrize('damage',['drop','wrong_row','wrong_sign','wrong_page'])
def test_directional_source_cells_reject_tampering(document_id,damage):
    import copy
    from decimal import Decimal
    from viva.sample.resources import load_pack
    from viva.sample.curation import canonical,decode_envelope,validate_pdf_cells
    pack=load_pack();doc=next(item for item in pack.documents if item['id']==document_id)
    row=pack.readings[doc['sha256']];envelope=copy.deepcopy(row['envelope'])
    assert validate_pdf_cells(pack.original(doc),envelope)==doc['page_count']
    if damage=='drop':
        envelope['source_cells'].pop()
        with pytest.raises(ValueError):decode_envelope(canonical(envelope).decode(),row['doc_type'])
    else:
        cell=envelope['source_cells'][0]
        if damage=='wrong_row':cell['association']['row_reference']='E999999'
        elif damage=='wrong_sign':cell['raw']=str(-Decimal(cell['raw']))
        else:cell['page']=doc['page_count']+1
        with pytest.raises(ValueError):validate_pdf_cells(pack.original(doc),envelope)


def test_every_curated_source_passes_closed_envelope_and_physical_row_validation():
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    pack=load_pack();reader=CuratedReader(pack);cells=0
    for doc in pack.documents:
        reading=reader(pack.original(doc),doc['sha256'])
        assert reading.facts is not None and reading.error is None,doc['id']
        cells+=len(pack.readings[doc['sha256']]['envelope']['source_cells'])
    assert cells>6000

@pytest.mark.parametrize('metadata',[{'cost_usd':.25},{'input_tokens':5,'usage_reported':True},
    {'output_tokens':10,'usage_reported':True},{'resolved_model':'provider-reported-route'},
    {'input_tokens':5,'usage_reported':False}])
def test_unattributed_actual_producer_metadata_is_retained_without_local_claim(tmp_path,metadata):
    from dataclasses import replace
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.ingest import capture_and_ingest
    from viva.ingest.raw_store import RawStore
    from viva.ledger import Ledger
    pack=load_pack();doc=pack.documents[0]
    reading=replace(CuratedReader(pack)(pack.original(doc),doc['sha256']),**metadata)
    ledger=Ledger.open(tmp_path/'events.jsonl','public-synthetic-test');raw=RawStore.open(tmp_path/'raw','public-synthetic-test')
    result=capture_and_ingest(raw,ledger,pack.original(doc),lambda data,doc_id:reading,filename=doc['file'],captured_at='2026-10-25')
    assert result.action=='parked'
    receipt=next(e for e in ledger.events() if e.event_type=='ReadRecorded')
    assert receipt.body['model']=='' and 'acquisition' not in receipt.body
    assert receipt.body['parse_error'].startswith('unsupported producer state')
    assert receipt.body['response_text']==reading.raw_text
    assert receipt.body['cost_usd']==reading.cost_usd
    assert receipt.body['unsupported_producer_metadata']=={
        'configured_route_available':False,'input_tokens':reading.input_tokens,
        'output_tokens':reading.output_tokens,'usage_reported':reading.usage_reported}
    if reading.resolved_model:assert receipt.body['resolved_model']==reading.resolved_model
