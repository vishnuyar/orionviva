"""Committed source population includes unlinked, held and unknown-period payroll."""
from dataclasses import dataclass, fields
from viva.investment.contracts import Field, EvidenceError, canonical, digest, encode, day
from viva.investment.events import prefix, decode_field
from viva.investment.payroll import build_source, decode_source, source_fields, _complete
from viva.ledger.events import Event, Provenance
from .payroll_v2 import PayrollSourceExtractionV2, economic_facts, periods

OBSERVED = 'RetirementPayrollPopulationObserved'
RETRACTED = 'RetirementPayrollPopulationRetracted'

@dataclass(frozen=True)
class PopulationSource:
    version: str
    source: object
    period_start: Field | None
    period_end: Field | None
    disposition: str
    reading_id: str
    reading_digest: str

    def __post_init__(self):
        if self.version not in ('payroll-source-v1', 'payroll-source-v2') or self.disposition not in ('accepted', 'held', 'unknown'):
            raise EvidenceError('closed payroll population version/disposition required')
        if self.version == 'payroll-source-v1' and (self.period_start is not None or self.period_end is not None):
            raise EvidenceError('historical payroll periods cannot be backfilled')
        if self.version == 'payroll-source-v2' and any(type(f) is not Field for f in (self.period_start, self.period_end)):
            raise EvidenceError('typed v2 payroll periods required')
        if any(f is not None and f.document != self.source.document for f in (self.period_start, self.period_end)):
            raise EvidenceError('foreign payroll period source')


def decode(data):
    if type(data) is not dict or set(data) != {f.name for f in fields(PopulationSource)}:
        raise EvidenceError('closed population source required')
    args = dict(data); args['source'] = decode_source(args['source'])
    for key in ('period_start', 'period_end'):
        if args[key] is not None:
            args[key] = decode_field(args[key])
    return PopulationSource(**args)


def source_from_facts(facts, events, locale='en-US'):
    from viva.ingest.paystub import from_paystub_json
    # A posted source is the deterministic reading of the retained model response,
    # rather than a caller-supplied period attached to an existing cash event.
    candidates = []
    for event in events:
        if event.event_type != 'ReadRecorded' or event.body.get('doc_id') != facts.doc_id or not event.body.get('parse_ok') or event.body.get('phase', 'extract') != 'extract':
            continue
        from viva.acquisition import local_read
        local = local_read(event.body)
        if local:
            if (getattr(facts, 'acquisition', None) != event.body['acquisition']
                    or event.body['doc_type'] != facts.doc_type
                    or event.body.get('normalization_locale', 'en-US') != locale
                    or event.body.get('source_currency', 'USD') != facts.currency):
                continue
        elif getattr(facts, 'acquisition', None) is not None:
            continue
        text = event.body.get('response_text', '')
        if local:
            from viva.sample.curation import decode_retained_input
            text = decode_retained_input(event.body)
        parsed, error = from_paystub_json(text, facts.doc_id, locale, facts.currency)
        if parsed is not None:
            from dataclasses import replace
            metadata = {'acquisition': event.body['acquisition']} if local else {}
            parsed=replace(parsed,doc_type=facts.doc_type,doc_type_confidence=facts.doc_type_confidence,**metadata)
        if parsed is not None and parsed.to_dict() == facts.to_dict():
            if (type(facts.payroll_source) is PayrollSourceExtractionV2 and not local
                    and not event.body.get('prompt_version','').startswith('extract:paystub-base-v2+paystub-v2')):
                continue
            candidates.append(event)
    if not candidates:
        raise EvidenceError('authenticated payroll reading unavailable')
    reading = candidates[-1]
    is_v2 = type(facts.payroll_source) is PayrollSourceExtractionV2
    source = build_source(economic_facts(facts) if is_v2 else facts, locale)
    start, end = periods(facts, locale) if is_v2 else (None, None)
    complete = _complete(source) and bool(source.deductions)
    try:
        from decimal import localcontext, Decimal
        with localcontext() as context:
            context.prec = 128
            complete = complete and Decimal(source.gross.value) - sum((Decimal(row.amount.value) for row in source.deductions), Decimal(0)) == Decimal(source.net.value)
    except (ValueError, ArithmeticError):
        complete = False
    disposition = 'accepted' if complete else 'held'
    if not is_v2 or any(field.status != 'accepted' for field in (start, end)):
        disposition = 'unknown' if disposition == 'accepted' else disposition
    return PopulationSource('payroll-source-v2' if is_v2 else 'payroll-source-v1', source, start, end, disposition, reading.event_id, digest(reading.body))


def append(ledger, facts, *, locale='en-US',effective=None):
    if facts.payroll_source is None:
        # A missing source is still recorded by ReadRecorded and included as an
        # unavailable population member during materialization.
        return []
    def decide(events):
        source = source_from_facts(facts, events, locale)
        prior=[event for event in events if event.event_type in (OBSERVED,RETRACTED) and event.provenance.doc_id==facts.doc_id]
        if prior and prior[-1].event_type==OBSERVED and prior[-1].body.get('population')==encode(source):
            return ()
        if prior and prior[-1].event_type==RETRACTED:
            old=next((event for event in reversed(prior) if event.event_type==OBSERVED),None)
            if old is not None and old.body['population']['reading_id']==source.reading_id:raise EvidenceError('retracted payroll source requires a new authorized reading')
        previous=prior[-1].event_id if prior else None
        effective_date=day(effective or facts.pay_date) if previous else '0001-01-01'
        body = {'schema': 'retirement-payroll-population-v1', 'population': encode(source),'prior_id':previous,'effective':effective_date}
        identifier = 'retirement-payroll:' + digest(body)
        if any(e.event_id == identifier for e in events):
            return ()
        body['prefix'] = encode(prefix(events))
        event = Event(OBSERVED, facts.pay_date or facts.period_end or facts.period_start, body, Provenance(doc_id=facts.doc_id), event_id=identifier)
        return (event,)
    additions = ledger.append_atomically(lambda projection: decide(tuple(projection._source_events)))
    return additions


def records(events,as_of='9999-12-31'):
    """Enumerate every recorded payroll document before any date/eligibility cut."""
    day(as_of);readings={};histories={};by_id={e.event_id:e for e in events}
    if len(by_id)!=len(events):raise EvidenceError('duplicate committed population dependency')
    captured={}
    for ordinal,event in enumerate(events):
        if event.event_type=='DocumentCaptured' and event.body.get('doc_type')=='pay_stub':captured[event.body.get('doc_id')]=event
        if event.event_type=='ReadRecorded' and event.body.get('phase','extract')=='extract' and event.body.get('doc_id') in captured:
            readings[event.body['doc_id']]=event
        elif event.event_type==OBSERVED:
            body=event.body
            if set(body)!={'schema','population','prefix','prior_id','effective'} or body['schema']!='retirement-payroll-population-v1' or body['prefix']!=encode(prefix(events[:ordinal])):
                raise EvidenceError('population committed prefix differs')
            day(body['effective']);source=decode(body['population']);reading=by_id.get(source.reading_id);document=source.source.document
            if reading is None or reading.event_type!='ReadRecorded' or digest(reading.body)!=source.reading_digest or reading.body.get('doc_id')!=document or event.provenance.doc_id!=document:
                raise EvidenceError('population reading lineage differs')
            history=histories.setdefault(document,[])
            if (history[-1][0].event_id if history else None)!=body['prior_id']:
                raise EvidenceError('population predecessor differs')
            if not history and body['effective']!='0001-01-01':raise EvidenceError('initial population visibility differs')
            history.append((event,source,body['effective']))
        elif event.event_type==RETRACTED:
            body=event.body
            if set(body)!={'document','prior_id','prefix','effective'} or body['prefix']!=encode(prefix(events[:ordinal])):raise EvidenceError('population retraction prefix differs')
            day(body['effective']);history=histories.get(body['document'],[])
            if not history or history[-1][0].event_id!=body['prior_id']:raise EvidenceError('population retraction predecessor differs')
            history.append((event,None,body['effective']))
    output=[]
    for document,capture in captured.items():
        reading=readings.get(document)
        if reading is None:
            output.append({'document':document,'id':capture.event_id,'digest':digest(capture.body),'status':'unknown','population':None})
            continue
        history=histories.get(document,[])
        latest_source=next((source for event,source,effective in reversed(history) if source is not None),None)
        selected=next(((event,source) for event,source,effective in reversed(history) if effective<=as_of),None)
        if latest_source is None or latest_source.reading_id!=reading.event_id or selected is None or selected[1] is None:
            output.append({'document':document,'id':reading.event_id,'digest':digest(reading.body),'status':'unknown','population':None})
        else:
            event,source=selected
            output.append({'document':document,'id':event.event_id,'digest':digest(event.body),'status':source.disposition,'population':encode(source)})
    return tuple(output)


def change_dates(events):
    return tuple(event.body['effective'] for event in events if event.event_type in (OBSERVED,RETRACTED) and event.body.get('effective') not in (None,'0001-01-01'))


def retract(ledger,document,prior_id,effective):
    day(effective)
    def decide(events):
        history=[event for event in events if event.event_type in (OBSERVED,RETRACTED) and event.provenance.doc_id==document]
        if not history or history[-1].event_id!=prior_id:raise EvidenceError('population retraction predecessor is not current')
        body={'document':document,'prior_id':prior_id,'effective':effective,'prefix':encode(prefix(events))}
        event=Event(RETRACTED,effective,body,Provenance(doc_id=document),event_id='retirement-payroll-retraction:'+digest(body))
        return (event,)
    additions=ledger.append_atomically(lambda projection: decide(tuple(projection._source_events)))
    return additions
