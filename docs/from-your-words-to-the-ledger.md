# From Your Words to the Ledger — Viva listens

**State:** built
**Rules:** A1, A2, A3, PROJ-26, PROJ-27, PROJ-28, PROJ-29, PROJ-30, PROJ-31, PROJ-32, PROJ-33, PROJ-59

## Rules

### A1 — one generic scoped ruling event
**State:** enforced
**Code:** product/viva/ledger/events.py:516
**Test:** product/tests/test_ruling.py::test_a_person_outranks_a_model_and_the_ruling_generalizes

1. A ruling is a single `RulingRecorded` event carrying its own scope — movement, merchant, account, category, tag, attribute or rhythm.
2. A ruling under an unknown scope, or with an empty subject, raises where it is built.
3. A movement-scoped ruling outranks a merchant-scoped one on the same movement.

### A2 — an account born from a sentence lives in the same registry
**State:** enforced
**Code:** product/viva/listen.py (`resolve_account`, `repair_asserted_account_aliases`)
**Test:** product/tests/test_listen.py::test_an_account_a_document_opened_is_one_the_vault_already_holds; ::test_an_issued_brokerage_resolves_by_institution_and_kind; ::test_existing_asserted_brokerage_duplicate_is_repaired_without_new_value

1. There is one account registry; an account a person named and an account a document opened are candidates in the same match.
2. The account matcher, sprawl control and merge-later work unchanged over both.
3. A uniquely compatible issued brokerage account absorbs the alias of an asserted duplicate. The ruling remains in the record, while the represented value contributes only once.

### A3 — every account records who says it exists
**State:** enforced
**Code:** product/viva/ledger/events.py:155
**Test:** product/tests/test_ruling.py::test_an_account_records_who_says_it_exists

1. Every account carries `origin`, one of `issued` or `asserted`; anything else raises where the event is built.
2. `issued` means a document from an issuer attests the account exists; `asserted` means only the person says so.
3. A vault written before the field existed reads as `issued`.
4. Only issued accounts enter the own-account token index, so an asserted account named after a counterparty can never be read as evidence of an internal transfer.

### PROJ-26 — the model parses meaning and never supplies a figure
**State:** enforced
**Code:** product/viva/ledger/events.py:611 (a ruling leg carrying an amount raises), :600 (a reading may not supply a number the sentence did not carry), product/viva/listen.py:17
**Test:** product/tests/test_ruling.py::test_a_ruling_can_never_carry_a_figure, product/tests/test_listen.py::test_the_model_never_supplies_a_figure

1. A ruling leg carries no amount; the amount comes from the movement.
2. A recorded value may contain no number the person's own sentence did not carry.
3. A leg whose major is outside the closed vocabulary raises rather than being written.
4. The model parses intent into a structured proposal, does no arithmetic, never sees the ledger and never chooses an account.

### PROJ-27 — four majors, fixed at the top and free below
**State:** enforced
**Code:** product/viva/ledger/postings.py:45
**Test:** product/tests/test_ruling.py::test_the_major_is_fixed_code_and_everything_below_it_is_data

1. Every counter-leg is one of four majors: expense, asset, liability, income.
2. The major's root is fixed code and every level beneath it is free data.
3. A `:` inside a name is collapsed, so a name can never inject a level into the hierarchy.
4. Equity is absent from the vocabulary: for a person, equity is net worth, so it is derived and never asserted.

### PROJ-28 — the chart of accounts is materialized by the projection
**State:** enforced
**Code:** product/viva/ledger/postings.py:40
**Test:** product/tests/test_ruling.py::test_i_bought_a_car_stops_being_spending_with_no_reingest

1. The posted counter-leg stays an Uncategorized bucket; a ruled path such as `Assets:Vehicles:<name>` is never written into a posting.
2. A ruling changes what aggregates say without a re-ingest.

### PROJ-29 — an unknown split is its own nature
**State:** enforced
**Code:** product/viva/ledger/projection/movements.py:108
**Test:** product/tests/test_ruling.py::test_a_compound_payment_is_neither_counted_nor_dropped

1. A ruling whose legs imply more than one nature gives `MIXED`, which is neither counted as spending nor dropped from the account of where money went.
2. A mixed movement is marked provisional, and `undecomposed` reports the total, the count, the accounts and the document that would resolve it.
3. A missing document never blocks a ruling: the cash is posted because cash leaving is a measured fact, and only the decomposition waits.

### PROJ-30 — only a major that brings a thing into being opens an account
**State:** enforced
**Code:** product/viva/listen.py:255
**Test:** product/tests/test_listen.py::test_ordinary_spending_creates_no_account

1. An expense or income leg with no named thing goes to the Uncategorized bucket the ledger already has, where the category does the descriptive work.
2. An answer saying the person now owns or owes something without saying *what* returns the verdict `unnamed`, which is a question, not a path built from a placeholder.
3. Expense and income never enter the priority list that decides what a person is shown as holding.

### PROJ-31 — resolution asks only when ambiguous
**State:** enforced
**Code:** product/viva/listen.py:255
**Test:** product/tests/test_listen.py::test_resolution_asks_only_when_ambiguous

1. One exact match posts silently; more than one, or a substring match either way, returns `ambiguous` with the candidate named.
2. Exact matches are counted by account, not by name pair, so one account answering to two names does not read as two accounts.
3. Nothing matching returns `new` with a proposed path, and creating an account is the one verdict this path always confirms.

### PROJ-32 — confirmation is scoped to the account, not to every parse
**State:** enforced
**Code:** product/viva/listen.py:658
**Test:** product/tests/test_ask.py::test_an_answer_that_would_open_an_account_is_proposed_before_it_is_written

1. Nothing is written without an explicit yes; `listen` produces a reviewable Proposal and applying is a separate act.
2. An answer that would bring an account into being is not applied in the request that raised it; it comes back as a proposal.
3. After the binding is confirmed, the learned ruling applies silently and the question that prompted it is retired.

### PROJ-33 — every asserted account invites the document that would prove it
**State:** enforced
**Code:** product/viva/questions.py:514
**Test:** product/tests/test_listen.py::test_the_corroboration_ask_is_the_path_from_asserted_to_issued

1. An account this path creates raises a corroboration question — invoice, closing disclosure, 1098, loan statement.
2. The ask is never a gate: the account exists and the posting is already made.
3. The ask is ranked with every other question by consequence, and the arriving document upgrades the account's origin from `asserted` to `issued`.

### PROJ-59 — free text is an addition, never a dependency
**State:** enforced
**Code:** product/viva/reply.py:1
**Test:** product/tests/test_reply.py::test_with_no_reader_a_plain_answer_still_lands_and_a_loose_one_does_not

1. With no model configured, each declared scalar slot is offered the sentence as typed and the same deterministic checks decide.
2. A plainly-written reply still lands on a machine with nothing configured, and anything else is refused rather than guessed.
3. A sentence produces the same events the buttons would, with the same grade and reversibility.

## Why

The question queue offered three answers — spending, transfer, settlement — and
a real vault immediately produced two questions none of them fit: a mortgage
payment, which is three things at once, and a car purchase, which is something
you now own and the ledger could not represent. Answering more questions in that
vocabulary produces more wrong answers, and any net worth built on top inherits
them.

The diagnosis: **`nature` was an impoverished stand-in for what the counter-leg
*is*.** The ledger already posts to `Assets:`, `Income:`, `Expenses:` and
`Equity:` internally — double-entry's own vocabulary, complete and centuries old
— but the surface collapsed it to three words, and there was not even a
`Liabilities:` root, which is why *"I paid off debt"* was unsayable. That
vocabulary has many members and compound cases, so **it cannot go behind buttons
— but it fits in a sentence.** Free text is not a convenience here; it is the
only practical interface to a complete ontology.

**The four majors are the whole vocabulary.** An expense is money spent and
gone. An asset is something you still have, in another form — a car, cash
withdrawn, escrow, money lent to a friend, another of your own accounts. A
liability is a change in what you owe. Income is money that arrived. Equity is
deliberately absent, because for a person equity *is* net worth, so it is
derived rather than asserted. Everything below the four is data (I5), which is
the same shape as the primary categories with a free subcategory.

**Six steps, one model call.** Frame the question; suggest answers; *interpret*;
resolve the account; propose the posting; confirm and apply. The model touches
step three only. It never sees the ledger, never picks an account and never
emits an amount — any number in its output is discarded, because amounts come
from the movement.

**Account resolution is the account matcher.** Answering *which account does
this belong to?* is the same problem as *is this the same account as one I've
seen?*, which account identity resolution already solves: signals, graded match,
ask only when ambiguous, learn the ruling, never ask again. That reuse is what
made the slice cheap, and it is why A2 keeps one registry rather than opening a
second namespace for accounts nobody issued.

**Three cases shaped this.** *"I bought a car"* is one asset leg, and it records
**cost**, not value: what you paid is a measured fact, what it is worth now is
unknown, so the account carries cost basis and an `estimated` valuation class.
*"This is my mortgage"* is three legs — interest, principal and escrow — whose
proportions are unknown to the person as well, because they are printed on a
statement neither party has. *"This paid my car loan"* is one liability leg whose
balance is unknown until a loan statement arrives, and that is an honest state:
payments known, outstanding unknown, coverage says so.

**A missing document must not block the account.** Create the account now, post
the cash — cash leaving is a measured fact (M1) — and mark *the decomposition*
provisional rather than the movement. Spending stops being overstated, and the
liability balance derived from these payments is flagged unreliable so net worth
cannot quietly treat interest as debt reduction. The 1098 then arrives as a
suggestion for corroboration rather than a precondition.

**Big purchases have paperwork; ask for it, never to unblock, always to prove.**
Provenance is the product, so every account this path creates invites the
document that vouches for it. This turned out to be more than a nicety: the
invoice or the 1098 is literally the path from `asserted` to `issued`, which is
the mechanism by which a personal ledger becomes something another party can
trust. A3 is the expensive-to-miss decision because the distinction is only
capturable at write time; miss it and the ledger quietly becomes un-vouchable
with no way to reconstruct which accounts a third party could rely on.

**Plain English on the surface, always.** The person is never asked "is this an
asset?"; they are asked whether they still have it, in another form. The majors
are stored and never spoken. That also makes locally-phrased questions a
surface-only change later: phrasing touches no figure and no account, so it sits
entirely outside the T2 boundary.

**Confirmation is per account, not per parse.** The expensive,
sprawl-creating, hard-to-reverse act is binding money to an account for the first
time, and that is exactly what gets the explicit yes. Once *"Harborline is my
mortgage"* is confirmed, the next twelve payments post without a question. The
default, after the first answer, is silence — and **account sprawl is the failure
mode**, so the disciplines that tamed merchant descriptors apply: normalize the
name, suggest existing accounts before offering new, let the matcher offer
merges later.

**What the build falsified, kept because a log that only reports its wins would
refute this project's thesis.** A fifth nature was forced into existence: the
spec said an unknown compound payment "posts nothing it cannot justify", but
counting the whole mortgage payment as spending restates the exact overstatement
honest aggregates fixed, and dropping it understates. Neither is true, so it is
neither. The ruling rung was promoted above the own-account rung, because a
ruling is a person telling us what something is and the own-account rung is a
heuristic over description text. A ruling's new account then matched its own
movements as an internal transfer, which is why only issued accounts are
indexed. A model's reply turned out to be untrusted input rather than a
contract. An account was minted for an ordinary night out, which is what PROJ-30
exists to stop. And ordinary spending nearly appeared beside a car in "things you
hold".

**Graceful degradation is right in the product and wrong in everything that
reports on it.** The eval harness failed its own test on its first real run: all
sixty-six calls errored before reaching the model, and the report said *"0%
ruin, clean, safe but weak"* — every failure swallowed by `interpret`'s
degrade-never-raise behaviour and scored in the safe bucket. The tell was a p50
latency of 0.01s, two orders of magnitude too fast for local inference. An eval
that cannot distinguish *the model declined* from *we never reached the model* is
worse than no eval, because it is reassuring. The general rule: a component that
degrades gracefully must still report the difference between "I handled it" and
"it broke", and the confidently-wrong rate is `None` rather than `0` when nothing
was measured.

**A bounded answer must not be stitched.** The continuation driver, lifted into
the model layer because a truncated document read was silently losing
transactions, was doing its job where its job is wrong. Reading a statement,
truncation means the list was genuinely too long. Reading a sentence, the answer
is short by construction: hitting the limit means the model is rambling, and
stitching six more chunks onto a runaway reply turns one cheap recoverable
failure into unparseable garbage. A call whose output is short and bounded sets
its continuations to zero, and a truncated reply is refused rather than
half-read, because a cut-off reading is not partial — it is unknown, and guessing
the rest is how a wrong ruling gets written and then generalized.

**Nonsense in a finance app is a trust failure even when the ledger underneath is
correct** — arguably especially then, since the number was right and the sentence
still made the product look like it was not listening. The model reports what
kind of thing this is; deterministic code maps kind to document. Deciding which
document proves a claim is ours.

**The descriptor sometimes names the pipe, not the payee.** Every check in a
vault normalizes to the single token `check`, and so does the next one. A check
is not a counterparty; neither is an ATM withdrawal, a wire, a teller deposit or
a money order. So a conduit never generalizes: it is asked about one transaction
at a time, it never enters the shared catalog, and a ruling on one refuses
without being told which transaction. This is the same insight as *one payment to
a friend is a gift, the next a loan* — the design had it for peers and missed it
for instruments.

**A prompt is a file, and a slice that makes a model call puts its prompt in the
library and its version on the event.** The interpreter reads under
`interpret-v3`, which is a prompt about *any question a person was asked* rather
than about one movement of money: it takes the question, a context block and the
typed slots that question declares, and turns language into structure without
deciding anything. Its instructions began as a
module constant, rewritable in place; tuning it would have silently
reinterpreted every ruling recorded before the change with no way to recover what
the model had been told, and would have made eval runs incomparable across time.
The same prompt also assumed a bank — *"one payment from their bank account"*,
*"the counterparty on the statement"* — while the vault already held cards,
brokerages and retirement accounts. That framing is the same I5 failure the
project has caught elsewhere: an assumption baked into universal code instead of
arriving as data.

**The interpreter has its own model configuration**, overriding the document
reader's field by field. The split earns its place because these are not the same
task: reading a statement is a vision problem over dense tables that wants the
strongest model available, and reading *"this is my mortgage"* is a short text
problem a small model handles well. It is also the seam where a local model plugs
in — point the interpreter at a local server and no sentence a person types
leaves the machine, while document reading keeps whatever capability it needs.

Invariants this leans on: T2/ADR-010 (the model parses meaning; it never
supplies a figure, picks an account or posts), T3 (the sentence and the parse are
captured verbatim), T4 (a confirmed ruling is an append-only event), T8 (a
recorded `prompt_version` resolves to the exact text that produced the reading),
X2 (a proposal states what it changes, how much money it moves, and what it does
not know), X3 (nothing applied without an explicit yes), I5, and M1 (a created
asset records what you paid, not what it is worth). The proposal type and the
answering surface are
[viva-listens-and-speaks.md](viva-listens-and-speaks.md); the corroboration asks
route into [document-coverage.md](document-coverage.md); the failure taxonomy is
[eval-harness-design.md](eval-harness-design.md).

## Open

- **T3 is unmet on the interpretation edge.** There is no `interpret` capture
  phase and never was: the only phases in the codebase are `classify`, `extract`
  and `speak`. The model's parse is held for one retry and discarded, so a
  sentence that never reaches a write — and any answer to an identity, transfer,
  merchant, corroboration or expectation question — leaves no verbatim record. A
  better model cannot re-derive a reading from what a vault holds. This is on the
  one path whose own risk register says a mis-parse persists and generalizes, and
  `speak.py` already shows how to capture a read with no document behind it.
- No real-document run. Every slice is supposed to meet real statements before
  being called done, and this one has met only fixtures. Until a real mortgage or
  car purchase goes through the sentence path, treat it as built and unproven.
- `listen.py` is no longer the default reader for every free-text box: a question
  declares the typed slots an answer to it has, and `interpret` fills those slots
  rather than always reading a sentence as a ruling about the four majors. The
  four majors and the six steps are unchanged; how the two paths divide questions
  between them is not written down anywhere but the code.
- Splitting a mortgage by real amortization ratios, once a statement supplying
  them is ingested. `split_transaction` requires split magnitudes summing to the
  movement total, so it cannot express *three legs, proportions unknown* — it
  waits for real ratios rather than being made to accept invented ones.
- Asset *valuation* over time, as opposed to cost at acquisition.
- Open-world free text with no question attached, and proposal unification across
  sources.
- Locally-phrased questions: the templates are fixed strings, and a small
  in-house model phrasing them in the person's own language and tone is a
  surface-only change nobody has taken.
- A pointer from the merchant catalog to an account, so a ruling generalizes
  without re-resolving.
