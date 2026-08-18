# Knowledge & Expectations — where the domain rules live

**State:** partial
**Rules:** PROJ-19, PROJ-20, PROJ-21, PROJ-22, PROJ-23, PROJ-24

## Rules

### PROJ-19 — expectations are derived, never stored
**State:** enforced
**Code:** product/viva/knowledge/__init__.py:162
**Test:** product/tests/test_expectations.py::test_retirement_flow_raises_an_expectation

1. Every unmet expectation is derived on each projection from evidence already in the ledger.
2. No event type records an expectation.
3. `evaluate` is pure: the same events, registry and date give the same expectations.

### PROJ-20 — the registry is jurisdiction-tagged data, never a parser
**State:** enforced
**Code:** product/viva/knowledge/expectations-v1.json:1
**Test:** product/tests/test_expectations.py::test_jurisdiction_filters_the_registry

1. A registry entry names a universal mechanism, the document to pursue in plain words, the document types that satisfy it, and the jurisdictions it holds in.
2. No entry describes how to read a document.
3. An entry whose jurisdictions do not include the vault's raises nothing.

### PROJ-21 — an unknown mechanism fails loudly
**State:** enforced
**Code:** product/viva/knowledge/__init__.py:182
**Test:** product/tests/test_expectations.py::test_an_unknown_mechanism_in_the_registry_fails_loudly

1. A registry entry naming a mechanism the code does not hold raises, rather than being silently skipped.

### PROJ-22 — satisfaction is deterministic matching
**State:** enforced
**Code:** product/viva/knowledge/__init__.py:69
**Test:** product/tests/test_expectations.py::test_satisfaction_is_the_documents_arrival

1. An expectation is satisfied when one of its expected document types is present among the captured documents.
2. Matching is by the classifier's `doc_type`; no model opinion decides satisfaction.

### PROJ-23 — an unmet expectation is a ranked queue question and never a push
**State:** enforced
**Code:** product/viva/questions.py:643
**Test:** product/tests/test_expectations.py::test_cadence_expectation_ranks_below_money_and_names_the_edge

1. An unmet expectation reaches a person only as a question in the ranked queue, alongside every other question.
2. It is ranked by the money the document would attest; a cadence expectation carries zero and therefore ranks below every question that settles money.
3. Declining one suppresses it until its stake moves, through the queue's ordinary decline rule rather than a mechanism of its own.

### PROJ-24 — `check_completeness` reports what is held, not what is missing
**State:** enforced
**Code:** product/viva/tools/ledger_tools.py:1671
**Test:** product/tests/test_tools.py::test_completeness_counts_the_held_document

1. `check_completeness` reports documents held, documents posted, documents awaiting review, counterparties with no category yet, and each account's as-of date and grade.
2. It never consults the expectations engine, and never reports which statements are missing.

## Why

These "rules" are not instructions for reading documents — parsers are a
standing anti-goal, and models read. They are **expectations about what exists
in the world and how it relates**: completeness knowledge. An expectation is
just another kind of claim, so it flows through the trust machinery already
built — proposed, graded, confirmed by evidence or by the person, enforced
deterministically.

The layer has three tiers, and only the first two are built.

**Tier 1, mechanisms** — a handful of gears, true everywhere, knowing nothing
about any document type. Every account carries an expected document cadence, so
gaps are computable. Every recurring flow to an external destination implies a
counterpart account. Every inferred entity carries a grade and a source, like
any fact. Satisfaction is deterministic matching, never model opinion.

**Tier 2, the knowledge registry** — declarative, jurisdiction-tagged entries: a
table, not a codebase. Entries state what exists and relates, never how to parse
anything. They are versioned like normalization rules, and jurisdiction tags
make a German or Indian entry set a **knowledge pack** — the same pattern as
benchmark packs and the taxonomy (I6). The registry ships small and grows from
confirmations and community contributions rather than from anyone's attempt to
foresee finance.

**Tier 3, model world knowledge** — at ingestion the understanding model could
propose expectations beyond the registry ("solar loans typically issue annual
interest statements"), entering as low-grade expectation claims that promote
into personal knowledge on confirmation. Deliberately unbuilt; inferred accounts
are deferred with it. The shape is: the model proposes, the registry remembers,
tier 1 enforces.

The motivating pattern is one sentence: **documents are evidence that other
documents exist.** A pay stub showing a 401(k) deduction is evidence that a
retirement account and its quarterly statements exist. A mortgage statement with
an escrow line is evidence that an escrow analysis and a 1098 exist. That turns
every arrival into a checklist for the rest of the financial life, so organizing
and consolidating becomes *pursued* rather than passively received — without
nagging.

Deriving read-side rather than emitting events is the read-early/write-late
principle applied at its cheapest point: nothing to migrate, and a wrong entry
is fixed by editing data. The two states that need memory already have it —
*declined* is the decline event, and *satisfied* is the expected document's
arrival. No new agent tool was needed either, which was the scaling law's first
real test: a whole new subsystem, zero new verbs.

The boundaries this layer must never cross are the reason it stays small. Never
a parser: no entry may describe how to read a document. Never a nag: unmet
expectations are queue state, never a push. Never silent: an inferred account is
always visibly labeled as inferred, with its evidence, and never quietly becomes
real without linkage or confirmation. Never load-bearing for money math:
expectations affect completeness honesty, not balances.

The queue is the only surface. There is no dashboard and no separate renderer
anywhere in the product, and `check_completeness` answers for what the agent
holds rather than for what it lacks — the two reads are kept apart so that one
number never contradicts the other.

Invariants this leans on: T1 (inferred accounts and expectations are graded,
cited claims), T2 (expectation evaluation is deterministic), I5/I6 (knowledge is
jurisdiction-tagged data in community-extensible packs), X2 (unmet expectations
are visible quiet state, honestly labeled).

## Open

- Tier 3 is unbuilt: model-suggested expectations, and the inferred accounts
  deferred with them.
- Registry seed size: it holds three entries against the document types the
  corpus actually produces. Resisting encyclopedism is the rule; the tiers are
  meant to grow it.
- Upstreaming mechanics: how a personally-confirmed tier-3 pattern becomes a
  registry contribution without leaking personal detail. Entries must be generic
  by construction.
- Dismissal semantics: "I don't have a 401(k) anymore" should dismiss the
  expectation *and* be remembered, so it does not resurrect from the next pay
  stub. That interplay with memory is undecided.
