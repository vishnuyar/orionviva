from dataclasses import replace
import copy
import pytest
from test_payroll_counterpart import setup
from viva.investment.events import _validated_statements
from viva.investment.payroll import FundingValidationContext
from viva.investment.contracts import EvidenceError
from viva.ledger.postings import simple_transaction


def test_ephemeral_context_reuses_only_exact_authenticated_prefix(tmp_path):
 ledger,f,account=setup(tmp_path);events=tuple(ledger.events())
 context=FundingValidationContext(events,_validated_statements(events))
 first=context.records(events,'2021-01-31')
 assert context.records(tuple(events),'2021-01-31') is first
 assert context.records(events,'2020-12-31') is not first
 for changed in (events[:-1],(*events,simple_transaction('checking','1','extra','2021-02-01'))):
  with pytest.raises(EvidenceError,match='prefix changed'):context.records(changed,'2021-01-31')
 event=events[0];changed=(replace(event,body={**event.body,'institution':'mutated'}),*events[1:])
 with pytest.raises(EvidenceError,match='prefix changed'):context.destinations(changed,'2021-01-31')
 # In-place body mutation is also detected; no event identity shortcut.
 changed=copy.deepcopy(events);changed[0].body['institution']='mutated'
 with pytest.raises(EvidenceError,match='prefix changed'):context.records(changed,'2021-01-31')
