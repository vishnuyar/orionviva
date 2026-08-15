# OrionViva — Transaction Intelligence: Implementation Instructions

**Status:** approved direction · **Revised:** 2026-07-28 (see §9) · **Scope:** post-v0 · **Commons storage:** git repo (interim; final decision deferred)

This document instructs the implementation of transaction understanding beyond
merchant identity: behavioral classification (subscription, bill, payroll, loan
repayment, gift, rent) and the question/confirmation loop. It builds on the
existing merchantcore/vivacore split and assumes the cold-look review's next-steps
list is accepted.

**It extends existing machinery rather than paralleling it.** Four pieces of this
project already do part of this job — the question queue, the three-tier ladder,
the movement-nature derivation, and scoped rulings. Where this spec touches them
it says so explicitly and by name. Nothing here introduces a second ranker, a
second precedence ladder, or a second question surface. Two instruments counting
the same population differently has already been a bug in this codebase once.

---

## 0. Framing (read first — it constrains every decision below)

Knowledge in this system is exactly one of three types. Never mix their storage,
their sharing rules, or their acquisition paths.

> **Naming note.** These are **K-numbers** (knowledge types), deliberately *not*
> T-numbers. `T1`–`T9` are this project's design invariants — T1 is
> provenance-and-confidence, T2 is *arithmetic is deterministic, models never
> certify*, T5 is no-plaintext, T9 is the personal/impersonal boundary — and every
> doc in `docs/` cites them by number. A second T-numbered vocabulary in the same
> repo would make "T2 enforced here" unreadable to a cold audit.

| Type | What it is | Example | Where it lives | Shareable? |
|---|---|---|---|---|
| **K1 — Brand behavior** | Impersonal facts about a merchant's billing model | "Netflix sells subscriptions" | merchantcore (git repo) | Yes |
| **K2 — Institution grammar** | How a bank/rail formats descriptors | NACHA field widths, a bank's Zelle sentence shapes | merchantcore grammar registry (git repo) | Yes |
| **K3 — Personal patterns** | Facts about one user's money | "$500 to a named person monthly = loan repayment"; *and also* which plan they are on, and how variable their bill is | encrypted local ledger only | **Never** |

Rule of thumb enforced in code review: if a fact would be true for a stranger, it
is K1/K2. If it is only true because of who this user is — including *which plan
they bought* and *how much they used* — it is K3, and it never leaves the vault,
never enters the git repo, and never appears in a model prompt except as an
abstracted pattern (see §4.6).

This is the operational form of T9, and it belongs in `design-invariants.md`
rather than only here.

---

## 1. Prerequisites (in order, before any new intelligence work)

0. **One induction call.** Run the inducer `--no-write` on the largest
   (institution × kind) pair, and have a person read the templates it returns.
   Everything from §3 onward keys on a decomposition layer that has never returned
   a result; one call costs pennies and can invalidate a section. This is gate
   zero because it is the cheapest de-risking step available and it was missing.
1. **Fix C2 — DONE.** Stop persisting raw descriptors in the pending queue's
   plain-JSON file; lint before persisting. Landed with
   [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md):
   the catalog applies the lint before the example is stored, deliberately a
   second time, so it is a property of the store rather than of the caller.
2. **NACHA rule into Layer 0.** The
   `<company name(16)> <entry desc(10)> <SEC(3)> ID: <company id(10)>` shape is
   specification, not a bank convention. Parse it deterministically in
   `descriptor.py`. Re-measure Layer 0 coverage after; the 88 zero-coverage keys
   should move substantially.
   - **Preserve the Company Entry Description as a first-class field** on the
     movement. It is the ten characters that literally read `Payroll`,
     `Direct Dep`, `Moneyline`, `Cashout`, `Assn Dues`, `Sale` — by a wide margin
     the most informative thing in an ACH line, and it is consumed in §4.4.
   - Preserve the SEC code too, but as **weak corroboration only** (§4.4 explains
     why it cannot carry the weight originally assigned to it).
   - Note the second finding this rule produces: the Company Name field is
     **hard-truncated at sixteen characters**, so the brand string it yields is
     clipped. That is why §1.3 exists.
3. **Adopt the two-key model.** Write the ADR and implement:
   - **Local key** = versioned deterministic normalization of the descriptor
     (existing `merch-v2`). Stable per-user, not portable — a truncated company
     name is stable for one bank's customers and matches nothing another bank
     prints.
   - **Brand key** = identified canonical brand (model/KB output, graded, with
     provenance). Portable; this is the commons key.
   - The catalog is **re-keyed on brand key** when one exists; local keys become
     aliases pointing at the brand record. Two locations of one warehouse retailer
     must resolve to one brand record with two aliases. Acceptance test: one
     commons row per multi-location merchant.
   - Everything in §2–§4 keys on brand key where resolved, local key otherwise.

---

## 2. Behavioral enrichment (K1) — extend the existing enricher

**One field is brand knowledge. Two are not.** The original draft of this section
asked the model for three fields and shipped all three to the commons. Only the
first survives that treatment:

- **`billing_model`** ∈ { `subscription`, `metered_recurring`, `one_off`,
  `payroll`, `lender`, `government`, `p2p_rail`, `unknown` } — **K1, shareable.**
  A streaming service sells subscriptions; a utility meters; a lender lends. True
  for a stranger.
- **`cadence_class`** and **`amount_stability`** — **K3 with a K1 cold-start
  prior.** A streaming service bills monthly *or* annually; which one is a fact
  about the plan this user bought. A utility's amount stability is a fact about
  this user's consumption. These are **observed locally** (§4.3 already computes
  `median_interval_days` and `amount_cv`), with an optional model prior used only
  before observation exists (§5). Both are properties of a **flow** — one
  direction of a stream — rather than of the stream (§4.1).

Consequences, all mandatory:

1. **`cadence_class` and `amount_stability` never enter the commons export.** A
   lint test asserts it, in the same place the amounts/dates lint lives. A wrong
   shared prior is worse than no prior, because it arrives pre-trusted.
2. **`observed_local` outranks `model_knowledge`** for exactly these two fields,
   stated in the grade ladder, not left implicit. Otherwise a model's "bills
   monthly, fixed" persists against direct evidence that this user pays annually —
   and T2 (measurement beats assertion) is the invariant that forbids it.
3. `unknown` is a **first-class, rewarded answer.** The prompt states explicitly
   that a null/unknown answer for an unrecognized brand is correct and a guessed
   answer is a failure. The schema allows it. The output format must not imply an
   answer is expected. (X2.)
4. Every value carries the existing grade-and-provenance envelope. New provenance
   grades: `model_knowledge`, `model_websearch`, `user_confirmed`,
   `observed_local`.
5. **`billing_model` publishes to the commons only once corroborated**, on the
   same rule as merchant categories — independent vaults agreeing. Until pooling
   exists (§7), a `billing_model` derived from one model call in one user's run is
   held locally and marked as awaiting corroboration. Publishing a single model
   opinion as shared knowledge is the failure mode the graded-prior design exists
   to prevent, and the git repo is the place it would happen silently.
6. **Web-search escalation tier.** On low-confidence or unknown from tier 2, a
   second call may be made with a web-search tool attached. Constraints:
   - Search-enabled calls are a separate code path, separately logged, separately
     graded (`model_websearch`).
   - The query is composed **only** from the candidate brand name / linted key.
     Raw descriptors, names, amounts, dates, reference numbers never enter a
     search-enabled call. Lint assertion at this boundary.
   - **The return direction is also a boundary.** Search results are
     attacker-influenceable text entering a prompt whose output is graded and
     published. A page ranking for a brand name is an injection surface into the
     commons. Therefore: web-search-derived fields are **quarantined from the
     commons export** until corroborated by a non-search source, and graded
     strictly below `model_knowledge`. Add the case to
     `threat-model-and-ingestion-security.md`, which does not currently cover it.
   - Batched and threshold-triggered; this tier is the exception, not the default.

---

## 3. Grammar registry (K2) — commons-ready, git-stored

1. Induced institution grammars (the `profile.py` / `induce.py` output) are
   shareable by construction: slots and literals, no values. Store them in the
   merchantcore git repo keyed by `(institution × document kind)`.
2. **Do not freeze profiles yet.** Run the inducer `--no-write`, keep grammars in
   memory, freeze only after a second and third institution have passed through.
   The vocabulary took four structural corrections from forty lines of one
   statement; by this project's own *write-side-late* rule the shape is still
   moving. The registry format can be defined now; population waits for stability.
3. A grammar is **not automatically safe to publish.** Holes are bounded by the
   vocabulary, but the literal text between them comes from the model and could
   carry a name baked in. `narrow_templates()` flags any template matching zero
   or one distinct line of the corpus, deterministically, before a human reads
   it — a name baked into literal text can only ever match its own line, so it
   lands there. Both checks — the automated one and the human read — gate a
   contribution. *(Amended 2026-08-09: this named `suspect_literals()`, which
   measured the same worry by inspecting words rather than by counting matches.
   It was superseded, went uncalled, and was deleted.)*
4. Contribution path for now = pull request to the git repo. Each grammar carries
   provenance (which OrionViva version induced it, on how many lines, with what
   residue rate) and its `narrow_templates` result.

---

## 4. The stream engine (K3) — the core new build

Entirely local. **Deterministic first, inferential second** — §4.3 ships and is
useful before §4.4 exists, and §4.4's priors are checkable only once §4.3 can
measure them.

### 4.1 Streams

- A **stream** is the ordered sequence of movements sharing a **stream key**.
- The stream key is `(counterparty, channel)` — brand key if resolved, else local
  key, else (for peer rails) the counterparty extracted by Layer 0/1 parsing;
  paired with the channel (card / ACH / Zelle / wire / ATM / check).
  **Counterparty alone is not enough:** a large retailer is both a subscription
  and a one-off store, and a single institution receives both a savings sweep and
  a loan repayment. Features computed over that mixture describe nothing.
- **The channel is proven, or inherited, or stood in for.** A line's own
  structure proves a rail where it can; failing that the rail comes from the
  channel this counterparty's other lines on the same account prove, when they
  prove exactly one; failing that the matched template stands in for it, so an
  ATM withdrawal and a cheque still separate. The inheritance is bounded to one
  account at one institution, so a merchant paid on cards at two banks is still
  two streams.
- **A stream key never drops the party.** Two movements differing only in who
  was on the other side may not land in one stream, and an institution — the
  conduit, shared by everyone reached over it — never occupies the brand slot or
  counts as the party a template names. Fragmentation is recoverable;
  a merged key is a rhythm nobody has, computed over somebody else's money.
- **Direction splits the statistics and never the key.** Money moving both ways
  with one counterparty is one relationship — a brokerage, a loan to a friend, a
  refund against a purchase — so a stream holds a **flow** per direction and no
  rhythm statistic spans two directions. Anything reading a rhythm — a noticing
  that one changed, above all — reads a `(stream, direction)` pair.
- A stream may **split further** when its amounts are clearly bimodal. A split is
  **visible in the surface**, never silent — "one answer labels the stream" is a
  promise to the user, and a stream that silently divided has broken it. *(Built
  in step 2, and narrower than this bullet reads: the split is a **read-side
  decomposition by amount**, per `(merchant key, direction)` rather than per
  stream, into at most two parts — the longest run of amounts the flow already
  calls one amount, and the remainder. Every cadence, interval and stability
  belongs to one part, nothing is stored, and the visibility is the sentence
  itself: a mixture is named, each part's own count and money are stated, and
  the person is asked which is which. The remainder may itself be a mixture; it
  is not decomposed further.)*
- Streams are derived (a projection over the ledger), not stored state. Rebuild on
  ingest. §5 makes this load-bearing rather than merely tidy.

### 4.2 Streams are useful before any inference

Ship this half first. With no hypotheses at all, the engine answers *"here is
every counterparty you pay more than once, how often, how much, and how steady"* —
which is real user value, needs no model, and cannot be wrong about the world
because it only reports what the ledger contains.

### 4.3 Stream features (deterministic, computed on every ingest)

On the **stream**: `n` (count), `direction_mix`, `channel`, `role`,
`first_seen`, `last_seen`, `entry_descriptions` seen, `sec_codes` seen.

On each **flow** — one per direction the money moved: `n`,
`median_interval_days`, `interval_mad`, `amount_cv`, `amount_mode`,
`day_of_month_mode` and its stability, `first_seen`, `last_seen`,
`gap_since_expected` (§4.5).

`cadence_class` and `amount_stability` (§2) are **derived from these**, not
fetched, whenever a flow's `n` is sufficient — see §5 for what sufficient means.
A stream carries neither, so no figure averaged across both directions can be
read by accident.

### 4.4 Hypothesis distribution

Every stream carries an explicit belief: a distribution over `stream_kind` ∈
{ `subscription`, `recurring_bill`, `payroll`, `loan_repayment`, `rent`,
`gift_or_transfer`, `shared_expense`, `one_off_purchases`, `savings_transfer`,
`unknown` }.

**`stream_kind` feeds the existing movement-nature derivation** rather than
sitting beside it. `honest-aggregates-and-the-learning-loop.md` defines the
precedence — link → human ruling → own-account → what the counterparty implies →
default — and a stream kind enters that ladder as evidence at the implication
level, below a human ruling. It does not become a second, competing answer to
"is this spending?". Two systems describing the same fact and an aggregate
listening to only one is the bug that doc was written about.

_**Corrected 2026-08-15**, and it is two corrections in one line. This said
"link → own-account → human ruling → category hint → default", citing a document
that no longer says that: the two middle rungs are the other way round — a
person's ruling outranks the own-account heuristic, because that heuristic
matches raw account tokens with no distinctiveness filter and a loose heuristic
must not silently discard an owner's explicit answer — and the fourth rung reads
no category or subcategory **label** at all. It reads an `implies` entry on the
counterparty's enrichment record, filtered by direction, which is what a stream
kind now has to enter beside. The primary document was corrected 2026-08-14;
this line repeated the old order and attributed it there, which is the more
expensive kind of stale sentence, because it looks sourced._

Priors are seeded **from transaction one** — do not wait for frequency. Every row
below carries an explicit strength, and **every row is a claim about the world
that must be checked against a real vault before it is trusted**:

| Signal | Prior it moves | Strength |
|---|---|---|
| Brand `billing_model` (§2) | a `subscription` brand ⇒ subscription hypothesis dominant on first sight | **strong** |
| **Company Entry Description** (`Payroll`, `Direct Dep`, `Assn Dues`, `Cashout`, `Moneyline`) | names the purpose in the originator's own words | **strong** — the most informative field in an ACH line |
| Channel | a peer-rail outflow ⇒ {gift, loan_repayment, rent, shared_expense} only | **strong** (a constraint, not a guess) |
| Direction | inflows are never subscriptions; keep the inflow taxonomy honest (payroll, refund, transfer-in, gift-in) | **strong** (a constraint) |
| SEC code | `WEB` ⇒ consumer-initiated; `CCD` ⇒ corporate originator; `PPD` ⇒ prearranged, **nothing more** | **weak** |
| Day-of-month | 1st–5th large fixed outflow ⇒ rent/mortgage weight | weak |
| Amount shape | priced amounts (`15.49`) ⇒ subscription-like; round amounts ⇒ peer-like | weak — round-number subscriptions and priced utility bills are both common |

> **Correction, recorded because the failure is instructive.** An earlier draft of
> this table asserted `PPD inflow ⇒ payroll` as a dominant signal. PPD is the SEC
> code for *any* prearranged consumer credit or debit: dividends, tax refunds,
> benefit deposits, insurance payouts, wallet cashouts and brokerage transfers all
> arrive as PPD. The forty descriptors of the first real dry run already contained
> at least two PPD inflows that are not payroll. The rule was falsified by evidence
> that was on the table before it was written — which is the argument for checking
> each row of this table against the vault rather than reasoning it out.

Evidence from each new statement updates the distribution (simple Bayesian or
weighted-score update — keep it inspectable; no opaque ML in v1). Every belief
renders with its evidence: the "receipt" promise applied to inferences, not just
numbers.

> **What step 2 built, 2026-08-12, and how it differs from this section.** The
> first hypothesis is not a distribution over the ten `stream_kind` labels. It is
> one belief per `(merchant key, direction)` pair, over two inputs that each do
> half the work: **the impersonal billing prior licenses the question** and **the
> measured flow proposes its answer**. The prior is the first row of the table
> above, made real — `enrich-v6` returns `billing` (`standing` · `per_purchase` ·
> `either`) and `billing_period` (`monthly` · `annual` · `either`), validated in
> code against a closed set and dropped when it speaks outside it, filed in the
> catalog record's `attributes` bag as a fact about the merchant. A merchant the
> world only ever sells to per purchase raises nothing at all; that is the
> settled rung on this axis.
>
> Where the two disagree the ledger wins outright, and a measured absence of
> rhythm is something the ledger said: above the cadence floor the prior is not
> consulted, and movements whose spacing never settled propose `irregular`
> rather than being told there is too little here to see a pattern. Below the
> floor no cadence is claimed at all — only the count and what the world says
> about the merchant. A steady rhythm the confirmable vocabulary has no word for
> (weekly, quarterly) proposes nothing rather than rounding to a neighbour.
>
> A confirmation is a `rhythm`-scoped `RulingRecorded` keyed
> `<merchant key>|<direction>` — never a rail, never a stream key, because both
> are derived and change unattended — carrying a **set** of periodicities, so one
> relationship holding a monthly arrangement and an annual one is one subject
> with both and a correction is an ordinary re-answer. Step 3's *a rhythm broke*
> must therefore ask whether a measured cadence is **among** the confirmed set,
> never whether it equals one.
>
> Left open: the false-mixture rate is unmeasured on real data, and the
> decomposition accepts two survivors it describes as one arrangement — a
> monthly-plus-annual pair on one anchor day, and a sub-monthly interleave.
>
> *Amended 2026-08-13:* **a person is not a counterparty on this axis.** What
> two people arrange between them is a relationship rather than a billing model,
> so a movement whose other side a grammar slot declared a party is dropped
> before any flow is formed — no measurement, no hypothesis, no question, no
> subject. The declaration is the enrichment gate's, carried to the projection
> by the resolver, and it is exactly as wide: a name in a slot the grammar
> called `{brand}` is declared a person by nothing and still forms a flow.
>
> *Amended 2026-08-13 (second):* **the prior licenses on two facts of one
> record, not one.** The pair is raised only where the catalog says the
> counterparty is a `business` *and* says an arrangement with them is possible,
> so a record naming a rail or a person — or naming no kind at all — raises
> nothing however it bills. The flow is measured either way: the label withholds
> the question, never the measurement. The label is itself model-authored and is
> rewritten by the next enrichment, so this narrows what a name in a `{brand}`
> slot can reach and does not close it.

### 4.5 Forecast ledger

> **Naming note.** Called *forecasts*, not *expectations*. The **expectations
> registry** (`expectations-v1.json`) already exists and means something else —
> what a *document kind* should contain. Two different things called expectations,
> both events, both in the ledger, would be unreadable.

On every ingest, for each stream with a leading hypothesis above threshold, emit
dated **forecasts**: `expect ~15.49 from <brand> around 2026-08-03 ± 3d
(subscription hypothesis)`.

- Next ingest resolves forecasts automatically: hit ⇒ confidence up; miss ⇒
  evidence of cancellation or payoff ⇒ surface it.
- Forecasts live in the encrypted ledger as events, so replay reproduces belief
  history.
- **Forecasts are dated in value-time, not knowledge-time.** A bulk load emits
  forecasts for dates already past; those resolve immediately against movements
  already present and are never surfaced as misses. The ledger is already
  bitemporal; this makes use of it. See §5.
- This mechanism is why a monthly statement cadence is not a blocker: each
  statement is a batch of resolved experiments.

### 4.6 The question loop — an extension of the question queue, not a new one

`the-question-queue.md` already defines a read-side `Question` projection ranked by
consequence, with answers routed to existing writers and **no new event type**.
`where-the-intelligence-goes.md` already defines the three tiers — silence /
informed proposal / real question — and the forced-suggested-unlocalized ladder.
This section adds **a stream scope to that queue.** It does not add a ranker, a
surface, or an event type.

- A question is generated only from a **stream-level** ambiguity, never
  per-transaction. One answer labels the stream retroactively and prospectively,
  recorded through the existing scoped-ruling machinery (`user_confirmed`
  provenance).
- Every question is a **confirmation with a proposed default**, carrying its
  evidence — tier 2 of the existing ladder, not a new format. Never an
  open-ended "what is this?".
- **Ranking uses the existing consequence rank** (how much money answering it
  moves). The "it may resolve itself if we wait" intuition is expressed as a
  **hold filter**, not as a denominator: suppress a question whose leading
  hypothesis is above threshold *and* whose next forecast resolves within N days.
  An expected-information-gain denominator is not implementable as stated — it
  requires an arrival model and diverges toward zero.
- Also honour the repair list's B3 finding: skip a stream whose nature is already
  decided by something stronger than a category hint. Asking after we know is the
  failure the tier work exists to prevent.
- **Peer streams are strictly local.** Peer counterparty names, user answers about
  peers, and user-defined peer categories never enter merchantcore, the git repo,
  or any model prompt. If a model call labels an ambiguous stream, the prompt
  receives only the abstracted pattern — `"outflow, ~500, monthly on day 1, 4
  occurrences, p2p channel"` — never names, descriptors or exact amounts. Lint
  assertion at this boundary, identical in spirit to §2.6.

---

## 5. Ingestion shape — cold start, bulk load, and order independence

**Two arrival patterns must both work, and neither is the default.** One user
hands over a single statement and adds one a month. Another hands over a year in
one afternoon. The engine's behaviour differs enormously between them, and the
difference is not a tuning detail — it decides which source of belief leads.

### 5.1 Evidence strength decides precedence, not a fixed ladder

| stream state | who leads | what the other is for |
|---|---|---|
| `n = 1` | the **K1 brand prior** (§2) | nothing to observe yet; observation is silent, not zero |
| `n = 2` | prior still leads; one interval is not a cadence | the interval is recorded, not yet believed |
| `n ≥ 3` and `interval_mad` small | **local observation** | the prior becomes a tiebreak and an *explanation* ("this is a subscription brand"), never an override |
| `n ≥ 3` and observation **contradicts** the prior | local observation, decisively | the contradiction is itself surfaced: an annual payer of a monthly-billing brand is a fact worth showing |

The belief must **flip without asking the user again.** A hypothesis that was
model-seeded and is later overturned by observation is a normal transition, logged
with its evidence, not a question.

### 5.2 Order independence is an invariant, and it is testable

> **The stream projection is a pure function of the *set* of movements in the
> ledger, never of the order they were ingested in.**

A user who loads twelve statements in one afternoon and a user who loads one a
month for a year must arrive at the **same belief state** for the same underlying
money. This falls out of §4.1's "streams are derived, not stored" — which is why
that line is load-bearing rather than tidy — but it must be asserted by a test,
because the tempting optimisations (incremental feature updates, cached
hypothesis state) all break it silently.

The harness exists: the synthetic corpus already ingests documents **out of date
order** deliberately. Add the paired assertion — ingest the same corpus in
several orders, assert identical stream features and identical hypothesis
distributions.

### 5.3 A bulk load is one event, not forty

- **Questions fire after a batch settles, not per document.** A user who hands
  over a year gets *one* digest, not forty. The digest cap is per settled batch,
  not per ingested file.
- **Forecasts for past dates resolve silently.** A bulk load emits forecasts
  across the whole loaded period; those with movements already present resolve
  immediately and never surface. Only forecasts whose window is genuinely open —
  or genuinely missed within the loaded period, which is real evidence — are
  shown.
- **Nothing waits for volume to be useful.** §4.2's deterministic report works on
  one document (it reports `n=1` streams honestly). The drip user is not shown an
  empty product until month three.

### 5.4 Cold start is answered with silence, not a guess

With `n = 1` and no brand knowledge, the honest answer is `unknown`, and the
honest surface behaviour is **tier 1 — silence**. Not a low-confidence guess, not
a question. This is X2 applied to the moment the product knows least, which is
exactly the moment the temptation to appear clever is strongest.

---

## 6. Privacy invariants (enforced as tests, not conventions)

1. Raw descriptors: encrypted ledger only. Never in the git repo, never in plain
   JSON (C2), never in search-enabled prompts.
2. K3 facts never cross the vault boundary in any form except the
   abstracted-pattern shape of §4.6.
3. Anything entering the git-repo commons passes the lint and contains no amounts,
   dates, counts, account references, or personal names — **and no
   `cadence_class` or `amount_stability`** (§2).
4. Search-enabled model calls: query = candidate brand string only (asserted);
   results quarantined from the commons until corroborated (§2.6).
5. A grammar contribution passes `narrow_templates()` and a human read (§3.3).
6. Every derived claim (category, billing model, stream kind) carries grade +
   provenance + the pointer to its evidence.

---

## 7. Explicitly out of scope (do not build yet)

- **User-contributed behavioral priors:** pooling observed cadence/amount classes
  across users. Deferred until a real cohort exists; requires k-anonymity
  thresholds (k≥5, coarse classes only) and a contribution-signing story. This is
  also what would corroborate `billing_model` (§2.5) — until it exists, that field
  is held locally rather than published.
- **Commons hosting decision** (service vs git vs signed ledger): deferred.
  Current answer is the git repo; design nothing that assumes a server.
- Fuzzy merchant matching, keyword lists, model-written regexes: remain rejected
  per prior ADRs.

---

## 8. Build order and acceptance gates

| # | Work item | Done when |
|---|---|---|
| 0 | ~~One induction call~~ **DONE** | templates read; the person slot works, and reading them found three vocabulary gaps |
| 1 | ~~C2 fix~~ **DONE** | the example is Layer-0 linted, the store lints again on submit, and a test asserts no digit crosses |
| 2 | ~~NACHA → Layer 0~~ **DONE** | SEC code and company id parsed from the spec; the Name/Entry-Description boundary is gone from any single line and is recovered from the statement |
| 3 | ~~Two-key model~~ **DONE, and simpler than planned** | the vault is being rebuilt, so there is no catalog to migrate and no alias layer: enrichment keys on the brand from the start |
| 4 | ~~Stream engine + features~~ **DONE** | streams key on (counterparty, rail) and carry a role; cadence and stability are measured per direction on a flow, `unknown` below three observations |
| 5 | ~~Order-independence test~~ **DONE** | four shuffles plus a reversed run; asserted, not argued |
| 6 | Hypotheses + priors | **each row of §4.4's table checked against the real vault** and its strength recorded; distribution renders with evidence |
| 7 | Forecast ledger | a later ingest auto-resolves ≥1 forecast end-to-end; past-dated forecasts resolve silently |
| 8 | Question digest, as a stream scope on the existing queue | one batched digest from the existing ranker; answers land through existing writers; replay reproduces |
| 9 | Behavioral enrichment (`enrich-v5`) | `billing_model` flowing with grades; `unknown` observed on tail brands; cadence/stability **absent** from the commons export, asserted. *Enrichment itself is now brand-keyed and slot-gated (§4 of the conduit spec); only the three new fields remain.* |
| 10 | Web-search escalation tier | separate path, linted queries asserted, results quarantined from commons, threat-model entry merged |
| 11 | Grammar registry format in git | format merged; population deferred until profiles stop moving |

**The reordering versus the first draft is one idea:** ship the deterministic half
of the stream engine (4–5) before the inferential half (6–7), and ask the model
(9) only for what the ledger cannot answer. That is the same rule that produced
the parts of this codebase that have survived contact with real data.

Items 6–7 and 9 are parallelizable after 4–5.

---

## 9a. What the build settled (2026-07-28, evening)

Gates 0–5 are done, and two of them turned out differently than written.

**Gate 3 got cheaper, not harder.** The two-key model was specified as a
migration — brand key, local keys as aliases, an existing catalog re-keyed. The
vault is being rebuilt, so there is nothing to migrate: enrichment keys on the
brand from the first record, and the alias layer is never built. A decision that
was expensive because of history stopped being expensive when the history went.

**A rule this spec inherited was deleted.** Layer 0's attempt to strip the bank's
own words from a brand candidate was falsified on 1,076 real movements — bank
words, city names and merchant names interleave by frequency, so no cut separates
them. Recorded in the conduit spec. The lesson for §4.4's priors table stands
and is now evidenced twice: **a table of thresholds is a set of claims about the
world, and each row needs checking against a vault before it is trusted.**

**The agent layer arrived early.** `viva/agent/policy.py` turns a vault into
proposed actions with preconditions evaluated — pure, no calls, no writes, no
questions — so the tools stop needing a person to type them. The division it
encodes: mechanical decisions are the agent's, judgements about what money means
go to the person, and anything changing what *other* people see waits for a
human. That last line exists because every quality gate here measures whether a
template matched, never whether it slotted correctly.

## 9. Corrections in this revision (2026-07-28)

Recorded rather than silently applied, because several of these were wrong in an
instructive way.

1. **`T1/T2/T3` → `K1/K2/K3`.** The original names collided with this project's
   design invariants, where T2 already means something a reader would apply here.
2. **`expectations` → `forecasts`** (§4.5), and *"Layer A"* dropped in favour of
   naming the thing (pooled behavioral priors). Both collided with existing terms.
3. **`PPD inflow ⇒ payroll` removed** and the SEC code demoted to weak
   corroboration; the **Company Entry Description promoted to first-class**. The
   original rule was falsified by descriptors already in hand.
4. **`cadence_class` and `amount_stability` reclassified K1 → K3**, removed from
   the commons export, and given an explicit precedence rule (`observed_local`
   beats `model_knowledge`).
5. **`billing_model` held until corroborated** rather than published from a single
   model call, matching the corroborated-by-count rule the catalog already has.
6. **§4.6 rewritten as an extension** of the question queue and the three-tier
   ladder; `stream_kind` routed into the movement-nature derivation instead of
   beside it. The ranker denominator became a hold filter.
7. **Stream key widened to `(counterparty, channel)`** with a visible split rule.
8. **Web-search return direction addressed** — quarantine plus a threat-model
   entry.
9. **§5 added**, from a design question that had not been asked: users arrive with
   one document or with a year, and the engine must serve both. It produced the
   evidence-strength precedence table and the **order-independence invariant**,
   which is the most testable thing in this document.
10. **Gate 0 added.** Nine acceptance gates and none of them covered the fact that
    the layer everything sits on had never returned a result.
