"""Typed APR field selection from an already bounded instrument source snapshot."""
from ..ledger.apr_context import project_context


def select_context(snapshot,*,loan_id,numeric_terms_observation_id,effective_date,field):
    return project_context(snapshot.observations,snapshot.component_states,loan_id=loan_id,
        numeric_terms_observation_id=numeric_terms_observation_id,effective_date=effective_date,field=field)
