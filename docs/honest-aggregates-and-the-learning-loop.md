# Honest Aggregates & the Learning Loop

**State:** built
**Rules:** MON-1, MON-2, MON-3, MON-4, MON-5, MON-6, MON-7, MON-8, MON-9, MON-10, MON-11, MON-12

**Invariants touched:** T1 · T2 · T4 · **M1** · **M2** · X2 · principle 5 · principle 6.

## Rules

### MON-1 — the nature precedence ladder
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:231 (`decide_nature`)
**Test:** product/tests/test_nature.py::test_a_ruling_outranks_a_description_that_names_one_of_your_accounts

1. A movement in a live transfer link has nature `transfer` and reason `linked`.
2. Otherwise a ruling decides the nature, with reason `ruling`: one recorded on the movement, else one recorded on its merchant, else a `nature` carried on the movement's category overlay or on the merchant's attributes.
3. Otherwise a description containing a token of another account the person holds gives `transfer`, reason `own_account`.
4. Otherwise the counterparty's implication for the direction the money went decides, reason `category_hint`.
5. Otherwise the nature is `spending`, reason `default`.
6. A ruling outranks the own-account rung, and no rung reads the category or subcategory label.

### MON-2 — a nature says which rung decided it
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:79 (`MovementInfo.nature_reason`), :338 (`excluded_from_spending`)
**Test:** product/tests/test_nature.py::test_excluded_movements_explain_themselves

1. Every movement carries a `nature_reason` naming the rung that decided it.
2. `excluded_from_spending()` returns every expense-shaped movement kept out of spending, each with its reason.

### MON-3 — spending is shape and nature together
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:315 (`counts_as_spending`)
**Test:** product/tests/test_nature.py::test_transfers_never_appear_as_a_spending_line_item

1. A movement counts as spending only when it has the shape of an expense (money out of an asset, or a charge on a liability) **and** its nature is `spending`.
2. `spending_by_category`, `spending_by_subcategory`, `spending_by_category_then_subcategory`, `spending_by_tag` and `uncategorized_expenses` all filter on that one predicate.
3. A category label such as `transfers` or `loan_payments` never appears as a line item inside a spending breakdown.

### MON-4 — weak evidence excludes the money and says so
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:284 (rung 4), :323 (`provisional_spending`)
**Test:** product/tests/test_nature.py::test_a_suggested_implication_is_provisional_not_silent

1. A `forced` implication decides the nature and is not provisional.
2. A `suggested` implication decides the nature and marks the movement provisional.
3. A provisional movement is **excluded** from the spending aggregates, and `provisional_spending()` reports the total that was removed on that evidence.

### MON-5 — a ruling whose legs disagree is mixed, and is neither counted nor dropped
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:108 (`nature_of_legs`), :262
**Test:** product/tests/test_ruling.py::test_a_compound_payment_is_neither_counted_nor_dropped

1. Legs of one major give that major's nature; legs of several majors give `mixed`.
2. A `mixed` movement is provisional, is not in spending, and appears in `undecomposed()` with the document that would settle the split.

### MON-6 — every spending aggregate is on the nature predicate
**State:** contradicted-by-code
**Code:** product/viva/ledger/projection/movements.py:345 (`spending_by_currency`)
**Test:** product/tests/test_nature.py:71 (asserts the divergence)

1. Every aggregate that states spending counts card purchases and excludes non-`spending` natures.

**Contradiction:** the doc says every downstream aggregate excludes anything not `spending`, and M1 says a card purchase is spending ([design-invariants.md](design-invariants.md)). `spending_by_currency` (movements.py:345) instead inlines its own test — depository outflows only — so it **omits every card purchase**, and it is what four callers print or use as the spending headline: `rescan.py:60` and `debug/vault.py:87` both label it *"external spending (transfers excluded)"* directly above a category breakdown computed on the correct population; `desktop_bridge/vault_surface.py:59` publishes it; `bench/synthetic/run_corpus.py:170` picks a currency from it. `test_nature.py:71` asserts the two disagree (560.00 by category, 60.00 by currency). Not resolved here.

### MON-7 — which way the money went has one derivation (M2)
**State:** enforced
**Code:** product/viva/ledger/streams.py:79 (`money_effect(kind, amount)`); product/viva/ledger/projection/movements.py:305 and product/viva/ledger/projection/merchants.py:146 both delegate to it
**Test:** product/tests/test_streams.py::test_a_card_purchase_reads_as_money_out, product/tests/test_direction_site.py::test_direction_is_decided_by_the_one_function_that_knows

1. A movement's direction is derived from the account's kind, by one function, in the module that owns the words `in` and `out`.
2. No read derives direction from a posted sign.
3. A caller holding no account kind raises rather than falling back to the sign (product/tests/test_streams.py::test_a_stream_cannot_be_built_without_the_account_kind).

### MON-8 — the own-account rung is looser than the auto-link bar, deliberately
**State:** enforced
**Code:** product/viva/ledger/projection/accounts.py:134 (`own_account_tokens`, raw `account_tokens`, issued accounts only) vs product/viva/ingest/transfers.py:89 (`_distinctive`)
**Test:** product/tests/test_nature.py::test_an_asserted_account_does_not_make_its_own_payments_internal

1. The nature derivation tests a movement's description against every token of the accounts held; the link matcher first narrows those tokens to the distinctive ones.
2. Only `issued` accounts donate tokens, so an account a ruling brought into being never reads its own payments as internal.
3. The auto-link bar is not loosened to match.
4. Own-account tokens live in the ledger's identity layer as `account_tokens` (product/viva/ledger/identity.py:59), so the transfer matcher and the projection share one implementation with no import cycle; `transfers.account_tokens_from` delegates to it (product/viva/ingest/transfers.py:66).

### MON-9 — nature is derived, and no event says it
**State:** by-review
**Code:** product/viva/ledger/projection/movements.py:194 (`movements` calls `decide_nature`); product/viva/ingest/categorize.py:96 (`assign_category(nature=…)`)
**Test:** none

1. Nature and its reason are computed in the projection at query time; no event type records a nature.
2. A person's nature ruling rides on the existing category overlay or on `RulingRecorded`.
3. An existing vault becomes honest on the next read, with no re-ingest, and a replay reproduces every nature.

### MON-10 — a reset never destroys a person's rulings
**State:** enforced
**Code:** product/viva/reset_categorization.py:113
**Test:** product/tests/test_reset_categorization.py::test_reset_drops_model_categorization_but_keeps_my_rulings

1. `reset_categorization` preserves `by="human"` rulings by default.
2. Dropping them requires `--discard-my-rulings` (`keep_human=False`), and the report says which was done.

### MON-11 — abstract the read side early, the write side late
**State:** untestable
**Code:** none found
**Test:** none

1. A new capability is added as a read-side projection over events already written wherever that is possible.
2. A new event type waits until a further use proves its shape.

### MON-12 — route on the registry, not on the shape of the data
**State:** untestable
**Code:** none found
**Test:** none

1. A projection asks the registry what a thing is.
2. Nothing infers what a thing is from which fields happen to be present in what it was handed.

## Why

Spending must mean money that left your **life**, not money that left an **account** (M1). Two independent systems described the same fact and the aggregate listened to only one: a transfer *link* excluded a movement, while a *category* saying `transfers` excluded nothing, so every internal movement that never auto-linked — a card payment whose card statement is not held, a brokerage contribution, a cash withdrawal — was counted as consumption. On a real vault that was a large fraction of the headline, and `transfers` appeared as a line item *inside* spending, which is incoherent on its face.

The category cannot decide it. The largest "spending" category, `loan_payments`, decomposed exactly into mortgage payments and credit-card payments: real cash leaving a life, and money moving between a person's own accounts. **Same category, opposite natures.** Nature is therefore a property of the **counterparty** — is the other side an account you hold? — and where that is unknowable it is exactly the kind of question only the owner can answer.

The ladder's order is the argument. Rung 3 is a heuristic over description text matched against raw account tokens with no distinctiveness filter, so a bare institution name can fire it; a heuristic that loose must not outrank a person's explicit answer, which is why a ruling sits above it. Ordering them the other way costs a real number and discards an owner's answer in silence: a checking line reading `Payment To Northbank Card Ending IN 7799` against the owner's ruling "I paid a friend's card, not mine" is a four-hundred-dollar swing. The looseness of rung 3 is itself deliberate: a wrong nature is a weaker error than a wrong link, so nature gets the honest number without gambling on speculative links — a wrong link is a wrong number, an unlinked-but-transfer-natured movement is merely a weaker explanation.

A nature is never invented from a coincidence. Where only a *suggested* implication speaks, the suggestion is applied and the movement is flagged, so the doubtful money is removed from the headline and named rather than counted with a caveat. The number is honest about its own uncertainty rather than quietly wrong in either direction (X2), and `provisional_spending` is how much rests that way.

Deriving all of this on the read side is what makes it retroactive for free: aggregates re-derive from movements at query time, so an existing vault becomes honest on the next read with no re-ingest and no model cost. It also cost nothing to add, which is the standing trade — the read side is cheap and reversible, the write side is expensive and one-way.

Direction earned the same treatment the hard way. `nature` says whether money left your life; it does not say which way the money went, and a posting's sign does not either, because a charge on a liability is recorded positive and the money is gone. The rule lived as a function others were expected to call, and three separate readers re-derived it inline, one of them inverted. The third surfaced in the rhythm read, where direction is half the key a hypothesis is grouped under: one subscription paid from two kinds of account became two arrangements, each stating a total over half a relationship no sentence described, and the sentence a person would have been shown said the money came in from the merchant. The repair was to move the derivation **down**, into the module that owns the words `in` and `out` and imports nothing from the ledger package, and to promote the rule to a standing invariant (M2 in [design-invariants.md](design-invariants.md)) — a rule that only lives in a docstring is a rule that will be reinvented.

The learning loop is the other half. The rulings the system already writes — an account alias, a confirmed transfer, a human category, a merchant categorization — are one primitive implemented several times, and the question queue is one read-side projection gathering everything the system is genuinely unsure about into one ranked list ([the-question-queue.md](the-question-queue.md)). Its ranking is by leverage, its scope is the most general unit that is still honest, and below a threshold it takes the conservative default quietly rather than asking. What it deliberately does **not** hardcode is the answers: whether a payment to a counterparty is your own account, whether a cash withdrawal is spending or money moved to cash in hand, whether a large capital movement is spending or a change in what you own. Hardcoding any of those would be guessing on the owner's behalf. Each is asked once, ruled once, applied forever and retroactively; until answered, the affected total is reported provisional and never silently resolved either way.

Protecting the asset follows from the same framing. Under the original reading categories were cheap derived data; under the learning-loop reading a human ruling is the one thing a model call cannot regenerate, so a reset that dropped them was destroying the moat.

Where the doctrine reaches the answering path: an unanswered question leaves a number **incomplete**, never wrong. Asked what was owed, a run once stated one liability of three and graded it `corroborated` — true of that balance, and a false sentence assembled entirely out of true parts. A figure now states the set it was taken over, and an incomplete total states the number **with** its gap rather than refusing until the gap is filled, on the ground that a person asking what they owe is better served by a figure and its hole than by silence.

Finally, a read-side abstraction is only as reversible as its dispatch is explicit. Duck-typed checks — `"opening_amount" in facts`, an exact instrument-name match — silently did the wrong thing three times in one session where a route through the doc-type registry would have been correct. A missing route fails loudly; a route inferred from which fields happen to be present does the wrong thing quietly and keeps doing it, which is the expensive half of the trade.

## Open

- `spending_by_currency` measures something other than what its callers print it as (MON-6). Putting it on `counts_as_spending`, retiring it, or renaming it to what it measures is a ruling, because the assertions that pin the divergence are deliberate. This is the unresolved R5 from the July repair list; the partition test R5 asked for was never written.
- `implication_of` picks a counterparty's implication by the posted sign (MON-7's exception), and a structural guard against a further site is not built.
- Principal/interest splitting on a mortgage payment waits on amortization data.
- Minting, enumerating, renaming and styling custom categories remain unbuilt; assigning a known category to one peer movement is live through the question answer path ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)).
- Loosening the transfer auto-link bar is deliberately not done.
- The other half of the incomplete-total doctrine is unbuilt: a gap does not become a question Viva asks. The queue's question for the same account carries only a yes/no about whether a document exists, and answering it writes nothing by design. Closing it needs a question source that can record a balance.
