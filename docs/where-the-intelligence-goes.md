# Where the Intelligence Goes

**State:** built
**Rules:** PROJ-34, PROJ-35, PROJ-36, PROJ-37, PROJ-38, PROJ-39, PROJ-40

## Rules

### PROJ-34 — what a counterparty implies is impersonal knowledge, learned once
**State:** enforced
**Code:** merchant/merchantcore/enrich.py:149
**Test:** product/tests/test_tiers.py::test_a_counterparty_that_implies_structure_is_proposed_not_asked

1. `counterparty_kind` and `implies` are produced during merchant enrichment and stored on the merchant record's attributes, beside category and subcategory.
2. Enrichment is batched, sees nothing about the person, is cached per merchant and is versioned by its prompt.
3. The knowledge arrives through the merchant event already in use; the read side re-derives, so it applies retroactively with no re-ingest and no new event type.
4. An implication carries structure only — a relationship, a major, a direction, an account group, a document — and no sentence for anyone to say.

### PROJ-35 — three tiers, and the rule is ask only where the counterparty cannot tell us
**State:** enforced
**Code:** product/viva/ledger/projection/tiers.py:26
**Test:** product/tests/test_tiers.py::test_an_ordinary_counterparty_is_settled_and_silent

1. A known counterparty implying nothing is `settled`: the category and the major are assigned and no question is raised.
2. A counterparty implying structure is `structural`: an informed proposal carrying its grounds and specific options, never a naive open question.
3. An instrument or a peer is `unknown`: one real question per transaction, free text first-class.
4. A counterparty enrichment has not reached is `unenriched` and raises no nature question at all — the order is ingest, enrich, then ask.
5. A descriptor that may never be shared is `unknown` rather than `unenriched`, because an identification that cannot arrive must not be promised.

### PROJ-36 — direction is part of the implication, never a branch in the caller
**State:** enforced-with-exception
**Code:** product/viva/ledger/projection/merchants.py:146
**Test:** product/tests/test_tiers.py::test_the_same_counterparty_means_opposite_things_by_direction

1. An implication carries `on` — inflow, outflow or both — and the caller selects on that data rather than on an `if`.
2. An implication that does not apply in this direction is ignored, and money in from a lender and money out to one reach different conclusions.

**Exception:** product/viva/ledger/projection/merchants.py:152 picks the direction from the posted sign (`m.amount > 0`) rather than from `money_effect(kind, amount)`, so on a liability account the implication is selected for the wrong direction.

### PROJ-37 — the confidence ladder decides how decisively an implication is applied
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:279 (assertion 1); merchant/merchantcore/enrich.py:205 (`clean_implications` — assertions 2 and 3: `.strip().lower()`, an unknown `major` dropped and logged at :224, `on` defaulting to `both` at :228, `confidence` to `suggested` at :231)
**Test:** product/tests/test_tiers.py::test_forced_is_decisive_and_suggested_says_it_is_not

1. A `forced` implication is applied and is decisive; a `suggested` one is applied and marks the movement provisional; an absent implication leaves the default.
2. An unrecognised confidence degrades to `suggested` and an unrecognised direction to `both` — always toward the rung that asks rather than the rung that acts.
3. Tolerant on transport noise, strict on claims: whitespace and case are noise, and a value outside the closed vocabulary is dropped and logged.

### PROJ-38 — a model writes the rules and deterministic code applies them
**State:** by-review-with-exception
**Code:** product/viva/ledger/projection/merchants.py:155
**Test:** none

1. Whether a descriptor names a business, an instrument or a person is learned at enrichment and stored, never matched against a word list in code.
2. The major, the account group and the document that would prove a claim are properties of the implication, learned once and cached, rather than entries in a table this project maintains.
3. Applying an implication is deterministic: auditable, free, offline, unit-testable, and incapable of inventing a number.

**Exception:** two substring classifiers over raw text remain — product/viva/ingest/brokerage.py:154 (`_CASH_MARKERS`) and merchant/merchantcore/normalize.py:31 (`_PEER_MARKERS`, which fails closed by design).

### PROJ-39 — a rhythm question is licensed by two facts of one record
**State:** enforced
**Code:** product/viva/ledger/projection/rhythm.py:64
**Test:** product/tests/test_rhythm.py::test_a_merchant_with_no_billing_prior_is_never_asked_about

1. A rhythm proposal is raised only where the catalog record says the counterparty is a business **and** says a standing arrangement with them is possible.
2. A record naming a rail, naming a person, or naming no kind at all raises nothing, however it bills.
3. The label withholds the question and never the measurement: the flow is measured either way.

### PROJ-40 — a person is not a counterparty on the rhythm axis
**State:** enforced
**Code:** product/viva/ledger/projection/rhythm.py:224
**Test:** product/tests/test_rhythm.py::test_a_merchant_with_no_billing_prior_is_never_asked_about

1. A movement whose other side a grammar slot declared a party is dropped before any flow is formed: no measurement, no hypothesis, no question, no subject a ruling could be written under.
2. The limit is the declaration's: a person's name in a `{brand}` slot is declared a person by nothing and is sorted like any merchant.

## Why

Viva listens worked and was aimed at the wrong moment. **It made the *answer*
intelligent and left the *question* stupid.** The queue asked *"Is this money
spent, or something you now own?"* about a counterparty the vault had already
enriched as loan payments and mortgage servicing. We knew it was a mortgage
servicer. We asked anyway. Then a model was spent interpreting a sentence whose
content we could have proposed ourselves.

Three costs follow and they compound. The person carries load we could have
carried — being asked what you already told the system is the opposite of a
butler. The model call happens at the point of least leverage: one sentence, one
merchant, one person, uncacheable, unshareable, repeated forever, when the same
reasoning done once per merchant would serve every transaction and every other
user. And it reads as unintelligent even when it is correct, because a person
would already have a hypothesis.

**The correct shape is the inverse: the product forms the belief; the person
confirms or corrects it.**

**The missing idea is that a merchant category implies structure.** Mortgage
servicing is not a weak hint about spending. It is a near-certain statement about
the shape of a financial life: there is a property, there is a loan, the payment
is compound, an escrow account probably exists, and a tax form exists once a
year. None of that is uncertain. What is uncertain is narrower and much more
answerable — *which* property, and whether they want it tracked. Most categories
imply nothing at all: groceries, utilities, restaurants, streaming. Those should
be assigned silently, which is most transactions, and that deletion of a question
is the single largest improvement here.

**Where that knowledge belongs is the decision everything else follows from.**
*"Mortgage servicers imply a property and a loan"* is impersonal, universal and
true for everyone; it carries no amount, no date, no account, no name. So it
belongs in merchant enrichment, under the same T9 boundary that already governs
category and subcategory. That single placement resolves the rest: the call is
batched, the knowledge is T9-safe by construction, cached forever, versioned by
the enrichment prompt, retroactive because the read side re-derives, and
shareable — which is precisely the commons the project has been building toward.
Compare where the earlier design put it: one personal call, per sentence,
uncacheable, unshareable. Same reasoning, wrong side of the boundary.

Enrichment vendors already infer *"financial products held with other
institutions"* from transaction data and sell it to banks for cross-sell. The
capability is proven; the *direction* is what differs. They infer your products
to market to you. Here the same inference describes you to yourself, on your
machine, with the derived knowledge shared only in its impersonal form. **We are
not inventing the inference, we are inverting who it serves.**

**Notice what is absent: a second personal model call.** The impersonal step did
the thinking; turning an implication into this person's options is matching
against their own account registry, which is the account matcher pointed at yet
another target. Deterministic, free, offline, testable. That is the answer to
*"send it to a model saying I have this, what could it be"* — yes, but once per
merchant rather than once per person per transaction. Same intelligence, orders
of magnitude less of it, and it becomes an asset instead of a cost.

**The confidence ladder reuses the contract this project already has** for
verification findings — forced, suggested, unlocalized. Three benefits from
reuse rather than a new vocabulary: it is already tested, already understood, and
it keeps *never bluff* structural. A forced application is one we can defend, a
suggestion states its own doubt, and an open question admits we do not know.
Confirming a `suggested` implication changes no figure — **it removes the doubt
about one**, which surfaced when a test asserted spending would drop on
confirmation and it did not. That is the ladder working, and a better story than
the old one: *I believed this, and now I'm sure.*

**Rules versus intelligence, reconciled: a model writes the rules, deterministic
code applies them.** Nobody codes *mortgage → house*. A model reading a merchant
category produces the implication from world knowledge, generally, for categories
nobody anticipated. The implication is stored as data, versioned and correctable.
Applying it is deterministic. This is the same stance as *we own the schema, the
model assists authoring* and *read documents like a person would, no
per-institution parsers*. A hardcoded table is a rule *we* wrote and will be
wrong about; a learned implication is a rule *the world* wrote that we can check,
cache and share. **And a person's correction beats both, permanently** — memory
of the user is the moat, not the model.

**The self-inflicted problem this fixed was a reflex, not a slice.** Building the
sentence path produced five separate keyword tables; counting properly found
**nine** raw-text classifiers, four of which predated it. So every time the code
met ambiguity in raw text, it reached for a word list — and the project's own
anti-goals say that whole class of workaround is obsolete. Naming the reflex is
more useful than blaming a slice, because it recurs unless the alternative is
easier than the list. The most instructive deletion was a card-word list that was
**always true** — a card statement prints "card" on nearly every line — so it was
approving links rather than checking them, and it had linked a cash withdrawal to
an unrelated card payment of the same amount. Worth a standing test nobody has
written: **measure how often a classifier says no.** A rule that never refuses is
not classifying, and cheapness plus always-true is exactly the profile of a rule
nobody audits.

Not everything that looks like a table is drift. A mapping of our own structured
field values is schema we deliberately own. The drift is specifically
**classifying raw descriptors by substring**.

**The measurement.** On a synthetic vault of six movements — four ordinary
merchants, one mortgage servicer, one check — the queue went from six questions
to two: four settled without asking, one proposed with its grounds, one asked one
transaction at a time. Two-thirds of the queue disappeared, and the two that
remain are the two a person would actually ask.

**Two things the build taught.** `implication_for(merchant, direction)` had to
exist separately from `implication_of(movement)`, because a proposal must ask
what a counterparty implies *before* it has a movement in hand. And a tier that
promises a future that cannot arrive hides the size of the genuinely unknown set:
185 counterparties sat in `unenriched` on the first real run, about counterparties
nothing will ever identify, because the privacy boundary means enrichment can
never see a peer or an instrument.

**The ladder runs on a second axis too.** Asked of a *rhythm* rather than a
nature, tier 1 is a merchant the world only ever sells to per purchase — silence,
however many times it was bought from — and tier 2 is a merchant one can deal
with by a continuing arrangement, which earns one informed proposal per
counterparty and direction. The impersonal knowledge that sorts them is the
catalog's billing field, and it licenses the question without ever answering it:
what the person actually arranged is theirs to say, and where the ledger has
measured enough to have an opinion, the measurement is what the proposal
proposes.

**Nothing was thrown away.** The scoped ruling event, the four majors, the
derived chart of accounts, `origin`, the mixed nature, per-transaction conduits,
the Proposal type and the eval harness all earned their place and keep doing
their job. What changed is the entry point — the product opens with a belief and
the sentence becomes the correction channel and the unknown tier's primary path
— and the model call moved upstream, from per-sentence to per-merchant, from
personal to impersonal, from uncached to cached.

**Tier 2 has a successor.** An informed proposal names what the product already
believes about a *movement*. What it cannot do is ask what the *thing* is — a
property, a loan, a term deposit each have a shape a movement does not carry.
That is the interview
([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md)):
the implication says an instrument exists, the schema pack says what may be asked
about it, and the answer is a scoped ruling like any other.

**Merchant identity is permanent; recognition is evidence.** A grammar brand,
a published-parser result, a prefix bounded by a proven occurrence slot and the
normalized descriptor are ordered candidates, not identities. Only an exact
reviewed catalog alias maps one onto a permanent merchant id. Reads retain the
canonical id and every structural/legacy candidate so a stronger local ruling is
never stranded; no match leaves the normalized local key honestly unknown. The
whole vault is still the unit where corpus-dependent boundaries such as ACH
company names are resolved, and people/refused lines never consult business
aliases.

Invariants this leans on: T2/ADR-010 (a model may perceive and infer;
deterministic code decides and posts), T4, T9 (the impersonal/personal boundary,
leaned on hard), X2, X3, I5, and principle 5 (serve, don't overwhelm). The
precedence ladder a stream kind enters is in
[honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md);
the confidence vocabulary is
[verification-findings-and-correction.md](verification-findings-and-correction.md);
the word-list deletion is recorded in
[transfer-links-and-cross-document-corroboration.md](transfer-links-and-cross-document-corroboration.md).

## Open

- The direction defect: `implication_of` reads the posted sign, so on a card the
  implication is selected for the wrong direction. Known and scheduled as its own
  cycle with a structural guard against the next one.
- The rhythm fence stands on a model-authored label that the next enrichment
  re-authors, so a reply saying `business` turns it off for the very keys it was
  built for. It narrows the residue a grammar's declaration cannot reach and does
  not seal it.
- Because the label withholds the question and never the measurement, a peer
  relationship is still counted and totalled locally — so a later read over flows
  must license itself, inheriting nothing from this one.
- What fraction of a *real* vault is each tier. The synthetic measurement is
  suggestive and settles nothing; the standing practice's real-vault before-and-
  after has not been run.
- Whether a model reliably produces implications, measured. **Inventing structure
  where none exists is the ruin case** — a coffee shop implying a loan would
  create phantom accounts across a whole vault — and it must be scored
  disqualifyingly rather than averaged against successes.
- Whether the commons holds: an implication must be checked to carry no personal
  residue before it can be shared, which is the existing boundary lint applied to
  a new field.
- Multi-party and household implications; using implications to *predict* future
  obligations; switching on sharing of the implication commons.
- A standing test nobody has written: how often does each classifier refuse?
