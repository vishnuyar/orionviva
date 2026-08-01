# The Repair List — decisions for everything the audit and the first run found

**Status:** Proposed — awaiting rulings · **Date:** 2026-07-27 · **Invariants touched:** T1, T2, T4, T5, T7, T9, I2, M1, X2, X3

## How to read this

Two investigations produced findings: a cold read of all four packages, and the
first end-to-end run on real model output ([cold-read-audit-2026-07.md](cold-read-audit-2026-07.md),
`bench/synthetic`). This document turns both into decisions.

**Options appear only where there is a genuine fork** — where two defensible
designs exist and the choice has consequences beyond this repair. Where there is
one obviously right fix, it is stated as a fix and not dressed up as a choice; a
menu with one good item on it wastes the reader's attention.

**Ordering principle.** What can put a wrong number in front of a person comes
first. Within that, read-side before write-side: a projection change is cheap
and reversible and heals the existing vault with no re-ingest, an event-schema
change is permanent. Every repair below is marked **read** or **write**, and the
read-side ones can all land without touching a stored event.

**Two findings cannot be decided from here** — R5 and R6 need the corpus vault
inspected. They are stated with a hypothesis and the command that would settle
them, rather than a guess dressed as a diagnosis.

---

# Wave 1 — the wrong numbers

## R1 · A holding has no identity, so one instrument became two · **read**

The model wrote `BND VANGUARD TOTAL BOND MKT ETF` on one statement and
`BND - VANGUARD TOTAL BOND MKT ETF` on another. Positions are keyed by that raw
string, so those became two instruments rather than two measurements of one, and
net worth counted an entire stale January snapshot a second time: **+20,026.85**,
graded `corroborated`.

Accounts anchor on a number. Merchants normalize deterministically. Categories
were made resolved identities when two spellings halved every total that touched
either. Instruments are the last bare string, and the design doc says so
outright — *"tickers are usually clean. Reserve the seam; don't build it."*
Tickers **are** clean. The model rendering them is not, and that is a different
claim which the first real run falsified.

**Option A — anchor on the symbol; the description is a supporting attribute.**
Exactly the account-identity shape: the number anchors, the name assists. `BND`
is the identity and the description varies freely without splitting anything.
Deterministic, no model call, no new event.
*Fails when a statement prints no symbol* — many 401(k) and mutual-fund
statements print only `Vanguard Target Retirement 2045 Trust II`. Needs a
fallback, which is Option B.

**Option B — normalize the whole string, versioned, like merchants.**
One rule for symbol-bearing and symbol-less statements alike.
*The risk is real and specific:* aggressive normalization collapses share
classes. `Vanguard 500 Index Admiral` and `Vanguard 500 Index Investor` are
different instruments with different prices, and a normalizer that merges them
produces a wrong holding rather than a duplicate one — a worse failure than the
one being fixed.

**Option C — a resolved identity with a recorded ruling, like categories.**
A read-side alias map; two keys that look like one holding are asked about once
and settled with `RulingRecorded(scope="instrument", same_as=…)`. Retroactive,
reversed by appending, no re-ingest. The sixth use of ask-once-and-learn.
*Costs a question* the person shouldn't often have to answer.

**Option D — fix it at extraction: make the prompt emit symbol and name as
separate fields.** Cheapest, and wrong on its own: it leaves every stored claim
mis-keyed, and it makes correctness depend on the model doing as it is told,
which is the thing this project refuses to rely on.

**Recommendation: A with B as fallback, C for the residue.** Symbol anchors when
present; a normalized description keys the instrument when no symbol is printed;
anything still ambiguous becomes a ruling. That is the account pattern and the
category pattern composed, and every layer is deterministic except the last,
which asks.

### R1b · The cross-check that would have caught this already exists, unused · **read**

An investment statement attests `cash + Σ holdings = total`. Ingest checks that
per statement. **Net worth recomputes the same sum across statements and never
compares it to the most recent attested total.** Here it computed 43,943.06 for
an account whose latest statement says 23,916.21, and reported it as fact.

Adding that comparison turns a double-count into a `conflicted` line naming both
figures, whatever is decided about R1 — and it defends against every future
cause of the same shape, not just this one. **Recommended regardless of the
option chosen above**, and arguably worth doing first, since it converts a silent
wrong number into a loud one.

## R2 · Checking and savings at the same bank collide on identity · **read**

Both savings statements held: *"a holder name matches an existing account."* The
last four digits differ — 8802 against 4417 — which is the entire premise of
anchoring on the number. Resolution falls through to a holder-name overlap that
fires because both accounts are `depository` at the same institution. Card and
checking are handled because their kinds differ. Checking and savings is the
commonest pairing a person has.

**Option A — a readable and different number defeats a name overlap.** When both
accounts carry an extracted number and the last-fours differ, the verdict is
`new`, never `ambiguous`. The name signal survives for its actual job: matching
when the number is absent or unreadable.
*Accepts one risk:* a genuine re-numbering (a replaced card, an account
migration) now creates a second account instead of asking. That is recoverable
by a merge ruling and is the rarer event.

**Option B — add the product name to the signal set.** `Everyday Checking`
against `High-Yield Savings` distinguishes them. More signal, and more surface
to be wrong about — product names are marketing strings that change.

**Option C — keep asking, make the question cheap.** It is one tap. But it fires
on the most ordinary account pairing there is, and the queue's whole thesis is
that a question we can answer ourselves should not be asked.

**Recommendation: A**, with B's product name kept as an attribute that
*strengthens* a `same` verdict rather than one that resolves ambiguity.

## A1 · Net worth's grade is a constant, so `provable` means nothing · **read**

`closing_balance_observed` writes no `grade` key; the projection stores `""`;
net worth does `grade or CORROBORATED`. Every line is `corroborated` and the
`provable` subtotal equals the total.

**The fix is not a fork: net worth should read the grade `balance()` already
computes**, rather than a field nobody writes. Read-side, no event change,
retroactive.

**But it exposes a decision that has to be made explicitly.** `provable` is
currently `grade == CORROBORATED`, which *excludes* `VERIFIED` — the grade a
figure earns when a person confirms it. Once the grade is real, that matters:

- **Option A — provable means issuer-attested arithmetic only** (`corroborated`).
  A human confirmation is trusted for your own view and does not enter the
  subtotal a counterparty would be shown. Honest to a third party by
  construction; means your own confirmation *lowers* what you can prove, which
  reads strangely until you remember who the audience is.
- **Option B — provable means corroborated or verified.** "We can show our work,
  and a person stood behind this one." Simpler to explain; weaker as a claim to
  someone who does not trust the person making it.

This is the audience question the net-worth decisions already raised and left
open. It should be settled now rather than inherited by the disclosure view.

## A2 · `en-us` silently reads dates day-first · **read**

`parse_amount` normalizes its locale; `parse_date` compares the raw string
against a two-entry tuple and falls through to day-first. `env.py` validates the
lowercased language part, so `VIVA_LOCALE=en-us` passes validation and then
flips every ambiguous date, with an assumption string that reads like a decision
made on evidence.

**Fix:** normalize case and separator in `parse_date` as `parse_amount` already
does. The only judgement is on validation strictness:

- **Option A — normalize and accept.** `en-us`, `en_US`, `en-US` all mean the
  same thing. Forgiving; hides a typo in a region subtag (`en-UK` is not a
  locale and would silently become day-first, which happens to be right for the
  UK and would be wrong for a real mistake).
- **Option B — validate the region subtag too, and refuse an unknown one.** A
  locale is a setting that decides how every figure in the vault is read; a
  typo in it should stop the run and list the valid values, which is what the
  language part already does.

**Recommendation: B**, on the precedent of the incident `env.py` already records.

## A5 · A unit count is verified by nothing · **write-adjacent**

`units_raw` is parsed by the **money** parser — locale grouping, currency
semantics — and the snapshot identity `Σ market_value + cash = total` never
touches units. A mis-grouped share count passes every check and posts
`corroborated`.

**Fix:** parse units with a share-count parser that has no currency and no
thousands ambiguity. Separately, where a statement prints a unit price, add
`units × price ≈ market_value` as a second identity. The corpus prints a price
column, so this is testable immediately.

*Note this changes what a stored claim means*, so it is the one Wave 1 item that
is not purely read-side: existing `units` values were parsed by the old rule and
a rebuild would re-derive them.

---

# Wave 2 — totals that overstate their own certainty

## R3 · The curve says `complete=True` while documents sit held · **read**

Savings has no account, so it cannot appear in `missing` or `skipped` — it is
invisible rather than named. The net-worth work fixed silent dropping of
accounts it *could not value*; this is the same failure for an account that was
never created, and the curve does not consult the held set.

- **Option A — `complete` goes false whenever any document is held**, and
  `missing` names them by type and reason. A held statement is a known hole in
  the picture, whether or not it produced an account.
- **Option B — leave `complete` alone and surface coverage beside the curve.**
  `coverage_summary` already computes this; the surface simply does not show it
  next to the figure. Less invasive, and keeps `complete` meaning strictly
  "every account I know of is valued".
- **Option C — both.**

**Recommendation: C.** `complete` is a claim about the whole picture, and a
person reading a net-worth figure has no way to know two statements are parked.

## R5 · The headline spending figure and its own breakdown disagree · **needs the vault**

The run reported spending **3,114.80** and a category breakdown summing to
**4,794.28**. In a product whose stated rule is that a report whose parts do not
add up to its total is a bluff, that gap needs a name before it needs a fix.

Hypothesis: `spending_by_currency` is scoped to depository and card legs while
`spending_by_category` walks a different population, so the two answer different
questions under one word — the honest-aggregates failure again, one layer down.

**Settle it with:** `python -m viva.debug_categories` against the corpus vault,
which lists per-category membership.

**Then, regardless of cause — a test that the breakdown sums to the headline.**
The partition rule is currently prose in a design doc; making it a build failure
is what stopped the category sprawl recurring and would stop this.

## R6 · The brokerage balance is `conflicted` · **needs the vault**

The cash chain reconciles by hand at every step: 1,240.18 → 1,464.10 → 1,668.30
→ 1,803.66, and each statement posted. Possible causes, in order of suspicion:
the duplicated instrument keys of R1 polluting the account's postings; the sweep
`position_cash` path adding cash the closing already includes; or an opening
observed at a date that does not order as expected against a string comparison.

**Settle it with:** `python -m viva.debug_vault` on the corpus vault, which
prints the reconciliation inputs. Worth doing **after** R1 lands, since the
first hypothesis is that this is a symptom rather than a defect.

---

# Wave 3 — the queue asks badly

Five findings, one theme: Viva asks about things the product already knows.

## R4 · Questions about movements a link already settled · **read**

Six transfer links formed, and the queue then asked *"2026-01-15: PAYMENT TO
MERIDIAN CARD 2291 — could you tell me what this one was?"* The tier-3 path
gates on the **merchant's** tier and never checks whether the movement's nature
is already decided.

**Fix:** skip a movement whose `nature_reason` is stronger than default or
category-hint — a link, a ruling, or an own-account match means we know. No
option here; asking after we know is the failure the tier work exists to prevent.

## B1 · A confident `0.00` for every non-expense counterparty · **read**

Totals accumulate from expense-shaped movements while the loop walks *every*
uncategorized counterparty, so an employer asks about itself claiming zero and
sorts last.

- **Option A — pass `expenses_only=True`.** Restores the narrow population. The
  cheapest fix, and it re-creates the blind spot that widening it fixed:
  employers and inflows stop being asked about at all.
- **Option B — total over all movements, not just expenses.** The question then
  states the counterparty's real volume in either direction. Keeps the wide
  population and makes the figure true.

**Recommendation: B.** A is a smaller diff and undoes a deliberate correction.

## B2 · Corroboration questions never go silent · **read**

No satisfaction check: the ask re-raises for every ruled account whose ruling
names a document, regardless of whether that document has since arrived. The
expectations path does this correctly and deterministically; this one can simply
borrow it. A mortgage currently re-asks for the 1098 every month, forever, after
you have given it the 1098.

## B3 · Ranking and the tail total add across currencies · **read**

`sort(-amount)` compares raw magnitudes regardless of currency, and the tail
emits a bare summed string with no currency at all — which the answer path and
the net-worth curve both explicitly refuse to do.

- **Option A — rank within currency, report the tail per currency.** Honest;
  needs a rule for interleaving two currencies in one list.
- **Option B — rank by a stated "primary" currency and list others after.**
  Simple, and it makes a choice on the person's behalf.

**Recommendation: A.** Invisible in a single-currency vault either way, which is
exactly how it would survive to the first vault that has two.

## B4 · Three option actions have no route · **read**

`review` and `dismiss` have no endpoint, and `assign_merchant` sends no
`category` where the handler requires one. `dismiss` matters most: it is "Not
right now" on corroboration and expectation questions, so the decline event is
currently unreachable from the two question kinds that most need it. Mechanical.

## B5 · A held non-balance document ranks at zero · **read**

Built with `amount=0` two lines below a comment insisting such a document "must
never be invisible". Ranking is by consequence, and a held pay stub's
consequence is not zero — the honest stake is the figure on the document, which
is already parsed.

---

# Wave 4 — the write side, and the boundary

These change events, guards, or what leaves the machine. Later by the
read-side-early rule, not by importance — A3 and A4 are honesty-wall findings.

## A3 · A model-invented `share` reaches the ledger · **write**

The comment states the rule and no code implements it. `unknown_split` also
inverts: it goes **false** when the model supplies a ratio, so the surface stops
saying "I can't tell how it splits" precisely when it should say it loudest.

- **Option A — refuse a share the sentence does not contain.** A deterministic
  check that the ratio appears in `said`. Keeps the capability for the person
  who genuinely says "sixty forty".
- **Option B — drop `share` from interpretation entirely.** A compound movement
  always lands `undecomposed` and asks for the document that states the split.
  This is *already the settled doctrine* for mortgages; Option B simply stops
  making an exception to it.
- **Option C — structural, like the amount rule.** `ruling_recorded` refuses a
  leg carrying a share unless the event's `said` contains it. The strongest, and
  it puts the guard where the amount guard already lives.

**Recommendation: C**, falling back to B if the `said` check proves brittle. The
amount boundary is the precedent and it has held.

## A4 · A tapped answer mints an unnamed asset into net worth · **write**

Tier-3 options carry only `{movement_key, major}`, so the account hint is empty,
`resolve_account` falls past the expense/income shortcut, and `rule_major`
applies in the same request without ever returning a Proposal. Answering *"I
still have it, in another form"* about an unidentified cheque creates
`Assets:Other:Unnamed` and adds it to the curve.

- **Option A — `rule_major` returns a Proposal when it would open an account**,
  and applies immediately when it would not. Preserves one-tap for the common
  case and confirms the irreversible one.
- **Option B — an asset or liability answer always requires a name.** The card
  gains a text field. Simpler rule, more typing.
- **Option C — refuse to mint an unnamed account at all.** Empty hint plus an
  asset or liability major becomes a question rather than an account.

**Recommendation: A and C together.** They are the same guard from two sides,
and X3 says this is enforced in code rather than remembered.

**Ruled and built 2026-08-01 — A and C together, as recommended.** `rule_major`
returns a proposal whenever an answer would open an account or bind an
ambiguous one, and applies in the request only when it would change nothing
structural. `resolve_account` answers an empty hint on an asset or liability
with an `unnamed` verdict — a question, not a path — and `apply_proposal`
refuses a proposal carrying one, as well as any path that is not a named
account under the chart of accounts. The related finding below is closed too:
`summary()` now says which existing account it took the answer to mean, so a
merge is confirmed rather than assumed.

Related, same area: when `resolve_account` returns `ambiguous`, the leg is
**already bound** to the fuzzy match, `confirm_accounts` is populated and never
read, and `summary()` — the one sentence a person confirms — does not mention
the merge. The match is a substring test, so `Car` matches `Carvana Loan`.

## C1 · The store appends onto a chain it never verified · **write-path**

`EventStore.__init__` takes the last record hash without checking continuity or
recomputing anything; `verify_chain` exists and `open()` never calls it. A
tampered or truncated ledger opens cleanly and accepts appends onto the bad tail.

- **Option A — verify on open, always.** Costs a full pass over the file at
  startup, without decrypting.
- **Option B — verify the tail only** (the last N records), full verification on
  demand. Cheap; a break earlier in the file survives until something reads it.
- **Option C — leave it, and document the trade.** Reads verify already, so a
  break is caught before any answer rests on it.

**This is the one repair where I do not have a recommendation**, because the
cost side is a measurement nobody has taken: how long a full verify takes on a
vault of realistic size. Worth measuring before choosing.

## C2 · The raw descriptor crosses the boundary, and persists unencrypted · **write**

What crosses to `merchantcore` is `m.description` — the raw bank descriptor,
verbatim — where T9 and the docstring both say "a normalized key and a
**linted** example". `is_shareable` gates *whether* a merchant crosses, not what
the example contains, so store numbers, city and state travel to the model
provider. Then `Catalog._save()` writes the **pending** queue — those same raw
descriptors — into the plain JSON that is unencrypted by decision and now shared
across vaults by decision. Anything submitted and never enriched stays there.

**Fixes, both needed:** lint the example (drop digits, trailing geography) so
what crosses matches what the invariant describes; and stop persisting `pending`
to disk, or persist only its keys.

## E1 · Two pay stubs can decompose one deposit · **write**

The matcher takes any unlinked depository inflow of equal amount within ten
days, and nothing marks the deposit consumed. Monthly and bi-weekly pay are safe
only because the interval exceeds the window — an accident of the constant, not
a property of the code. The corpus was built with differing nets specifically so
this failure would be visible rather than latent.

## E2 · Cross-document corroboration truncates its candidate list at twelve · **write**

`_subsets_summing_to` silently takes the first twelve candidates, and uniqueness
over that truncated set is the entire safety argument for auto-applying a
correction with no human in the loop. A thirteenth candidate that would make the
set ambiguous is invisible. **At minimum it must log when it truncates** — the
no-silent-caps rule applies here more than anywhere, because this is the one
place a silent cap can produce a wrong figure rather than a hold.

---

# Wave 5 — the instruments, and the cheap ones

Measured wrong, or merely untidy. Each is a stated fix.

- **D1 · The bench records prompt versions that do not resolve.** `t1`, `ti1`,
  `p2` and `p1` appear in the run log; none loads. The product already solved
  this with a self-describing composite id that reverses back to its parts; the
  bench never received the fix. Until then its published findings cannot be tied
  to the text that produced them.
- **D2 · `_system_metrics` does not compare values across runs** despite saying
  it does, and carries a literal `pass` marking the unfinished half. The headline
  table rests on it.
- **D3 · ECE is floored by the bin midpoint**, so a perfectly calibrated model
  scores 0.10 — which is the uniform figure in the published findings. Use the
  mean stated confidence within each bin.
- **D4 · `reset_categorization` prints arithmetic that does not add up**: kept
  human rulings are counted in both "kept" and "dropped". The count is the
  tool's entire value proposition.
- **D5 · `check_brokerage_identity` is not re-exported.** One line.
- **E3 · `apply_ruling` re-hydrates a client Proposal with no revalidation**,
  while the function twenty lines away deliberately re-derives its input
  server-side "so a stale page cannot pin the wrong fingerprint". Same reasoning,
  higher stakes. Related: `Proposal.settles` counts all movements for a merchant
  while `amount` is one movement's, so the confirmation sentence states a figure
  that is not the one being settled.
- **E4 · `movements()` is memoized nowhere**, and the net-worth curve rebuilds it
  two to three times per point. This is also the precondition for splitting
  `projection.py`: without a materialized `movements()`, the modules end up
  passing the whole projection to each other, which `networth` already does.
- **E5 · `_today()` is defined twice in one module with different formats**, and
  the projection's horizon comparison is lexical, so an event dated *on* the
  horizon is excluded.

---

# Proposed sequence

1. **R1b first** — the attested-total cross-check. It converts a silent wrong
   number into a loud one, and it makes R1 verifiable rather than hoped-for.
2. **R1, R2, A1, A2** — the wrong numbers. All read-side; the existing vault
   heals with no re-ingest.
3. **Re-run the corpus.** R6 may vanish; R5 gets diagnosed; the identity fixes
   get measured against a known answer rather than asserted.
4. **Wave 2 and Wave 3** — honest totals and the queue. Read-side throughout.
5. **Wave 4** — the write side, once the read side is settled.
6. **Wave 5** — the instruments, before they are trusted again.

## What this list does not contain

No repair here changes what a document means, adds a dependency to the trust
path, or requires a re-ingest of stored claims — with one exception, A5, which
is flagged as such. That is not an accident of the findings; it is the
read-side-early rule paying out, and it is the reason a list this long is not
alarming.
