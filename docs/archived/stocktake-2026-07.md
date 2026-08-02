# Stocktake — July 2026

**Status:** ⛔ Historical — the July 2026 audit, complete; its surviving rules live in the standing practices and WORKFLOW.md · **Created:** 2026-07-25 · **Origin:** Vishnu: *"look at this project holistically — stale documents, stale code, mismatch between code and documents. Take stock, then discuss next steps."*

> ## ⛔ HISTORICAL RECORD — do not read this as current
>
> **A point-in-time audit of the project as it stood in July 2026. Everything stale it found has since been fixed or superseded; the rules it produced live on in the standing practices.** Kept because it is the honest record of six occasions when a measuring instrument reported something untrue, and of how the project audits itself. Nothing in it describes how OrionViva works today.

A full pass over code, docs and the vision. Method: mechanical audits (orphan docs, deleted-symbol references, unreferenced modules, roadmap-vs-reality, size and test balance), then judgement about what the numbers mean.

---

## The shape of the thing

| | |
|---|---|
| Code | **11,136** lines across 3 packages (`vivacore`, `viva`, `merchantcore`) + `bench` |
| Tests | **6,006** lines, **296 passing** — a 0.54 test-to-code ratio |
| Docs | **51** files, 4,768 lines, 11 ADRs |
| Prompts | **20 versions**, all in files, none in code |
| Slices | 1 → 6.7 built, plus 9a and the tier refactor |

**The ratio is healthy and the tests are real** — they encode failures found on live data (the sweep double-count, the broken pipe reported as clean, the account minted for a night out), not coverage theatre. That is the part of this project I would defend hardest.

---

## What is genuinely stale

### 1. Doc statuses have rotted — **16 of 51 still say "Draft"**

Several describe things now built. The two that actively mislead:

- **`honest-aggregates-and-the-learning-loop.md`** — *"Move 1 + the reset guard BUILT; Move 2 (question queue) specced, next."* Move 2 shipped days ago.
- **`viva-listens-and-speaks.md`** — *"pre-build, Slice 9 proposed to split into 9a / 9b."* 9a is built; the split happened.

A status line is the first thing a reader trusts and the last thing anyone updates. **This is the same class of failure as the prompt drift**: a discipline that depends on remembering.

### 2. I created a naming collision — "Slice 9b" means two different things

The roadmap's **Slice 9b is "Viva speaks"** — the *read* direction, a tool registry and planner, explicitly waiting for a toolset worth asking. But I committed the tier/implication refactor as *"Slice 9b: the intelligence moves to the question"*. That work is **not** Viva speaking; it is the question queue getting smarter.

Two different things now share a number in the repo's own history. It should be renamed — my suggestion: **Slice 6.8 — Counterparty implications**, since it belongs with the 6.x queue-and-aggregates family, leaving 9b free for the read direction it was always reserved for.

### 3. Dead surface path — the old three natures are still wired

`Detail.jsx` still calls `api.ruleNature(merchant, 'spending' | 'transfer' | 'settlement')`, and `/api/rule-nature` still exists behind it. The four majors replaced that vocabulary, and *"settlement"* was the option that was **wired wrong in the first place** (it meant debt repayment while the button said "something I now own"). Live code contradicting the current design is worse than no code.

### 4. `projection.py` is 1,175 lines and becoming a god object

It now owns: balances, grades, accounts, identity resolution, transactions, movements, nature (5 rungs), categories, the merchant catalog, rulings, positions, transfer suggestions, implications and tiers. Everything reads from it, so everything imports it, so it grows.

Not urgent, and **deliberately cheap to fix** — it is all read-side, so splitting it (`balances` / `movements` / `catalog` / `tiers`) is a refactor with no schema risk. Worth doing before it reaches 1,500.

### 5. Roadmap markers lag

6.5 and 6.7 are built but carry no ✅. The Slice 9 entry still reads *"9a likely next"*.

---

## What is *not* stale (checked, and worth saying)

- **No orphan docs.** The three outside the reading guide — `TODO.md`, `phases.md`, `reading-guide.md` — are all deliberately outside it and say so.
- **No stale references to deleted code.** Every mention of `is_conduit`, `_TRANSFER_HINT_*`, `_group_for`, `CORROBORATION` lives in a doc that *describes them as deleted*. That is a build log doing its job.
- **No unreferenced modules.** The three that look unused (`debug_claim`, `debug_read`, `rescan`) are CLI entry points invoked as `python -m`. Worth one check that `rescan` still has a purpose.
- **All 11 ADRs are decided** — ADR-011 (blind-host tier) is no longer sitting on `Proposed`.
- **No dead endpoints** — the surface contract test enforces that, and it passes.

---

## The honest gaps (not staleness — absence)

These are the ones that matter, and none is new:

1. **Nothing since Slice 6.5 has met real money.** 9a, the tier refactor, brokerage Stage 2 and `enrich-v3` are all measured on synthetic data only. The project's own standing practice is *"a slice isn't done until real statements pass through it"* — and the practice exists because Slice 6 was declared done without one and had two defects.
2. **The eval harness measures one surface.** `eval_listen` scores sentence-interpretation. **Document reading — the thing the whole trust thesis rests on — has no live measurement.** The confidently-wrong rate on real statements is still unknown.
3. **Net worth (Slice 7) is unbuilt** and has quietly become the cheapest high-value thing on the board. Assets, liabilities, `origin`, valuation classes and `reliable_balance` all now exist; net worth is a projection over them.
4. **The presentation layer is explicitly a throwaway debug surface.** Roughly 40 projection queries behind a thin page, and the real design conversation has never happened.
5. **Vault lifecycle is ad hoc.** `reingest`, `reset_categorization`, `debug_tiers` are scripts. Event types keep multiplying. No migration story.

---

## Proposed order

**Now — prove it on real money.** `debug_tiers` (before) → `enrich` under `enrich-v3` → `debug_tiers` (after). One session, no new code, and it either validates six steps of work or exposes what synthetic data hid. *Everything else should wait behind this.*

**Then — a tidy-up pass, half a day.** Rename the 9b collision, refresh the 16 statuses, mark the roadmap, delete the three-nature surface path and `/api/rule-nature`. Cheap, and the docs are this project's memory.

**Then — Slice 7, net worth.** Pure projection, correct-by-construction (balances, not flows), and it is the *payoff* for 9a and the implication work: it is the first view where "what you own" and "what you owe" actually appear. It also immediately exercises `reliable_balance` and `asserted` on real numbers.

**Then — the eval harness on document reading.** The biggest standing gap between what the project claims and what it can show. `eval_listen` is a working template; the corpus and answer key were designed in discovery and never frozen.

**Watching, not scheduled:** splitting `projection.py`; the real presentation layer; vault lifecycle.

### What I would resist

Building Slice 8 (obligations) or 9b (Viva speaks) next. Both are attractive and both would stack more unproven behaviour on top of behaviour that has never met real data. The last two sessions produced a lot of correct-looking work; **the next one should find out whether it is correct.**

---

## The rebuild, run for real (2026-07-26)

40 documents, replayed from stored claims through today's parsers. No model calls, no money. It found **two bugs of mine and one real defect** — and then a fourth thing nobody was looking for.

### Ordering decides the grade — ❌ **RETRACTED, see the correction below**

The same 40 documents, two ingest orders:

| order | posted | held as gaps | movements |
|---|---|---|---|
| content hash (what a replay naturally does) | 16 | **14** | **919** |
| oldest first | **31** | **0** | **919** |

**The money is order-independent — 919 either way.** Slice 1's substantive promise holds, and that is the important half.

**The grade is not.** The same statements are `corroborated` in one order and `conflicted` in the other. For a product whose entire output is trust, *the grade is the product*: a vault telling someone 14 of their statements don't reconcile, when they plainly do, is saying something false. It errs pessimistically, which is the safer direction, but wrong is wrong.

**And `sweep` healed zero of them.** That is the precise defect: the cascade heals *forward* as each document lands, and **nothing re-examines a gap once its missing neighbour has since arrived.** `rescan` exists for exactly this case and does not do it. Recorded as an xfail test rather than a note, so it stays visible.

`rebuild` now replays oldest-first by default — correct for a batch regardless — with `--hash-order` kept to reproduce the bug.

### The other findings

- **My replay skipped a step**: the balance family's `doc_type` comes from the classify phase and the reader stamps it onto the facts. Missing that parked **33 of 40** documents as `unknown`. Brokerage and pay stubs were unaffected because their extract JSON names its own type, which is why the failure looked selective and confusing.
- **A genuine parser defect**: 3 brokerage statements park on unit quantities like `117.360` — the *money* parser applied to a *share count*, where three decimals are normal but a thousands separator is possible. Correct caution, wrong context. Still open, deliberately: loosening a money-safety rule deserves a decision, and the better fix is arithmetic (units × price ≈ market value) rather than permission.
- **A real reconciliation conflict** on one card statement, off by −2,640.27, which the old vault had settled by a human correction we deliberately discarded.
- **2 identity conflicts** — expected and wanted: the account-alias rulings were dropped, so "whose account is this?" gets re-tested.

### And the meta-finding

Four times in this session a tool reported success it had not earned: the eval harness scored a broken pipe as clean, the surface gave one message for four distinct failures, the rebuild reported success on an empty vault, and a sweep that healed nothing printed nothing at all. Each was fixed on its own; together they are one lesson, now in memory: **graceful degradation belongs in the product and never in the instrument that measures it.**

---

## Correction: Slice 1 was not broken (2026-07-26)

**The finding above is wrong and is retracted.** `debug_gaps`, run against the hash-order vault — the one summarised as *"14 gap"* — reported:

> No gap-held statements. Every chain connects.

**The gaps were transient.** A statement that arrives before its neighbour is a gap *at that instant*, and posts as soon as the neighbour lands and the heal fires. Both vaults ended identical: 11 accounts, 919 movements, zero holds. **Slice 1's order-independence holds completely — money and grade.**

What actually went wrong was mine, and it is the same failure a fifth time: the rebuild's summary counted **each document's action at the moment it arrived** and never revised it. `14 gap` was a sum of moments, not a state.

**This one is worse than the four before it.** Those tools under-reported failure; this one **manufactured** one — a confident, specific, documented accusation against code that was correct, complete with a table, a diagnosis, and an xfail test asserting a defect that does not exist. A measurement that errs in the *alarming* direction is not the safe kind of wrong: it would have sent someone to rewrite a working invariant.

**Fixed:** `rebuild` now prints `still held after everything: N` read from the vault itself, and says plainly when arrival-gaps healed. `debug_gaps` distinguishes "nothing held" from "nothing balance-shaped held". The xfail is replaced by a test asserting the true behaviour.

**The rule, sharpened:** *report the final state, never the sum of moments* — and when a measurement accuses the code of a defect, verify it against the artifact before writing it down.

### What still stands from that run

- The **doc_type replay bug** (mine) — real, fixed, and it parked 33 of 40 documents.
- The **brokerage unit-quantity defect** (`117.360` read as ambiguous money) — real, open, 3 statements.
- One genuine **reconciliation conflict**, −2,640.27, on a card statement.
- Two **identity conflicts** — expected and wanted, since the alias rulings were deliberately dropped.
- `rebuild` defaulting to oldest-first — still correct for a batch, just not a bug fix.

---

## The answer key, scored — and a sixth false alarm (2026-07-26)

`diff_rulings` re-judged **33 things Vishnu had told the old vault** against the rebuilt one. It reported three CONTRADICTIONS, under the heading it reserves for the single dangerous failure:

```
  READ THESE FIRST — Viva disagrees with you:
    northwind motors nw moto ppd id    you: category:transport     viva: auto loan
    brokerhouse svc llc moneyline ppd id  you: category:transfers     viva: brokerage account
    01 09 online domestic wire transfer  you: category:down payment  viva: property purchase
```

**None of the three is a disagreement.** Every pair is true at the same time: a Northwind ACH is transport spending *and* an auto loan; a brokerage MoneyLine is a transfer *and* evidence of the brokerage it transfers into; a wire is a down payment *and* a property purchase. A spending **category** and a structural **relationship** are different axes, and the scorer compared across them.

The giveaway was in its own output: the wire transfer appeared in the CONTRADICTED list **and** the ANTICIPATED list of the same report — two rulings on one subject, graded on two axes, reaching opposite verdicts.

The `missed` column was the same error mirrored: **12 of the 15 "misses" were ATM withdrawals**, plus cheques and peers. T9 forbids sending those to the commons, so enrichment never sees them and no implication can ever exist. Scoring them as misses grades the *design* — and specifically grades the product for correctly refusing to guess about a cash withdrawal.

**Fixed.** Two verdicts that are not grades — `incomparable` (different axes) and `unknowable` (a peer or an instrument) — both excluded from the denominator, so the score counts only what could have been anticipated. The peer/instrument test asks the **learned** `counterparty_kind` first and falls back to `is_shareable` only second: `is_shareable` is a substring list, it catches `zelle` and ` to ` but not `ATM WITHDRAWAL 03 15 MAIN ST`, and judging the tool by the weaker of the two tests is exactly how 12 withdrawals became misses. `tests/test_diff_rulings.py` (8 tests) holds all of it, including that a same-axis disagreement is **still** loudly CONTRADICTED.

### The meta-lesson, sixth occurrence

This is the same failure as the retracted Slice 1 defect, and the same *direction*: a measurement that **manufactured an accusation** against correct behaviour. Five of the six were an instrument reporting something it had not earned; two of the six accused working code of being broken.

The rule now has a second clause: *report the final state, never the sum of moments* — **and never grade one axis against another.** Whenever a scorer compares two labels, the first question is whether they answer the same question. "Transport" and "auto loan" do not.


### The corrected run, and what it honestly shows

```
  anticipated       2     6%
  proposed         13    39%
  incomparable      3     9%    a category vs a relationship — different axes
  unknowable        8    24%    a peer or instrument — correctly silent
  missed            7    21%
  CONTRADICTED      0     0%
```

**The empty CONTRADICTED column is the result worth having.** On the same axis, the rebuilt vault never confidently disagrees with the person who owns the money. For a product whose output is trust, that column mattering more than the others is the whole thesis in one line.

**2/22 is the uncomfortable number, and it should stay uncomfortable.** The vault reaches the author's exact conclusion twice and merely *raises the subject* thirteen times. There is a good argument that proposing is correct for houses, car loans and brokerage accounts — principle 7, deferential where it counts. There is also the fact that **the metric was designed expecting anticipation, returned 6%, and the designer then argued anticipation was the wrong target.** That is the most self-serving move available and it should not be settled by argument. It is settled by the author reading the 13 proposals and marking each one "I would have hit yes" or "no".

**A third flaw in the scorer, recorded and deliberately not fixed.** A warehouse club, a large online retailer, the tax authority and a tutoring service all sit under `missed` — but they are ordinary businesses, now `settled`, which the queue will never ask about at all. **A ruling the new design makes unnecessary is the best possible outcome, and it is being scored as a failure.** So the real picture is better than 2/22. It is left unfixed because three consecutive corrections to this instrument have each moved the number in the builder's favour, and that pattern is more informative than any of the three corrections. The fourth needs a colder eye.

**Overall judgement, stated plainly:** the architecture is right and the plumbing works on real money — the naive question the whole refactor existed to kill is gone, and 55% of the vault's money now arrives as an informed proposal. What remains unproven is **quality**: whether the proposals are ones a person would accept, and whether the categories are right at all (`poker` and `playing poker` both appear in the author's own answer key). That is the next thing to measure, and the builder should not be the sole grader of it.

---

## The cleanup, done (2026-07-26)

Everything above that was *findings* is now *fixed*. What changed, and the rule each change came from.

**Seven documents marked ⛔ HISTORICAL RECORD rather than deleted.** `discovery-plan`, `discovery-map-and-reversibility`, `agent-and-model-landscape`, `competitive-landscape`, `form-factor-and-stack`, `domain-model-vs-orchestration`, `v0-scope`. Each now opens with a banner naming what it was true of, why it is kept, and where to look for what is true now.

The test applied was Vishnu's: **"nothing a new reader would find confusing."** These seven failed it in three distinct ways — they lied about the present tense (*"we are deliberately in a discovery phase before writing product code"*, with 11,000 lines of product code in the repo), they were dated snapshots of an outside world that moves (*"as of July 2026"*, never updated again), or they reopened a door that an ADR has since closed.

Deletion was considered and rejected. A project whose entire argument is that **trust must be earned and provable** does not quietly erase its own reasoning; a stranger reading `discovery-map-and-reversibility.md` learns why eleven decisions were made before any code existed, which is worth more than the tidiness of removing it. But a document that cannot be dated by its reader is worse than no document, so the banner is doing the actual work.

**Sixteen status lines corrected.** Every one said `Draft` (or "next") about code that is built and running. The reason this matters is disproportionate to the effort: a status line is the first thing a reader trusts and the last thing anyone updates, which is the same shape as the prompt drift — *a discipline that depends on remembering.* The honest fix here is a habit, and the honest admission is that habits have failed twice in this repo already.

**The naming collision resolved: Slice 9b → Slice 6.8 — Counterparty implications.** The tier/implication work was committed under a number reserved for *Viva speaks*, the read direction. It is not Viva speaking; it is the question queue getting smarter, which is the 6.x family. The roadmap now carries a full 6.8 entry with the naming note, and commit messages before today still say 9b.

**Roadmap markers caught up** — 6.5, 6.7 and 9a marked built.

**The dead three-nature path deleted.** `Detail.jsx` still offered *spending / transfer / settlement* through `/api/rule-nature`, a month after the four majors replaced that vocabulary — and *"settlement"* was the option that had been **wired wrong from the start**: it meant debt repayment while the button read *"Something I now own"*, which is an asset. A person answering that button honestly recorded the opposite of what they meant.

Removing it exposed a live defect underneath: the surface unpacked each question's options by hand into `{merchant, major, descriptor}`, so a **movement-scoped** question — a cheque, an ATM withdrawal, a peer payment, all of the `unknown` tier — posted an undefined merchant and dropped its `movement_key`. The queue had decided the scope correctly and the page re-decided it wrongly. Options are now forwarded whole. Two contract tests hold both properties, and they check the *vocabulary*, not just the function name, so reintroducing three natures under a new name still fails.

**317 tests green.** The reading guide gained a *Historical record* section and a sharpened placement rule: **superseded means we changed our minds; historical means this was true then.** Neither is ever deleted.
