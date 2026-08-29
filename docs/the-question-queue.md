# The Question Queue

**State:** built
**Rules:** MON-44, MON-45, MON-46, MON-47, MON-48, MON-49, MON-50, MON-51, MON-52, MON-53, MON-54, MON-55

**Invariants touched:** T1 · T2 · **T4** · X2 · **X3** · principle 5 · principle 6 · principle 7. Extends [verification-findings-and-correction.md](verification-findings-and-correction.md)'s Rung 2 — *the human, asked well* — from one document to the whole vault.

## Rules

### MON-44 — a question is a read-side projection, and answering uses the writers that exist
**State:** enforced
**Code:** product/viva/questions.py:670 (`open_questions`)
**Test:** product/tests/test_questions.py::test_the_queue_introduces_no_new_event_type

1. `open_questions()` gathers every source of ambiguity the vault already records; it adds no event type and no ingest change: questions, pending state and declines are projections over events the ledger already has.
2. Answering routes to the existing writers, through the one door in `product/viva/engine.py`.
3. Every question carries the evidence it rests on and the figure it moves (T1).

### MON-45 — ranked by consequence, with stable ids
**State:** enforced
**Code:** product/viva/questions.py:705 (`open_qs.sort(key=lambda q: (-q.amount, q.id))`)
**Test:** product/tests/test_questions.py::test_questions_are_ranked_by_what_answering_moves

1. The list is ordered by how much money answering moves, highest first, with ties broken by id so the order is stable between reads.
2. A question's id is derived from what it is about, so the same question does not churn between projections (product/tests/test_questions.py::test_question_ids_are_stable_across_reads).
3. No model chooses a subject or an order; the persona changes the words of a question and never promotes a movement between the three tiers.

### MON-46 — a question is raised at the most general unit that is still honest
**State:** enforced
**Code:** product/viva/questions.py:276 (`_nature_questions`, grouped by merchant key); product/viva/listen.py:566 (what may generalize)
**Test:** product/tests/test_questions.py::test_answering_a_nature_question_settles_the_merchant_and_stops_asking

1. A commercial counterparty's question is scoped to the merchant, so one answer settles every transaction from it, past and future.
2. A peer or instrument descriptor, and a genuinely one-off ambiguity such as a transfer pair, is scoped to itself (product/tests/test_questions.py::test_a_peer_payment_is_scoped_to_itself_not_a_rule).
3. Answering is idempotent: the ruling changes state, so the question does not return (product/tests/test_questions.py::test_a_ruled_one_off_question_is_never_asked_again).

### MON-47 — silence by ranking, never by hiding
**State:** enforced
**Code:** product/viva/questions.py:707 (`shown, rest`), :778 (`pending_questions`), :759 (`_split_declined`)
**Test:** product/tests/test_questions.py::test_the_tail_is_summarized_never_dropped

1. The top N surface and the rest are reported as a tail with its count and its total; nothing is dropped, because hiding them would be a lie of omission.
2. There is no materiality threshold, which would be a currency- and jurisdiction-shaped guess (I1, I5).
3. A declined question is still built and still findable in the pending list; the decline filter is what keeps it out of the ranked list, and it returns when its stake changes.

### MON-48 — question text is a deterministic template from the persona pack
**State:** enforced
**Code:** product/viva/questions.py (every `say(...)` call); the persona pack under product/viva/persona/
**Test:** product/tests/test_persona_pack.py::test_question_text_no_longer_lives_in_code

1. A question's words are a template, never a model call, so the queue is reproducible, free and offline-testable.
2. A phrasing may only place fields the deterministic intent supplied, and the slot's declared type is checked as well as its name (product/tests/test_persona_pack.py::test_phrasings_use_only_their_intent_fields).
3. Every figure a question states goes through the one renderer that writes every other amount in the product.

### MON-49 — every question declares what structure an answer has
**State:** enforced
**Code:** product/viva/reply.py:138 (`Slot`), :323 (what a model is told)
**Test:** product/tests/test_listen.py::test_the_model_never_supplies_a_figure

1. Each question carries typed slots, and one inbound router reads any reply into them, whatever the question's kind.
2. The model turns language into structure and never into a value; deterministic code validates each value against its type and writes.
3. A reply that does not hold up goes back to the model once, with what it sent and what was wrong with it, before anyone troubles the person (product/tests/test_ask.py::test_a_reply_that_does_not_hold_up_comes_back_in_vivas_words).

### MON-50 — a substantive answer has no button payload
**State:** enforced
**Code:** product/viva/reply.py:536 (a closed vocabulary is validation, not a payload); desktop/src/features/conversation/Questions.tsx (`AnswerControls`)
**Test:** product/tests/test_ask.py::test_a_reply_she_could_not_read_leaves_the_question_where_it_was

1. A question's substantive answer offers no clickable payload; it enters as the person's sentence and is read through the slots the question declared.
2. A closed vocabulary survives as validation of what a person said.
3. `offered` — the part of a vocabulary a model is told — may be narrower than `choices`, which is what a reply is validated against.
4. After that sentence produces an inspectable Proposal, explicit confirm and decline controls may answer only its declared `yes_no` slot; they carry no proposed ledger structure.

### MON-51 — confirmation is an explicit typed decision (X3)
**State:** enforced
**Code:** product/viva/listen.py:538 (`propose`), :658 (`apply_proposal`); product/viva/desktop_bridge/conversation_actions.py (`ConversationActions.confirm`)
**Test:** product/tests/test_ask.py::test_an_answer_that_would_open_an_account_is_proposed_before_it_is_written, product/tests/test_conversation_actions.py::test_bridge_can_confirm_a_held_proposal_and_verify_the_durable_account

1. An answer that would do something irreversible comes back as a proposal stating in plain words what it would do.
2. The decision is a declared `yes_no` slot, filled either from the person's words or by an explicit confirm-or-decline control and decided by code (product/tests/test_ask.py::test_a_confirmation_is_read_as_language_not_as_a_word; desktop/src/features/conversation/Questions.test.tsx).
3. A proposal never confirmed leaves the ledger untouched (product/tests/test_ask.py::test_a_proposal_that_is_never_confirmed_leaves_the_ledger_untouched).
4. The opened-vault bridge retains the proposed structure and gives the interface only an opaque identity, summary and decision sentence; a client cannot submit replacement legs.

### MON-52 — a nature question is raised only where the evidence is weak
**State:** enforced
**Code:** product/viva/questions.py:305 (`if m.nature_reason not in (BY_CATEGORY, BY_DEFAULT): continue`); product/viva/ledger/projection/tiers.py:26 (`tier_of`)
**Test:** product/tests/test_questions.py::test_an_ordinary_known_merchant_is_never_asked_about

1. A movement is asked about only where its nature rests on a category hint or the plain default; anything a link, an own account or a ruling settled is not asked about again, at any tier.
2. A settled counterparty raises nothing; a counterparty implying a relationship raises one grouped proposal; an instrument or a peer raises one question per movement; an unidentified merchant raises the merchant question instead, so the two never collide.
3. There is no list of capital-looking categories anywhere — leverage ranking is the filter (I5).

### MON-53 — a rhythm question is one proposal per counterparty and direction, licensed by the catalog
**State:** enforced
**Code:** product/viva/questions.py:417 (`_rhythm_questions`)
**Test:** product/tests/test_rhythm.py::test_a_standing_prior_raises_one_grouped_proposal_per_pair

1. The catalog must say two things before a question is raised: that the counterparty is a business, and that an arrangement with them is possible. A record naming a rail or a person, or naming no kind at all, raises nothing (product/tests/test_rhythm.py::test_a_merchant_with_no_billing_prior_is_never_asked_about).
2. A pair whose other side a grammar slot declared a person raises nothing, and no measurement is dropped either way.
3. The answer is a ruling at the rhythm scope carrying a set-valued value; it settles the pair in the open list and the set-aside list alike, and more of the same money does not reopen it (product/tests/test_rhythm.py::test_more_of_the_same_money_does_not_reopen_a_confirmed_rhythm).
4. "No rhythm" is an answer rather than a decline.

### MON-54 — a stake is money already measured
**State:** enforced
**Code:** product/viva/questions.py:670 (every builder's `amount` comes from posted movements)
**Test:** product/tests/test_rhythm.py::test_a_question_is_ranked_on_money_already_measured

1. The figure a question is ranked on is money the ledger has measured, never a projection of what a relationship will move next.
2. An interview question about an account whose money its statements already explain carries a stake of zero rather than borrowing its balance.

### MON-55 — a cash withdrawal is a spend until an unexplained asset says otherwise
**State:** unmet
**Code:** none found
**Test:** none

1. The trigger is an asset declared that no card spend and no bank withdrawal explains, never a withdrawal on its own.
2. The machine proposes that past withdrawals were that asset's acquisition and never re-reads a movement on its own word (T9).
3. The answer is a ruling on the movement, which already outranks the heuristic rung that defaulted it, so answering is idempotent and needs no new event type.

## Why

Movement nature made the spending figure honest and, in doing so, **quantified what the system does not know**: on a real vault a third of reported spending rested on a category hint alone, alongside dozens of unknown merchants and a handful of unresolved transfer suggestions. The system knew precisely what it was unsure about and had no way to work through it with the person.

It also already asked several kinds of question, built several separate times — whose account is this, are these the same money, what is this merchant, is this spending or moving — each with its own writer, its own queue and its own card in a surface. Four implementations of one primitive. The queue is one front door over them, and the reason it needed no write path is the standing trade: abstract the read side early, the write side late.

Three rules keep it a butler rather than a chore list. **Leverage ranking** — ask the question that moves the most money first; on the real vault two questions resolved roughly half the outstanding uncertainty, and a hundred small ones can wait forever without harming the picture. **Scope** — one ruling should clear many, so a question is raised at the merchant, the unit that already generalizes retroactively and forward. **Silence by ranking rather than hiding** — the top surface, the tail is summarized, and an unanswered question leaves its figure provisional and labelled, so silence degrades the picture's precision and never its honesty.

The words are deterministic because a model that phrases a question could smuggle a claim into it, and because a queue that is reproducible and free can be tested offline. What moved over time is where the templates live — the persona pack, with a lint holding a phrasing to the fields and types the intent supplied — not the rule.

The answer path had to be typed for a reason that showed up in a real sitting. Routing a reply by the *kind* of question meant a sentence typed into a transfer question's box was parsed as a ruling about the four majors. Now each question declares the structure of an answer to it, one router reads any reply into those slots, and the split of labour is fixed: the model turns language into structure, deterministic code turns structure into a write.

Buttons remain excluded from the substantive answer because a pre-baked payload
would bypass the person's own account of what is true. Confirmation is narrower:
the proposal is already visible, the only admissible decision is its declared
`yes_no` slot, and the client holds no structure it could change. A closed
vocabulary otherwise survives as *validation* rather than as clickable payloads
— and it is closed in one direction only for a good reason: a label the
vocabulary does not hold is still read, because a category a person coins is
theirs to add. That leaves a near-duplicate open, and closing it would need
either a fence, contradicting the local-categorization decision, or a stemming
rule, which is the class of workaround this project has deleted twice.

A confirmation is not a rival to X3; it *is* the mechanism. What the design
excludes is an uninspected or client-authored write, not an explicit decision
between the proposal and its application. Ask, read, record — or propose,
inspect, decide, record.

What raises a nature question was the build's sharpest surprise. The spec advertised a vehicle purchase and a property closing as the two highest-leverage questions, and neither is provisional: both are confidently categorized and counted as spending. So "ask about provisional items" would have missed exactly what was promised. A nature question is therefore raised wherever nature rests on **weak evidence** — a category hint, or the plain default — and leverage ranking is the filter. Big-ticket ambiguity floats up and a grocery run sinks, with no jurisdiction-shaped list of capital-looking categories anywhere.

Idempotence was falsified once, and the repair says where such a fix belongs. A nature question scoped to a single movement was built from the movement's tier alone, and a tier never consults rulings, so the question returned however many times it was answered and the queue could not be driven to empty. The fix went one layer up: the builder drops any movement whose nature something stronger already decided, before the tier is consulted at all. A reader checking the tier alone will conclude the falsification stands. The surviving limit is worth watching — the filter reads the *derivation*, not "this was answered", so a ruling recorded at a scope the nature derivation does not consult would suppress nothing and reintroduce the failure.

The fifth question type — rhythm — proved the shape the generic scoped ruling was waiting on, and settled three things about the queue itself. **A prior may license a question the ledger cannot yet evidence**, provided the sentence carrying it claims no measurement: a merchant seen twice and a merchant seen fourteen times raise the same kind of question with visibly different sentences. **Answering it is idempotent**, and "there is no rhythm" is an answer rather than a decline, so no new decline behaviour was needed. **The stake is money already measured**, because a stake is a ranking key and a projected one would put a claim about the future into the ordering with nothing saying so. The licensing conjunction is the T9 asymmetry applied: a model-authored label may *withhold* a question and may not *delete* a measurement, so the flow the ledger measured is unchanged whatever the label says.

The sixth type is chartered and unbuilt, and its charter is deliberately narrow. A cash withdrawal is a spend unless the person says otherwise — the same shape as money moving to a card, except that with no statement on the other side there is nothing for it to be the settlement *of*. What may reopen it is evidence, and the evidence runs **backwards**: an asset declared that nothing explains. A question raised per withdrawal would be exactly the chore list rule 3 forbids. This is the first question type that reaches back to movements already posted, already counted, and possibly already spoken in an answer — and what that costs a person whose spending figure later moves is named, not settled (M1 in [design-invariants.md](design-invariants.md)).

Two questions have no correct answer among anything the queue can offer: a **compound payment**, where a mortgage is interest and principal and escrow at once, and a **capital purchase**, where the thing bought is something the person now owns. Forcing a nature ruling on either produces a wrong figure in one direction or the other. The fix is not a better option list; it is to recognize these cases and say what is missing — the document that states the split, or the primitive that represents the thing — rather than inviting a guess.

## Open

- MON-55 is unbuilt: nothing raises a question from an unexplained asset, and nothing re-reads past cash withdrawals.
- What a person is owed when a figure they were already shown moves afterwards is undecided.
- The queue's filter for repeat nature questions reads the derivation rather than "this was answered", so a ruling at a scope the nature derivation does not consult — a category-scoped rule is the standing case — would suppress nothing.
- Near-duplicate category labels minted through an answer ([issue #7](https://github.com/vishnuyar/orionviva/issues/7)); the ruling is Vishnu's.
- Model-phrased questions are unbuilt. Interruptive timing is not a missing
  queue capability: findings belong in the picture, and Viva waits to be
  opened rather than initiating or notifying.
- Learned auto-apply for peer descriptors ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)) is unbuilt.
- The interview source is the one place where answering produces *another* question ([the-interview-and-the-schema-pack.md](the-interview-and-the-schema-pack.md)); the compound and capital-purchase cases above are recorded in [learning-mode.md](learning-mode.md) and deferred by decision.
