# Account Identity & Entity Resolution — a learning building block

**Status:** Partially implemented — signals, keys, the matcher, the ask and alias learning are built; the **Party** primitive and joint-account links are not (corrected 2026-08-14) · **Last updated:** 2026-08-14 · **Origin:** real-run finding — the same checking account arrived sometimes labelled by product name, sometimes by holder name, so a free-text `account_ref` produced different account ids and statements failed to stitch. The fix is not a smarter label; it is a *learning* identity block. Code: `viva/ledger/identity.py` (keys + name matching), `LedgerProjection.resolve` (the matcher), `viva/ingest/review.apply_identity_ruling` (ask-once-and-learn via `AccountAliasConfirmed`).
**Invariants touched:** T1 (provenance on every identity signal), T2 (a match is graded, never guessed), T4 (identity rulings are correction-events, append-only), T7 (honest about ambiguity), I5 (no country-shaped identity table — format specifics are data). Serves the moat: identity learned per-user, per-institution, forever.

## The multi-problem, and why we don't enumerate it in code

Account identity is open-ended: same name / different number, same number / different name, two names (joint), reissued numbers, and endless per-country / per-institution formats (US routing+account; India IFSC+account; varied masking). You cannot hardcode the cases — you'll never finish. So identity uses the system's universal shape:

> **Extract signals → produce a graded match → act automatically when confident, ask only when ambiguous → learn from the answer.**

That one shape absorbs every case, including unseen ones. The *intelligence we are adding is the learning*: the person confirms each **new kind** of ambiguity once, and the system resolves that pattern automatically ever after — for **all** account types, no bank-specific code.

## The building block (four reused blocks + two primitives)

1. **Signals, not a label.** Extract identity *signals* separately per statement: `account_number`, `institution`, `account_names[]` (a list — joint accounts have two), plus currency/jurisdiction. Each signal carries provenance (T1). **Amended 2026-08-01:** jurisdiction is not yet one of them. It is a plain field on the account with no source and no grade, defaulting to empty — *nobody has said* — rather than to a country nothing attested. Making it a graded attribute with the country tag derived is designed and unbuilt.
2. **A universal matcher (deterministic).** Score a new statement's signals against every known account and emit a **graded** verdict (reusing the grade block): number+institution+name agree → `corroborated` (same, automatic); partial agreement (name matches / number differs, number matches / name differs, a new second name) → ambiguous; nothing agrees → new account. The matcher is universal code; it scores whatever signals it is handed.
3. **Ambiguity → a Finding (reused).** The same Finding mechanism used for reconciliation surfaces the evidence and a plain question: *"matches your name but a different number — new account or same?"* / *"same number, different name — same account or someone else's?"* / *"two names — a joint account of A and B?"*
4. **The answer → a correction-event (reused, T4).** The person rules once; it is appended, never overwritten, and it **teaches the identity map**. This is the moat.
5. **Account primitive (seeded here); Party designed, unbuilt.** An **Account** carries an *identity set* (aliases: numbers, name variants, institution). **Amended 2026-08-14:** holder names are a flat list of strings on the account, and they do not accumulate — the list is *replaced* by the statement that opened the account, and `AccountOpened` is emitted at most once per account, so a second statement that first reveals a joint holder never records that name at all. There is no `Party` type, no `account → parties` link, and no joint-account representation anywhere in the ledger; "joint" survives only as a comment explaining why the list is a list.
6. **The identity map is a projection (reused pattern).** Confirmation events replay into `signal → account`. _(There is no `account → parties` map — see 5.)_ Known signals resolve automatically; only new/ambiguous ones ask. **Per-format specifics live in a registry (data, not code)** — how a given institution prints/masks a number is a profile row (like the doc-type registry and the normalization rules), so the code never branches per country.

**The same block, reused later:** merchants ("AMZN Mktp" = "Amazon"?), employers, and transfer counterparties are all *entity resolution* — the identical *signals → graded match → ask → learn* block. Accounts are just its first use.

---

## Account identity & entity resolution (learning)

**Blocks seeded:** Account (identity set) · the universal entity-resolution matcher · the identity-map projection · the per-format registry (seed). _(Party — names, joint — was listed here and was never planted.)_

**Open state:** account identity is a slug of a free-text `account_ref`, which the model renders inconsistently, so statements of the *same* account get *different* ids and don't stitch (gaps never fill); joint accounts and reissued numbers have no representation. *Proof:* two statements of one account with different `account_ref` labels post as two accounts and never fill each other's gap (a red test).

**Implementation:**
- Extract `account_number`, `institution`, `account_names[]` as dedicated fields (schema + prompt), each with provenance.
- Derive a **deterministic identity from the normalized account number** (institution-scoped) for the confident common case — this alone fixes the stitching bug.
- A **matcher** producing a graded verdict; **ambiguous** verdicts raise a **Finding** and are **held for confirmation** rather than guessed.
- The person's ruling is a **correction-event** that updates the **identity map** (a projection): add an alias, split into a new account, or link Parties (joint). Future matches of that pattern resolve automatically — **ask-once-and-learn, for every account type**.
- Account carries its identity set; `account_id_for` consults the identity map, not the raw label. _(Parties: designed, unbuilt.)_
- (Bundled, from the same finding) **sort transactions by value-time date** in the view — the log stays append-only knowledge-time; only the display is chronological (bitemporality made visible).

**Final state:** the same account is recognized across statements regardless of how it is labelled; ambiguous identity is asked once and learned forever, for all account types; backfilled statements read in date order. _(The joint-accounts-link-two-Parties clause was struck 2026-08-14 — unbuilt, see block 5.)_

**Done criteria / tests:** two statements of one account with different labels but the same number stitch into one chain; same name / different number raises a Finding and, once confirmed "new account," never asks again for that pattern; a confirmed alias auto-resolves on the next matching statement (no re-ask); transactions display in date order after a backfill; existing any-order ingestion tests stay green.

**Why now + future use:** it is the true fix for what blocked real stitching, and it is a prerequisite for the doc-type registry (multi-account). It seeds the Account primitive and the **entity-resolution block that later resolves merchants, employers, and transfer counterparties** — one learning mechanism, reused everywhere. The learning-from-corrections is the moat, turned on for identity from the first ambiguous statement.
