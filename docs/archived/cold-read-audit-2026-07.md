# What a Cold Read Found — the 2026-07-27 correctness audit

**Status:** ⛔ Historical — the 2026-07-27 correctness audit, complete · **Date:** 2026-07-27 · **Archived:** 2026-08-04 · **Invariants touched:** T1, T2, T4, T5, T8, T9, I2, M1, X2, X3

> ## ⛔ HISTORICAL RECORD — do not read this as current
>
> **A point-in-time line-level read of the four packages as they stood on 2026-07-27.** Findings A1 (the constant grade on every net-worth line), A2 (the locale comparison against a raw string) and C2 (the raw descriptor persisted unlinted) have all been fixed in code. Its test count is stale by roughly half, and every one of its code citations names `ledger/projection.py`, which became the package `ledger/projection/` in the 2026-08-01 decomposition — so no line reference in it resolves. Kept as the record of how the project audits itself, and of the one finding that survived it (`_today()` defined twice in `web/service.py`). Nothing in it describes how OrionViva works today.

## Why this doc, and what it is not

[stocktake-2026-07.md](stocktake-2026-07.md) was a *holistic* audit — what was stale, what was absent, what a real run proved. This is a narrower and duller thing: a **line-level correctness read** of all four packages by a reader arriving with no priors, holding each claim in the docs against the code that is supposed to implement it.

The method's value and its limit are the same fact: **no priors.** A cold reader has no memory of why a line is the way it is, so it notices a gap a builder's eye slides over — and equally, it can mistake a deliberate trade for an oversight. Every finding below therefore carries how it was established, and is marked **CONFIRMED** (the exact code path was read, and where possible executed) or **HAZARD** (structurally reachable, not observed on real data). Nothing here is reported as a defect on the strength of a plausible-sounding argument. That distinction is the whole discipline the stocktake's own rule demands, after six occasions when an instrument reported something untrue — including one that manufactured a defect in correct code.

**What this audit did not do**, stated so the record is honest:

- **It did not run the test suite.** The device's Python is 3.10; the packages require ≥3.11 and the checked-in `.venv` is a macOS build. The 453 test functions currently in the tree were read, never executed. (For the record: `docs/TODO.md` says 432 and the P2 note says 373 — both stale.)
- **It did not run anything against the real vault.** Every "this would produce" below is derived from the code, not observed in your numbers. Several findings can only be *sized* by a real run, and say so.
- **It did not read `web/static/`.** Findings about the surface contract are about what the server offers and what the queue emits, not about what the page does with them.

## The findings, ranked by what they threaten

Ranked the way the queue is meant to rank: by consequence, not by tidiness. Tier A can put a wrong number in front of a person. Tier B makes Viva ask badly. Tier C touches the log and the privacy boundary. Tier D is instruments measuring wrong. Tier E is hazard and cost.

---

### Tier A — the "never bluff a number" wall

#### A1 · Every net-worth line grades `corroborated`, so `provable` carries no information · CONFIRMED

`closing_balance_observed` (`ledger/events.py:208–219`) writes a body of `{account_id, amount, confirmed_by}`. There is no `grade` key, and neither producer supplies one (`ingest/pipeline.py:468`, `:719`). The projection stores `event.body.get("grade", "")` into `st.closings` (`ledger/projection.py:496–497`), so every entry carries `""`. Net worth then reads `grade=grade or CORROBORATED` (`ledger/networth.py:295`), and `NetWorthLine.provable` is exactly `self.grade == CORROBORATED` (`networth.py:73–78`).

Net effect: **the grade on every closing-derived net-worth line is a constant, not a measurement.** The `provable` subtotal is arithmetically identical to the total of all closing lines, and the D4 decision it implements — *"provable" is `corroborated`, reuse the grade ladder rather than inventing a second issued/asserted vocabulary* — is not actually wired to the ladder. Meanwhile `balance()` (`projection.py:1272–1310`) computes a real grade — `verified` / `corroborated` / `unverified` / `conflicted` — that net worth never consults.

There is a second-order conflict underneath it. `confirmed_by="human"` is documented (`events.py:213–215`) to grade `verified`, *above* `corroborated`. But `provable` admits only `corroborated`. If the grade were plumbed through as-is, a figure a person personally attested would be **excluded** from the provable subtotal while an unconfirmed one stayed in. Two orderings of the same ladder coexist (`_GRADE_RANK` at `projection.py:142` ranks verified highest; `provable` treats it as disqualifying), and the missing key is currently the only reason they never collide.

Against X2 — *uncertainty is visible, never decorative* — this is decoration. It is the highest-consequence finding here because net worth is the number the whole surface leads with.

#### A2 · `en-us` silently reads dates day-first while `en-US` reads month-first · CONFIRMED (executed)

`parse_amount` normalizes its locale before deciding anything: `locale.split("-")[0].lower()` (`core/vivacore/verify/normalize.py:175`). `parse_date` does not — it tests `locale in _MONTH_FIRST_LOCALES` against the raw string, where `_MONTH_FIRST_LOCALES = ("en-US", "en-PH")` (`normalize.py:249`, used at `:306–309`), and **any other truthy locale falls through to day-first**. Run on the device against `03/04/2025`:

```
'en-US'  ok  2025-03-04   ('locale en-US reads month-first',)
'en-us'  ok  2025-04-03   ('locale en-us reads day-first',)
'en_US'  ok  2025-04-03   ('locale en_US reads day-first',)
''       ambiguous  None  ()
```

The empty-locale case is correct and exemplary — I2 working exactly as designed, refusing rather than guessing. The other two are the failure: a *confident* answer, with an assumption string that reads as though a decision was made on evidence.

`env.py:50` validates `locale.split("-")[0].lower()` against `known_language_tags()`, so **`VIVA_LOCALE=en-us` passes validation and then day-firsts every ambiguous date in the vault.** This is the same shape as the incident `env.py:29–58` already records at length: a locale string that satisfies one layer and means something different in the next, whose visible symptom is downstream and whose investigation cost days. That docstring is the argument for fixing this one; the bug it describes was `"US"`, and this is its sibling.

Related, smaller, same module: `$-50.00` is rejected as unparseable while `-$50.00` parses, because sign handling (`:74–96`) runs before currency stripping (`:98–118`). Both forms appear on real statements.

#### A3 · A model-invented `share` reaches the ledger; only the eval counts it · CONFIRMED

`listen.py:210–213` states the rule in a comment: *"A share is only ever honoured if the PERSON stated it; a model-invented ratio is exactly the kind of confident wrong number this project exists to refuse."* No code implements it. `interpret` copies `leg["share"]` verbatim (`:213`), `propose` copies it into the Proposal (`:438`), `apply_proposal` passes `proposal.legs` straight through (`:519–523`), and `ruling_recorded` persists `"share": str(leg.get("share",""))` (`ledger/events.py:463`). Nothing compares the share against `said`.

The amount boundary next to it *is* structural — `ruling_recorded` raises on any leg carrying an `amount` (`events.py:460–461`), which is exactly the right pattern. The share simply never got the same treatment.

Worse, the honesty signal inverts: `unknown_split = interp.compound and not interp.shares_known` (`listen.py:457`). When the model *supplies* a fabricated ratio, `shares_known` becomes true and `unknown_split` goes **False** — so the summary stops saying "I can't tell how it splits, so I won't guess" precisely in the case where it should say it loudest.

`eval_listen` scores this as RUIN (`eval_listen.py:77–79`) and that is the right alarm. But an alarm is a measurement, not a guard, and the mortgage case in [from-your-words-to-the-ledger.md](../from-your-words-to-the-ledger.md) is exactly the one where a wrong ratio is both plausible and generalizing.

#### A4 · Tapping an answer on an unknown transaction can mint `Assets:Other:Unnamed` — and put it in your net worth · CONFIRMED

> **Closed 2026-08-01.** The unnamed path is refused before any event is written, and an answer that would open an account returns a proposal for an explicit yes. `confirm_accounts` is now named in `summary()`, so the fuzzy match is confirmed rather than silently bound.

Trace, all confirmed by reading each hop:

1. A tier-3 (genuinely unknown) NATURE question emits options whose args are **only** `{movement_key, major}` — no `merchant`, no `descriptor` (`questions.py:276–278`).
2. `POST /api/rule-major` → `rule_major` builds `account_hint = group or descriptor or merchant` = `""` (`web/service.py:171–172`).
3. `resolve_account(proj, "asset", "")`: the empty-hint shortcut covers only `MAJOR_EXPENSE` / `MAJOR_INCOME` (`listen.py:324–326`), so `asset` falls past it; both match loops require a truthy `want` and are skipped; the function returns `account_path("asset", _FALLBACK_GROUP, "Unnamed")` = **`Assets:Other:Unnamed`**, verdict `new` (`listen.py:339`, `_FALLBACK_GROUP = "Other"` at `:86`).
4. `rule_major` then calls `apply_proposal` **in the same request** (`service.py:181`) — no Proposal is ever returned to the person.
5. `apply_proposal` opens it with `origin=ASSERTED` (`listen.py:513–517`).
6. It becomes a row in `ruled_accounts()` with `paid` = the movement amount (`projection.py:867–896`), and `_asserted_lines` puts `Assets:` rows into the net-worth curve at cost (`networth.py:191–241`).

So tapping *"I still have it, in another form"* on an unidentified cheque silently creates an unnamed asserted asset **and adds it to net worth**, with no confirmation step. Two stated rules are crossed at once: `resolve_account`'s own docstring says creating a new account is *"the ONE thing this slice always confirms (D2)"* (`listen.py:310–316`), and X3 says irreversible-ish actions wait for an explicit yes *enforced in code, not prompts*. It is also precisely the account sprawl the same docstring warns about, arriving through the button path rather than the sentence path.

Related, same area: when `resolve_account` returns `ambiguous`, `propose` has **already bound the leg** to `match.account` (`listen.py:437`) and puts the candidate in `confirm_accounts` (`:441–442`) — a field `Proposal.summary()` never mentions (`:373–391`) and `apply_proposal` never reads. The match is a substring test (`want in tail or tail in want`, `:336`), so "Car" matches "Carvana Loan". The person confirms a sentence that does not mention the merge.

#### A5 · A holding's unit count is verified by nothing · CONFIRMED

`units_raw` is parsed by `parse_amount` — the **money** parser, with locale grouping rules and currency semantics — at `ingest/brokerage.py:279–281`. The snapshot reconciliation identity is `Σ(market_value) + cash = total` (`ingest/pipeline.py:629`). It never touches `units`. There is no unit price on `PositionFact`, so no `units × price ≈ market_value` cross-check is even available.

Consequence: **a mis-grouped unit count passes every check in the system silently.** `117.360` shares reads as `117.36` or `117360` depending on locale, and the document still reconciles, still posts, still grades `corroborated`. The figure then flows into `PositionObserved` and out to the surface.

This is *not* the "brokerage unit-quantity defect" — the stocktake correctly retracted that, and the real cause was four entry points defaulting the locale four ways, now fixed in `env.py`. But retracting the defect left the *shape* unexamined: the retraction established that the reading was right, not that a wrong reading would have been caught. Under T1 every figure carries a source and a verification grade; `units` carries a grade it did not earn.

---

### Tier B — the queue asks badly

Filed together because you flagged you are not yet happy with the queue's results on the real vault, and three of these produce exactly the kind of symptom that would read as "the questions are wrong" without pointing at a cause.

#### B1 · Merchant questions state a confident `0.00` for every non-expense counterparty · CONFIRMED

`_merchant_questions` accumulates `totals` from `proj.uncategorized_expenses()` (`questions.py:190`) but then iterates `proj.uncategorized_merchants()` with **no argument** (`:202`). Since 2026-07-25 that returns *every* uncategorized counterparty — employers, inflows, card payments — deliberately, and correctly, because the blind spot it fixed was real (`projection.py:1199–1206`). `expenses_only=True` exists for the narrow view and is not passed.

For any counterparty with no expense-shaped movements: `amount = Decimal("0")`, `cur = ""`, and the pack renders `say("merchant", …, money=_money(Decimal("0"), ""))`. Two consequences, both bad: a figure is **stated with confidence that is not the merchant's volume**, and the question sorts to the very bottom and into the tail. Your employer — the largest counterparty in the vault — asks about itself last, claiming zero.

Sizing this needs a real run: it is the count of uncategorized counterparties with no expense movements.

#### B2 · A corroboration question never goes silent when the document arrives · CONFIRMED

`_corroboration_questions` (`questions.py:320–359`) re-raises for every ruled account whose ruling names a `corroborates` document, **with no check of whether that document has since been captured**. Compare the expectation path, which does exactly this check deterministically — `_doc_type_seen` against `proj.captured_docs()` (`knowledge/__init__.py:67–71`) — and goes quiet.

The only escape is a decline, and the decline is stake-fingerprinted (`questions.py:422–426`), so it un-suppresses the moment another payment lands on that account. A mortgage therefore re-asks for the 1098 every month, forever, after you have given it the 1098. That contradicts the settled-→-silence rule the persona work established, and it is the failure mode most likely to make the queue feel like nagging.

Dead code alongside it: `if row.get("origin") != ASSERTED: continue` (`:334–335`) can never fire, because `ruled_accounts()` hard-codes `"origin": ASSERTED` (`projection.py:872`). Harmless, but it reads as a guard and is not one.

#### B3 · Ranking and the tail total add across currencies · CONFIRMED

`qs.sort(key=lambda q: (-q.amount, q.id))` (`questions.py:429`) compares raw `Decimal` magnitudes regardless of currency, and the tail reports `str(sum(q.amount for q in rest))` with **no currency at all** (`:434–435`).

`answer.py:176–183` refuses to do this in the answer path, explicitly — *"I don't convert between them"* — and `net_worth.by_currency()` refuses a converted grand total for the same reason (`networth.py:106–112`). The queue does it in two places. In a single-currency vault it is invisible, which is how it survives to the first multi-currency one; and the I-invariants say that day is a design target, not an edge case.

#### B4 · Three option actions have no endpoint, and one is missing a required field · CONFIRMED

Actions the queue emits (`questions.py`) against routes the server has (`web/server.py:73–174`):

| action | emitted at | route |
|---|---|---|
| `confirm_identity` | `:126`, `:128` | ✅ |
| `confirm_transfer` / `reject_transfer` | `:174`, `:176` | ✅ |
| `rule_major` | `:276`, `:301`, `:305` | ✅ |
| `upload` | `:354`, `:380` | ⚠️ exists, but takes raw bytes + `X-Filename` and ignores `{account, document}` |
| `assign_merchant` | `:215` | ⚠️ route requires `d["category"]` (`server.py:152`); args carry only `{merchant}` → `KeyError` → 400 |
| `review` | `:131`, `:146` | ❌ no route |
| `dismiss` | `:356`, `:382` | ❌ no route |

`dismiss` matters most: it is the "Not right now" button on corroboration and expectation questions — the two kinds most in need of it, given B2 — and the actual decline path is `POST /api/decline` keyed on `question_id`, not on `{account}`. Unless the page translates, **the 6.10 decline event is unreachable from the two question kinds that need it**.

#### B5 · A held non-balance document ranks at zero · CONFIRMED

`_held_questions` builds `other_holds` questions with `amount=Decimal("0")` (`questions.py:136–148`), two lines below a comment insisting *"a document we're sitting on must never be invisible"*. With ten money questions open, a held pay stub is summarized into the tail. Not invisible — but not surfaced either, which is a distinction the comment was written to deny.

---

### Tier C — the log and the boundary

#### C1 · The store appends onto a chain it never verified · CONFIRMED

`EventStore.__init__` walks `_iter_raw()` and takes the last `record_hash` (`ledger/store.py:62–68`) **without checking `prev_hash` continuity or recomputing any hash**. `verify_chain` exists (`:155`) and is correct — it recomputes without needing the key, which is a nice property — but `open()` (`:72`) never calls it.

So a tampered or truncated ledger opens cleanly and accepts new appends chained onto the bad tail. The break surfaces later, on the next `events()` read, by which point good events sit on top of it. Against T4 — *state is a projection of the append-only, anchored log* — the anchor is checked on read and not on write, which is the inverse of where a chain is cheap to defend. Whether that is a deliberate cost trade is exactly the kind of thing a cold reader cannot tell; it is flagged as a question, not an accusation.

#### C2 · What crosses the T9 boundary is the raw descriptor, not a linted example · CONFIRMED

`enrich_merchants`'s docstring says what T9 requires: *"a normalized key and a **linted** example — nothing about amounts, dates, or accounts crosses"* (`ingest/categorize.py:200–203`). The amounts/dates/accounts half holds; I checked, nothing numeric crosses. The linted half does not exist. `row["example"] = m.description` — the **raw bank descriptor, verbatim** (`ledger/projection.py:1216–1217`) — and `categorize.py:211–214` passes it straight to `catalog.submit`.

`is_shareable` gates *whether* a merchant crosses, on peer markers, and it keeps Zelle/Venmo descriptors out. It does not redact what does cross. So store numbers, city and state, and any order-id fragment that survived normalization go to the model provider inside the example.

Then it persists: `Catalog._save()` writes the **`pending` queue** — raw examples, unenriched — into the plain JSON at `~/.viva/merchant-catalog.json` (`merchantcore/catalog.py:96–102`). `export()` correctly excludes pending and filters by `is_shareable` (`:74–78`); the on-disk file does neither. That file is unencrypted **by decision** because it is supposed to hold only impersonal knowledge, and it is now **shared across vaults by decision** (`VIVA_CATALOG`, 2026-07-26). Anything submitted but never enriched — a failed chunk, an interrupted run — stays there in plaintext.

Against T9 and T5, the boundary is enforced at the *export* edge and asserted by convention everywhere else; `merchantcore` itself has no structural guard that a submitted example is impersonal (`submit` and `add` do not lint). That is the same shape as the `amount` boundary in A3 — the rule is written, the type does not carry it.

---

### Tier D — the instruments

The stocktake's rule: *graceful degradation belongs in the product, never in the instrument that measures it.* These are instruments.

#### D1 · The bench records `prompt_version`s that do not resolve — the exact T8 failure `promptstore` exists to prevent · CONFIRMED (executed)

`PROMPT_VERSIONS = {"image": "p2", "text": "t1", "text+image": "ti1"}` (`core/vivacore/prompts.py:26–30`), and those ids are written into every run record. Executed on the device:

```
t1  FAILS: PromptNotFound
ti1 FAILS: PromptNotFound
p2  FAILS: PromptNotFound
```

The files are `header-text-t1.txt`, `header-textimage-ti1.txt`, `extract-image-p2.txt` — the ids never match the filenames. Worse, the text-mode prompt is *composed* at call time from three files, splicing the task body out of `extract-image-p2.txt` by searching for a literal marker (`prompts.py:75–76`), so **no single id could ever resolve to it.** And `bench/bench-data/runs/runs.jsonl` on disk records 12 × `t1`, 12 × `ti1`, 12 × `p2`, and 4 × `p1` — a version whose id is no longer even in the table.

This is the enrich-v2 failure from [prompts-as-files.md](../prompts-as-files.md), one package over. The product already solved it properly: `prompt_library` records the self-describing composite `extract:<base>+<frag>` and `resolve()` reverses it, deliberately never falling back to current text (`ingest/prompt_library.py:59–68`). The bench simply never received that fix. Given that the bench's whole output is comparisons that are only meaningful *within* a prompt version (`prompts.py:3–4`), the recorded findings currently cannot be tied back to the text that produced them.

#### D2 · `_system_metrics` does not compare values across runs · CONFIRMED

The docstring says *"a claim is 'system-accepted' if the majority of runs agree on the same value"* (`bench/vivabench/score.py:247–252`). The code never compares values — it counts whether a label appeared in ≥ half the runs and then splits on whether the *key* says those runs were right (`:262–270`). The two branches are exhaustive over that condition, so every label present in ≥ half the runs is accepted regardless, and there is a literal `if …: pass` at `:266–267` marking the unfinished half.

So `system_confidently_wrong` is a re-labelling of majority accuracy, not a pipeline metric. In fairness the docstring does say *"A faithful version also folds in arithmetic checks; this is the agreement core"* — it is honestly self-labelled as approximate. The finding is that the headline table in `findings.md` is built on it, and the label on the column does not carry the caveat that the docstring does.

Alongside: `verify/arithmetic.py` is fully implemented and tested and **no bench code calls it**, so `KeyEntry.verified_by="arithmetic"` is documented (`claims.py:124`) and never produced. "Verified coverage" is currently pure inter-run agreement — confidence from self-consistency, which `report.py:86–88` itself argues against.

#### D3 · ECE is floored by the bin midpoint · CONFIRMED

`_calibration` scores each bin against `CalibrationBin.stated`, which is `(lo + hi) / 2` (`score.py:147–149`, used at `:175–191`). A model that always states 0.9 and is always right lands in the 0.8–1.0 bin and scores `|1.0 − 0.9| = 0.10` — perfectly calibrated, graded 0.10. Using the mean *stated* confidence within each bin instead of the midpoint removes the floor. Given that calibration is the thesis, a metric that cannot distinguish a well-calibrated model from the bin geometry is worth fixing before the harness has a real subject.

#### D4 · `reset_categorization` prints arithmetic that does not add up · CONFIRMED

`dropped = sum(counts_in[t] for t in CATEGORIZATION_EVENTS)` counts every *input* event of those types, but human-authored rulings were **kept** (`keep_human=True` by default, `reset_categorization.py:118`). `kept = sum(counts_out.values())`. So the printed `N in → K kept, D dropped` (`:191–193`) can satisfy `K + D > N`. The correct expression is `sum(counts_in[t] - counts_out.get(t, 0) for t in CATEGORIZATION_EVENTS)`.

Small, but this is a tool whose entire stated value is *"Verifiable — it prints a per-type before/after count."* The count is the product.

#### D5 · `check_brokerage_identity` is not re-exported · CONFIRMED

`core/vivacore/verify/__init__.py:24–25` imports three of the four checks. `from vivacore.verify import check_brokerage_identity` raises. One line.

---

### Tier E — hazards and cost

#### E1 · Two pay stubs can decompose the same deposit · HAZARD

`_net_pay_deposit` matches a depository inflow of equal amount, unlinked, within 10 days of the pay date (`ingest/pipeline.py:511–520`) — and **nothing marks the deposit as consumed**. `post_paystub` posts the decomposition without referencing the deposit at all (`:564`). With weekly pay and a constant net, stub B (pay_date + 7) matches the same deposit stub A already used, and gross income is booked twice. Bi-weekly is safe only because 14 > 10, which is an accident of the constant rather than a property of the code.

Not observed — it depends on your pay cadence, and a real run would settle it in one query. The sibling case is worth noting too: the matcher requires `not m.linked`, so if `link_transfers` links the payroll deposit first, the stub parks at `AWAITING` and `heal_paystubs` can never find it again. Two overlays contend for one movement with no arbitration.

#### E2 · Cross-document corroboration evaluates uniqueness over a truncated candidate list · HAZARD

`_subsets_summing_to` does `n = min(len(items), 12)` and then `items[:n]` (`ingest/transfers.py:260–262`), silently. The caller acts **only if there is exactly one subset** (`:246–249`), and that uniqueness is the entire safety argument for auto-applying a correction at `corroborated` with no human in the loop. A 13th candidate that would have made the set ambiguous is invisible, so a non-unique explanation can be accepted as decisive.

The candidate list is pre-filtered to movements that distinctively name the account, so it is genuinely small in practice — the comment is right. But *usually small* and *bounded* are different claims, and this is the one place in the system where a silent truncation can produce a wrong **number** rather than a hold. At minimum it should log when it truncates; the stocktake's rule about no silent caps applies with full force here.

#### E3 · `apply_ruling` re-hydrates a client-supplied Proposal with no revalidation · HAZARD

`Proposal(**fields)` straight from the POST body (`web/service.py:245–249`): legs, `new_accounts`, `amount`, `currency`, `settles`, even `prompt_version` are all caller-controlled and go directly to `apply_proposal`. Compare `decline_question` twenty lines away, which deliberately re-derives the stake **server-side** *"so a stale page cannot pin the wrong fingerprint"* (`:550–552`). Localhost-only blunts the security angle; it does nothing about the stale-page angle, which is the one the neighbouring function was written to defend against.

Related sizing bug in the same path: `Proposal.settles` counts *all* movements matching the merchant, both directions (`listen.py:444–447`), while `amount` is the single movement's amount from the card. `summary()` then renders something of the shape *"I'd record &lt;one payment's amount&gt; across N payments"* — a wrong figure in the exact sentence the confirmation rests on.

#### E4 · `movements()` is memoized nowhere, and the net-worth curve rebuilds it per point · PERF, CONFIRMED

`movements()` (`projection.py:625`) re-sorts every account's lines and re-runs `_decide_nature` per movement on every call — and `_decide_nature` calls `normalize_merchant` up to three times per movement. There are ~25 call sites, 11 of them inside `projection.py` itself. `networth.series()` (`networth.py:310`) evaluates one point per change date, and each point calls `change_dates()` **and** `_asserted_lines()`, each of which walks `movements()` in full: roughly 2–3 complete movement rebuilds per point on the curve, so O(dates × movements) with heavy per-movement work.

`Ledger` was built to eliminate redundant event *replays* and does. Redundant *derivations* were never addressed. This is also the precondition for splitting `projection.py`: any split has to make `movements()` a materialized artifact with an explicit dependency set first, or the modules end up passing the whole projection to each other — which `networth` already does, reaching into `proj._state()` (`networth.py:254`, `:275`), a `setdefault`-based accessor that therefore *mutates* `_acct` from a read path.

#### E5 · `_today()` is defined twice in one module, with different formats · CONFIRMED

`web/service.py:252` returns a bare `2026-07-27`; `:580` returns `2026-07-27T20:39:00Z`. The second wins at import for **all** callers, so `rule_major`, `apply_ruling`, `decline_question` and `upload` all stamp full timestamps while `questions.py:404–405` derives `as_of` as a bare date. The projection's `as_of` horizon comparison is lexical (`projection.py:373`), so `"2026-03-31T00:00:00Z" > "2026-03-31"` — an event dated *on* the horizon is excluded. Delete one and pick a format deliberately.

---

## Impact pass — what this changes in the existing record

- **[net-worth.md](../net-worth.md)** — D3 ("two kinds of unknown") and D4 ("reuse the grade ladder") are both stated correctly and **A1 shows D4 is not implemented**. The doc should carry a note that the grade is currently constant, pending the fix.
- **[design-invariants.md](../design-invariants.md)** — no new invariant is proposed. But T9's wording *"a normalized merchant key + a privacy-linted example"* is currently aspirational (C2); either the code gains a linter or the invariant should say what actually crosses.
- **[prompts-as-files.md](../prompts-as-files.md)** — records the discipline and the enrich-v2 recovery. D1 is a second live instance, in `bench`, which the two tests that made recurrence a build failure do not cover (they guard the product's prompt library, not the bench's `PROMPT_VERSIONS` table). Worth an amendment: the rule held where it was tested and drifted where it was not, which is the doc's own thesis.
- **[the-question-queue.md](../the-question-queue.md)** — B1–B5 are all in the queue's contract rather than its concept. The concept holds: I found no model call where a template was promised, and the deterministic-text rule is clean throughout `questions.py`. The leaks are *values*, not phrasing.
- **[from-your-words-to-the-ledger.md](../from-your-words-to-the-ledger.md)** — A3 and A4 are both gaps between what the doc settles (D2, the share rule) and what the code enforces. The `amount` boundary it describes *is* structural and works.
- **[stocktake-2026-07.md](stocktake-2026-07.md)** — A5 refines rather than reopens the retracted unit-quantity defect: the retraction was correct, and it established that the reading was right, not that a wrong one would be caught.
- **[honest-aggregates-and-the-learning-loop.md](../honest-aggregates-and-the-learning-loop.md)** — B3 is the same class of error the doc names: two systems describing one fact, and the aggregate listening to only one. Here it is currency.
- **`docs/TODO.md`** — the test count (432 / 373) is stale; the tree holds **453** test functions.

## What held

Worth recording, because an audit that only lists failures misrepresents the thing it audited.

- **No per-institution parsers.** Checked by grep across all of `ingest/`: the only institution string anywhere is `"chase"` in the transfer stopword list, as a *non*-distinctive token. Fidelity and SPAXX appear in a comment. The registry really is data rows plus composed prompt fragments.
- **No keyword classifiers.** The nine substring lists are gone and the deletions are commented with why (`merchantcore/normalize.py:61–69`, `projection.py:192–198`). `is_shareable` and `_CASH_MARKERS` are the two survivors, both bounded so that being wrong causes a hold, never a mis-post.
- **The amount boundary is a type, not a prompt.** `ruling_recorded` raises on a leg carrying an amount. That is the pattern the share needs.
- **Arithmetic refuses floats.** `_as_decimal` raises a `TypeError` naming T2 by name.
- **Ambiguity is refused, not guessed.** The empty-locale case in A2's own transcript; `parse_date` never inventing a year; `find_corroborating_legs` returning `[]` unless the subset is unique; `unrealized_gain` returning `None` rather than 0 when no cost basis exists; `confidently_wrong` being `None` rather than 0 when nothing was measured.
- **`eval_listen` refusing to average away a broken run** (`BROKEN` never scored) is the harness declining to commit the error it exists to catch — the single best piece of instrument discipline in the tree.
- **The reversal in [the-surface-cards.md](../the-surface-cards.md)** — dropping a compiled bundle because a stale artifact can serve last hour's product with no error — is the process working, and it is the reasoning that should be pointed at D1.
