from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
from time import monotonic
import pytest
from viva.ingest.apr_context_contracts import AprContextPayload,AprContextResult,GroundingReceipt
from viva.ingest.apr_context_grounding import MeasuredPage,MeasuredSpan,ground_context,extract_measured_page
from viva.ingest.apr_context_parser import LocalAprCandidate
from viva.ingest.instrument_contracts import ContractError,Source


def measured(lines):
    text='\n'.join(lines);offset=0;spans=[]
    for index,line in enumerate(lines):
        spans.append(MeasuredSpan(index,offset,offset+len(line),line,(10.,700.-index*12,500.,708.-index*12)))
        offset+=len(line)+1
    return MeasuredPage('doc',1,text,tuple(spans),sha256(text.encode()).hexdigest())


def source(lines=None):
    return measured(lines or ['Document D-A | Account reference REF-A | USD | en-US','Disclosure apr: 5.25',
        'Disclosure apr status: fictional source wording','Disclosure apr basis: Source-owned qualification.'])


def grounded(page=None,field='status',value='fictional source wording',index=2,**kwargs):
    return ground_context(page or source(),LocalAprCandidate(field,value,1,index,(index,)),
        account_reference=kwargs.get('reference','REF-A'),currency='USD',locale='en-US',
        numeric_apr=kwargs.get('apr',Decimal('5.25')),numeric_source=kwargs.get('numeric_source',Source('doc',1)),deadline=kwargs.get('deadline',monotonic()+1))


def test_grounding_accepts_literal_not_legal_classification_and_roundtrip():
    result=grounded()
    assert result.disposition=='accepted'
    from viva.ledger.instruments import encode_change,decode_change
    from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
    from viva.ingest.instrument_contracts import SourcedDate
    result=replace(result,grounding=replace(result.grounding,numeric_terms_observation_id='numeric'))
    payload=AprContextPayload(1,'loan','numeric','2021-01-31','status',result,'doc','doc')
    observation=ObservationChange('obs','loan',ObservationKind.APR_CONTEXT,SourcedDate('2021-01-31',Source('doc',1)),
        Operation.CREATE,Source('doc',1),payload)
    encoded=encode_change(observation)
    assert decode_change(encoded)==observation
    assert encoded['payload']['result']['value']=='fictional source wording'



@pytest.mark.parametrize('mutation',[
    lambda lines:lines+[lines[1]],lambda lines:lines+[lines[2]],
    lambda lines:lines+['Document D-B | Account reference REF-B | USD | en-US'],
    lambda lines:[s.replace('status:','wrong:') for s in lines],
    lambda lines:[s.replace('5.25','4.25') for s in lines],
])
def test_wrong_or_ambiguous_field_does_not_ground(mutation):
    assert grounded(source(mutation([s.text for s in source().spans]))).disposition=='unavailable'


@pytest.mark.parametrize('kwargs',[{'reference':'REF'},{'numeric_source':Source('doc',2)},
    {'deadline':0},{'value':'fictional source wording.'},{'value':'fictional Source wording'},
    {'value':'fictional source wordіng'}])
def test_wrong_identity_page_deadline_and_literal_refuse(kwargs):
    assert grounded(**kwargs).disposition=='unavailable'


def test_fake_span_and_geometry_refuse():
    assert grounded(index=1).disposition=='unavailable'
    page=source(); spans=list(page.spans)
    spans[2]=replace(spans[2],box=(40.,680.,500.,688.))
    assert grounded(replace(page,spans=tuple(spans))).disposition=='unavailable'


def test_unavailable_rate_requires_status_and_no_numeric_row():
    page=measured(['Document D-A | Account reference REF-A | USD | en-US','Disclosure apr status: unavailable'])
    assert grounded(page,value='unavailable',index=1,apr=None).disposition=='accepted'
    assert grounded(apr=None).disposition=='unavailable'


def test_whitespace_wrap_keeps_source_text():
    page=measured(['Document D-A | Account reference REF-A | USD | en-US','Disclosure apr: 5.25',
        'Disclosure apr status: source','  qualification'])
    spans=list(page.spans)
    first=spans[2];left=10.+len('Disclosure apr status: ')*5
    boxes=tuple((10.+i*5,first.box[1],15.+i*5,first.box[3]) for i in range(len(first.text)))
    spans[2]=replace(first,character_boxes=boxes)
    spans[3]=replace(spans[3],box=(left,spans[3].box[1],left+100,spans[3].box[3]))
    page=replace(page,spans=tuple(spans))
    proposal=LocalAprCandidate('status','source qualification',1,2,(2,3))
    result=ground_context(page,proposal,account_reference='REF-A',currency='USD',locale='en-US',numeric_apr=Decimal('5.25'),
        numeric_source=Source('doc',1),deadline=monotonic()+1)
    assert result.value=='source\n  qualification'


@pytest.mark.parametrize('raw',['{','{"terms":{"disclosure_apr_context":"injected"}}'])
def test_unknown_model_context_does_not_gain_local_authority(raw):
    from viva.ingest.instrument_read import parser_for
    facts,error=parser_for('mortgage_statement')(raw,'doc','en-US','USD')
    assert facts is None and error


def test_multibyte_cap_and_boolean_page():
    with pytest.raises(ContractError):LocalAprCandidate('status','é'*129,1,0,(0,))
    with pytest.raises(ContractError):LocalAprCandidate('status','word',True,0,(0,))


def test_actual_unchanged_pdf_local_text_layer():
    from pathlib import Path
    root=Path(__file__).parents[2]/'output/pdf/synthetic_life_5y'
    name='D0012-mortgage-LOAN-A-2021-01-31.pdf'
    if not (root/name).is_file():pytest.skip('campaign synthetic documents are not part of the product package')
    data=(root/name).read_bytes()
    assert sha256(data).hexdigest()=='6d18a3baafd506c8d8125a5b62767640e9380ce46a62f432ff24dfad1d07fbdf'
    page=extract_measured_page(data,'doc',1,deadline=monotonic()+1)
    for field,label in [('status','Disclosure apr status:'),('context','Disclosure apr basis:')]:
        span=next(s for s in page.spans if s.text.startswith(label))
        value=span.text.split(':',1)[1].strip()
        result=ground_context(page,LocalAprCandidate(field,value,1,span.span_id,(span.span_id,)),account_reference='LOAN-A',
            currency='USD',locale='en-US',numeric_apr=Decimal('5.25'),numeric_source=Source('doc',1),deadline=monotonic()+1)
        assert result.disposition=='accepted'


def test_actual_unchanged_rate_witnesses_fit_local_format_and_receipt_caps():
    from pathlib import Path
    from viva.ingest.apr_context_grounding import construct_context
    root=Path(__file__).parents[2]/'output/pdf/synthetic_life_5y'
    if not (root/'source-ledger.json').is_file():pytest.skip('campaign source unavailable')
    docs=[d for d in json.loads((root/'source-ledger.json').read_text())['documents'] if d['family'] in {'mortgage','refinance'}]
    assert len(docs)==61
    for doc in docs:
        page=extract_measured_page((root/doc['file']).read_bytes(),doc['id'],1,deadline=monotonic()+1)
        apr=doc['facts'].get('disclosure_apr')
        apr=Decimal(str(apr)) if apr is not None else None
        for field,key in [('status','disclosure_apr_status'),('context','disclosure_apr_basis')]:
            result=construct_context(page,field,account_reference=doc['account_ref'],currency=doc['currency'],locale=doc['locale'],
                numeric_apr=apr,numeric_source=Source(doc['id'],1),numeric_terms_observation_id='numeric:'+doc['id'],deadline=monotonic()+1)
            if key in doc['facts']:
                assert result.disposition=='accepted', (doc['id'],field,result.reason)
                assert result.value==str(doc['facts'][key])
                assert len(json.dumps(result.grounding.to_dict(),ensure_ascii=False).encode())<=8192
            else:assert result.disposition=='unavailable'


@pytest.mark.parametrize('mutation',['literal','document','page','numeric_dependency','character_range'])
def test_corrupted_stored_receipt_or_literal_refuses(mutation):
    from viva.ingest.apr_context_grounding import construct_context
    result=construct_context(source(),'status',account_reference='REF-A',currency='USD',locale='en-US',numeric_apr=Decimal('5.25'),
        numeric_source=Source('doc',1),numeric_terms_observation_id='numeric',deadline=monotonic()+1)
    if mutation=='literal':result=replace(result,value='not the measured source literal')
    elif mutation=='document':result=replace(result,grounding=replace(result.grounding,document_id='other'))
    elif mutation=='page':result=replace(result,grounding=replace(result.grounding,page=2))
    elif mutation=='numeric_dependency':result=replace(result,grounding=replace(result.grounding,numeric_terms_observation_id='other'))
    else:
        with pytest.raises(ContractError):replace(result.grounding.measured_spans[0],end=1)
        return
    with pytest.raises(ContractError):AprContextPayload(1,'loan','numeric','2021-01-31','status',result,'doc','doc')
