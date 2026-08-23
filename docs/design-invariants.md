# Design Invariants — the checklist every decision answers to

**State:** partial
**Rules:** T1, T2, T3, T4, T5, T6, T7, T8, T9, I1, I2, I3, I4, I5, I6, M1, M2, X1, X2, X3, SPINE-12

## Rules

### T1 — Provenance, grade, exactness and boundary on every figure
**State:** enforced-with-exception
**Code:** product/viva/tools/envelope.py:139 · product/viva/tools/runner_binding.py:281
**Test:** product/tests/test_shape_binding.py::test_a_figure_that_states_no_set_fills_no_hole_asking_for_one

1. Every number a tool asserts is emitted as a figure with an id, and an answer cites the id rather than restating the value.
2. A figure declares its kind. `financial` and `computed` carry a grade; `activity` (what the agent did or holds on record) and `hypothetical` (a value resting on the person's own premise) carry none and cannot acquire one by composition.
3. What sorts a count into a kind is *what would a wrong number here move?* — the person's money makes it financial, the agent's account of its own records makes it activity.
4. A grade is inherited from a figure's operands and never declared by its caller; a grade outside the ladder raises where the figure is written.
5. `grade` and `record_ids` say what a value rests on; `exactness` says whether the derivation terminated. Exactness carries no evidentiary meaning and never moves a grade.
6. Scaling an attested quantity by a bare magnitude preserves attestation; adding an unattested term leaves the total standing on no record, so it carries no grade at all.
7. A figure declares the set of axes it is the intersection of; a magnitude hole declares the set its sentence narrows on; a binding holds only on set equality in both directions.
8. A figure that declares no boundary fills no hole that declares one — silence is *unknown*, never *everything*.
9. Arithmetic composes a boundary: identical operand boundaries are inherited, differing ones give a number over neither set, a literal contributes none and removes none.
10. Where a clause states a figure and names, through a hole, a thing of a kind that figure was cut by, the figure's own boundary names what the clause names, on every axis.

**Exception:** `figure()` accepts a money-kind figure with an empty grade — product/viva/tools/envelope.py:181. Nothing at the emitter requires a claim about money to say what stands behind it.

### T2 — Arithmetic is deterministic; models never certify
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:1
**Test:** core/tests/test_arithmetic.py::test_float_poison_rejected

1. Every verification identity is exact `Decimal` arithmetic in inspectable code; a float raises rather than being coerced.
2. No confidence grade, reconciliation result or arithmetic answer is produced inside a model's forward pass.
3. Tolerance is explicit per check, defaults to zero, and is recorded in the result.

### T3 — Capture-first
**State:** enforced-with-exception
**Code:** product/viva/ingest/raw_store.py:51 · product/viva/ledger/events.py:271 · product/viva/ingest/pipeline.py:104
**Test:** product/tests/test_raw_store.py::test_put_is_content_addressed · product/tests/test_capture_first.py::test_the_raw_blob_is_stored_before_the_reader_is_called, ::test_a_reader_that_raises_does_not_take_the_document_with_it

1. Every original document is written, encrypted and content-addressed, before anything parses it.
2. Every model response is captured verbatim with the model and the prompt version that produced it.
3. Nothing trust-relevant is ever pruned, summarized in place, or cleaned up.

**Exception:** the ingest path records no request field of any kind — product/viva/ledger/events.py:271. It takes the position that a request is reconstructable from the stored document plus the immutable prompt version, which is faithful in content and not in bytes. The answering path stores the request verbatim (product/viva/session.py:90), so the gap is a choice rather than a limit.

### T4 — Everything is an event
**State:** enforced-with-exception
**Code:** product/viva/ledger/store.py:95 · product/viva/ledger/store.py:153
**Test:** product/tests/test_store.py::test_the_chain_verifies_without_the_passphrase

1. Every state change is an event in an append-only log; each record embeds the previous record's hash.
2. Current state is a rebuildable projection of the log and is never independently authoritative.
3. The chain verifies without the encryption key.
4. The log assumes multiple writers, so a second device is a sync problem and never a schema problem.
5. The chain head is anchored to two independent external timestamps.

**Exception:** assertion 5 has no implementation. No OpenTimestamps call, no RFC 3161 call, no periodic job and no anchor-lag record exists anywhere in the tree; `EventStore.append` (product/viva/ledger/store.py:95) computes a head that nothing carries off the machine.

### T5 — No plaintext phase, anywhere, ever
**State:** enforced
**Code:** product/viva/crypto.py:31 · product/viva/ingest/raw_store.py:57
**Test:** product/tests/test_store.py::test_nothing_readable_at_rest

1. All data at rest — event log, document blobs, model captures — is sealed with the versioned AES-256-GCM envelope from the first commit that touches real data.
2. Tests, fixtures and debug output are inside the rule, not exempt from it.
3. Every sealed object carries its envelope version, algorithm and key-derivation parameters, so a cipher can be upgraded by re-encryption rather than by archaeology.

### T6 — Nothing leaves silently
**State:** by-review
**Code:** core/vivacore/models/openai_compat.py:76 · core/vivacore/models/anthropic_adapter.py:64
**Test:** none

1. New outbound bytes of any kind are a decision — an ADR plus a promise check — never an implementation detail.
2. The only code in the tree that opens a network connection is the two model adapters; there is no telemetry, analytics, update ping or crash-reporting endpoint.

### T7 — IDs are permanent; fingerprints are versioned
**State:** contradicted-by-code
**Code:** product/viva/ingest/raw_store.py:44 · product/viva/ledger/projection/movements.py:17
**Test:** product/tests/test_raw_store.py::test_same_bytes_dedup

1. A record's identity is permanent and is never changed by a correction, a re-categorization or a schema migration.
2. Recognition — detecting that the same reality has arrived twice — is a separate, versioned content fingerprint.

**Contradiction:** the doc says two fields doing two jobs (ADR-007). The code has one content-derived string doing both: a document's id is the SHA-256 of its bytes (product/viva/ingest/raw_store.py:44), and a posted movement is referenced by a key built from that document id, the account, the date, the amount, the description and an occurrence index (product/viva/ledger/projection/movements.py:17). Every overlay points at that key. There is no separate fingerprint field and no versioning of one. Events carry a random `event_id` (product/viva/ledger/events.py:127), but nothing references it. Permanence therefore holds only while the content holds.

### T8 — Models are pinned, provider-swappable, and never trusted
**State:** enforced-with-exception
**Code:** core/vivacore/models/spec.py:18 · core/vivacore/versions.py:1
**Test:** product/tests/test_prompt_library.py::test_active_versions_are_frozen

1. A model is named by a pinned identifier in a spec, reached through an adapter, and the key is read from the environment at call time rather than stored in the spec.
2. Nothing in the data model or the verification layer assumes a provider, or assumes that inference is remote.
3. Every prompt is a versioned file; a released version's bytes never change, so a recorded `prompt_version` resolves to the exact text that produced a reading, forever.
4. Access modes are bundled local, OAuth-brokered, BYOK, and future attested-cloud.

**Exception:** assertion 4 is reachable only as BYOK and as a keyless local endpoint — core/vivacore/models/spec.py:22 offers an `api_key_env` or nothing. No OAuth-brokered path and no attested-cloud path exists.

### T9 — The personal/impersonal boundary is drawn at package edges
**State:** enforced-with-exception
**Code:** product/viva/ledger/hints.py:1 · merchant/merchantcore/descriptor.py:265 · merchant/merchantcore/catalog.py:162
**Test:** product/tests/test_hints.py::test_a_brand_a_grammar_named_crosses_only_where_a_published_format_agrees

1. A shared-knowledge package holds and shares only impersonal data — merchant knowledge, format knowledge. Amounts, dates, accounts and PII descriptors never cross the product → package edge.
2. *Impersonal by construction* means corroborated by something that is not a model.
3. A slot name in an induced grammar may say a hole holds a person; it may not, by itself, say a hole holds a business. The unit withheld is the whole hint — brand and context together.
4. A model-authored label may withhold a question and may never delete a measurement, so a fence goes where a wrong label costs coverage and not where it would drop a measured flow.
5. A model may propose a fold of two labels and may never apply one; a shipped vocabulary leads a list and never displaces a label already in use.
6. A deterministic fold on punctuation alone is permitted, because it carries no vocabulary and cannot merge two labels differing in anything but separators; it reports every group it made.
7. The unencrypted-safety of a shared catalog is a consequence of this boundary, never an exception to T5.

**Exception:** one of the two corroborating signals the crossing gate accepts is recovered from the corpus rather than read from a published boundary — product/viva/ledger/hints.py. A person's name that an ACH head hands back as a company name still crosses, which is why the maintenance agent's enrichment step is not autonomous.

### I1 — Currency is first-class
**State:** enforced-with-exception
**Code:** product/viva/render.py:176
**Test:** product/tests/test_render.py::test_an_amount_whose_currency_is_unknown_is_not_given_one

1. An amount is always (value, currency) and never a bare number.
2. No field, schema, computation or display assumes USD.
3. A figure whose currency is unknown is written without one rather than given a default.

**Exception:** assertion 2 does not hold at five live sites, which fall back to `USD` rather than to absence — product/viva/env.py:70, product/viva/knowledge/__init__.py:64, :89, :107, product/viva/ledger/statements.py:114, product/viva/listen.py:688 (which writes `USD` onto an `account_opened` event) and product/viva/rebuild.py:74. Assertion 3 is the half the cited test holds.

### I2 — Normalization is locale-aware and versioned
**State:** enforced-with-exception
**Code:** core/vivacore/verify/normalize.py:20
**Test:** core/tests/test_normalize.py::test_german_comma_decimal

1. Number formats, date formats and negative conventions are handled by explicit, versioned, deterministic rules that record every assumption they used.
2. A reading is never picked silently between two valid ones: `ambiguous` is a first-class outcome.
3. Where locale cannot be determined from context the figure grades `conflicted` rather than being guessed.

**Exception:** the structural `YYYY-MM-DD` checks use `str.isdigit()`, which accepts non-ASCII digits — product/viva/tools/runner.py:165 and product/viva/tools/ledger_common.py:277.

### I3 — Trust is earned per locale
**State:** enforced-with-exception
**Code:** bench/vivabench/score.py:204
**Test:** bench/tests/test_claims_and_score.py::test_scorecards_group_and_calibrate

1. Model autonomy scorecards are keyed on (model, document type, locale); no composite score is computed across them.
2. Proven-in-one-locale grants no autonomy in another.
3. Viva states, per region, where she has not been proven.

**Exception:** assertion 3 has no implementation. Nothing keys a capability statement to a locale; the product's capability honesty is a judgement rather than a property (ADR-013).

### I4 — Ground truth carries locale metadata from day one
**State:** enforced
**Code:** bench/vivabench/config.py:178
**Test:** bench/tests/test_match_and_capture.py::test_german_amount_cross_format

1. Every corpus document declares a locale and a currency, or it is refused.
2. Every answer-key figure stores its raw-as-printed form beside its normalized value.
3. Matching compares raw and normalized forms, so a cross-format reading is graded rather than failed.

### I5 — No US-shaped taxonomy
**State:** enforced
**Code:** product/viva/schemas/__init__.py:1 · product/viva/interview.py:164
**Test:** product/tests/test_interview.py::test_the_pack_loads_and_every_kind_is_jurisdiction_tagged

1. Account types, tax concepts and document categories are extensible to non-US instruments without migration.
2. Every schema-pack entry is jurisdiction-tagged, and a jurisdiction-scoped question does not travel to another jurisdiction.
3. Deduction and category vocabularies are universal buckets rather than one country's table.

### I6 — The admission exam is pack-extensible
**State:** by-review
**Code:** bench/vivabench/config.py:145
**Test:** none

1. Regional benchmark packs run through identical machinery — a pack is corpus rows, not a code path.
2. Real statements are never committed; the repo carries example configs and synthetic packs, and live corpora are gitignored.
3. International expansion is evidence-gated rather than promised: a contributor verifies locally and shares scorecards only.

### M1 — Cash-flow over accrual, when in doubt
**State:** enforced
**Code:** product/viva/ledger/postings.py:135 · product/viva/ledger/projection/positions.py:15 · product/viva/ledger/projection/movements.py:289
**Test:** product/tests/test_brokerage.py::test_unrealized_gain_is_a_derived_as_of_view_not_a_ledger_fact

1. The ledger records realized cash events. Accrual and paper figures — unrealized gain, mark-to-market revaluation — are never posted, never reconciled as ledger facts, never events.
2. Such figures are derived as-of-date presentation views, always carrying their date and valuation class (X2).
3. Where a modeling choice is ambiguous, the cash-flow reading wins.
4. Cash leaving an account is a realized cash event and counts as spending until something stronger says otherwise; a card purchase is the spend and repaying the card is a loan repaid.
5. Re-reading a past cash withdrawal as the acquisition of an otherwise unexplained asset is proposed to the person and never applied on the machine's own word (T9).
6. A ruling on a movement outranks the heuristic rung that defaulted it, so an answer sticks and does not reopen.

### M2 — Which way the money went is decided by the account's kind, in one place
**State:** enforced
**Code:** product/viva/ledger/streams.py:79 (`money_effect`), product/viva/ledger/projection/merchants.py:146 (`implication_of`)
**Test:** product/tests/test_streams.py::test_a_stream_cannot_be_built_without_the_account_kind, product/tests/test_direction_site.py::test_a_purchase_on_a_liability_is_money_leaving_not_money_arriving, ::test_the_site_reads_no_posted_sign_at_all

1. A posted amount is signed by its effect on the balance the document prints, so on a liability a purchase posts positive.
2. The direction of a movement is derived from the account's kind by one function, and no read derives it from a posted sign.
3. A reader holding no account kind raises; there is no fallback to the posted amount.
4. Direction splits a relationship's statistics and never its key: a card-paid subscription and the same subscription paid from checking are one arrangement under one subject.

### X1 — Target user skill: "can install an app"
**State:** unmet
**Code:** product/viva/env.py:1
**Test:** none

1. No feature may require self-hosting, a terminal, or knowing what an API key is on the default path.

The shipped entry points read the vault passphrase and the model key from environment variables or a hand-edited `.env` file (product/viva/env.py:14), and nothing in the tree supplies either without the person editing a file. A desktop shell exists under `desktop/`; no credential path reaches it.

### X2 — Uncertainty is visible, never decorative
**State:** enforced-with-exception
**Code:** product/viva/tools/runner_delivery.py:268
**Test:** product/tests/test_persona_pack.py::test_every_grade_a_figure_can_carry_has_a_reviewed_sentence

1. Confidence language in any surface maps 1:1 to verification grades, and a build check holds the sentences and the ladder to each other in both directions.
2. Every answer that states a graded money figure as a number in a sentence carries one line saying how well what it stated is stood behind.
3. That line is one whole reviewed sentence per word on the ladder, never a frame with a word dropped into it.
4. A property of a figure that the machine holds is placed by the machine, never asked for through a hole.
5. A value the arithmetic could not write exactly never reaches a person without the term that says so.

**Exception:** assertion 1 holds for the grade line the machine places and not for the prose a model writes around a hole; nothing stops a model typing a strength word into its own clause text ([ADR-013](decisions/ADR-013-the-shape-before-the-data.md), *Exception*).

### X3 — Irreversible actions wait for an explicit yes
**State:** enforced
**Code:** product/viva/engine.py:165 · product/viva/engine.py:162
**Test:** product/tests/test_ask.py::test_a_proposal_that_is_never_confirmed_leaves_the_ledger_untouched

1. An answer that would do something irreversible comes back as a proposal stating in plain words what it would do.
2. The yes that applies it is a question like any other: a declared `yes_no` slot, a model reading the person's words into it, deterministic code deciding.
3. A confirmation that never arrives leaves the ledger exactly as it was.
4. What the design excludes is a channel that writes with nobody saying anything, not a second function with this gate between its halves.
5. A loop that cannot confirm cannot satisfy this invariant at all.

### SPINE-12 — An invariant joins the checklist by deliberate decision
**State:** unmet
**Code:** none found
**Test:** none

1. A new invariant is added to this checklist by deliberate decision, and the addition is recorded as a decision rather than arriving as an edit.

## Why

Some requirements are cross-cutting: they belong to no single feature, so they are exactly the ones forgotten when deep inside one. This is the standing checklist. Every design doc, ADR and feature spec states which of these it touches and how it honors them; silence about a relevant invariant is a review failure rather than an oversight. During review, ask of each proposal: which invariant does this strain? A proposal straining none is either trivial or under-examined.

**Why a figure is an object and not a number.** A number a model restates is a number nothing can trace. Giving every asserted figure an identity means an answer cites rather than repeats, so a figure no tool emitted has nothing to cite. Grade, exactness and boundary are three different questions and one property answering all three answers none of them: a number true of one account and a number true of all of them declared the same thing, so a subset was spoken as a total and graded as though it were one. Exactness is separated from grade for the same reason in the other direction — a number known perfectly well can still be one no pair of decimals holds, and treating that as weak evidence would be a lie about the evidence.

**Why models never certify.** A model that tallied internally cannot show its work, and a check that cannot be audited is not a check. Two models agreeing is evidence; a deterministic identity that passes is proof. This holds regardless of how good models get, because provable and correct are different properties and this product sells the first.

**Why capture comes first.** Irreversibility lives mostly in what is not captured: a source region not recorded at extraction time can never be attached later, and a discarded model response cannot be re-audited. Storage is cheap and the past is unrecoverable, which is why the raw exchange is written before any parsing touches it. This doctrine is also what demotes most other decisions from one-way to revisable — schemas, grades and models can all be re-derived from retained truth.

**Why the log rather than a database with an audit table.** Audit tables are bypassable by the code that writes them. A projection-of-log architecture makes unaudited mutation structurally impossible rather than procedurally forbidden, and it gives multi-device sync and retroactive re-grading for free. Anchoring is what turns a self-attested history into a provable one, which is why history before the first anchor is a permanent gap rather than a delay.

**Why encryption has no phase.** Encryption posture is reversible while keys are held; a single leak is absorbing. The first user is the author with real statements, so real financial data exists from the first day of development, and "we will add encryption before release" *is* the plaintext phase.

**Why the outbound path is enumerated.** The promise "nothing leaves your machine silently" is legible to a non-technical person in a way no privacy-preserving aggregate ever will be, and trust must be verifiable by the person extending it. Off-by-default telemetry has a documented tendency to creep toward on-by-default, so the receiving infrastructure is not built and the temptation has no object.

**Why identity and recognition are two jobs.** Content-derived ids are elegant and self-verifying, and they break precisely where this product lives: correct a misread figure and the record's identity changes, orphaning every pointer aimed at it. Random ids alone push duplicate detection to later, under pressure, and it is then solved by adding the fingerprint the hybrid adds calmly.

**Why the personal/impersonal fence sits at a package edge.** A boundary that lives inside a function is a boundary a caller can forget. Put it at the edge of a package and the shareable half of the product — merchant knowledge, format knowledge — can be unencrypted and public without any per-call judgement. The asymmetry about model claims follows from what a wrong answer costs: believing a model that says "this is a person" costs enrichment coverage, believing one that says "this is a business" costs a name. So the same label may withhold a question and may never delete a measurement, and the general form of it — a model may propose a fold and never apply one — is what keeps a person's own distinction from being merged away silently at the funnel every aggregate reads through.

**Why internationalization is an invariant and not a feature.** Currency, locale and taxonomy shape cannot be retrofitted: a bare number loses its currency permanently, an answer key without locale metadata cannot be re-graded, and a US-shaped account type forces a migration on the first ISA. Trust is also not transferable across regions, which is why autonomy is keyed per locale rather than averaged into one score.

**Why the ledger is cash-flow.** The thesis is that clean data is measurements, not generations. Posting a price change that was not a cash movement fabricates an event that never happened; keeping the ledger cash-flow keeps it aligned with reality and with tax, and leaves unrealized change where it belongs — a presentation view carrying its own date. Cash withdrawn falls out of the same preference: the money left, no counterpart statement says where it went, and there is nothing for the withdrawal to be recognised as the settlement of.

**Why direction has one owner.** A posted sign is a fact about a document, not about a person's money, and a read that derives direction from it reports every card purchase as money arriving. The failure is quiet: it produces a wrong direction silently and keeps producing it. This rule had lived in a docstring and two design documents and was still independently reinvented, with the sign inverted, by a third reader within days — which is why it is a checklist entry rather than a note in the module that owns it.

**Why uncertainty is placed rather than asked for.** The 1:1 map between confidence language and grades held wherever confidence language appeared; whether it appeared at all was a model's bet, because the only route by which a strength word reached a person was a hole a model had to author before it had read anything. A property of a figure that the machine holds belongs to the machine.

**Why the confirmation is a question.** The proposal-then-confirm pair is the explicit-yes mechanism rather than a rival to it. Making the yes an ordinary typed slot means there is no second door to guard, and an irreversible action becomes a property of the type rather than a rule someone has to remember.

## Open

- Whether the ingest path should build the request capture, or the ADR should ratify reconstruction from document plus prompt version. Reconstruction is faithful in content and not in bytes, and it holds only while every prompt version stays resolvable forever.
- Nothing anchors the chain head, and every unanchored day lengthens the stretch a future reader must take on trust. An anchor placed later proves only that the head existed then.
- Which identity scheme the product carries forward, and what a correction to an already-posted movement must do to the pointers aimed at it. The orphaning is latent today only because the sole correction path acts on a statement that has not yet posted.
- No OAuth-brokered or attested-cloud model access exists, so T8's access-mode list describes a destination rather than a state.
- The enrichment crossing accepts one corroborating signal recovered from the corpus rather than read from a published boundary, so the T9 fence is narrowed and not sealed, and the maintenance agent's enrichment step stays non-autonomous until it is.
- `figure()` accepts a money-kind figure with no grade, and nothing stops a model typing a strength word into its own clause text.
- Reclassifying a past cash withdrawal as an asset acquisition moves money out of a spending total that was true when it was spoken. What the product owes a person whose figure changes afterwards is undecided.
- `implication_of` still reads a counterparty's implication off the posted sign, and there is no structural guard against a fifth site doing the same.
- The default path requires a passphrase and a model key in the environment or a `.env` file, so X1 is a target rather than a property.
- Nothing computes, per locale or in general, whether a question can be answered before a call is made, so capability honesty is a judgement rather than a property of the registry.
- The structural date check accepts non-ASCII digits.
- Nothing checks that a new invariant arrived by a recorded decision rather than by an edit to this file, so SPINE-12 holds only by review.
