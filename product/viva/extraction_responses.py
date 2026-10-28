"""Closed extraction response audit records and nonfinancial disclosure summaries."""
from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

RESPONSE_EVENT = 'ModelExtractionResponseRecorded'
_SCOPED_FIELDS = frozenset(('transport_receipt_ids','transport_complete',
                            'extraction_id','phase_attempt'))
_FIELDS = frozenset(('schema_version','doc_id','extraction_id','phase','phase_attempt',
    'transport_attempt','adapter_kind','configured_model','prompt_version','input_mode',
    'response_status','response_bytes_base64','response_encoding'))


def response_body(document, extraction, phase, phase_attempt, ordinal, kind, model,
                  prompt, mode, status, raw):
    body = dict(schema_version=1,doc_id=document,extraction_id=extraction,phase=phase,
        phase_attempt=phase_attempt,transport_attempt=ordinal,adapter_kind=kind,
        configured_model=model,prompt_version=prompt,input_mode=mode,response_status=status,
        response_bytes_base64=base64.b64encode(raw).decode('ascii'),response_encoding='base64')
    validate_response_body(body)
    return body


def validate_response_body(body):
    if not isinstance(body,Mapping) or set(body)!=_FIELDS:
        raise ValueError('closed extraction response body required')
    if type(body['schema_version']) is not int or body['schema_version']!=1:
        raise ValueError('unsupported extraction response version')
    if body['phase'] not in ('classify','extract') or body['adapter_kind'] not in ('openai_compatible','anthropic'):
        raise ValueError('unknown extraction response kind')
    for key in ('doc_id','extraction_id','configured_model','prompt_version','input_mode'):
        if type(body[key]) is not str or not body[key]:raise ValueError('missing response identity')
    for key in ('phase_attempt','transport_attempt','response_status'):
        if type(body[key]) is not int or body[key]<0:raise ValueError('invalid response ordinal')
    if body['response_encoding']!='base64' or type(body['response_bytes_base64']) is not str:
        raise ValueError('invalid response encoding')
    base64.b64decode(body['response_bytes_base64'],validate=True)


def validate_links(body, events):
    """Check the exact preceding authenticated response population for a phase."""
    present=_SCOPED_FIELDS.intersection(body)
    if not present:return
    if present!=_SCOPED_FIELDS:
        raise ValueError('incomplete scoped extraction response fields')
    links=body['transport_receipt_ids']
    if (type(links) not in (list,tuple) or
            any(type(value) is not str or not value for value in links) or
            len(set(links))!=len(links) or
            type(body['transport_complete']) is not bool or
            type(body['extraction_id']) is not str or not body['extraction_id'] or
            type(body['phase_attempt']) is not int or body['phase_attempt']<0):
        raise ValueError('invalid extraction response links')
    matching=[]
    for event in events:
        if event.event_type!=RESPONSE_EVENT:continue
        source=event.body
        validate_response_body(source)
        if all(source.get(key)==body.get(key) for key in ('doc_id','extraction_id','phase','phase_attempt')):
            if event.to_dict()['provenance'].get('doc_id')!=body['doc_id']:
                raise ValueError('response provenance differs')
            if source['transport_attempt']!=len(matching):raise ValueError('response order differs')
            if (source['configured_model']!=body.get('model') or
                    source['prompt_version']!=body.get('prompt_version') or
                    source['input_mode']!=body.get('input_mode','text+image')):
                raise ValueError('response configuration differs')
            matching.append(event.event_id)
    if matching!=list(links):raise ValueError('missing or foreign extraction response links')


def summary(event):
    """Return only bounded metadata; raw provider contents stay in the event log."""
    body=event.body
    validate_response_body(body)
    result={key:body[key] for key in ('doc_id','extraction_id','phase','phase_attempt','transport_attempt')}
    result['response_id']=event.event_id
    result.update(input_tokens=None,output_tokens=None,cost_usd=None)
    try:
        data=json.loads(base64.b64decode(body['response_bytes_base64']),parse_float=Decimal)
        usage=data.get('usage') if type(data) is dict else None
        if type(usage) is not dict:return result
        fields=(('prompt_tokens','completion_tokens') if body['adapter_kind']=='openai_compatible'
                else ('input_tokens','output_tokens'))
        for field,target in zip(fields,('input_tokens','output_tokens')):
            value=usage.get(field)
            if type(value) is int and value>=0:result[target]=value
        value=usage.get('cost')
        if value is not None and not isinstance(value,bool):
            cost=Decimal(str(value))
            if cost.is_finite() and cost>=0:result['cost_usd']=str(cost)
    except (ValueError,TypeError,InvalidOperation,UnicodeError):pass
    return result
