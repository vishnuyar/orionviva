"""Deterministic local context extraction after accepted numeric observations."""
from hashlib import sha256
import json
from time import monotonic
from .apr_context_contracts import AprContextPayload,AprContextResult
from .apr_context_grounding import extract_measured_page,construct_context,GroundingError
from .instrument_contracts import Disposition,Source,ContractError
from .instrument_observations import ObservationChange,ObservationKind,Operation
from ..ledger.instruments import encode,observation_event
from ..crypto import CryptoError


def _accepted(projection,change):
    record=projection.core._instrument_observations.get(change.observation_id)
    state=projection.core._instrument_component_states.get(change.observation_id)
    return bool(record and not record['superseded'] and record['change'].operation!=Operation.RETRACT and state
        and any(part.component=='mortgage_terms' and part.disposition==Disposition.ACCEPTED for part in state.components))


def extract_apr_context(raw,ledger,doc_id,*,locale='',deadline=None):
    """No model calls, numeric mutations, source search or truth classification."""
    deadline=min(monotonic()+1.0,deadline if deadline is not None else float('inf'))
    projection=ledger.projection()
    selected=[]
    for record in projection.core._instrument_observations.values():
        change=record['change']
        if (record['superseded'] or change.operation==Operation.RETRACT or change.source.doc_id!=doc_id
                or change.kind!=ObservationKind.MORTGAGE_COMPONENTS):continue
        if _accepted(projection,change):selected.append(change)
    if len(selected)!=1:
        return {'status':'numeric_terms_unavailable','context':'numeric_terms_unavailable','appended':0}
    change=selected[0];terms=change.payload.terms
    anchor=terms.disclosure_apr.source if terms.disclosure_apr is not None else terms.note_rate.source if terms.note_rate is not None else None
    results={}
    if type(locale) is not str or not locale:
        results={field:AprContextResult('unavailable',reason='unsupported_representation') for field in ('status','context')}
    elif anchor is None:
        results={field:AprContextResult('unavailable',reason='numeric_terms_unavailable') for field in ('status','context')}
    elif anchor.doc_id!=doc_id:
        results={field:AprContextResult('unavailable',reason='ambiguous_association') for field in ('status','context')}
    else:
        try:
            if monotonic()>deadline:raise GroundingError('source_limit')
            first_field_deadline=min(deadline,monotonic()+0.5)
            data=raw.get_bounded(doc_id,max_plaintext=50*1024*1024,max_envelope=70*1024*1024)
            page=extract_measured_page(data,doc_id,anchor.page,deadline=first_field_deadline)
        except GroundingError as error:
            results={field:AprContextResult('unavailable',reason=str(error)) for field in ('status','context')}
        except OverflowError:
            results={field:AprContextResult('unavailable',reason='source_limit') for field in ('status','context')}
        except (OSError,ValueError,RuntimeError,CryptoError):
            results={field:AprContextResult('unavailable',reason='source_unavailable') for field in ('status','context')}
        else:
            for field in ('status','context'):
                results[field]=construct_context(page,field,account_reference=change.payload.identity.account_reference.value,
                    currency=projection.account_info(change.subject_id).currency,locale=locale,
                    numeric_apr=terms.disclosure_apr.percent if terms.disclosure_apr is not None else None,
                    numeric_source=anchor,numeric_terms_observation_id=change.observation_id,deadline=first_field_deadline if field=='status' else min(deadline,monotonic()+0.5))
    count={'value':0}
    def append(current):
        if not _accepted(current,change):return ()
        existing=current.core._instrument_observations
        events=[]
        for field,result in results.items():
            payload=AprContextPayload(1,change.subject_id,change.observation_id,change.effective.value,field,result,doc_id,doc_id)
            identity=sha256(json.dumps(encode(payload),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            if identity in existing:continue
            source=result.source if result.source is not None else change.source
            contextual=ObservationChange(identity,change.subject_id,ObservationKind.APR_CONTEXT,change.effective,
                Operation.CREATE,source,payload)
            events.append(observation_event(contextual))
        count['value']=len(events)
        return tuple(events)
    ledger.append_atomically(append)
    return {**{field:result.reason or result.disposition for field,result in results.items()},'appended':count['value']}
