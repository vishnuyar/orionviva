# Viva Listens, and Viva Speaks — the agent and the learning loop

**Status:** Design spec — **both directions are BUILT, and Stage C's option set is superseded (2026-08-07; see the note under Stage C).** Rulings in your own words (see [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md)), and the read direction: a model commits the shape of a sentence before any tool runs, and deterministic code binds and renders it. O1 was built first, ran twice against the real vault, and was replaced; `answer.py` remains the scripted test modality and the oracle. Stage C's machinery — the registry, the adapters, the planner, `viva.speak` — exists; the real-vault proving run of what replaced O1 is still owed. · **Created:** 2026-07-25 · **Origin:** Vishnu, using the debug surface to categorize: *"I am feeling a lot of deficiency and I do not want to create deterministic answers."*

**Invariants touched:** **T2 / ADR-010 (a model may parse what a person *means*; it must never supply a figure or do arithmetic)** · T3 (the person's own sentence and the model's parse are captured verbatim — raw capture applies to interpretation too) · T4 (a confirmed ruling is an append-only event; we reuse the writers we have) · T6 (nothing leaves silently) · X2 (a proposal states what it would change and how sure it is) · **X3 (nothing irreversible without an explicit yes — structurally, not by prompt)** · principle 6 (you direct the pace) · principle 7 (autonomous where safe, deferential where it counts).

---

## The question, and the answer

*Are the conversational agent and the learning loop one thing or two?*

**One engine, two directions.** Both are the same machinery — natural language on one side, structured truth on the other, deterministic tools holding the facts in between. What differs is who initiates, and therefore what can go wrong:

| | **Viva listens** (write) | **Viva speaks** (read) |
|---|---|---|
| You | say what something *is* | ask what is *true* |
| The model | parses **intent** into a proposal | plans **tool calls**, composes the answer |
| It must never | invent the structure or the amount | supply a figure from its own head |
| Failure mode | a wrong ruling **persists and generalizes** | a wrong answer **misleads once** |
| Needs | the writers we already have | a rich toolset (net worth, obligations…) |

The roadmap treats Slice 9 as one thing, positioned after net worth and obligations. **It should split, and the listening half should come first** — it needs no new tools, it is what the author feels the absence of today, and it de-risks the agent's hardest safety property in a bounded setting before a model goes anywhere near the whole ledger.

## Why free text, and not a better set of buttons

The deficiency is not impatience with clicking. **A closed-option question cannot express a compound truth.** A mortgage payment is interest *and* principal *and* escrow at once ([learning-mode.md](learning-mode.md)); no button captures that, and forcing a choice produces a wrong number in one direction or the other. Free text is the only channel wide enough for what is true.

The distinction that keeps this safe: **the input becomes non-deterministic; the effect stays deterministic.** We are widening the channel into the ledger, not loosening the ledger.

## What the field settled on (research, July 2026)

Three findings, and all three support the boundary rather than softening it:

- **Intent-to-execution integrity** is the right frame: an agent must preserve what the person meant from parse through to effect, and the named failure sources are untrusted data ingestion and untrusted tool execution ([arXiv 2605.16976](https://arxiv.org/html/2605.16976)).
- **Human confirmation is not a training-wheel.** A survey of 21 deployed systems found runtime approval, policy specification and scope configuration each adopted by at least 14, and concluded that current model capability is *insufficient to close the intent-alignment gap without human participation* ([arXiv 2605.24309](https://arxiv.org/html/2605.24309v1)). Confirm-before-apply is the state of the art, not a compromise.
- **Structured output, not open-ended text**, is the base safety pattern for anything consequential ([arXiv 2506.08837](https://arxiv.org/pdf/2506.08837)).

### The finding that changes a decision

The memory literature now distinguishes **preference memory** ("what the user likes") from **institutional knowledge** ("corrections that compound over time — domain patterns, entity relationships"), and warns that frameworks built for one get *awkwardly stretched* to cover the other ([Atlan, 2026](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)).

Our rulings are firmly the second kind. *"This is my mortgage"* is not a taste; it is a **fact about this person's financial reality** that must apply identically forever. And the hard problems those frameworks are currently benchmarking — [when memory should stay silent](https://arxiv.org/pdf/2606.06055), [whether an agent can tell its memory has gone stale](https://arxiv.org/pdf/2605.06527), [retrieval you can trust beyond similarity](https://arxiv.org/pdf/2606.06054) — are all problems of *fuzzy retrieval over unstructured text*.

**We do not have them, by construction.** A ruling is append-only, dated, graded, provenance-carrying, superseded by a later event, and **deterministically applied** rather than similarity-retrieved. So: **do not adopt an agent-memory framework.** The event log already is the memory, and for this domain it is strictly better than the state of the art. Recording that as a decision, because it will be tempting later.

---

# The growth architecture — one new block, many uses

The project's rule is that a small set of primitives compose, and *the same block used somewhere new becomes something else*. So the question is not "what does a chat feature need" but **which single block makes all of this composable**.

## The new block: **Proposal**

> A **Proposal** is a structured, *un-applied* intent: what it would change, how much money it moves, the evidence behind it, how confident it is, and how to reverse it.

`Finding` was the read side's version of this — "here is what I think went wrong, forced / suggested / unlocalized." **Proposal is its write-side twin.** And the moment it exists, things we already built turn out to be instances of it:

| Already built | Is really a Proposal that… |
|---|---|
| `TransferSuggested` (transfer links) | proposes linking two movements; awaits confirmation |
| A model's category suggestion (the category overlay) | proposes a category, graded `unverified` until confirmed |
| A **forced** correction (the doc-type registry and transfer links) | is a Proposal decisive enough to auto-apply, and reports that it did |
| A Question's options (the question queue) | are pre-baked Proposals with the free text removed |

And things not yet built become instances too, with no new mechanism:

| Later | Is a Proposal that… |
|---|---|
| Free-text ruling | a model parsed from your sentence |
| A drafted budget or payoff plan (Slice 10) | proposes a plan; you accept or edit |
| A Phase-3 *action* | proposes to do something irreversible — **X3 is satisfied structurally**, because a Proposal by definition is not applied until confirmed |

That last row is the payoff. If Proposal is the only path to a change, then "nothing irreversible without an explicit yes" stops being a rule we have to remember and becomes a property of the type.

## The blocks it reuses (nothing new needed)

Model access (`ModelSpec`/adapters) · Claims record (the verbatim capture, extended to interpretation) · Grade (proposed = `unverified`; confirmed = `verified`) · Correction-as-event (every applied ruling) · Question (the ask side) · Projection (everything derived). **The interpreter is a new edge, not a new spine.**

---

# How it grows, stage by stage — with the options at each

> _Concretised 2026-07-25 in [from-your-words-to-the-ledger.md](from-your-words-to-the-ledger.md), which settles what the parse may emit: the **four majors** (expense/asset/liability/income) plus an account hint and an optional split. That supersedes the A1-vs-A2 framing below — the schema is neither "per question kind" nor "a union of ruling types" but **the counter-leg vocabulary**, which is the same for every question. The open decisions are now D1 (accounting words vs plain English on the surface) and D2 (when a parse may auto-apply)._

## Stage A — Viva listens, *inside a question*

The narrow, safe beginning: you answer an existing question in your own words. Crucially, **the question supplies the context**, so the model is never parsing open-world intent — it is answering *"given that I asked about this merchant, what did they mean?"* That single constraint removes most of the hallucination surface.

**Options for how the parse works:**

- **A1 — per-question-kind schema.** One small prompt and one JSON schema per question kind (nature / merchant / transfer / identity). Most constrained, cheapest, easiest to test offline; four little prompts to maintain. *Recommended start.*
- **A2 — one union schema.** A single prompt covering every ruling type, the model picks. Fewer prompts, more flexible, but a wider space to hallucinate in and a harder schema to validate.
- **A3 — tool-calling.** Expose the writers as tools and let the model call them (gated by confirmation). Most "agentic", most familiar, and the loosest — the model chooses the *action*, not just the *meaning*. Hardest to bound.

**Lean: A1 → A2 once three or four kinds exist**, mirroring how prompts became versioned data only after the second document type. A3 belongs in Stage C, if ever, and only behind Proposal.

**Options for capturing the exchange (T3):**

- **C1 — reuse `read_recorded` with `phase="interpret"`.** The claims layer already has phases (`classify`, `extract`). No new event type; the sentence and the parse land in the same mine that feeds evals and the flywheel. *Recommended* — it honours *abstract the write side late*.
- **C2 — a new `InterpretationRecorded` event.** Cleaner semantically, but a schema commitment for something we can get for free.

**Options for applying it:**

- **P1 — always confirm.** Every parse is shown back in plain words with the money it moves; you press yes. Slowest, safest, matches the research.
- **P2 — confirm unless decisive.** Auto-apply when the parse is unambiguous *and* the consequence is small, exactly as a forced correction does today. Faster; needs a defensible "decisive" definition.
- **P3 — confirm only high-value.** Threshold-based — but a money threshold is a currency- and jurisdiction-shaped guess (I1/I5), the same trap we avoided in the question queue.

**Lean: P1 for the first release**, then P2 using the *existing* forced/suggested contract rather than a new threshold — reusing a block instead of inventing a rule.

## Stage B — one Proposal, many producers

Unify what already exists. `TransferSuggested`, model category suggestions, and findings all become Proposals with a common shape, surfaced through the queue. **No new capability ships in this stage** — it is the refactor that makes Stage C and Slice 10 cheap, and it should only happen once Stage A has proven the shape on real use.

The prize: the surface, the CLI and later the agent all consume *one* thing, so a new kind of proposal costs a row rather than a feature.

## Stage C — Viva speaks (Slice 9)

Now the read direction, which needs two things Stage A does not:

**The toolset made explicit.** Today the projection has ~40 query methods; the agent needs a *registry* of tools — name, arguments, what it returns, and the grade + provenance it carries — which is the doc-type registry pattern applied again: **data, not code**. [agent-toolset.md](agent-toolset.md) already argues the number is about twelve and grows with *verbs, not nouns*.

**Options for the orchestration:**

- **O1 — planner + deterministic tools** (the standing proposal): the model plans calls, tools compute, the model composes prose from tool *results only*. Never emits a number it did not receive.
- **O2 — template answers with model phrasing**: deterministic code answers, the model only re-voices. Safest, least capable — effectively today's answer path with better prose.
- **O3 — retrieval over the ledger**: let the model search freely. Rejected — it reintroduces exactly the fuzzy-retrieval failure modes our event log avoids.

**Lean: O2 as a stepping stone, O1 as the destination.** O2 is nearly free once the persona exists and it makes the voice work concrete before any planning risk is taken.

> _**Superseded 2026-08-07 — the lean, and the option set.** O1 was built directly and ran twice against the real vault. It holds as far as it goes: no wrong number ever reached a person. What it could not do is release true sentences — a whitelist over the prose a model wrote had to decide afterwards which of its numeric tokens were claims, and after five cycles of new rules it was still refusing correct answers over bare years and account names._
>
> _What replaced it is **a fourth option none of these three named**: the model composes neither prose nor values, but a **shape** — clauses of literal words with typed holes, committed before any tool has run — and deterministic code binds each hole to something the run established and renders it. It is not O2: the sentence is authored per question, so there is no template library to grow with question types (the scaling-law objection that rejected O2 as a destination). It is not O1: the model never writes a figure or a finished sentence, so there is nothing to scan afterwards. O3 stays rejected for the reason given._
>
> _The same mechanism runs inbound. A question declares the typed slots an answer to it has; the model turns what a person typed into those slots, filled; deterministic code validates each value against its type and writes. **Model proposes structure, code disposes** — in both directions, which is what makes this one machine rather than two. Recorded in the closing amendment of [projection-decomposition-and-the-tool-registry.md](projection-decomposition-and-the-tool-registry.md); an ADR and a design doc are owed once the round trip has run against real money._

## Stage D — Proposals that act (Slice 10 and Phase 3)

Budgets, payoff plans, and eventually real actions. **No new safety machinery is needed** if Stage A is built correctly, because every one of them is a Proposal and a Proposal is never applied unconfirmed. This is the test of whether the block was designed right: if Stage D needs new gating, Stage A was wrong.

---

# Architecture decisions to take now (so it grows rather than sprawls)

1. **Proposal is read-side first.** An unconfirmed proposal is *derived*, not stored — the same discipline that made movement nature and the question queue free. It becomes an event only if we ever need proposals to survive across sessions, and that is a later, evidenced decision.
2. **The interpreter is an edge, quarantined like the reader.** One module, injectable (`interpret_fn`) so everything else is offline-testable, with the live model call the only thing that touches the network. It **proposes and cannot write** — the powerless-orchestrator pattern (ADR-010 / CaMeL) applied to the write direction.
3. **The interpreter never sees more than it needs, and never echoes figures.** It receives the question, the descriptor, and the person's sentence — not the ledger. Any amount in its output is ignored; amounts come from the projection. This is the T2 line drawn at a new boundary.
4. **Persona is configuration, not code** — voice, hedging language, when to stay silent. It has to be swappable per person and per locale (I5), and it is the same config Stage C will read.
5. **Tools become a registry when Stage C starts, not before.** Formalizing forty projection methods today would be abstraction ahead of evidence.
6. **No agent-memory framework.** Recorded above; the event log is the memory.

# Risks, named

- **A mis-parsed ruling scoped to a merchant is worse than a mis-categorized transaction** — silent, and it generalizes. Mitigations we already have parts for: show what will change *and how much money it moves* before applying (the queue computes exactly this), keep every ruling reversible and attributable, and grade a parsed ruling no higher than a confirmed one.
- **Prompt injection** is low here (the input is the person's own words) but non-zero once documents feed context. The parse stays powerless, so the blast radius is a bad proposal, not a bad write.
- **Over-asking.** Free text invites conversation; the product's rule is *speak when spoken to*. Stage A adds a way to answer, not a reason to chat.
- **The abstraction trap.** Stage B is a refactor with no user-visible gain. It must wait for Stage A's evidence, or it is exactly the premature generalization this project has avoided four times.

# Done criteria for Stage A (rulings in your own words)

- Answering a question in your own words produces the **same event** as pressing the button would, with the same grade and reversibility.
- The sentence and the parse are captured verbatim in the claims layer (`phase="interpret"`), so a better model can re-derive later without asking again.
- Nothing is applied without confirmation, and the confirmation states what changes and how much money it moves.
- The interpreter never supplies a figure — asserted by a test that feeds it a sentence containing an amount and proves the amount is ignored.
- With no model configured, the queue still works with buttons: free text is an *addition*, never a dependency.

# Deferred

Open-world free text with no question attached (Stage A's harder sibling). The tool registry and planner (Slice 9 — Viva speaks). Proposal unification (Stage B). Voice/persona beyond the minimum. Anything that acts.
