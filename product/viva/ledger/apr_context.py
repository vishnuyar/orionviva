"""Field-local APR context projection over the authenticated observation frontier."""
from dataclasses import dataclass
from ..ingest.apr_context_contracts import AprContextPayload,AprContextResult
from ..ingest.instrument_observations import Operation
from ..ingest.instrument_contracts import Disposition


@dataclass(frozen=True)
class AprContextSelection:
    result: AprContextResult
    observation_ids: tuple[str,...]
    numeric_terms_observation_id: str
    field: str


def project_context(observations,component_states,*,loan_id,numeric_terms_observation_id,effective_date,field):
    """Unavailability cannot overwrite a literal; only explicit frontier edits can."""
    states={state.observation_id:{part.component:part for part in state.components} for state in component_states}
    rows={row['change'].observation_id:row for row in observations}
    numeric=rows.get(numeric_terms_observation_id)
    if numeric is None or numeric.get('superseded') or numeric['change'].operation==Operation.RETRACT:
        return AprContextSelection(AprContextResult('unavailable',reason='numeric_terms_unavailable'),(),numeric_terms_observation_id,field)
    change=numeric['change']
    component='mortgage_terms'
    status=states.get(change.observation_id,{}).get(component)
    if (change.subject_id!=loan_id or change.effective.value!=effective_date or status is None
            or status.disposition!=Disposition.ACCEPTED):
        return AprContextSelection(AprContextResult('unavailable',reason='numeric_terms_unavailable'),(),numeric_terms_observation_id,field)
    accepted=[]
    for row in observations:
        candidate=row['change'];payload=candidate.payload
        if (row.get('superseded') or candidate.operation==Operation.RETRACT or type(payload) is not AprContextPayload
                or candidate.subject_id!=loan_id or candidate.source.doc_id!=payload.document_id
                or candidate.effective.value!=effective_date
                or payload.loan_id!=loan_id or payload.numeric_terms_observation_id!=numeric_terms_observation_id
                or payload.effective_date!=effective_date or payload.field!=field):continue
        # Numeric and contextual facts must come from the very same capture.
        if payload.document_id!=change.source.doc_id or payload.capture_id!=change.source.doc_id:continue
        if payload.result.disposition=='accepted':
            terms=getattr(change.payload,'terms',None)
            anchor=terms.disclosure_apr.source if terms and terms.disclosure_apr is not None else terms.note_rate.source if terms and terms.note_rate is not None else None
            if anchor is None or payload.result.source!=anchor or candidate.source!=anchor:continue
            if payload.result.grounding.numeric_terms_observation_id!=change.observation_id:continue
            accepted.append((candidate.observation_id,payload.result))
    if not accepted:
        return AprContextSelection(AprContextResult('unavailable',reason='historical_absence'),(),numeric_terms_observation_id,field)
    identities={(result.value,result.source,result.grounding) for _,result in accepted}
    identifiers=tuple(sorted(identifier for identifier,_ in accepted))
    if len(identities)>1:
        if len(identifiers)>8:raise ValueError('resource_limit')
        return AprContextSelection(AprContextResult('conflicted',conflicts=identifiers),identifiers,numeric_terms_observation_id,field)
    return AprContextSelection(accepted[0][1],identifiers,numeric_terms_observation_id,field)
