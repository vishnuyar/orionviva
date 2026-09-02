# Semantic requests and deterministic AnswerProgram lowering

**State:** built; exact-model admission and private-vault Witness pending
**Rules:** AP-9, AP-10, AP-11, AP-12, AP-13
**Invariants touched:** T1, T2, T3, T8, I1, X2

This is the current design for the read-answer boundary. The historical build
record in [answer-program-and-financial-query-engine.md](answer-program-and-financial-query-engine.md)
still describes the validator, executor, Financial Query IR, evidence graph,
binder, renderer, and the direct-program experiment. Its decision to make a
runtime model author the executable program is superseded here.

The boundary now has two different contracts. A model returns a compact
semantic request: one reviewed financial family, its typed parameters, and its
reviewed requested claims. Deterministic code lowers that request into the
complete AnswerProgram. The already-built runtime then validates the whole
program before any financial read and executes, binds, and renders it through
the same one grounded path.

## Rules

### AP-9 — The runtime model names meaning and cannot author execution
**State:** enforced
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/intents.py
**Test:** product/tests/test_semantic_answering.py::test_model_contract_cannot_author_executable_program_fields

1. Model output contains only a version, catalog digest, semantic family,
   typed parameters, grounded parameter sources, and requested claims, or one
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
   conventions, and the semantic catalog. It receives no current-turn financial
   result and no executable schema.

### AP-10 — One registry owns admitted meaning and deterministic lowering
**State:** enforced
**Code:** product/viva/answer_program/intents.py
**Test:** product/tests/test_semantic_answering.py::test_every_reviewed_family_lowers_and_validates_before_a_read

1. One registry owns the six runtime-selectable family definitions, their
   parameter and claim schemas, native tool catalog, text schema, builder
   lookup, supported-family report, catalog digest, and admission digest.
2. The first scope is named-account balance, needs-attention, explicit-period
   category spending, net worth, card debt, and classification explanation.
3. Broad account inventory remains a separately reviewed builder and is not in
   the runtime model catalog.
4. Every accepted request becomes a complete data-blind AnswerProgram and
   passes the existing static validator before its first read.

### AP-11 — Required claims are the requested financial meaning
**State:** enforced
**Code:** product/viva/answer_program/intents.py, product/viva/tools/ledger_audit.py
**Test:** product/tests/test_semantic_answering.py::test_net_worth_has_no_unrequested_staleness_clause, product/tests/test_semantic_answering.py::test_named_account_scope_and_date_survive_lowering_and_delivery, product/tests/test_semantic_answering.py::test_materially_different_classification_matches_request_clarification

1. Named-account answers bind only the claims requested. A requested date stays
   attached to its supporting account figure; a balance-only request does not
   acquire a date clause.
2. Net worth reads the authoritative per-currency net-worth view. Unrequested
   staleness is not a required clause and cannot erase the requested result.
3. Card totals and per-card rows come from the deterministic `card_account`
   document subtype. The broader liability population, including loans, is not
   a card population; no partial card selection may claim to be its whole.
4. Attention reads a bounded preview of the existing consequence-ordered queue;
   it does not create, regroup, or rerank questions.
5. Classification explanations expose the deterministic nature reason and its
   evidence; materially different matching treatments refuse as ambiguous.

### AP-12 — Unsupported meaning is a precise boundary
**State:** enforced
**Code:** product/viva/answer_program/compiler.py, product/viva/answer_program/runtime.py
**Test:** product/tests/test_semantic_answering.py::test_unsupported_meaning_is_a_structured_capability_gap

1. Unsupported financial meaning returns the requested family and the exact
   supported-family list as a structured capability gap. The desktop adapter
   preserves those fields and displays the precise boundary to the person.
   Plain labels and examples come from the semantic-family registry rather than
   exposing or rewording internal identifiers.
2. It neither becomes a generic invalid-program failure nor reaches an old
   planner or open-ended program-authoring fallback.
3. The desktop renders the refusal sentence once, presents Requested and
   Available now as distinct information, and announces a newly settled
   capability boundary through a polite atomic live region.

### AP-13 — Publication proves the compact boundary and its lowering
**State:** enforced-with-exception
**Code:** product/viva/answer_program/admission.py, product/viva/answer_program/admission_fixture.py, product/viva/answer_program/release.py, product/viva/session.py, product/viva/answer_program/replay.py
**Test:** product/tests/test_answer_program_contracts.py::test_all_45_frozen_cases_derive_real_oracles_before_scoring_a_bad_result, product/tests/test_answer_program_contracts.py::test_late_broken_oracles_are_all_reported_before_compiler_or_provider_use, product/tests/test_answer_program_contracts.py::test_release_gate_rejects_a_profile_fabricated_from_passing_scores

1. Admission binds one exact provider route, requested and resolved model,
   modality, locale family, semantic prompt, compact schema, catalog, builder
   digest, retained runtime contracts, persona, frozen corpus, canonical
   admission-only synthetic fixture, and the oracle set derived from it.
2. The corpus contains seven exact questions repeated exactly five times,
   reviewed paraphrases, and follow-up, ambiguity, and forbidden-result cases.
   Every routine supported turn must select the correct family and grounded
   typed parameters on its first attempt.
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
   manifest, persona, and resolved model identity. Replay re-lowers semantics
   and refuses either digest mismatch.

**Exception:** the deterministic gate exists, but no exact live-model profile
has been published for this contract and no new private-vault Witness has run.
Runtime availability remains intentionally closed until both are true.

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
requires all 45 frozen cases (35 exact repetitions, seven paraphrases, and
three focused coverage cases), the malformed-request recovery cases, the
retained adversarial runtime suite, exact keyed financial oracles, complete
provider attempt evidence, zero unsafe-figure or semantic errors, and the exact
build digests. The later private-vault Witness also waits
for the separately governed account-identity, question-intelligence, and
desktop-progress workstreams.
