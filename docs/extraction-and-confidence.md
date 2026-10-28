# Extraction & Calibrated Confidence

**State:** built
**Rules:** ING-1, ING-2, ING-3, ING-7, ING-4, ING-5, ING-6

## Rules

### ING-1 — Confidence is constructed, never self-reported
**State:** by-review
**Code:** product/viva/ledger/events.py:61 (grades are set by deterministic checks downstream), product/viva/ingest/statement_projector.py:361
**Test:** none

1. A figure's grade is assigned by deterministic code after a check runs, never copied from a number the model produced.
2. The model's own `doc_type_confidence` is stored as a claim on the document and never becomes, gates, or modifies any grade.

Brokerage extraction requests `investment-source-v2` through the versioned
`brokerage-base-v7` prompt. Its raw fields and genuine rendered pages are claims,
not verification. References, role wording, explicit no-activity assertions and
separate exposure/vehicle classifications must come from the printed source;
the model does not create canonical ids, grades or accepted funding witnesses.
The request copies a separately printed holding identifier exactly into both
ordinary and source fields. Activity correspondence uses only that activity
row's printed security token; a holding cannot supply an unprinted activity
identifier. Names remain labels and descriptions retain their printed wording.
Missing identifiers remain missing, so evidence can still be unavailable.
Existing numeric, page, multiplicity and opposing-source checks still determine
what the read surfaces may use. Historical absent-extension and source-v1 reads
remain supported. Deterministic prompt/parser tests do not establish model
compliance; live source comparison and fresh exact qualification are still owed.

### ING-2 — The grade vocabulary is closed and four-valued
**State:** enforced
**Code:** product/viva/ledger/events.py:63-67
**Test:** product/tests/test_postings.py::test_posting_rejects_unknown_grade

1. The only grades are `verified`, `corroborated`, `unverified`, `conflicted`.
2. Constructing a posting with any other grade raises rather than defaulting.

### ING-3 — What each grade means
**State:** enforced
**Code:** product/viva/ledger/events.py:63-67 · product/viva/ingest/statement_projector.py:361 · product/viva/ledger/projection/balances.py:99, :110
**Test:** product/tests/test_pipeline.py::test_checking_statement_posts_and_reconciles, product/tests/test_tool_contract.py::test_balances_match_the_projection_and_carry_grades

1. `verified` means an issuer's document attests the figure and nothing is in doubt about how it was read — a lone attested closing, or an attested figure whose reading a person has confirmed.
2. `corroborated` means two independent observations agree — including an opening plus a period's transactions reconciling to an attested closing.
3. `unverified` means asserted or derived with nothing having checked it.
4. `conflicted` means observations disagree; it is surfaced and never averaged away.
5. Passing an arithmetic identity earns `corroborated`, never `verified`: two routes agreeing is agreement, not attestation.

### ING-7 — A person's word is its own rung, below agreement
**State:** unmet
**Code:** none found — the ladder is four rungs (product/viva/ledger/events.py:67), and a figure standing only on the person's word is graded `verified` today (product/viva/ledger/networth.py:175, :272)
**Test:** none

1. A figure that exists only because the person said so is graded `asserted`, never `verified`.
2. The ladder runs `verified` > `corroborated` > `asserted` > `unverified`. A person's word is not a check, and is stronger than a derivation nothing looked at.
3. `asserted` is not trustworthy for the purposes of an answer's headline grade.
4. A person confirming a figure an issuer's document already attests leaves it `verified` — confirmation settles the reading, it does not replace the attestation.
5. Every rung carries one reviewed sentence, so `asserted` reaches a person in words saying the figure stands on their word alone.
6. Net worth's provable subtotal is decided by a figure's origin, not by borrowing the grade to sort it.

### ING-4 — A claim's identity is its value and position, never its label
**State:** contradicted-by-code
**Code:** bench/vivabench/keybuild.py:113
**Test:** none

1. Two extractions of the same document are matched on printed value and page position.
2. A model-authored label is a free-text annotation and is never a join key.

**Contradiction:** this doc records the measured finding that label-matching manufactures false conflicts — two frontier drafters matched by `(type, normalized label)` scored ~21% agreement on one document, and the same pair re-matched by value agreed on 99–100% of amounts. The rule that follows is above. `bench/vivabench/keybuild.py:113` still indexes drafts as `indexed[(c.type, _norm_label(c.label))]`, joining on the normalized label, and `bench/vivabench/keybuild.py:99-101` documents that grouping as the intended behaviour.

### ING-5 — Deterministic cross-checks decide, to the cent
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:44 (`check_balance_identity`), :71 (`check_paystub_identity`), :98 (`check_brokerage_identity`)
**Test:** core/tests/test_arithmetic.py::test_balance_identity_catches_one_cent, core/tests/test_arithmetic.py::test_explicit_tolerance_is_honored_but_never_default

1. A document's own arithmetic identity is checked in Decimal, with a tolerance of zero unless one is passed explicitly.
2. A float reaching the check raises rather than being coerced.

### ING-6 — Every stored figure carries a source pointer
**State:** by-review-with-exception
**Code:** product/viva/ledger/events.py:39 (`Provenance`), product/viva/ingest/statement.py:37
**Test:** none

1. Every figure written to the ledger carries a `Provenance` naming the document it came from.
2. The pointer names the page the figure was read from where the model reported one.

**Exception:** `Provenance.region` (product/viva/ledger/events.py:45) is declared as "a bounding-box id or text anchor within the page" and is never populated anywhere in ingest — no extraction prompt asks for a region and no code writes one. Provenance today resolves to document and page, not to a spot on the page.

## Why

**One word was doing two jobs, and the second one was invisible.** The ladder has a
single axis — how strongly a figure is checked — but the evidence has two: how
strong the check is, and *who stood behind it*. `corroborated` is a pure point on
the first axis. `verified` was being asked to mean both "an issuer attests this"
and "the person told me", which are different in kind: an issuer cannot be wrong
about what it printed, and a person can be wrong about what their car is worth.

The cost was not theoretical. The sentence the machine places on an answer whose
weakest figure is `verified` reads *"every figure in it is attested by the
document it came from"*. A figure that exists only because the person said so
carries that sentence today (`product/viva/ledger/networth.py:272`, whose own
comment reads "Their word, which no document has checked"), so a person is told
a document attests a number they invented. That is X2 failing at the one place
X2 was strengthened to protect.

Three readings of `verified` were live at once. One of them — that a figure earns
`verified` by passing an arithmetic identity — is simply wrong, and this document
was where it was written: two routes agreeing is agreement, and the code has
always posted `corroborated` there. The other two are the real distinction, and
they get a rung each (ING-7).

Confirmation is not the same as assertion, and the ladder must not flatten that
either. A person confirming a reading of an issuer's document removes the last
doubt about an attested figure, which is why it *raises* a reconciled balance to
`verified`. A person supplying a figure no document mentions is standing alone.
The first is attestation settled; the second is `asserted`.


Models bluff. A self-reported "confidence: 0.95" is a generated token, not a
measurement, and the training objectives that produce frontier models reward
confident guessing over calibrated uncertainty. So the design question is never
"how do we get the model to say how sure it is" — it is "how do we *construct* a
trustworthy confidence signal around a model that cannot report one."

Financial documents make that possible in a way most extraction domains do not:
they are self-auditing. Opening balance plus transactions equals closing
balance; line items sum to totals; a statement's closing balance is the next
month's opening. Every such check that passes is proof rather than inference.
That arithmetic ground truth is this product's structural advantage, and it is
why verification — not the model — is the thing that grades a figure.

Ranked by what the evidence supports, the signals available are: deterministic
cross-checks (strongest, and model-free); sample disagreement across repeated
extractions, which is mechanical doubt rather than opinion; cross-model
agreement, which is stronger than one model agreeing with itself because
self-consistent errors are a documented failure mode; schema discipline, where a
missing source triggers a refusal path in code rather than a hedge in the
answer; and post-hoc calibration of token logprobs, which needs accumulated
ground truth before it means anything.

The architecture that falls out is **extract → verify → reconcile → store**,
with confidence as an output of verification. The model perceives; deterministic
code certifies; storage keeps the figure, its source pointer, its grade and the
trail of which checks ran. The trail is what lets the product say *why* it is
sure rather than only that it is.

The user-facing half of that follows from the storage half: confidence language
in any answer maps one-to-one onto verification grades, and an answer inherits
the weakest grade of any figure it stands on. That is invariant X2 and the
composition half of T1 — enforced on the answering path, not here — and it is
what turns "never bluff a number" from a prompt instruction into a property of
the system.

Matching two reads by label rather than by value is the mistake that looks like
a disagreement crisis and is in fact a vocabulary difference: one model writes
`"<ticker> proceeds"` where another writes `"proceeds"`, identical values land
in different buckets, and a human auditor is buried in phantom work. Identity
belongs to the value and its position on the page, because those are what the
issuer printed.

Cross-model agreement is also what preprocessing most improves: feeding two
models the issuer's own characters rather than pixels moves their agreement on
non-Latin number grouping by roughly thirty points, which is the difference
between the answer-key design working on international documents and needing
constant human audit. The measured results are in
[document-preprocessing.md](document-preprocessing.md).

N-sample extraction costs N× inference, which is acceptable precisely because
documents are ingested rarely and queried often. Extraction is where the money
goes; queries then run against data that has already been verified.

## Open

- **ING-7 is a ruling, not a build.** The rung is decided and nothing implements
  it: `GRADES` is still four, and the two sites that grade a figure standing only
  on the person's word (`product/viva/ledger/networth.py:175`, `:272`) still say
  `verified`. Landing it needs its own cycle — the constant, the ordering in
  `weakest`, the reviewed sentence X2 requires for the new rung, and net worth's
  provable subtotal reading `origin` instead of borrowing the grade to sort by.
- **The grade may want to stop being one axis at all.** The end state ING-7
  approximates is two: evidence strength on the grade, and the attestor —
  issuer, person, machine — travelling on every figure rather than only on an
  account, where `ORIGINS` lives today (`product/viva/ledger/events.py:157`).
  The rung is the smallest change that makes the spoken sentence true; the
  second axis is the change that would make the distinction impossible to lose
  again. Undecided, and deliberately not settled by ING-7.
- **`asserted` needs its own reviewed sentence before it can reach anyone.** A
  build check holds the ladder and the persona pack's sentences to each other in
  both directions, so the rung cannot ship without one being written and
  reviewed. That is the machinery working, and it is also the long pole.

- Do arithmetic identities cover most figures on real statements, or is coverage patchy on documents such as brokerage statements with implied but unstated totals?
- How often do N samples agree on a wrong figure, and what is the cross-model disagreement rate on exactly those cases?
- Can models reliably report a source region (page plus bounding area) well enough for click-through provenance, and what does the answer cost?
- What N buys what error rate, at current inference prices, per statement?
- Schema discipline on the source pointer: an empty `source` is meant to trigger a refusal path in application code, never a shrug in the answer. Nothing enforces it — a missing page degrades to `None` at parse time, and a figure carrying no record ids is built without complaint. ING-6 requires the pointer to exist; it does not refuse the read that arrives without one.
- `conflicted` and `unverified` figures need a correction surface a person can use in one tap; those corrections are also the seed of the personal memory moat.
- Does the four-grade vocabulary survive contact with more document types? Keep it small either way.
- The three conflicting definitions of `verified` (ING-3) need one ruling, and the ruling has to name which of the doc or the code moves.

## Sources

- [Lakera: LLM hallucinations 2026 guide](https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models)
- [FutureAGI: reducing hallucinations, structured-output patterns](https://futureagi.com/blog/taming-hallucination-beast-strategies-reliable-llms/)
- [Too Consistent to Detect: self-consistent errors in LLMs](https://arxiv.org/pdf/2505.17656)
- [BaseCal: unsupervised confidence calibration](https://arxiv.org/pdf/2601.03042)
- [Calibrating LLM confidence via perturbed representation stability](https://arxiv.org/pdf/2505.21772)

## Mortgage principal source representation

The mortgage-principal-source-v2 reader distinguishes a printed positive magnitude from a signed
principal-balance effect. A signed row retains its exact scalar/page, explicit
kind and supporting page, plus the literal principal_balance_effect-v1 basis.
The backend records mortgage-principal-source-v2 in normalization context schema2;
other families retain schema1 and numeric normalization remains nv1. Only a
finite nonzero signed effect agreeing with the explicit kind becomes a positive
canonical magnitude. Payment and escrow semantics, financial checks and grades
are unchanged. Supporting-page pointers remain proposals, not certified readings.

Immutable raw replies and context preserve that distinction. Old contexts and
mortgage v1 replies keep their old interpretation, including old failures; new
contract/prompt mismatches reject. Full replay validates the retained source
against the captured document's rendered page bounds before acceptance. A
preliminary parse without a rendered page count does not establish that check.
See [ADR-019](decisions/ADR-019-mortgage-principal-source-representation.md).

The active reader combines immutable mortgage-base-v2 with mortgage-v3. The
fragment clarifies escrow.identity's three printed fields separately from the
loan identity. A common institution or holder header can supply a field only
when its printed scope unambiguously includes escrow. Missing, unreadable,
competing or ambiguously scoped fields leave the entire escrow identity null;
other readable escrow components remain. Only the explicitly printed escrow
account identifier supplies its reference: loan, payment, property and
continuity references cannot substitute. No institution or holder is inferred
from a lender name, balances, matching references or another document.

The source contract remains mortgage-principal-source-v2 with the complete
base-v2 schema and schema2 context unchanged. Both exact base-v2/fragment-v2 and
base-v2/fragment-v3 pairs retain their finite unique support suffixes; all other
new-contract pairings reject. Historical v2 replay, signed-principal kind/sign
and page checks, escrow arithmetic, identity resolution and unique cash
counterpart requirements remain unchanged. Identity text/page survive parsing;
numeric/date scalars normalize, with their original text in the retained raw
response. Accepted escrow allocation does not create duplicate household cash.

Offline handcrafted replies test this machinery, not actual-model compliance.
Fresh exact-candidate qualification and authorized browser Witness comparison
of the three public sources, missing/ambiguous-header controls, saved originals
and allocation remain owed before any live-success claim.

The brokerage v7 request copies both ordinary and typed cash-effect raw strings
from the same printed settled row without removing or inventing a sign. Local
ordinary parsing still interprets a magnitude; typed source raw stays exact.
The v6 security/row correspondence rules and historical prompt bytes remain.

Term-deposit fragment v2 asks for the full applicable printed withdrawal
restriction clause rather than an adjacent status token when both are printed.
It preserves scope, conditions and any printed destination without paraphrase
or combining clauses. Token-only sources keep their literal; absent or ambiguous
clauses use null/omission. Existing schema, source pages, parser and financial
availability rules do not change. Older token proposals remain their original
literals; they are not rewritten into prose. Actual model fidelity, complete
source comparison and financial answers still need exact-candidate qualification
and Witness evidence; these prompt changes do not establish them.
