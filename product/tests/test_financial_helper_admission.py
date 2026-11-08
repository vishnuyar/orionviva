"""Financial helper bytes belong to the existing implementation admission identity."""
from pathlib import Path
from hashlib import sha256
import pytest
from viva.answer_program.intents import SemanticFamilyRegistry

HELPERS=(
    ('viva.ingest.cash_source_pages','viva/ingest/cash_source_pages.py'),
    ('viva.ledger.projection.investment_snapshots','viva/ledger/projection/investment_snapshots.py'),
    ('viva.read_store.investment_bindings','viva/read_store/investment_bindings.py'),
)


@pytest.mark.parametrize('module,relative',HELPERS)
def test_financial_helper_mutation_changes_admitted_implementation(module,relative,tmp_path,monkeypatch):
    key='foundation_dependency:'+module
    original=SemanticFamilyRegistry._admitted_source_only_paths
    actual=original({key:(module,relative)})[key]
    before=SemanticFamilyRegistry._admitted_implementation_digests()
    assert key in before
    assert before[key]==sha256(actual.read_bytes()).hexdigest()[:16]
    replacement=tmp_path/'synthetic_helper.py';replacement.write_bytes(actual.read_bytes()+b'\n# Synthetic changed source bytes.\n')
    def resources(values=None):
        paths=original(values)
        if key in paths:paths={**paths,key:replacement}
        return paths
    monkeypatch.setattr(SemanticFamilyRegistry,'_admitted_source_only_paths',staticmethod(resources))
    after=SemanticFamilyRegistry._admitted_implementation_digests()
    assert after[key]==sha256(replacement.read_bytes()).hexdigest()[:16]
    assert before[key]!=after[key]
    assert {k:v for k,v in before.items() if k!=key}=={k:v for k,v in after.items() if k!=key}
