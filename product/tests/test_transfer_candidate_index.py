"""Exact candidate graphs retain old rivals while avoiding unrelated amounts."""
from decimal import Decimal
from types import SimpleNamespace

from viva.ingest import transfers
from viva.ledger.events import Provenance
from viva.ledger.projection.movements import MovementInfo


def movement(key, amount, *, currency='USD', date='2021-01-10', account=None,
             kind='depository', linked=False):
    return MovementInfo(key, account or key, kind, date, Decimal(amount), '',
                        currency, Provenance(), linked=linked)


def legacy_candidates(rows):
    sources = [m for m in rows if not m.linked and transfers._flow(m) == 'source']
    dests = [m for m in rows if not m.linked and transfers._flow(m) == 'destination']
    graph = {}
    for source in sources:
        matches = [dest for dest in dests if transfers.is_transfer_candidate(source, dest)]
        if matches:
            graph[source.key] = matches
    return graph, {source.key: source for source in sources}


def test_exact_candidate_graph_and_ambiguous_rivals():
    rows = [movement('old-source', '-10'), movement('new-source', '-10.00'),
            movement('a', '10.0', date='2021-01-05'),
            movement('b', '-10', kind='liability', date='2021-01-15'),
            movement('too-late', '10', date='2021-01-16'),
            movement('bad-date', '10', date='invalid'),
            movement('other-currency', '10', currency='EUR'),
            movement('same-account', '10', account='old-source'),
            movement('linked', '10', linked=True), movement('zero', '0')]
    projection = SimpleNamespace(movements=lambda: rows)
    actual = transfers._candidates(projection)
    assert actual == legacy_candidates(rows)
    graph, _ = actual
    strengths = {(source, dest.key): 3 for source, dests in graph.items() for dest in dests}
    assert transfers.decide(graph, strengths) == {}


def test_unrelated_amounts_do_not_enter_pairwise_gate(monkeypatch):
    rows = [movement(f's{i}', str(-i)) for i in range(1, 41)]
    rows += [movement(f'd{i}', str(i)) for i in range(1, 41)]
    expected = legacy_candidates(rows)
    original = transfers.is_transfer_candidate
    calls = []
    def counted(source, destination):
        calls.append((source.key, destination.key))
        return original(source, destination)
    monkeypatch.setattr(transfers, 'is_transfer_candidate', counted)
    assert transfers._candidates(SimpleNamespace(movements=lambda: rows)) == expected
    assert len(calls) == 40
