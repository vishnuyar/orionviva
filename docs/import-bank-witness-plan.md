# Stable bank funding provenance

**State:** bank-witness repair implemented and measured on a synthetic hundred-document run; complete sample acceptance pending
**Rules:** none

## Goal and authority

The owner asked: “go ahead and make each of those changes, prepare the plan, follow checklist and complete them, use multiple agents to orchestrate this”. This amendment serves the [import performance plan](import-performance-plan.md). It removes historical investment revision cascades caused solely by a later document repeating an already established bank account reference, while preserving genuine evidence-driven healing, accepted cash, conflicting-source treatment and immutable provenance.

The amendment changes neither financial meaning nor the canonical storage boundary. It requires an independent factual check and Director ruling before product implementation. It does not establish release readiness or completion of the full sample.

## Evidence and diagnosis

The retained candidate completes its first hundred documents in 275.634 seconds versus an earlier 376.645-second observation. Individual examples still grow from document 13 at 0.944 seconds to document 65 at 19.761 seconds. These observations describe identified runs, not a paired full-run proof or completion forecast. An earlier document-78 profile attributes approximately 129 of 140 profiled seconds to `heal_after_source` across thirteen roots. The orchestrator stopped only the disposable synthetic build worker after retaining its progress. Full prepared-artifact and full import acceptance remain unresolved.

In `product/viva/investment/healing.py`, `heal_after_source` treats every account-scoped `FinancialAccountReferenceObserved` on the current document as a candidate dependency change and revisits matching historical contributions. `heal_root` passes the row's existing funding witness to `bind_funding`. In `product/viva/investment/funding.py`, that preference reaches investment binding but is dropped for bank binding. Bank binding always selects the last matching account-reference observation. A later document repeating the same account and reference therefore changes the witness's source document or page. Dataclass inequality marks the row changed and appends a successor statement although its bank cash dependency and account resolution are unchanged. The extra revisions increase the historical material processed later.

The independent Fact-checker reproduced an old bank witness remaining valid after a new identical reference, followed by healing appending four events, changing reference provenance and leaving cash unchanged. The retained synthetic log contains 2,306 events and 104 captures, with 81 account-reference observations for thirteen unique account/reference pairs, 63 evidence changes, 87 statement events and 549 rows. These counts and the reproduction support this mechanism; they do not alone attribute the full profile cost to it.

## Existing financial and provenance contract

A bank funding witness establishes an accepted printed reference, a uniquely resolved counterpart account, a unique matching bank transaction, exact date and opposite amount, cash body digest, depository account kind, currency and source lineage. `validate_funding` in `product/viva/investment/events.py` does not require the newest account-reference document. Its ordinary bank branch resolves the counterpart identity but does not directly establish that an arbitrary preferred witness's historical reference page is genuine. Preservation therefore needs an explicit exact-source guard rather than assuming any supplied witness is trusted.

Fields and witnesses in `product/viva/investment/contracts.py` retain immutable document and page provenance. The existing `test_post_ingest_bank_healer_uses_retained_observation_without_original_facts` in `product/tests/test_investment_evidence_source_projector.py` expects a second unchanged heal to append nothing. Investment-to-investment binding already conditionally preserves prior opposing evidence, but its source lifecycle is separate and must not be changed by this amendment.

## Recommendation

Thread `preferred_witness` through the ordinary bank branch. Preserve the exact existing own-bank witness only after fresh binding against the current locked event prefix proves that its economic relationship remains uniquely valid and its own historical reference evidence still exists with the exact encoded field provenance. Recompute current account resolution and transaction candidates first. A preferred witness is never authority to bypass ambiguity.

Require the same role, counterpart account, transaction identifier, cash body digest and printed-reference lineage as the freshly rebound candidate. Require the preferred counterpart-reference field to be supported by a retained account-scoped `FinancialAccountReferenceObserved` for that account and reference. The existing binding constructs such a field as `Field(counterpart.value, observed.provenance.doc_id, observed.provenance.page, raw=counterpart.value)`. Equality with one of these reconstructed fields checks every encoded attribute, including value, raw text, document, page, status, grade and anchor; matching only value or account is insufficient. The preferred printed-reference field must equal the freshly rebound transaction-reference field. Do not preserve a missing, forged or unsupported historical field.

Without a valid preference, retain the existing deterministic last-reference fallback. Full statement validation and the existing locked append remain unchanged. An unchanged valid row yields no successor. New evidence that changes resolution, introduces a competing cash candidate, cures a missing dependency or changes a relevant source must still take the normal healing and validation path. Existing historical events remain untouched.

## Alternatives and scope fence

Filtering duplicate account-reference notifications could reduce target scans further, but a repeated reference can introduce ambiguity through a different account, and a document can carry relevant cash, payroll or investment evidence as well. Broad target filtering is excluded. If it remains necessary, a separate bounded proposal must compare exact before-and-after dependency resolution and preserve both conflict transitions and missing-to-known arrivals before implementation.

Private immutable basis sharing could reduce cloning, but requires its own ownership and invalidation proof. It is independent of funding-witness selection and is excluded here. Neither alternative permits skipping validation.

Product changes in this slice are limited to ordinary own-bank witness selection and preference plumbing, with deterministic regression coverage. Do not change cash arithmetic or postings, reference identity, accepted/held/conflicted policy, retraction or supersession, payroll or investment-to-investment behavior, source grades, SQL authority, physical chain authentication, provider consent, budgets or outbound access. Do not rewrite retained events, hide a conflict or synthesize source evidence. No private vault, paid call, installation replacement, ship action or commit is authorized by this document.

## Checklist and acceptance

- [x] Independently reproduce a repeated reference replacing an otherwise valid bank witness and adding four events without changing cash.
- [x] Fact-check this complete amendment and obtain the Director ruling before product edits.
- [ ] Demonstrate repeated and equivalent account-reference arrivals retain the original exact witness, statement identity, cash count and financial answer when all current checks still hold.
- [ ] Demonstrate missing-to-accepted evidence still heals; ambiguous counterpart resolution and duplicate matching cash are not masked; missing, forged and wrong-page preferred provenance is not trusted.
- [ ] Preserve unrelated contributions, payroll, broker-to-broker funding, copy lineage, retraction and historical SQL behavior through affected tests and independent review.
- [ ] Sequentially measure comparable increasing-history progress, including the earlier document-78 and hundred-document boundaries; separate profiling from timing.
- [ ] Complete full 794-document import and artifact restoration at the original composed boundary, with source closure and replay agreement.
- [ ] Report residual global validation costs and unresolved acceptance explicitly; obtain fresh review before any completion or readiness claim.

No invariant, event schema or trust-timing change is proposed. The governing storage, exact-arithmetic and provider-consent boundaries remain those of the parent plan.

## Checkpoint 1 ruling

The Director approved this bounded amendment after reviewing brief SHA256 `ef47c1a7582f416e7c4fe66b54fdb9701973333ad937844be5c6c4219dde97a0` and the independent factual tables. The account-scoped discovery wording qualification was absorbed before implementation. Exact reproduction, source hashes, execution output and claim dispositions are retained in ignored `runs/incremental-import/bank-witness-factcheck/`.

The approved choice preserves an exact supported ordinary bank witness only after fresh unique account and cash binding against the current locked prefix. Complete historical Field support and unchanged printed-reference lineage, role, account, transaction identity and digest are mandatory. Existing currency, date, amount, kind, destination, statement and physical-chain validation remain mandatory. Unsupported preferences retain the deterministic fallback.

This chooses between equally valid retained observations; it establishes no general citation-preference rule. Reject forged provenance, masked ambiguity, lost missing-to-known healing, history rewriting or changes outside the stated fence. Broad target filtering and private basis sharing remain excluded. Comparable growing-history measurements and full sample/source/replay/restoration evidence remain required. Approval establishes neither runtime dominance nor acceptance completion and grants no commit, installation replacement, release, push or merge authority.
