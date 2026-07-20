# The Format Commons — distilled document knowledge, shared without the documents

**Status:** Draft · **Last updated:** 2026-07-20 · **Origin question:** the first German document is read expensively by a frontier model; that format knowledge should persist and serve *every* user afterward via cheap/local models with pointed questions. Share the knowledge, never the document.
**Invariants touched:** T1/T2 (profile-guided extraction passes the same verification floor), T3 (blind reads that birth profiles are raw-captured), T6 (contribution is explicit user action; nothing leaves silently), T8 (profiles carry versions and scorecards like models), I2/I5/I6 (profiles are locale/jurisdiction-tagged data packs), X1 (all invisible to the user)

## The anti-goal tension, resolved precisely

"No per-institution parsers" bans hand-written, code-shaped, load-bearing readers. Format profiles are the opposite regime on every axis: **machine-distilled** (a frontier model writes them after reading blind), **declarative data** (YAML describing the form, never code), **hints not authority** (a cheap model guided by a profile still submits claims to the same verification floor), and **self-healing** (drift demotes them automatically). The one rule that keeps this true forever: **extraction must always work with no profile at all.** Profiles make reading cheaper; they are never required for reading to be possible.

## What a format profile is

A declarative description of a document *form* — never its values:

```yaml
format_id: de-sparkasse-kontoauszug-v3     # + fingerprint features for matching
doc_type: checking_statement
locale: de-DE
jurisdiction: DE
layout:
  closing_balance: {page: 1, region: top-right, label: "Neuer Saldo"}
  transactions_table:
    columns: [Buchungstag, Verwendungszweck, Betrag]
    continuation: subsequent pages, repeated header
conventions: {amounts: "1.234,56", dates: "DD.MM.YYYY", negatives: trailing-minus}
pointed_questions:            # what a small model is asked, instead of open reading
  - "What is the value labeled 'Neuer Saldo' on page 1?"
  - "List each row of the transactions table: date, description, amount as printed."
checks_hint: [balance_identity]            # which registry checks apply
provenance: {distilled_by: <model+version>, from_n_documents: 3}
```

Contains: institution, layout, labels, conventions, question set. Never contains: amounts, names, account identifiers, dates-of-anything-personal. Human-readable by design so a contributor can *see* it's clean.

## The lifecycle

1. **Blind read.** Unmatched document → frontier model, open extraction (expensive, raw-captured) → verification as always.
2. **Distillation.** After verified success, a second pass asks the frontier model to describe the form + the pointed-question set → profile written to the **personal format cache** (local; immediate benefit: this user's next same-format document is cheap).
3. **Guided reads.** Matched documents → profile's pointed questions to a cheap/local model → same verification floor → profile scorecard updates (success rate per profile, exactly like model autonomy).
4. **Self-healing.** Institution redesigns → guided reads start failing verification → profile auto-demoted → frontier blind read → fresh profile distilled. Format drift costs one expensive read, never an engineering ticket.
5. **Contribution (explicit, three gates).** User reviews the profile and chooses to share (T6) → deterministic privacy lint (no high-entropy strings, no numerics beyond convention examples, schema-constrained fields) → human review as a **pull request to the format registry — a git repo**, v1 infrastructure cost: zero, mechanics: the same as all open-source contribution (DCO applies). Registry ships as data with app updates.

## Why this matters economically (confirmed)

- Frontier cost is paid **once per format, ecosystem-wide** — not per user, not per document.
- Pointed questions are far easier than open extraction → **profiles raise the local-model floor**, accelerating the ADR-001 flip-to-local and strengthening adoption rung 1 ("installs and just works").
- Complementary to the LoRA flywheel: profiles = shareable knowledge about *documents*; personal LoRAs = private skill on *your* documents. A local model + profile + LoRA is the endgame stack for near-zero-cost, fully-private ingestion.
- Internationalization becomes community-driven at the extraction layer too: the first German user quietly bootstraps German support for everyone. The I6 pattern's fourth appearance (benchmark packs, taxonomy, knowledge packs, format profiles) — "code is universal; everything regional is data" is now the product's constitution.

## Trust integration (nothing new needed — by design)

- Profile-guided extraction is just another candidate under the **model trust policy**: scorecards per (model, doc_type, locale) gain an optional (format) dimension — which answers that policy's open question about per-institution granularity: *profiles are where format granularity lives*, not model scorecards.
- The **benchmark harness** gains a future mode: profile-guided vs blind extraction on the same corpus — measuring exactly how much a profile buys (accuracy and cost). Worth adding once profiles exist.
- Verification never changes. That's the point.

## Boundaries

- No profile is ever required (blind path always exists).
- No profile ever contains a personal value (lint + review + schema).
- No silent contribution (explicit act, previewable artifact).
- No hand-editing culture: humans review profiles; models write them. A profile that needs artisanal maintenance is a profile that should be re-distilled.

## Open questions

- Format matching: how a document finds its profile (classifier + layout fingerprint features in the profile header) — architecture phase detail.
- Distillation trigger: after 1 verified document or N? (Leaning: distill after 1, mark provisional, promote after the profile survives its next verified use.)
- Registry governance at scale: lint automation is easy; review load if contributions grow is a community-phase question (E5 territory).
- Whether profile contribution can be *suggested* by the app after repeated blind reads of an unshared format ("this format isn't in the commons — share the knowledge?") without becoming a nag (the no-push rule applies here too).
