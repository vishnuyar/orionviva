# The Interview & the Schema Pack — a question that continues

**State:** partial
**Rules:** VOICE-122, VOICE-123, VOICE-124, VOICE-125, VOICE-126, VOICE-127, VOICE-128, VOICE-129, VOICE-130, VOICE-40, VOICE-41, VOICE-42, VOICE-43, VOICE-44, VOICE-45, VOICE-46, VOICE-47, VOICE-48, VOICE-49

Governed by [ADR-012](decisions/ADR-012-the-interview-model-boundary.md).

## Rules

### VOICE-122 — the interview is a primitive with a next step, and it is read-side
**State:** enforced
**Code:** product/viva/interview.py:46 (`Interview`)
**Test:** product/tests/test_interview.py::test_a_vault_built_before_this_replays_identically

1. There is no interview object stored and no interview event; an interview is a projection over the attribute rulings and declines already recorded for a subject.
2. Answered, set aside and settled are all derived states.
3. A vault built before the interview existed replays identically.

### VOICE-123 — the schema is a closed vocabulary
**State:** enforced
**Code:** product/viva/schemas/__init__.py (`ANSWER_TYPES`), product/viva/schemas/schemas-v1.json
**Test:** product/tests/test_interview.py::test_an_answer_outside_the_offered_vocabulary_is_refused_not_guessed

1. An answer outside the vocabulary a question offered is refused rather than guessed at.
2. A key outside the schema is dropped, not acted on.
3. A free-form answer is never read as a number.

### VOICE-124 — seed small, generate on first encounter, promote on review
**State:** unmet
**Code:** none found
**Test:** none

1. A previously unseen kind triggers one impersonal model call that drafts its schema.
2. The draft is written to the pack, flagged unreviewed, asked from immediately, and promoted when a person reads it.

### VOICE-125 — no amounts and no currency in the interview envelope
**State:** unmet
**Code:** none found
**Test:** none

1. The interview envelope carries no amount and no currency; the jurisdiction tag carries what currency would have told the phrasing.
2. No amount leaves in an envelope without an [ADR-012](decisions/ADR-012-the-interview-model-boundary.md) amendment.

### VOICE-126 — the interview interleaves and never holds the queue
**State:** enforced
**Code:** product/viva/questions.py, product/viva/interview.py:78 (`next_question`)
**Test:** product/tests/test_interview.py::test_an_interview_ranks_with_the_other_questions_not_ahead_of_them

1. The next question ranks with every other question, never ahead of them.
2. "Not now" defers the question into pending state; it leaves the ranked queue and can still be found.
3. It returns when new evidence touches its subject, or when the person opens the pending list. Never on a timer.

### VOICE-127 — essentials terminate the interview and gate net worth
**State:** enforced
**Code:** product/viva/interview.py:72 (`terminated`), :86 (`unfilled_essentials`)
**Test:** product/tests/test_interview.py::test_an_asset_with_no_stated_cost_is_a_gap_never_a_zero

1. An interview is over when every essential is answered or declined.
2. An asserted asset whose essential cost is unfilled is reported as a disclosed gap — never a zero, never a guess, never silently omitted.
3. Which essential gates net worth is `gates_net_worth` in the pack, and which one dates the carried figure is `dates_net_worth`; the curve infers neither from an answer type.
4. A stated cost is a line at cost and *replaces* any cash-derived line for that account rather than adding to it.

### VOICE-128 — tags gain account scope, and the model copies the person's word
**State:** contradicted-by-code
**Code:** product/viva/ledger/events.py:732
**Test:** none

**Contradiction:** the doc says a tag gains account scope and flows to every movement touching the account. `product/viva/ledger/events.py:732` restricts a tag assertion to `SCOPE_MOVEMENT` or `SCOPE_MERCHANT` and refuses anything else, so account-scope tags cannot be written at all. The half that holds is that no model coins a tag: the interpret prompt in force, `interpret-v3`, tells the model a label is *their own short word for a thing they named, copied from their* sentence, and to invent no name — and [categories-and-tags.md](categories-and-tags.md) MON-76 is unchanged.

### VOICE-129 — cycle 1 is deterministic, and a model selector must beat it on measured grounds
**State:** enforced
**Code:** product/viva/interview.py:78 (`next_question`)
**Test:** product/tests/test_interview.py::test_an_account_with_a_schema_is_asked_one_thing_at_a_time

1. Pack order is the deterministic selector: the next essential owed, in pack order.
2. The deterministic walk never goes away; it is the model selector's permanent fallback.
3. A model selector ships only against measured numbers — questions to settle, essentials unfilled at termination, off-schema rate, confidently-wrong rate.

### VOICE-130 — jurisdiction is an attribute of the account, and the country tag is derived
**State:** unmet
**Code:** product/viva/schemas/schemas-v1.json (jurisdiction tags on kinds)
**Test:** product/tests/test_interview.py::test_a_jurisdiction_scoped_question_does_not_travel (a jurisdiction-scoped question staying home only; nothing tests that the country tag is derived)

1. Every schema is jurisdiction-tagged, and a jurisdiction-scoped question does not travel to another jurisdiction.
2. An account created from a schema records its jurisdiction as a graded, upgradeable attribute, and the country tag is a read over that attribute rather than a second stored label. *This half is not implemented: the field is stored on the account and defaults to empty, meaning nobody has said.*

### VOICE-40 — a schema question may never ask for an identifier
**State:** enforced
**Code:** product/viva/schemas/__init__.py (`ANSWER_TYPES`)
**Test:** product/tests/test_interview.py::test_no_answer_type_means_an_identifier

1. The answer vocabulary is `money`, `date`, `rate`, `yes_no`, `choice`, `label`, `institution`, `link` — and no member of it means an identifier.
2. No account number, policy number, address, UAN, PAN, SSN, VIN, registration number or plate is ever asked for.
3. Widening the vocabulary is a visible act that fails this test first.

### VOICE-41 — a schema names only documents the pipeline actually classifies
**State:** enforced
**Code:** product/viva/schemas/__init__.py
**Test:** product/tests/test_interview.py::test_a_schema_may_only_name_a_document_the_pipeline_classifies

1. A corroborating document type must exist in the ingestion pipeline's own registry.
2. An alias is refused, because a document resolves to its canonical type and an alias would match nothing.
3. A schema may only claim an account kind the ledger uses.

### VOICE-42 — an account comes into being only through a confirmed Proposal
**State:** enforced
**Code:** product/viva/engine.py:165 (`confirm_proposal`), :474 (`open_kind`)
**Test:** product/tests/test_interview.py::test_an_answer_that_would_open_an_account_comes_back_to_be_confirmed

1. A yes that would open an account returns a Proposal; nothing is created until the Proposal is confirmed.
2. Existing accounts are offered first, by name, and a near-match returns `ambiguous` rather than minting a second account.
3. The Proposal carries no suggested name and the code refuses to invent one: an answer that names nothing returns `unnamed`, which is a question, not a path.
4. A name cannot inject a level into the account hierarchy.

### VOICE-43 — a figure in an attribute answer must appear in the person's own words
**State:** enforced
**Code:** product/viva/ledger/events.py:573
**Test:** product/tests/test_interview.py::test_a_figure_absent_from_their_words_is_refused

1. A value the sentence does not carry is refused, however well the model read it.
2. A sign nobody wrote is refused; a non-finite value is refused; a negative one is refused.
3. The same figure written differently — a symbol, another grouping — is still accepted.
4. An attribute money value is `(value, currency)`, read by the locale-aware parser.

### VOICE-44 — a value on a ruling is confined to the scopes that declare one
**State:** enforced
**Code:** product/viva/ledger/events.py:558
**Test:** product/tests/test_interview.py::test_a_value_outside_attribute_scope_is_refused

1. Only attribute and rhythm scopes may carry a value; every other scope refuses one outright.
2. An attribute value is open, so it is guarded against a figure the words do not carry.
3. A rhythm value is a closed vocabulary, so it is guarded at construction against any word outside it.

### VOICE-45 — attribute rulings are a history, and a correction does not reach backwards
**State:** enforced
**Code:** product/viva/interview.py:111 (`attributes`)
**Test:** product/tests/test_interview.py::test_an_answer_today_does_not_rewrite_an_earlier_point

1. Reading attributes as of a date keeps the last answer dated at or before that date.
2. A correction recorded later is the answer today and was not the answer then.

### VOICE-46 — a released schema pack is frozen
**State:** enforced
**Code:** product/viva/versions.json (`schema_pack`)
**Test:** product/tests/test_interview.py::test_released_schema_packs_are_frozen

1. A person answered the words that were there, so those words keep resolving.
2. Changing a schema is a new pack file with a new version id, never an edit.

### VOICE-47 — a kind with no schema asks nothing and records the gap
**State:** enforced
**Code:** product/viva/interview.py:98 (`_why_no_schema`)
**Test:** product/tests/test_interview.py::test_a_kind_with_no_schema_asks_nothing_and_records_the_gap

1. A kind the pack does not cover raises no question.
2. The absence is recorded as a coverage gap rather than silently passed over.
3. A kind the ledger cannot tell apart — a loan and a card are both `liability` — resolves nothing, and the gap is recorded rather than a question built on a guess.

### VOICE-48 — every question says what it unlocks, and a choice enumerates its alternatives
**State:** enforced
**Code:** product/viva/schemas/__init__.py
**Test:** product/tests/test_interview.py::test_a_question_must_say_what_it_unlocks

1. A pack entry with no `unlocks` sentence fails the build.
2. A `choice` answer with no enumerated alternatives fails the build.
3. A conditional essential is not owed until the answer it depends on has arrived.

### VOICE-49 — what a document already said is not asked again
**State:** enforced
**Code:** product/viva/schemas/schemas-v1.json (`answered_by_document`)
**Test:** product/tests/test_interview.py::test_what_a_statement_already_said_is_not_asked_again

1. A classified document answers the question its own type settles, from pack data mapping document type to answer.
2. A schema finds an account by three sources of evidence, strongest first: the path's `account_shape`, the document types the issuer produced for it, then the ledger's account kind — the last only when one kind claims it.

## Why

**The schema owns what may be asked; the model owns what to ask next; the person
owns whether anything is created.**

The diagnosis was structural, not cosmetic. A question was a one-shot record —
text, options, a free-text box, refs — with no next step anywhere in the
product. So "a list of buttons with no intelligence" was an accurate description
of a fact, and better wording could not have fixed it. The same fact explains an
audit finding: a tier-3 option carried only a movement key and a major, so with
nowhere to ask *which one, and what is it called?*, applying immediately was the
only move the shape allowed — and an unnamed asset reached the net-worth curve.
The interview is that finding's structural fix, which is why the guard and the
capability are one piece of work rather than two.

Five settled positions this builds on and must not undo: Viva decides how to ask
and never what ([viva-persona-and-interview.md](viva-persona-and-interview.md)),
extended rather than broken, because now the *schema* decides what may be asked
and a model may only order and word what the schema already permits;
intelligence at the question rather than the answer
([where-the-intelligence-goes.md](where-the-intelligence-goes.md)); model as
interpreter, person as ratifier, code as applier
([from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)); a
question that cannot be honestly asked is not asked
([learning-mode.md](learning-mode.md)); and never a nag
([experience-vision.md](experience-vision.md)).

Making the interview read-side is the read-side-early rule paying out again: it
lands with no schema migration, heals an existing vault on replay, and is
reversed by deleting a projection rather than by living with an event shape
forever.

A closed vocabulary is the mechanism this project already uses to let a model be
smart without being dangerous — `interpret` drops any leg outside its
vocabulary, grammar induction slots into a closed set. A model choosing among
reviewed questions cannot steer the interview toward what *it* wants to know.

Seeding small rather than enumerating forty kinds is the expectations
registry's precedent: an enumeration written from here produces a US-shaped list
whose omissions are invisible. Nine kinds do not describe a financial life; they
describe the part of one that can be checked against real documents. Everything
else arrives by being met, drafted, flagged unreviewed and promoted on a read.

Removing a whitelist field is free and adding one is an amendment, which is why
the envelope carries no money: the count and cadence make a question feel
informed, the money adds nothing to selection, and it is the most sensitive
field there is.

Deferring into pending rather than into silence is how *"it always comes back"*
and *"never a nag"* are both true. Ranking by consequence is settled, and an
interview that outranked a larger finding would be incoherent.

Naming the account fixes half the audit finding; the other half is a named asset
whose number nobody stated. A zero would be a number nobody stated, and this
product does not put those in front of people. An asserted asset with unfilled
essentials is neither counted nor hidden — it is a stated gap, exactly as a
liability with an unknown balance already is.

The deterministic baseline exists so that "the model asks better questions" is
not a feeling with nothing to compare against. Build the dumb walk, feel how
dumb it is, then beat it with a number.

Jurisdiction as one attribute with the country tag derived gives one source of
truth, so "show me everything in India" works across accounts, movements and
holdings without two vocabularies drifting apart. It does not breach
[categories-and-tags.md](categories-and-tags.md) MON-76 — what that forbids is a
*model* minting personal meaning, and a tag derived deterministically from a
stated fact is the opposite of a guess. Jurisdiction is the instrument's home,
not the person's, and it is not currency: a person may hold an INR instrument
from anywhere.

**Three schema fields carry more weight than they look.** `essential` does three
jobs — it ranks, it terminates, and it gates net worth. `unlocks` is the benefit
sentence the persona's tone rules already require, so a question can always
explain why it is worth answering. `opens` is how branching is expressed as data
rather than as a loop: *"yes, I'm paying an EMI"* opens the loan's own interview
and links the two accounts, with no model involved at all.

**Why an interview never asks for an identifier.** None of them makes an answer
better — a nickname does everything an identifier would do here — and an
interview that collects identifiers turns the vault into the most attractive
file on the machine. It is enforced as a lint over the pack rather than
remembered.

**Why the pack is jurisdiction-tagged from the first entry.** A pack written for
one country and internationalized afterwards is exactly the migration pain I5
exists to prevent. India ships in v1 because it is the author's own exposure, so
the omissions are checkable rather than theoretical. Reading the deltas is the
point: it is almost never a difference of *concept* but the same fact attested
by a different instrument — a US Form 1098 and an Indian provisional interest
certificate do the same job; a certificate of deposit and a fixed deposit are one
instrument under two names. Where the concept genuinely differs — a PPF lock-in,
a sovereign gold bond that pays interest and matures — it earns a
jurisdiction-scoped field rather than a separate kind. `retirement_account` is
the entry that most tests this: a single `401k` kind would have been the natural
US-shaped mistake. `precious_metals` is there deliberately as the pack's own
proof that it is not US-shaped, because household gold is a material asset class
in an Indian financial life and a list written from the US would never have
contained it.

**How a schema finds an account.** The spec assumed a path names its kind. It
does not: an ingested account is `acct:<institution>:<last4>`, and an account a
ruling opens is `<Root>:<group>:<name>` where the group is a word a model wrote
at enrichment. So resolution runs on the ledger's own account kind, by evidence,
strongest first — and it refuses an ambiguous answer rather than guessing,
because a loan and a card are both `liability` and that word alone resolves
nothing.

**Boundaries.** Never a chat agent: the interview is a bounded form with an
intelligent order of asking, and it terminates. The model never chooses a
subject, only an order and a wording, and only from a reviewed set. The model
never supplies a value, picks an account, emits a figure or writes. A schema
never describes how to read a document. No question is asked whose answer the
product could not use, and none the person could not honestly be expected to
know — ask for the document instead.

**The standing gate.** A slice is not done until it has run on a real document
and a real answer. Every mini-slice worth having came from one; the one declared
done without one had two defects.

## Open

- Cycle 1 has not run on a real document and a real answer, which the standing gate requires before it is called done.
- An attribute ruling does not stamp the schema pack version the way the persona and prompt packs stamp theirs.
- VOICE-130's jurisdiction-as-graded-attribute, with the country tag derived, is unimplemented; the field is stored on the account and defaults to empty.
- A retirement account is unreachable from a document, because `401k_statement` and `ira_statement` alias to `brokerage_statement`.
- Two conflicting document types on one account degrade to the ledger's account kind rather than refusing. Defensible, not yet ruled.
- Does `opens` create the second account immediately, or ask first? A loan opened from a property answer is an account coming into being, so X3 says confirm — but confirming twice in one breath may read as friction.
- An *essential* declined leaves the interview terminated and the asset gapped indefinitely. Correct, and it should be visible in coverage rather than merely true.
- How pending looks on a surface — a marker saying something else is waiting. Belongs to the presentation layer's own design conversation; VOICE-126 requires only that pending state exists and is reachable.
- Account-scope tags, multi-proposal `interpret`, attribute upgrade `asserted → corroborated` on a document, and the generated-schema promotion path are all unbuilt.
- `insurance_policy` is blocked, not merely unwritten: protection-only cover is not an asset and a policy with a surrender value is, and India's endowment and unit-linked policies make that split load-bearing. The Provision question should be settled on its own before a schema encodes an answer to it by accident.
