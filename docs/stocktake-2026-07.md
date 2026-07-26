# Stocktake — July 2026

**Status:** Audit · **Created:** 2026-07-25 · **Origin:** Vishnu: *"look at this project holistically — stale documents, stale code, mismatch between code and documents. Take stock, then discuss next steps."*

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

### Ordering decides the grade

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
