# OrionViva — Transaction Intelligence: Implementation Instructions

**State:** partial
**Rules:** PROJ-41, PROJ-42, PROJ-43, PROJ-44, PROJ-45, PROJ-46, PROJ-47, PROJ-48, PROJ-49, PROJ-50, PROJ-51, PROJ-52, PROJ-53, PROJ-54, PROJ-55, PROJ-56, PROJ-57, PROJ-58

## Rules

### PROJ-41 — knowledge is exactly one of three types, and their storage never mixes
**State:** enforced
**Code:** merchant/merchantcore/normalize.py:68
**Test:** merchant/tests/test_merchantcore.py::test_peer_payment_is_not_shareable

1. K1 (brand behavior — impersonal facts about how a merchant bills) and K2 (institution grammar — how a bank or rail formats descriptors) are impersonal and may be shared.
2. K3 (personal patterns — facts about one user's money, including *which plan they bought* and *how much they used*) lives in the encrypted local ledger only, and never enters the shared catalog, the repo, or a model prompt except as an abstracted pattern.
3. A fact that would be true for a stranger is K1 or K2; a fact true only because of who this user is, is K3.
4. The commons export carries only records whose key passes the shareability lint, and that lint fails closed.
5. These are K-numbers, deliberately not T-numbers: T1–T9 are the design invariants, and a second T-vocabulary in the same repo would make "T2 enforced here" unreadable to a cold audit.

### PROJ-42 — the ACH line shape is specification, parsed deterministically
**State:** enforced
**Code:** merchant/merchantcore/descriptor.py:186
**Test:** product/tests/test_streams.py::test_the_ach_entry_description_is_recovered_from_the_statement

1. The NACHA company-name, entry-description, SEC-code and company-id shape is parsed deterministically rather than treated as a bank convention.
2. The Company Entry Description is preserved as a first-class field: it is the originator's own word for the purpose, and by a wide margin the most informative thing in an ACH line.
3. The SEC code is preserved as weak corroboration only.
4. The Company Name field is hard-truncated by the specification, so the brand string it yields is clipped and is not portable across banks.

### PROJ-43 — two keys: a stable local key and a portable brand key
**State:** enforced
**Code:** product/viva/ledger/projection/merchants.py:59
**Test:** product/tests/test_merchant_keys.py::test_two_locations_of_one_brand_are_one_key

1. The local key is a versioned deterministic normalization of the descriptor: stable per user, not portable.
2. The brand key is the identified canonical brand: portable, and the key the commons uses.
3. Every lookup considers both candidates, brand first, so an answer a person recorded under the older name is not stranded.
4. Enrichment keys on the brand from the first record; two locations of one retailer resolve to one record.

### PROJ-44 — billing is a fact about the merchant, from a closed set
**State:** enforced
**Code:** merchant/merchantcore/enrich.py:165
**Test:** merchant/tests/test_merchantcore.py::test_a_billing_model_outside_the_closed_set_is_dropped

1. A billing model outside the closed set is dropped and logged, and takes its period with it.
2. A period outside the closed set, or one offered for a merchant billed only per purchase, is dropped on its own and the model survives.
3. Absent is a normal answer, not a parse failure.
4. Billing is identical for every customer of that merchant, and is never a claim about any person's own arrangement.

**Contradiction:** this document specifies a field `billing_model` over `{subscription, metered_recurring, one_off, payroll, lender, government, p2p_rail, unknown}` (§2 as originally written). The code has `billing` over `{standing, per_purchase, either}` with a separate `billing_period` over `{monthly, annual, either}` (merchant/merchantcore/enrich.py:165). No `billing_model` field exists anywhere.

### PROJ-45 — the measurement beats the prior, and a measured absence is something the ledger said
**State:** enforced
**Code:** product/viva/ledger/projection/rhythm.py:183
**Test:** product/tests/test_rhythm.py::test_a_measured_absence_of_rhythm_beats_what_the_world_says

1. Above the cadence floor the prior is not consulted at all; the measurement decides.
2. Movements whose spacing never settled propose `irregular`, rather than being told there is too little here to see a pattern.
3. Below the floor no cadence is claimed: only the count, and what the world says about the merchant.
4. A steady rhythm the confirmable vocabulary has no word for proposes nothing, rather than rounding to a neighbour.

### PROJ-46 — a stream key is a counterparty and a channel, and never drops the party
**State:** enforced
**Code:** product/viva/ledger/streams.py:418
**Test:** product/tests/test_streams.py::test_a_stream_key_never_drops_the_party

1. A stream is the ordered sequence of movements sharing a key of counterparty and channel.
2. Two movements differing only in who was on the other side may not land in one stream.
3. An institution — the conduit, shared by everyone reached over it — never occupies the brand slot and never counts as the party a template names.
4. The channel is proven by the line's own structure where it can be; failing that it is inherited from the channel this counterparty's other lines on the same account prove, when they prove exactly one; failing that the matched template stands in for it. Inheritance is bounded to one account at one institution.

### PROJ-47 — direction splits the statistics and never the key
**State:** enforced
**Code:** product/viva/ledger/streams.py:131 (`Flow` — every rhythm statistic lives here, not on the stream), :274 (`Stream`)
**Test:** product/tests/test_streams.py::test_no_rhythm_is_offered_across_two_directions

1. Money moving both ways with one counterparty is one relationship, so a stream holds a flow per direction.
2. No rhythm statistic spans two directions, and anything reading a rhythm reads a stream-and-direction pair.

### PROJ-48 — a direction is decided by the account's kind, never by the posted sign
**State:** enforced-with-exception
**Code:** product/viva/ledger/streams.py:79
**Test:** product/tests/test_streams.py::test_a_card_purchase_reads_as_money_out

1. One derivation answers direction, `money_effect(kind, amount)`.
2. A movement whose account kind is unknown raises rather than being read off its sign.

**Exception:** product/viva/ledger/projection/merchants.py:152 still picks an implication by the posted sign.

### PROJ-49 — cadence and stability are measured, never asked for
**State:** enforced
**Code:** product/viva/ledger/streams.py:132
**Test:** product/tests/test_streams.py::test_cadence_and_stability_are_measured_not_asked_for

1. Cadence class and amount stability are derived from a flow's own measured features, not fetched from a model.
2. Below three observations they are `unknown` rather than guessed.
3. A stream carries neither, so no figure averaged across both directions can be read by accident.

### PROJ-50 — the stream projection is a pure function of the set of movements
**State:** enforced
**Code:** product/viva/ledger/streams.py:418
**Test:** product/tests/test_streams.py::test_ingest_order_never_changes_a_belief

1. Streams are derived on read and are never stored state.
2. A vault loaded in any order arrives at the same stream features and the same beliefs.
3. A user who loads a year in one afternoon and a user who loads one statement a month reach the same belief state for the same underlying money.

### PROJ-51 — a split is visible in the sentence, never silent
**State:** enforced
**Code:** product/viva/ledger/projection/rhythm.py:284
**Test:** product/tests/test_rhythm.py::test_a_mixture_states_what_it_saw_of_each_part_and_asks_which_is_which

1. The decomposition is read-side, per counterparty and direction, into at most two parts: the longest run of amounts the flow already calls one amount, and the remainder.
2. Every cadence, interval and stability belongs to one part, and nothing is stored.
3. A mixture is named in the sentence, each part's own count and money are stated, and the person is asked which is which.
4. The remainder is not decomposed further.

### PROJ-52 — a rhythm confirmation is a scoped ruling carrying a set
**State:** enforced
**Code:** product/viva/ledger/events.py:560
**Test:** product/tests/test_rhythm.py::test_which_is_which_is_recorded_as_one_set_valued_ruling

1. A confirmation is a `rhythm`-scoped ruling keyed by merchant key and direction — never a rail and never a stream key, because both are derived and change unattended.
2. Its value carries a *set* of periodicities, so one relationship holding a monthly arrangement and an annual one is one subject with both, and a correction is an ordinary re-answer.
3. Any later check asks whether a measured cadence is *among* the confirmed set, never whether it equals one.

### PROJ-53 — the question is a stream scope on the queue that already exists
**State:** enforced
**Code:** product/viva/questions.py:1
**Test:** product/tests/test_rhythm.py::test_a_question_is_ranked_on_money_already_measured

1. A question is generated from a stream-level ambiguity, never per transaction; one answer labels the relationship retroactively and prospectively.
2. Every question is a confirmation with a proposed default carrying its evidence, never an open-ended *what is this?*.
3. Ranking uses the existing consequence rank. No second ranker, no second surface, no new event type.
4. A stream whose nature is already decided by something stronger than a counterparty hint is skipped: asking after we know is the failure the tier work exists to prevent.

### PROJ-54 — a grammar is not automatically safe to publish
**State:** enforced
**Code:** merchant/merchantcore/induce.py:159
**Test:** merchant/tests/test_profile.py::test_a_template_is_judged_by_what_it_MATCHES_not_by_its_words

1. `narrow_templates` flags, deterministically and before any human reads them, every template matching zero or one distinct line of the corpus.
2. A name baked into literal text can only ever match its own line, so it lands there.
3. Both gates — the automated count and the human read — stand between a grammar and a contribution.
4. A grammar carries its provenance: which version induced it, on how many lines, with what residue rate.

### PROJ-55 — induced grammars are held outside any working tree until a person promotes them
**State:** by-review
**Code:** merchant/merchantcore/home.py:37 (`learned`), :43 (`shipped`), :51 (`shipped_profiles_dir`)
**Test:** none

1. A locally-induced grammar carries literal text a model wrote, so it is written outside any working tree where it cannot be committed by accident.
2. Lookup is layered and learned wins; nothing moves from learned to shipped automatically.

**Superseded:** an earlier draft of this document said induced institution grammars were "shareable by construction" and should be committed to the merchantcore repo keyed by institution and document kind. That is not what the code does and not what this rule says. `merchant/merchantcore/home.py:37` writes learned grammars outside any working tree; `:51` leaves the in-repo directory a read-only seed a person promotes into by hand, and it holds no grammars.

### PROJ-56 — cold start is answered with silence, not a guess
**State:** enforced
**Code:** product/viva/ledger/streams.py:64
**Test:** product/tests/test_streams.py::test_below_the_floor_it_says_unknown_rather_than_guessing

1. With one observation and no brand knowledge, the honest answer is `unknown` and the honest surface behaviour is silence.
2. Not a low-confidence guess, and not a question.
3. Nothing waits for volume to be useful: the deterministic report works on one document and reports a single-observation stream honestly.

### PROJ-57 — the forecast ledger
**State:** unmet
**Code:** none found
**Test:** none

1. For each stream whose leading hypothesis is above threshold, a dated forecast is emitted on every ingest, and the next ingest resolves it: a hit raises confidence, a miss is evidence of cancellation or payoff and is surfaced.
2. Forecasts live in the encrypted ledger as events, so replay reproduces belief history.
3. Forecasts are dated in value-time, not knowledge-time: a bulk load emits forecasts for dates already past, and those resolve immediately and silently.
4. They are called forecasts, never expectations: the expectations registry already exists and means what a *document kind* should contain.

### PROJ-58 — a search-enabled call is a separate, quarantined path
**State:** unmet
**Code:** none found
**Test:** none

1. Search-enabled calls are a separate code path, separately logged and separately graded.
2. The query is composed only from the candidate brand name or linted key; raw descriptors, names, amounts, dates and reference numbers never enter one.
3. Search results are attacker-influenceable text entering a prompt whose output is graded and published, so search-derived fields are quarantined from the commons until corroborated by a non-search source, and graded strictly below ordinary model knowledge.
4. The tier is batched and threshold-triggered: the exception, not the default.

## Why

This describes transaction understanding beyond merchant identity — behavioral
classification and the question loop that goes with it. **It extends existing
machinery rather than paralleling it.** Four pieces of this project already do
part of the job: the question queue, the three-tier ladder, the movement-nature
derivation and scoped rulings. Nothing here introduces a second ranker, a second
precedence ladder or a second question surface. *Two instruments counting the
same population differently has already been a bug in this codebase once.*

**The three knowledge types constrain every decision.** Never mix their storage,
their sharing rules or their acquisition paths.

| Type | What it is | Example | Where it lives | Shareable? |
|---|---|---|---|---|
| **K1 — brand behavior** | impersonal facts about a merchant's billing model | a streaming service sells subscriptions | the shared catalog | yes |
| **K2 — institution grammar** | how a bank or rail formats descriptors | NACHA field widths; a bank's peer-payment sentence shapes | the grammar registry | yes |
| **K3 — personal patterns** | facts about one user's money | this person pays annually; this bill varies a lot | the encrypted local ledger | never |

**One field is brand knowledge; two are not.** An early draft asked the model for
three behavioral fields and shipped all three to the commons. Only the billing
model survives that treatment: a streaming service sells subscriptions, a utility
meters, a lender lends — true for a stranger. Cadence and amount stability are
**K3 with a K1 cold-start prior**: a streaming service bills monthly *or*
annually, and which one is a fact about the plan this user bought; a utility's
amount stability is a fact about this user's consumption. So they are observed
locally, with a prior used only before observation exists. A wrong shared prior
is worse than no prior, because it arrives pre-trusted. And `observed_local` must
outrank model knowledge for exactly those fields, or a model's "bills monthly,
fixed" persists against direct evidence that this user pays annually — which T2
forbids: measurement beats assertion.

`unknown` is a first-class, rewarded answer. The prompt says so explicitly: a
null answer for an unrecognized brand is correct and a guessed answer is a
failure. That is X2 at the moment the product knows least, which is exactly when
the temptation to appear clever is strongest.

**Publish nothing from one model call.** A billing model derived from a single
run in one vault is held locally and marked as awaiting corroboration, on the same
independent-agreement rule the merchant categories already use. Publishing a
single model opinion as shared knowledge is the failure mode the graded-prior
design exists to prevent, and a shared store is where it would happen silently.

**Deterministic first, inferential second.** The stream engine is useful before
any inference at all: with no hypotheses it answers *here is every counterparty
you pay more than once, how often, how much, and how steady* — real value,
needing no model, and incapable of being wrong about the world because it only
reports what the ledger contains. The inferential half then has something to be
checked against.

**A stream key must not merge two relationships.** Counterparty alone is not
enough: a large retailer is both a subscription and a one-off store, and a single
institution receives both a savings sweep and a loan repayment. Features computed
over that mixture describe nothing. Fragmentation is recoverable; a merged key is
a rhythm nobody has, computed over somebody else's money.

**Direction is the same argument one level down.** A posted amount is signed by
its effect on the balance the *document* prints, so on a card a purchase is
positive — what is owed grew — and the sign says nothing about which way the
person's money went. Without one derivation answering this, the same arrangement
splits by which account paid it: a subscription charged to a card is filed as
money arriving, and one relationship becomes two rhythms with half the movements
each.

**Priors are seeded from transaction one, and every prior is a claim about the
world that must be checked against a real vault.** An early draft asserted that a
prearranged ACH inflow means payroll. That SEC code covers *any* prearranged
consumer credit or debit — dividends, tax refunds, benefit deposits, insurance
payouts, wallet cashouts, brokerage transfers — and the forty descriptors of the
first dry run already contained at least two that were not payroll. The rule was
falsified by evidence that was on the table before it was written. **A table of
thresholds is a set of claims about the world, and each row needs checking
against a vault before it is trusted.** The same lesson arrived a second time
when an attempt to strip a bank's own words from a brand candidate was falsified
on 1,076 real movements: bank words, city names and merchant names interleave by
frequency, so no cut separates them.

The prior and the measurement each do half the work, and the division is exact:
**the impersonal billing prior licenses the question, and the measured flow
proposes its answer.** A merchant the world only ever sells to per purchase
raises nothing at all. Where the two disagree, the ledger wins outright.

**Order independence is an invariant because the tempting optimisations break it
silently.** Incremental feature updates and cached hypothesis state all violate
it, and it falls out of streams being derived rather than stored — which is why
that line is load-bearing rather than tidy.

**Ranking by consequence, with a hold filter rather than a denominator.** The
intuition that a question may resolve itself if we wait is expressed as
suppression — hold a question whose leading hypothesis is above threshold and
whose next forecast resolves soon — not as an expected-information-gain
denominator, which is not implementable as stated because it requires an arrival
model and diverges toward zero.

**Peer streams are strictly local.** Peer names, answers about peers and
user-defined peer categories never enter the shared catalog, the repo, or any
model prompt. If a model call labels an ambiguous stream, the prompt receives
only the abstracted pattern — *outflow, around this much, monthly on day one,
four occurrences, peer channel* — never names, descriptors or exact amounts.

**A grammar's holes are bounded by the vocabulary; its literal text is not.** The
words between the holes come from the model and could carry a name baked in. A
name baked into literal text can only ever match its own line, so counting
matches finds it — which is a stronger check than inspecting words, and it
replaced an earlier check that measured the same worry by looking at which words
were rare.

**The web-search return direction is a boundary too.** A page ranking for a brand
name is an injection surface into shared knowledge, so the quarantine is on
results as well as on queries, and this belongs in the threat model.

**The build order is one idea:** ship the deterministic half of the stream engine
before the inferential half, and ask the model only for what the ledger cannot
answer. That is the same rule that produced the parts of this codebase that have
survived contact with real data.

Two things the build settled that were specified harder than they turned out to
be. The two-key model was written as a migration — re-key an existing catalog,
keep local keys as aliases — and the vault was being rebuilt, so there was
nothing to migrate and the alias layer was never built: **a decision that was
expensive because of history stopped being expensive when the history went.** And
the agent layer arrived early, turning a vault into proposed actions with
preconditions evaluated — pure, no calls, no writes, no questions. The division
it encodes: mechanical decisions are the agent's, judgements about what money
means go to the person, and anything changing what *other* people see waits for a
human.

Corrections worth keeping, because several were wrong in an instructive way. The
knowledge types were renamed from T-numbers, which collided with the design
invariants. Expectations were renamed forecasts, because the expectations
registry already means something else and two different things called
expectations, both events, both in the ledger, would be unreadable. Cadence and
stability were reclassified out of the commons. The billing model was held until
corroborated. The question loop was rewritten as an extension of the queue rather
than as a second one. And a gate was added for the fact that the layer everything
sits on had never returned a result — the cheapest de-risking step available, and
it was missing.

The prerequisites are done: the induction call, the raw-descriptor leak in the
plain-JSON pending queue, the NACHA rule, the two-key model, the stream engine
with its features, and the order-independence assertion. The privacy invariants
stand as tests rather than conventions: raw descriptors in the encrypted ledger
only; K3 crossing the vault boundary only in the abstracted-pattern shape;
nothing entering shared knowledge that carries amounts, dates, counts, account
references or personal names; and every derived claim carrying grade, provenance
and a pointer to its evidence.

Related: [the-conduit-and-the-counterparty.md](the-conduit-and-the-counterparty.md),
[the-question-queue.md](the-question-queue.md),
[where-the-intelligence-goes.md](where-the-intelligence-goes.md),
[honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md),
[threat-model-and-ingestion-security.md](threat-model-and-ingestion-security.md).

## Open

- The hypothesis distribution over ten stream kinds is unbuilt. What exists is
  one belief per counterparty and direction, over the billing prior and the
  measured flow. Whether the fuller taxonomy is wanted, and how a stream kind
  enters the nature ladder at the implication level, is undecided.
- Each row of the priors table is unchecked against a real vault, and the
  strength column is an assertion until it is.
- The forecast ledger is unbuilt, and with it the auto-resolution of a forecast
  end to end and the silent resolution of past-dated forecasts.
- The batched digest is unbuilt: questions should fire after a batch settles
  rather than per document, so a person who hands over a year gets one digest and
  not forty.
- The web-search escalation tier is unbuilt, as is its threat-model entry.
- The grammar registry format is unmerged and population is deliberately
  deferred; profiles are still moving.
- The false-mixture rate is unmeasured on real data, and the decomposition
  accepts two survivors it describes as one arrangement: a monthly-plus-annual
  pair on one anchor day, and a sub-monthly interleave.
- User-contributed behavioral priors — pooling observed cadence and amount
  classes across users — are out of scope until a real cohort exists. They need
  k-anonymity thresholds, coarse classes only, and a contribution-signing story.
  They are also what would corroborate a billing model, so until they exist that
  field is held locally rather than published.
- Where shared knowledge is hosted — a service, a repo, a signed ledger — is
  undecided. Design nothing that assumes a server.
- The new provenance grades this document specifies (model knowledge, model
  web-search, user confirmed, observed local) do not exist. The ledger's grade
  ladder is verified, corroborated, unverified, conflicted, with a separate
  source field of model, human or commons. Whether the behavioral fields need a
  grade vocabulary of their own is unruled.
- No lint asserts that cadence and stability stay out of shared knowledge. Today
  nothing writes them onto a merchant record, so the rule holds by absence rather
  than by construction.
- Fuzzy merchant matching, keyword lists and model-written regexes remain
  rejected.
