# Semantic requests and deterministic AnswerProgram lowering

**State:** built; fresh v11 exact-model admission and retained-vault retest pending
**Rules:** AP-9, AP-10, AP-11, AP-12, AP-13
**Invariants touched:** T1, T2, T3, T8, I1, X2

This is the current design for the read-answer boundary. The historical build
record in [answer-program-and-financial-query-engine.md](answer-program-and-financial-query-engine.md)
still describes the validator, executor, Financial Query IR, evidence graph,
binder, renderer, and the direct-program experiment. Its decision to make a
runtime model author the executable program is superseded here.

The boundary now has two different contracts. A model returns a compact
semantic request: one reviewed financial family, its typed parameters, and its
reviewed canonical answer effects. Deterministic code lowers that request into the
complete AnswerProgram. The already-built runtime then validates the whole
program before any financial read and executes, binds, and renders it through
the same one grounded path.

The active compact artifacts are `semantic-request-v11`,
`semantic-request-retry-v9`, and `semantic-request-schema-v8`; exact-model
publication uses `semantic-request-admission-v8`. The profile version changed
because the admission policy changed; its availability thresholds remain unchanged.
The active selection catalog adds eight everyday analysis meanings and six
measurement/projection meanings and three scenario meanings to the original six. Fixed code-owned reads and arithmetic implement those meanings;
the active descriptions are `tools-v25`. The prior admission profile does not
qualify the expanded surface. Measurements and existing projections are
implemented, including savings, loan-payoff and cash-flow scenarios; expanded qualification and retained-vault testing remain pending. See [financial-analysis-measurements-and-scenarios.md](financial-analysis-measurements-and-scenarios.md) for numerical source forms, timing, quantities and receipts.

## Rules

### AP-9 — The runtime model names meaning and cannot author execution
**State:** enforced
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/intents.py
**Test:** product/tests/test_semantic_answering.py::test_model_contract_cannot_author_executable_program_fields

1. Model output contains only a version, catalog digest, semantic family,
   typed parameters, grounded parameter sources, and canonical answer effects,
   or one
   structured non-answer outcome.
2. Model-visible tools and text schema contain no AnswerProgram node, tool,
   financial query, answer clause, binding, importance, result-policy, or
   resource-limit field.
3. Every parameter is proven by an exact quote in the question or an indexed
   prior visible turn. Verbatim values must normalize to that quote; explicit
   calendar-month quotes may derive only their deterministic first or last ISO
   date. A fabricated subject such as `Brokerage` in a checking question is
   rejected before any read.
4. The model receives the question, prior visible text, date and locale
   conventions, the semantic catalog, and a bounded user-specific entity
   catalog. The entity catalog contains account ids/names/institutions/kinds,
   category labels, and counterparty labels, but no balances, amounts, movement
   rows, documents, evidence, or current-turn financial result. It receives no
   executable schema.
5. A model may select a canonical entity id from that catalog while its source
   proof preserves the person's exact wording. Code verifies both the quote and
   catalog membership before any financial read. A catalog group that exceeds
   its bound says it is incomplete. A named-account phrase cannot establish
   uniqueness over omitted accounts; it returns unsupported before reads.
   A visible canonical id retains its recorded role even in a truncated catalog.
   Partial-word matches refuse and multiple complete-catalog matches clarify.
   Named-account option labels use recorded name/institution to distinguish
   duplicate names, with canonical-id fallback when those labels still collide.
   Uniqueness is established before the existing option limit; general display
   labels and reference materialization remain unchanged.
   Clarification tags are a closed reviewed vocabulary.

### AP-10 — One registry owns admitted meaning and deterministic lowering
**State:** enforced
**Code:** product/viva/answer_program/intents.py
**Test:** product/tests/test_semantic_answering.py::test_every_reviewed_family_lowers_and_validates_before_a_read

1. One registry owns the runtime-selectable family definitions, their
   parameter and answer-effect schemas, native tool catalog, text schema, builder
   lookup, supported-family report, catalog digest, and admission digest.
2. The original six meanings are one account's latest whole-account measurement, queued
   account/document decisions, explicit-period category spending, current net
   worth by currency, measured card-population debt, and scoped classification
   explanation. Eight further meanings cover category, merchant and account
   spending, period comparison, transaction search, attributed income, surplus
   and observed recurring costs.
3. Broad account inventory remains a separately reviewed builder and is not in
   the runtime model catalog.
4. Every accepted request becomes a complete data-blind AnswerProgram and
   passes the existing static validator before its first read.
5. The per-user entity catalog is created lazily for the question, is capped by
   kind and by total serialized bytes. Trusted major account kind selects the
   named program's held/owed quantity before current-turn financial reads.
   Different users contribute different candidate metadata through the same
   contract; canonical admission supplies its existing synthetic registry catalog.

### AP-11 — Canonical answer effects are the requested financial meaning
**State:** enforced
**Code:** product/viva/answer_program/intents.py, product/viva/tools/ledger_audit.py
**Test:** product/tests/test_semantic_answering.py::test_net_worth_has_no_unrequested_staleness_clause, product/tests/test_semantic_answering.py::test_named_account_scope_and_date_survive_lowering_and_delivery, product/tests/test_semantic_answering.py::test_materially_different_classification_matches_request_clarification

1. The named request effect `balance` means one latest whole-account amount.
   The financial quantity stays `balance` for depository/investment accounts and
   `owed` for liabilities. Existing canonical id wins; otherwise complete
   requested whole-word tokens must occur contiguously in a visible account name
   or institution. Unique known major kind authors the wording, money slot and
   amount/date selectors together before reads. Unknown/missing kind refuses,
   never defaults to held. Grounding remains the original person's quote.
   A requested date stays attached to that same figure; a balance-only request
   does not acquire a date clause. Negative owed preserves the existing direction
   refusal. The balance read requires an existing dated composed measurement for
   every liability regardless of origin; opened-only or movement-only debt
   remains missing rather than zero. Asserted held-account suppression and
   issued held-account policies remain unchanged. An opening-backed unverified
   replay value stays eligible, and a dated observed zero stays zero. Mixed
   debt populations keep unmeasured identifiers/gap boundaries while excluding
   unsupported monetary rows; an all-unmeasured population gives the existing
   no-accounts refusal. No measurement helper, grading rule, currency/sign,
   projection arithmetic or movement policy changes.
2. Net worth reads the authoritative per-currency net-worth view. Unrequested
   staleness is not a required clause and cannot erase the requested result.
3. Card totals and per-card rows come from the deterministic `card_account`
   document subtype. The broader liability population, including loans, is not
   a card population; no partial card selection may claim to be its whole.
4. Attention reads a bounded preview of the existing consequence-ordered queue;
   it does not create, regroup, or rerank questions.
5. Classification explanations expose the deterministic nature reason and its
   evidence; materially different matching treatments refuse as ambiguous.
6. A model-visible claim is a canonical answer effect, not every concept in the
   question. Two labels that lower to the same deterministic clause are one
   effect. Category/date scope stays in typed parameters; classification
   treatment/reason/evidence, net-worth limitations, and card completeness are
   deterministic parts of their fixed answer shapes.
7. Admission requires the answer effects the question needs and rejects effects
   outside the reviewed set. Deterministic safety, evidence, exclusion, and
   completeness language may be added without pretending it is a separately
   selected output.

### AP-12 — Unsupported meaning is a precise boundary
**State:** enforced
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/runtime.py
**Test:** product/tests/test_semantic_answering.py::test_unsupported_meaning_is_a_structured_capability_gap

1. Unsupported financial meaning returns the requested family and the exact
   supported-family list as a structured capability gap. The desktop adapter
   preserves those fields. For an unknown requested-family descriptor, the
   current Requested label remains generic: “a financial answer that is not
   available yet”. The structured descriptor is retained; custom display copy
   is not inferred from it.
   Plain labels and examples come from the semantic-family registry rather than
   exposing or rewording internal identifiers.
2. It neither becomes a generic invalid-program failure nor reaches an old
   planner or open-ended program-authoring fallback.
3. The desktop renders the refusal sentence once, presents Requested and
   Available now as distinct information, and announces a newly settled
   capability boundary through a polite atomic live region.
4. Recorded cash, account value history and statement-period coverage are reviewed
   runtime-selectable meanings. Payment terms, financial uncertainty and
   question-impact analysis remain outside that catalog. A mixed request with an unsupported material part must
   use unsupported, not present a supported fragment as its complete answer.
5. This boundary reduces statistical selection risk; it does not understand
   arbitrary prose deterministically. A model that selects a nearby well-formed
   request can still pass structural validation. Live meaning checks must verify
   that the selected contract answers the actual question.

### AP-13 — Publication proves the compact boundary and its lowering
**State:** enforced-with-exception
**Code:** product/viva/answer_program/admission.py, product/viva/answer_program/admission_fixture.py, product/viva/answer_program/release.py, product/viva/session.py, product/viva/answer_program/replay.py
**Test:** product/tests/test_answer_program_contracts.py::test_all_73_frozen_cases_derive_real_oracles_before_scoring_a_bad_result, product/tests/test_answer_program_contracts.py::test_late_broken_oracles_are_all_reported_before_compiler_or_provider_use, product/tests/test_answer_program_contracts.py::test_release_gate_rejects_a_profile_fabricated_from_passing_scores

1. Admission binds one exact provider route, requested and resolved model,
   modality, locale family, semantic prompt, compact schema, catalog, builder
   digest, retained runtime contracts, persona, frozen corpus, canonical
   admission-only synthetic fixture, and the oracle set derived from it.
2. The corpus contains seven exact questions repeated exactly five times,
   thirty-five varied paraphrases, and follow-up, ambiguity, and
   forbidden-result cases.
   At least 95% of the complete corpus must produce a valid semantic request on
   the first attempt, and at least 95% of the repeated exact questions must also
   pass their oracle cleanly on that attempt. At least 95% of the complete corpus
   must produce a valid program within the single repair and complete the answer
   expected by its oracle. These are
   availability thresholds approved by the product owner. Entity
   surface strings are not golden answers: admission grades the resolved ledger
   identity, exact record set, figures, currency, dates, status, and evidence.
   An emitted wrong figure, identity, scope, period, completeness claim,
   unsupported figure, false zero, or hypothetical presented as measured remains
   an absolute failure. Safe refusals, missing answers, and repair use count
   against the statistical availability thresholds.
3. Runtime answering is unavailable without a published profile and the
   measured report it came from. Profile creation and release-bundle writing
   additionally require the process-local, non-serializable measured-run
   capability minted by the live runner. The capability is immutable and binds
   the exact canonical report snapshot and digest; replacing its report or
   mutating any nested report field invalidates publication. A reconstructed
   serialized report is valid replay evidence but cannot confer publication authority.
4. Before constructing the compiler or making any paid provider call, admission
   derives every case's oracle from a fresh copy of the canonical synthetic
   fixture. It collects every failure in a structured preflight result. The
   measured phase consumes immutable snapshots of that complete oracle set.
   A full-corpus run constructs fresh canonical registries internally and
   loads the frozen cases internally. It rejects caller-supplied full-corpus
   cases or registry factories, even ones carrying the same ids or a copied
   fixture digest.
   Publication binds both the fixture and canonical sorted
   `{case_id: oracle_digest}` set; provider doubles, alternate fixtures, and
   fabricated score reports cannot publish a profile.
5. An empty financial period is exactly zero only when posted statement
   documents attest the complete requested interval for every eligible account.
   Partial or absent coverage refuses, and a supported zero cites those statement
   document ids rather than account ids.
6. Captures retain raw exchanges, semantic request and digest, lowered program
   and digest, validation, execution, bindings, outcome, prompts, schemas,
   manifest, persona, and resolved model identity. Replay rehydrates the supplied
   registry's actual entity catalog and verifies its digest before re-lowering;
   it never substitutes a captured digest for missing metadata. Changed labels,
   roles, membership or coverage refuse before reads. Semantic/program digest
   mismatches also refuse. Old captures remain records; cross-version migration
   is not promised. The implementation digest authenticates the intent and
   capability builders, tool registration, reused numerical and measurement
   authorities, source-context facade, and numerical binding/rendering route
   alongside compiler, runtime, replay and model adapter. Frozen packaging
   carries the exact source resources named by that map. This does not hash
   unrelated ledger files or replace complete candidate binding; guarded
   qualification still binds the full working diff and final host/sidecar/
   instrument identities. Expanded catalog qualification remains pending.
7. Admission reports keep a bounded interpretation observation and sanitized
   per-attempt failure code so a failure says what the model selected and why
   repair was needed without copying source excerpts or provider output. A
   refusal or absent answer is scored as missing, never confidently wrong;
   confidently wrong is reserved for an emitted incompatible keyed figure.
   Lowered answer-family comparisons apply to answer programs and delivered
   answers or figures. A no-figure clarification, assumption request, or
   outside-domain program remains an availability miss when an answer was
   expected; its non-answer family is not a financial-integrity defect.
8. The exact-provider run uses the canonical fixture's own entity catalog, so
   it exercises the same catalog-selection protocol as a real session. The
   shared profile binds the protocol and builder, not any user's candidate ids.
   Synthetic non-financial counterparties fill the normal catalog bound during
   admission, ensuring the measured prompt is not the unrealistically small
   three-account happy path.
9. Model-facing entity parameters distinguish an exact catalog-id selection
   from a grounded phrase explicitly. A unique whole-word catalog match may be
   resolved by code; other semantic matches remain the model's selection. When
   the selected catalog label differs from the person's wording, the answer
   states that interpretation. Multiple deterministic candidates ask rather
   than guess. Native tool schemas direct the model to resolve both direct names
   and indirect descriptions by meaning before choosing a representation;
   grounded phrases are reserved for referents with no fitting catalog entry.

**Qualification status:** the earlier v9 qualification012 profile was published
and used by the retained-vault campaign013. That campaign exercised 45 questions
and found a named liability display failure plus eight wrong requested meanings.
Those results remain evidence for the old bytes; they do not qualify this v11
prompt, changed catalog labels, role-aware builder or replay digest. Fresh
exact-model qualification and retained-vault retesting remain pending. The
canonical corpus and minimum availability/integrity thresholds are unchanged;
it contains no named owed case, which needs supplemental fictional and live
controls. No model-free result alone grants runtime admission.

## Why this boundary

The direct compiler made language understanding carry execution authorship as
well: it had to reproduce a private graph, query, selector, and delivery
language for ordinary balance and spending questions. The retained runtime was
effective at refusing malformed work, but refusal happened before useful
financial reads. A small semantic request keeps natural-language variation in
the model while placing financial execution and certification in reviewable
code.

The ordering accepted by ADR-013 does not change. The answer's reviewed shape
and selection policy still exist before current-turn data; deterministic
lowering makes that ordering stronger. New breadth is added only by admitting a
new reviewed family. Repeated pressure for near-duplicate families is the
evidence that would justify a later composable semantic language.

## Release boundary

The code and model-free tests do not publish a runtime profile. Publication
requires measuring all 123 default cases: the unchanged 73 version-4 cases (the same seven exact Witness questions and
their 35 repetitions, 35 varied paraphrases, and three focused coverage
cases), plus the 50 independently frozen capability cases, the malformed-request recovery cases, the
retained adversarial runtime suite, exact keyed financial oracles, complete
provider attempt evidence, at least 95% first-attempt validity overall and in
the exact-question cohort, at least 95% validity within one repair and
answerable completion, zero financial-integrity errors, and the
exact build digests. The expanded qualification needs a concrete funded plan before provider calls. The prior continuation budget does not authorize a new expanded run; retain the existing qualification-phase guard and fresh identity review. A passing profile permits
retesting the nine failures and ten supported controls in retained vault006;
no document re-ingestion is required. Deferred document wording, unresolved
reader validation and page/region viewing remain separate campaign gaps.


## Evaluating a replacement model

Run `python -m viva.answer_program.candidate` in the installed product environment
for the offline deterministic preflight. It derives all frozen-case oracles without
constructing a provider or reading a personal vault. This is an engine readiness
check, not evidence that a model understands the questions.

Set the existing `VIVA_SPEAK_*` (or fallback `VIVA_MODEL_*`) process environment
configuration and `VIVA_LOCALE`, then run:

```sh
python -m viva.answer_program.candidate --live --output /absolute/path/candidate.json
```

The command reads process environment only; it does not load `.env` files.
Live evaluation sends the combined canonical and supplemental synthetic questions and catalog to the
configured provider and may incur provider charges. It runs the complete existing
end-to-end suite with authenticated case-specific fixture dates and unchanged minimum thresholds.
The measured diagnostic report is written beside the bundle as
`candidate.json.report.json`, or to `--report`. A passing run automatically produces
the runtime bundle through the existing sealed-evidence publication gates. A failed
run does not replace an existing approved bundle. Bundle replacement is atomic.
Output directories must already exist.

Select a passing bundle explicitly with `VIVA_ADMISSION_PROFILE`; evaluation does
not change the active configuration. Runtime still checks the configured provider,
requested model, returned model, locale, and build contracts. The command does not
claim private-vault or installed-host acceptance.

New profiles serialize `resolved_model` as the single returned-model identity.
The current reader also accepts legacy profiles containing `model_version`, but
only when it agrees with `resolved_model`. The admission policy remains v8 because
its criteria have not changed. Older application readers require the legacy field
and cannot read newly serialized bundles; keep their original bundle when rolling
back the application. Prompt, schema, and engine versions remain separate contracts.
