# Doc-Type Registry & Format Profiles — how new statement types become data

**State:** built
**Rules:** ING-32, ING-33, ING-34, ING-35, ING-36, ING-37, ING-30, ING-31
**Invariants touched:** T1 (provenance per extracted field), T2 (a verification identity per type, run by universal code), T4 (profiles are versioned; a re-read is an event and nothing is overwritten), I5 (no country- or institution-shaped tables — format specifics are profile data), X2 (a type the model cannot yet read is parked honestly). Serves the "code universal, specifics are data" doctrine.

## Rules

### ING-32 — Classify first, then extract with that type's profile
**State:** enforced
**Code:** product/viva/ingest/reader.py:62 (`classify`), :100 (profile lookup), :104 (park after classify)
**Test:** product/tests/test_reader_two_phase.py::test_unsupported_type_records_only_the_cheap_classify

1. A read is two passes: a cheap classify pass over the first page plus embedded text names the type, then an extract pass runs the prompt that type's profile owns.
2. The classify pass asks for a type and never for figures.
3. A classified type with no projector is parked after the classify pass, and no extraction is paid for.
4. The classification is authoritative for the document type and is stamped onto the extracted facts.

### ING-33 — We own the schema; the model owns the reading
**State:** enforced
**Code:** product/viva/prompts/extract-base-v1.txt (the shape we ask for), product/viva/ingest/statement.py:243 (`from_model_json` accepts only that shape)
**Test:** product/tests/test_prompt_library.py::test_no_prompt_text_lives_in_code

1. The extraction shape is fixed by us and lives as versioned prompt data, not as code and not as a model's choice.
2. The model fills the shape; it never decides what to extract.

### ING-34 — A profile may be model-authored, but is ratified before it is used
**State:** unmet
**Code:** none found
**Test:** none

1. A frontier model may read a genuinely new format once and propose a profile — fields, identity check, labels.
2. The proposal is ratified by cross-model agreement or a human ruling, and frozen with a version, before any read uses it.
3. A model never owns the schema at read time.

_Profiles are authored by hand today. The versioning the rule depends on exists; the authoring loop does not._

### ING-35 — The verification identity is universal code; the per-type formula is data
**State:** enforced
**Code:** product/viva/ingest/registry.py:28-35 (identities as constants), :55 (`identity` is a profile field), core/vivacore/verify/arithmetic.py:44
**Test:** product/tests/test_registry.py::test_whole_balance_family_shares_one_identity, product/tests/test_pipeline.py::test_new_balance_type_via_registry_row_only

1. `opening + Σ(effect on the printed balance) = closing` reconciles checking, savings and credit card alike, because a card is a liability whose effect on balance inverts.
2. A transaction's sign is its effect on the printed balance, which makes the identity account-kind-agnostic; `kind` is a separate interpretation attribute.
3. A divergent family supplies its own identity as a profile field, and is run by the same gate rather than by new gate code.

### ING-36 — Personal knowledge and format knowledge are kept strictly apart
**State:** by-review
**Code:** product/viva/ingest/registry.py:67-106 (rows hold type names, kinds, identities and prompt version ids only)
**Test:** none

1. Personal knowledge — accounts, aliases, categories, corrections — never leaves the machine.
2. Format knowledge — how an institution formats a statement — is impersonal, being about the document rather than about the money, and is shareable.
3. A profile contains no personal data of any kind.

### ING-37 — A profile is versioned, and every read records the version that produced it
**State:** enforced-with-exception
**Code:** product/viva/ingest/prompt_library.py:60 (`compose_extraction` yields `extract:<base>+<fragment>`), :71 (`resolve` reconstructs any recorded version), product/viva/ingest/brokerage_projector.py:124 (one `ReadRecorded` per phase)
**Test:** product/tests/test_prompt_library.py::test_active_versions_are_frozen, product/tests/test_prompt_library.py::test_a_missing_version_raises_rather_than_defaulting, product/tests/test_prompt_library.py::test_resolve_round_trips_every_kind_of_version

1. Prompt files are append-only: changing a prompt means adding a new id, never editing a released one.
2. A recorded `prompt_version` resolves to the exact text that produced the reading, and resolving an unknown version raises rather than falling back to current text.
3. Each phase of a read records its own prompt version, so a read is reproducible and its profile version is known.

**Exception:** the *surgical* re-read is not built. Nothing compares a document's stored `prompt_version` against the version in force — `product/viva/reingest.py:65` reads that field only to recover a missing doc type. What exists is narrowing, not selection: `--only <doc_type>` confines a run to one document family and `--dry-run` prices it before a cent is spent (product/viva/reingest.py:83-89, test: product/tests/test_registry.py::test_reingest_can_filter_to_one_document_family_and_cost_nothing_first). Choosing which documents are stale is still the operator's job.

### ING-30 — A held document is polymorphic, and consumers route on the registry
**State:** by-review
**Code:** product/viva/ingest/registry.py:143 (`identity_of_facts`), product/viva/ingest/statement_projector.py:73, :118, product/viva/ingest/brokerage_projector.py:147
**Test:** none

1. Anything that walks the held set asks the registry which identity a facts blob belongs to before constructing a typed object from it.
2. No consumer assumes a held document has a balance-family shape.

### ING-31 — Account kind is derived by the registry, never asked of the model
**State:** enforced
**Code:** product/viva/ingest/registry.py:130 (`account_kind_for`), :37-40 (the kinds)
**Test:** product/tests/test_registry.py::test_card_is_a_liability_savings_is_depository, product/tests/test_pipeline.py::test_credit_card_statement_posts_as_a_liability_owed

1. `depository`, `liability` and `investment` are this system's interpretation of an account, looked up from the classified type.
2. Kind drives display — held versus owed — and the kind-aware counter-leg; the model is never asked for it.

## Why

The v0 pipeline hardcoded one projector. Holding a whole financial life needs
many statement types, and the claim the entire architecture rests on is that
adding one is **data**, not a code change. Everything here exists to make that
claim true for types nobody has thought of yet, not merely for the next two.

Reading after classifying, rather than with one mega-prompt, is forced by the
fact that the shapes genuinely diverge: checking is a balance plus transactions,
brokerage is positions times price plus cash, a pay stub is gross minus
deductions equals net, a 1099 is boxes, an insurance policy is provisions. A
single prompt covering all of them gets worse at each as more are added. So the
read is a cheap classification followed by the type's own extraction profile.
The balance family shares one base shape while each type contributes its own
fragment — what the balance means, and that type's completeness traps —
composed at read time, so a card's "payments live in a separate section" hint
never pollutes a checking read.

We own the schema because deterministic verification requires a known shape. You
cannot reconcile a free-form extraction, and you cannot catch a *silent
omission* in one at all: nothing is missing from a shape nobody declared. The
model perceives — pixels and text become the fields we asked for — and never
decides what to extract. That is the CaMeL split one level up, and the reason
the schema is data rather than code is that a data schema can be versioned,
recorded on the read, and re-read from.

The verification identity being universal code, with the per-type formula as
data, is what makes a new balance-shaped type a registry row. Framing a
transaction's sign as its effect on the *printed* balance is what unified the
family: a card's `previous + charges − payments = new` is the same identity as a
checking account's, and the reframe is value-preserving for checking, so nothing
already read had to move.

Keeping personal knowledge and format knowledge apart is what makes a commons of
profiles possible at all without breaking local-first. Your accounts, aliases
and corrections are the moat and never leave. How a bank lays out a statement is
a fact about the document, not about the money, and can be shared. Because
profiles were versioned, self-contained and personal-data-free from the start,
that sharing channel is a later *addition* rather than a redesign.

Versioning pays for itself twice: a recorded reading stays reproducible after
its prompt is superseded, and a profile that gains a field can re-read only the
documents an outdated profile read. The second half of that — selecting which
documents are stale — is the piece still missing.

A held document is polymorphic, and skipping that step is not a graceful
failure. A corroboration heal once rebuilt every conflict-hold as a
balance-family facts object and died on a held brokerage statement, which has no
opening balance at all: one document of an unexpected shape took down a pass
that had nothing to do with it. Routing on the registry rather than on the shape
of the data is the rule that prevents it.

Several later seams are deliberately left open. A card payment corresponds to a
checking withdrawal, and that cross-account link belongs to transfer linking on
the same graded-finding and correction pattern — card ingest must not guess it.
Net worth is a projection over posted data, so a card showing as *owed* composes
in later with no migration. Obligations will want the card's credit limit,
minimum payment and due date, which is a profile version bump and a targeted
re-read rather than a redesign. And format authoring, when it comes, reuses the
trust pattern already in use everywhere else: a model proposes, cross-model
agreement or a human ratifies, and the result is frozen and versioned.

## Open

- Model-assisted profile authoring (ING-34) is unbuilt: today a new format is a hand-written profile.
- Surgical re-read selection: nothing compares a document's stored profile version against the one in force, so an operator still chooses which documents a prompt change made stale.
- No test pins ING-36 — that a registry row can never hold personal data is true by inspection and unchecked by the build.
- The format commons as a sharing channel over these profiles is designed and unbuilt; see [format-commons.md](format-commons.md).
- Divergent families beyond pay stub and brokerage — tax forms, insurance declarations — will test whether "a new type is a registry row" survives a shape with no arithmetic identity at all.
