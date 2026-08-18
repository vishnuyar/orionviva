# OrionViva — Working Documents

**State:** built
**Rules:** SPINE-1, SPINE-13, SPINE-2, SPINE-14, SPINE-3, SPINE-4

**[rules.md](rules.md) is the index of what is true today** — every rule in this folder, in one table, with its state and the test that pins it. Start there when the question is *what does this product actually do*. Come here, or to the document a rule names, when the question is *why*.

## Rules

### SPINE-1 — A document names no date
**State:** enforced
**Code:** none — the property is an absence, established by the test below rather than by any line of code
**Test:** product/tests/test_docs_track_the_code.py::test_a_document_names_no_date

1. No document under `docs/` names a date — not a "last updated", not an amendment date, not an "as of".
2. `docs/decisions/` keeps each ADR's decision date and status line, because an ADR records a moment on purpose, and `docs/archived/` is dated by nature. Both are exempt by where they sit rather than by being listed.
3. A date inside a citation's URL is not the document naming one.

### SPINE-13 — A document declares the rules it defines
**State:** enforced
**Code:** none — a structural property of the documents themselves
**Test:** product/tests/test_docs_track_the_code.py::test_a_document_declares_the_rules_it_defines

1. A document's **Rules:** line names exactly the rule ids its own `###` blocks define — no rule left unannounced, and no id left standing after a renumbering.
### SPINE-2 — An invariant is cited by the rule that bears on it
**State:** untestable
**Code:** none — which invariant a rule answers to is a judgement about meaning
**Test:** none

1. A rule that answers to a cross-cutting invariant names it, in the rule or in the argument beneath it.
2. Silence about a relevant invariant is a review failure rather than an oversight.
3. The citation sits at the rule, not in a header the whole document claims: a header says a document touches T5 somewhere, and cannot be wrong; a rule that cites T5 says which sentence answers to it, and can be.

### SPINE-14 — Every invariant a document cites is one that exists
**State:** enforced
**Code:** none — a property of the prose, not of any implementation
**Test:** product/tests/test_docs_track_the_code.py::test_an_invariant_a_document_cites_is_one_that_exists

1. Every invariant-shaped id cited anywhere in a live document resolves to a rule some document defines.
2. A citation inside a link target or a URL is not the document citing an invariant.

### SPINE-3 — No per-institution parsers
**State:** enforced
**Code:** product/viva/ingest/registry.py:1
**Test:** product/tests/test_pipeline.py::test_non_checking_is_parked_not_discarded

1. A new statement type becomes data — a registry row and a format profile — never a new code path named after a bank.
2. A document the registry cannot yet classify is parked and kept, never discarded and never guessed at.

### SPINE-4 — Authenticity uses no chain, token or on-chain mechanism
**State:** enforced
**Code:** product/viva/ledger/store.py:44
**Test:** product/tests/test_store.py::test_chain_detects_tampering

1. Tamper-evidence is a local hash chain plus external timestamps; the product mints no token and writes nothing on-chain.
2. A shared ledger, if one ever exists, is an additional anchor destination and never the authenticity mechanism.

## Why

This folder is the project's thinking made visible: discovery research, options considered, decisions made, and questions still open. Consistent with building in the open, these are honest work-in-progress documents — they record what is not known as prominently as what is.

A document that fuses rule, rationale and status forces every reader to replay its revision history before they can find today's rule, and a rule found that way is a rule nobody can test. Separating the three is what lets a test be written from a document and stay written: the rule is checkable and does not rot, the rationale never rots, and the status is quarantined where it can rot loudly.

**The format this folder follows.** A document opens with its state — `built`, `partial`, `design-only` or `superseded` — and the ids of the rules it defines. A rule states one checkable assertion in the present tense; the argument that produced it lives under *Why*, and anything that rots lives under *Open*.

Most of that is a convention, and deliberately stays one: whether a sentence is *one checkable assertion in the present tense* is a judgement, and a rule nothing can check is the thing this folder exists to stop producing. Two parts are not conventions, because they are the parts that rot silently and the parts a machine can hold — a document names no date (SPINE-1), and it declares the rules it defines (SPINE-13). The first is the whole property this rewrite bought: every document here accreted into a stack of amendments precisely because nothing stopped the next writer appending a date instead of revising a sentence.

**Where an invariant is cited.** The old format opened a document with an *Invariants touched* header. This one cites the invariant at the rule that answers to it. That is a strictly better claim — a header says a document touches T5 somewhere and cannot be falsified, while a rule citing T5 says which sentence answers to it and can be — and it turned out to be the better-populated one too: 29 documents still carry a header line, and 37 cite an invariant inside a rule. Where an invariant bears on a document's argument but on none of its rules, it is named in *Why* and cited nowhere, because a citation invented to preserve a header is exactly the kind of unfalsifiable sentence this folder is trying to stop keeping.

Rationale is the most valuable prose here and it is never deleted, only compressed. A rule with no argument behind it is a rule a future reader will argue with, or quietly delete, the first time it is inconvenient.

The ground rules are restated here so they are never out of sight: every extracted figure carries a source and a confidence signal (T1); arithmetic is deterministic and never done in a model's head (T2); local-first from commit one (T5); no per-institution parsers (SPINE-3); no chain, token or on-chain anything for authenticity (SPINE-4). When unsure, apply the decision heuristic, in order — does it increase trust in an answer, does it keep data and keys with the user, is it honest about what it knows, is it the simplest thing that works? A choice failing any of the first three does not ship, however clever.

**[rules.md](rules.md)** indexes every rule and its state, and is the one place to look for current truth. **[reading-guide.md](reading-guide.md)** is the single place document order lives; start there to read the argument in order. **[design-invariants.md](design-invariants.md)** is the full cross-cutting checklist, including the internationalization invariants.

**[decisions/](decisions/README.md)** holds the ADRs, and an ADR is a record of *reasoning*, not a report on current behaviour. It states the context, the alternatives, what was decided and what would reverse it. A decision standing in an ADR is not a claim that the code has met it — several have not, and one is contradicted outright. Whether a decision is met is the state column in [rules.md](rules.md), and nowhere else.

## Open

- The unchecked half of the document format — a **State:** header, assertions in the present tense, the argument under *Why* — is a convention nothing decided and nothing checks. It owes no ADR: SPINE-10 reserves those for one-way doors, and a documentation format is reversed by a script. Whether the rest is worth checking, or is better left a judgement, is open.
- Whether a rule cites the invariant it *should* cite is a judgement no test can make (SPINE-2, untestable). SPINE-14 holds the falsifiable half — every citation resolves — and the rest is review. The header line this replaced could not be wrong at all, which is why it went.
- [rules.md](rules.md) is still written by hand, but no longer unheld: `test_docs_track_the_code.py` parses every `### <id> — <name>` block and holds the index to it — membership, state, the no-test lists, and each state against the evidence it cites. What stays unheld is the prose around the tables: the counts under each list heading, and the contradictions table's own rows.
- Whether the archived banner and the superseded marker should also be machine-checked, given that both are load-bearing for a reader deciding whether a document describes the present.
