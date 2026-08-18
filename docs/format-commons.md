# The Format Commons — distilled document knowledge, shared without the documents

**State:** design-only
**Rules:** ING-80, ING-81, ING-82, ING-83, ING-84, ING-85, ING-86
**Invariants touched:** T1/T2 (profile-guided extraction passes the same verification floor), T3 (blind reads that birth profiles are raw-captured), T6 (contribution is an explicit user action; nothing leaves silently), T8 (profiles carry versions and scorecards like models), I2/I5/I6 (profiles are locale- and jurisdiction-tagged data packs), T9 and X1 (impersonal by construction, and invisible to the user)

_No **document** format profile — layout, labels, pointed questions — exists in the tree. The first built instance of the pattern is the merchant commons ([merchant-catalog-and-commons.md](merchant-catalog-and-commons.md)) and the **descriptor grammar** behind it, which applies the same lifecycle to statement lines rather than to page layout. Each rule below names which artifact it was checked against._

## Rules

### ING-80 — Extraction always works with no profile at all
**State:** enforced
**Code:** product/viva/ingest/reader.py:85 (`read_statement` consults no format profile), merchant/merchantcore/resolve.py:113 (a line with no grammar still resolves through the Layer 0 lint)
**Test:** merchant/tests/test_profile.py::test_no_template_matching_is_a_legitimate_answer, product/tests/test_hints.py::test_with_no_grammar_the_conservative_list_still_guards_a_peer_payment

1. A profile makes reading cheaper; it is never required for reading to be possible.
2. An unmatched document takes the blind path, and an unmatched line resolves through the deterministic fallback.

### ING-81 — A profile describes a form and never a value
**State:** enforced
**Code:** merchant/merchantcore/profile.py:1-18 (a template is literal words plus named holes and nothing else), :311 (`to_dict`)
**Test:** merchant/tests/test_profile.py::test_an_account_number_never_reaches_the_shareable_side, merchant/tests/test_profile.py::test_a_template_with_no_holes_is_an_example_not_a_grammar

1. A profile holds institution, layout, labels, conventions and the question set; it never holds amounts, names, account identifiers or personal dates.
2. A template with no holes is an example rather than a grammar, and is refused.
3. A profile is human-readable, so a contributor can see for themselves that it is clean.

### ING-82 — A profile-guided read passes the same verification floor as a blind one
**State:** unmet
**Code:** none found
**Test:** none

1. A profile is a hint, never an authority: claims a guided read produces go through the identical verification gate.
2. Verification never changes to accommodate a profile.

_No guided document read exists, so the rule has nothing to hold over yet._

### ING-83 — A profile is versioned, and a released version is never overwritten
**State:** enforced
**Code:** merchant/merchantcore/profile.py:448 (`write` raises rather than replacing), :319 (`from_dict` refuses a profile with no format version)
**Test:** merchant/tests/test_profile.py::test_a_released_profile_cannot_be_overwritten, merchant/tests/test_profile.py::test_a_missing_version_is_raised_not_defaulted

1. A profile carries a format version, and loading one without it raises rather than assuming.
2. Writing over a released profile id raises; a change is a new version.

### ING-84 — Drift demotes a profile automatically
**State:** enforced
**Code:** product/viva/agent/policy.py:33 (`reinduce_drifted`, thresholds as data), :55 (re-induction is autonomous), merchant/merchantcore/profile.py:293 (`weighted_coverage`)
**Test:** merchant/tests/test_profile.py::test_drift_shows_up_in_the_recent_number_long_before_the_lifetime_one, merchant/tests/test_profile.py::test_a_grammar_is_verified_by_behaviour_not_by_provenance

1. A profile's recent coverage is measured separately from its lifetime coverage, so drift shows up before the lifetime figure moves.
2. A drop past the threshold, over enough recent lines to mean anything, triggers re-derivation rather than an engineering ticket.
3. A profile is trusted for how it behaves on the lines in front of it, never for where it came from.

### ING-85 — No silent contribution
**State:** by-review
**Code:** product/viva/agent/policy.py:58 (`NEEDS_RATIFICATION` holds `publish_grammar` and `publish_merchant`), merchant/merchantcore/catalog.py:161 (`export`, the linted snapshot a contribution is built from)
**Test:** none

1. Sharing is an explicit act by the person, over a previewable artifact.
2. Anything that changes what other people see waits for a human ruling, always.
3. What is shared passes a deterministic privacy lint before it can be exported.

### ING-86 — What may travel is decided by structure, never by inspecting text
**State:** enforced
**Code:** merchant/merchantcore/profile.py:14-18, :238 (`personal`), :243 (`shareable`)
**Test:** merchant/tests/test_profile.py::test_personal_and_shareable_are_decided_by_slot_not_by_text, merchant/tests/test_profile.py::test_a_contact_where_the_party_belongs_is_personal_by_STRUCTURE

1. A slot name declares whether what it holds is personal; nothing downstream reads the extracted text to decide.
2. A slot vocabulary is closed — a profile may name those slots and nothing else.

## Why

The first document in a new language is read expensively by a frontier model.
That format knowledge should persist and serve every user afterwards, through
cheap or local models answering pointed questions. **Share the knowledge, never
the document.**

That sits in apparent tension with a standing anti-goal: no per-institution
parsers. The tension resolves precisely, because format profiles are the
opposite regime on every axis. They are **machine-distilled** — a frontier model
writes one after reading blind, rather than an engineer hand-writing a reader.
They are **declarative data** describing the form, never code. They are **hints,
not authority**: a cheap model guided by a profile still submits its claims to
the same verification floor. And they are **self-healing**: drift demotes them
automatically. The one rule that keeps all of this true forever is that
**extraction must always work with no profile at all.** A profile makes reading
cheaper; it is never a precondition for reading.

A profile is a declarative description of a document *form*:

```yaml
format_id: <institution>-<doc-kind>-v3     # + fingerprint features for matching
doc_type: checking_statement
locale: de-DE
jurisdiction: DE
layout:
  closing_balance: {page: 1, region: top-right, label: "<the issuer's own word>"}
  transactions_table:
    columns: [<as the issuer heads them>]
    continuation: subsequent pages, repeated header
conventions: {amounts: "1.234,56", dates: "DD.MM.YYYY", negatives: trailing-minus}
pointed_questions:            # what a small model is asked, instead of open reading
  - "What is the value labeled '<the issuer's own word>' on page 1?"
  - "List each row of the transactions table: date, description, amount as printed."
checks_hint: [balance_identity]            # which registry checks apply
provenance: {distilled_by: <model+version>, from_n_documents: 3}
```

Institution, layout, labels, conventions, question set. No amounts, no names, no
account identifiers, no personal dates.

The lifecycle is a loop. An unmatched document goes to a frontier model for open
extraction — expensive, raw-captured, verified as always. After a verified
success, a second pass asks the model to describe the *form* and the pointed
questions that would recover it, and that profile is written to a local cache,
so the immediate benefit is the person's own next document of the same format.
Matched documents then get the profile's pointed questions put to a cheap or
local model, through the same verification floor, with a scorecard per profile
exactly as models have scorecards. When an institution redesigns its statement,
guided reads start failing verification, the profile is demoted, a blind
frontier read runs, and a fresh profile is distilled. **Format drift costs one
expensive read, never an engineering ticket.**

Contribution is deliberately three gates rather than a switch: the person
reviews the profile and chooses to share it; a deterministic privacy lint
rejects high-entropy strings, numerics beyond convention examples, and anything
outside the schema; and a human reviews it as a pull request to a registry that
is an ordinary git repository. The infrastructure cost of that is zero, the
mechanics are the ones every open-source contribution already uses, the
developer-certificate-of-origin policy applies to a profile exactly as it does
to code, and the registry ships as data alongside application updates.

The economics are the point. Frontier cost is paid **once per format,
ecosystem-wide** — not per user and not per document. Pointed questions are far
easier than open extraction, so profiles *raise the local-model floor*, which
accelerates the flip to local inference and strengthens the promise that the app
installs and just works. Profiles and personal fine-tuning are complementary
rather than competing: profiles are shareable knowledge about *documents*, while
a personal adapter is private skill on *your* documents, and a local model plus a
profile plus that adapter is the endgame stack for near-zero-cost, fully-private
ingestion. Internationalization becomes community-driven at the extraction layer
too — the first user in a new country quietly bootstraps that country for
everyone.

Nothing new is needed on the trust side, by design. A profile-guided extraction
is just another candidate under the model trust policy, and the scorecard gains
an optional format dimension — which answers that policy's open question about
per-institution granularity: **profiles are where format granularity lives**,
not model scorecards. The benchmark gains a mode comparing profile-guided
against blind extraction on the same corpus, which measures exactly what a
profile buys in accuracy and cost. Verification itself never changes. That is
the point.

Four boundaries hold the whole thing together: no profile is ever required; no
profile ever contains a personal value; no contribution is silent; and there is
no hand-editing culture. Humans review profiles and models write them — a
profile that needs artisanal maintenance is a profile that should be
re-distilled.

## Open

- Format matching: how a document finds its profile, via a classifier plus layout fingerprint features carried in the profile header.
- The distillation trigger: after one verified document or after several. Leaning towards distilling after one, marking it provisional, and promoting it once it survives its next verified use.
- Registry governance at scale: lint automation is easy, but review load if contributions grow is a community-phase question.
- Whether the app may *suggest* contributing after repeated blind reads of an unshared format, without becoming a nag.
- No document format profile exists; the whole lifecycle above is realized only for descriptor grammars, whose artifacts are statement lines rather than page layouts.
- Nothing tests that a contribution cannot be published without a human ruling — the policy names it, and no build check holds it.
