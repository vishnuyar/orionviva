# Viva Listens, and Viva Speaks — the agent and the learning loop

**State:** built
**Rules:** VOICE-50, VOICE-51, VOICE-52, VOICE-53, VOICE-54, VOICE-57, VOICE-58, VOICE-59, VOICE-131

## Rules

### VOICE-50 — a Proposal is the only path to a change, and it is never applied unconfirmed
**State:** enforced
**Code:** product/viva/listen.py (`Proposal`, `apply_proposal`), product/viva/engine.py (`confirm_proposal`), product/viva/desktop_bridge/review_actions.py (`outcome_of`)
**Test:** product/tests/test_listen.py::test_applying_is_a_separate_explicit_act, product/tests/test_review_actions.py::test_a_confirmation_proposal_is_readable_and_proves_nothing_was_written, product/tests/test_review_actions.py::test_bridge_can_confirm_a_held_proposal_and_verify_the_durable_account

1. A Proposal is a structured, un-applied intent: what it would change, how much money it moves, the evidence behind it, how confident it is, how to reverse it.
2. Proposing and applying are separate acts; anything but a yes writes nothing.
3. A proposal states what it does not know, and names each meaning once.
4. X3 is satisfied structurally rather than by prompt: a Proposal is by definition not applied until confirmed.
5. The interface boundary preserves an unconfirmed Proposal as `proposal`, never as a completed write or an unreadable outcome; setting a question aside is likewise its own `set_aside` outcome rather than an answered question.
6. The opened-vault bridge retains the unapplied structure under an opaque identity. Confirmation applies that retained structure through its typed `yes_no` slot; declining writes nothing and closes it.

### VOICE-51 — the interpreter never supplies a figure
**State:** enforced
**Code:** product/viva/listen.py, product/viva/reply.py
**Test:** product/tests/test_listen.py::test_the_model_never_supplies_a_figure

1. Any amount in the interpreter's output is ignored; amounts come from the projection.
2. A figure the person's sentence never carried is refused, however well the model read it.
3. A stated split is kept and an invented one is not.
4. A share the model made up is still only a number it must prove.

### VOICE-52 — the interpreter is an edge, quarantined like the reader
**State:** enforced
**Code:** product/viva/engine.py:277 (`_interpreter`), product/viva/listen.py
**Test:** product/tests/test_listen.py::test_the_interpreter_is_configured_separately_and_can_be_local

1. The interpreter is one injectable module, so everything else is offline-testable, and the live model call is the only thing that touches the network.
2. It receives the question, the descriptor and the person's sentence — never the ledger.
3. It proposes and cannot write.
4. A broken model degrades the surface, never the ledger.

### VOICE-53 — with no model configured, nothing is guessed and the queue still works
**State:** enforced
**Code:** product/viva/listen.py, product/viva/reply.py
**Test:** product/tests/test_listen.py::test_with_no_model_nothing_is_guessed

1. Free text is an addition to the buttons, never a dependency of them.
2. A reader that cannot be reached says so and is not asked again.

### VOICE-54 — the button path and the sentence path write the same events
**State:** enforced
**Code:** product/viva/engine.py:38 (`answer_question`), :560 (`apply_ruling`)
**Test:** product/tests/test_listen.py::test_the_button_path_and_the_sentence_path_write_the_same_events

1. Answering in your own words produces the same event pressing the button would, with the same grade and the same reversibility.
2. A ruling retires the question that prompted it.

The speaking direction opens by committing a shape, and the model writes no
digits inside it. Both rules live once, in
[projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md):
**PROJ-1** (the shape is committed before anything is read) and **PROJ-2** (a
model writes no digits, and every clause carries a hole).

### VOICE-57 — a figure fills a hole only when kind, quantity and set all agree
**State:** enforced
**Code:** product/viva/tools/runner_binding.py:242
**Test:** product/tests/test_shape_binding.py::test_a_thing_of_the_wrong_kind_cannot_fill_a_hole

1. A hole holding a magnitude must say what the magnitude is of, and what set it was taken over.
2. A figure that states no set fills no hole asking for one; a total of everything cannot be spoken as one counterparty's.
3. A magnitude nothing measured can fill no hole at all.
4. A caveat a result wrote about its own number cannot be dropped.

### VOICE-58 — the same machine runs inbound
**State:** enforced
**Code:** product/viva/reply.py
**Test:** product/tests/test_reply.py::test_every_question_declares_the_structure_of_its_answer

1. A question declares the typed slots an answer to it has.
2. The model turns what a person typed into those slots, filled; deterministic code validates each value against its type and writes.
3. A slot nothing can check is a build error, not a person's mistake.
4. Model proposes structure, code disposes — in both directions.

### VOICE-59 — no agent-memory framework
**State:** untestable
**Code:** none found
**Test:** none

1. The event log is the memory; no similarity-retrieval memory framework is adopted.
2. A ruling is append-only, dated, graded, provenance-carrying, superseded by a later event, and deterministically applied.

### VOICE-131 — the sentence and the parse are captured verbatim
**State:** unmet
**Code:** none found
**Test:** none

1. A person's own sentence and the model's parse of it are captured in the claims layer, under an `interpret` phase, so a better model can re-derive later without asking again. This is what **T3** (capture-first) asks of the listening path.
2. No `interpret` phase exists. See [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md) for what is and is not kept.

## Why

*Are the conversational agent and the learning loop one thing or two?* **One
engine, two directions.** Both are natural language on one side, structured
truth on the other, deterministic tools holding the facts in between. What
differs is who initiates, and therefore what can go wrong: when you say what
something *is*, the model parses intent into a proposal and a wrong ruling
**persists and generalizes**; when you ask what is *true*, the model plans tool
calls and a wrong answer **misleads once**. The listening half came first
because it needs no new tools, it is what the author felt the absence of, and it
de-risks the hardest safety property in a bounded setting before a model goes
anywhere near the whole ledger.

**Why free text and not a better set of buttons.** The deficiency is not
impatience with clicking: a closed-option question cannot express a compound
truth. A mortgage payment is interest *and* principal *and* escrow at once
([learning-mode.md](learning-mode.md)), and forcing a choice produces a wrong
number in one direction or the other. Free text is the only channel wide enough
for what is true. The distinction that keeps it safe is that **the input becomes
non-deterministic; the effect stays deterministic** — this widens the channel
into the ledger, not the ledger itself.

The field agrees with the boundary rather than softening it. Intent-to-execution
integrity is the right frame, and the named failure sources are untrusted data
ingestion and untrusted tool execution ([arXiv 2605.16976](https://arxiv.org/html/2605.16976)).
Human confirmation is not a training wheel: a survey of 21 deployed systems
found runtime approval, policy specification and scope configuration each
adopted by at least 14, and concluded that current model capability is
insufficient to close the intent-alignment gap without human participation
([arXiv 2605.24309](https://arxiv.org/html/2605.24309v1)). Structured output,
not open-ended text, is the base safety pattern for anything consequential
([arXiv 2506.08837](https://arxiv.org/pdf/2506.08837)).

**Why no agent-memory framework.** The memory literature distinguishes
preference memory — what a user likes — from institutional knowledge:
corrections that compound, domain patterns, entity relationships. Our rulings
are firmly the second kind: *"this is my mortgage"* is not a taste but a fact
about a person's financial reality that must apply identically forever. The hard
problems those frameworks benchmark — when memory should stay silent, whether an
agent can tell its memory has gone stale, retrieval you can trust beyond
similarity — are all problems of fuzzy retrieval over unstructured text. We do
not have them by construction, and for this domain the event log is strictly
better than the state of the art. It is recorded as a decision because it will
be tempting later.

**Proposal is the block that makes everything else composable.** `Finding` was
the read side's version of this; Proposal is its write-side twin. The moment it
exists, things already built turn out to be instances: a transfer suggestion, a
model's category suggestion, a forced correction (a Proposal decisive enough to
auto-apply, which reports that it did), a question's options (pre-baked
Proposals with the free text removed). And things not yet built become instances
with no new mechanism — a drafted budget, a payoff plan, an action that does
something irreversible. That last one is the payoff: if Proposal is the only
path to a change, then *nothing irreversible without an explicit yes* stops
being a rule anyone has to remember and becomes a property of a type. It is also
the test of whether the block was designed right — if actions ever need new
gating, the Proposal was wrong.

An unconfirmed Proposal is *derived*, not stored, which is the same discipline
that made movement nature and the question queue free. It becomes an event only
if proposals ever need to survive across sessions, and that is a later,
evidenced decision.

**What the read direction settled on, and why the first answer was wrong.** The
original options were a planner over deterministic tools, template answers with
model phrasing, and retrieval over the ledger. Retrieval stays rejected: it
reintroduces exactly the fuzzy-retrieval failure modes the event log avoids. The
planner was built directly and ran twice against a real vault. It holds as far
as it goes — no wrong number ever reached a person — but it could not *release*
true sentences: a whitelist over prose a model wrote had to decide afterwards
which of its numeric tokens were claims, and after five cycles of new rules it
was still refusing correct answers over bare years and account names.

What replaced it is a fourth option none of the three named. The model composes
neither prose nor values but a **shape** — clauses of literal words with typed
holes, committed before any tool has run — and deterministic code binds each
hole to something the run established and renders it. It is not the template
option: the sentence is authored per question, so there is no template library
that has to grow with question types. It is not the planner option: the model
never writes a figure or a finished sentence, so there is nothing to scan
afterwards. And the same mechanism runs inbound, which is what makes this one
machine rather than two.

**Risks, named.** A mis-parsed ruling scoped to a merchant is worse than a
mis-categorized transaction: it is silent and it generalizes. The mitigations
are already parts we have — show what will change and how much money it moves
before applying, keep every ruling reversible and attributable, and grade a
parsed ruling no higher than a confirmed one. Prompt injection is low here (the
input is the person's own words) but non-zero once documents feed context; the
parse stays powerless, so the blast radius is a bad proposal, not a bad write.
Over-asking is the product risk: free text invites conversation, and the rule is
still *speak when spoken to* — this adds a way to answer, not a reason to chat.

**Persona is configuration, not code** — voice, hedging language, when to stay
silent — because it has to be swappable per person and per locale, and it is the
same configuration the read direction reads.

**Tools become a registry when the read direction needs one, not before.**
Formalizing forty projection methods ahead of evidence is abstraction ahead of
evidence; the registry is the doc-type registry pattern applied again — data,
not code — and it grows with verbs, not nouns
([agent-toolset.md](agent-toolset.md),
[projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md)).

## Open

- The `interpret` phase capture is unmet: the person's sentence and the model's parse are not landing in the claims layer, so a better model cannot re-derive from them later.
- The real-vault proving run of what replaced the planner is still owed. `answer.py` remains the scripted test modality and the oracle.
- An ADR and a design doc for the shape mechanism are owed once the round trip has run against real money.
- Proposal unification — one common shape behind transfer suggestions, category suggestions and findings — is a refactor with no user-visible gain, and must wait for evidence or it is premature generalization.
- The desktop keeps an accepted proposal only in the current review action state. Ordinary navigation clears its opaque identity while the opened-vault bridge still retains the proposal, so returning to Review cannot confirm or decline it.
- Open-world free text with no question attached.
- Whether a parse may ever auto-apply, and on what contract. The existing forced/suggested distinction is the candidate; a money threshold is a currency- and jurisdiction-shaped guess and is not.
- Accounting words versus plain English on the surface.
- Voice and persona beyond the minimum. Anything that acts.
