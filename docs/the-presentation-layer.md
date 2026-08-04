# The Presentation Layer

**Status:** BUILT, and **explicitly a debug surface, not the product's presentation layer** (Vishnu, 2026-07-25) · **Last updated:** 2026-07-25

> **This build is throwaway.** It exists so the author can see and exercise what the engine knows while building — nothing more. The real presentation layer is a **design conversation we have not had**: information architecture, what a person actually opens this for, the persona's voice, progressive disclosure done properly, mobile. Do not treat the current page as a decided design, and do not accumulate features on it. The rulings below (hybrid answering, implicit categories, React+Vite) were right *for a debug tool* and are all re-openable when the real thing is designed. What should survive is the **contract tests** — every endpoint called, every field rendered or deliberately dropped — because they are what caught the engine outrunning the surface in the first place. · **Block seeded:** the surface as a first-class layer — the ranked question queue as the page's spine, and every figure the engine knows finally visible.

**Invariants touched:** **X2 (uncertainty visible, never decorative — the honesty signals must appear on the page, not just in the payload)** · X1 (target user: "can install an app" — a build step is a *developer* concern, so it is compatible with X1 **only while the shipped artifact stays static and offline**: no runtime CDN, no toolchain on the user's machine) · X3 (irreversible actions wait for an explicit yes) · T1 (every figure taps through to its source) · **the valuation-class rule (a measured holding always shows its as-of date; a composed total that mixes vintages says so)** · principle 5 (serve, don't overwhelm — progressive disclosure, the page earns its panels) · principle 6 (you direct the pace).

---

## Why now

The engine has outrun the surface, and it is now measurable. The server exposes **four endpoints the page never calls** — `/api/questions` and `/api/rule-nature` (the question queue), plus `/api/categorize` and `/api/assign-category`, which have been reachable only by `curl` **since the category overlay shipped**. The overview payload carries **seven fields the page ignores**: `positions` (all of positions and investments — holdings are invisible), `provisional_spending` and `excluded_from_spending` (movement nature's honesty signals), `other_holds` (a held brokerage statement — its invisibility was fixed in the *data* and remains on screen), `spending_by_subcategory`, `uncategorized_count`, `nature`.

So roughly three slices' output has no surface at all, and the question queue's whole point — *one front door* — currently exists only in a CLI. A product whose promise is "open it and it's handled" cannot keep its best work in JSON.

## The spine

Today: total → four conditional review cards → accounts → upload. Proposed, honoring the experience-vision calls already made (**dashboard-first**, **speak only when spoken to** — findings become quiet state, never notifications, and **progressive disclosure** — the page is empty on day one and earns each panel):

1. **The picture** — total, coverage, and the honesty line (what's provisional, what was excluded and why).
2. **What Viva needs** — the ranked queue, with the answer inline. Replaces the four review cards.
3. **Your money** — accounts, and for an investment account its holdings with as-of dates.
4. **Where it went** — spending by category, expandable to subcategory.
5. **Add documents.**

## Decisions — RULED (Vishnu, 2026-07-25)

- **D1 → hybrid.** One-tap answers (transfer, identity, nature, merchant) inline in the ranked list; anything needing context (a held statement, a merchant's transactions, two sides of a transfer) opens a **focused detail view**. Cheap once routing exists — which D4 provides. Rationale: the highest-stakes decision shouldn't be visually squashed between quick ones, and clearing ten small items shouldn't cost ten page loads.
- **D2 → implicit storage, explicit affordance.** The picker offers the 16 primaries (suggestions) **plus every category you've already used** (implicit) **plus "add your own"**. No `CategoryDefined` event — a category exists by being used, consistent with *abstract the write side late*. **Known wrinkle, accepted:** a category named but not yet applied does not survive a reload. If that friction shows up in real use, it is the signal to make categories first-class (the generic scoped ruling, since arrived).
- **D3 → confirmed.** Peer descriptors (`scope: "one"`) get per-transaction categorization, finally wiring `/api/categorize` and `/api/assign-category`, dead since the category overlay shipped.
- **D4 → React + Vite, static output.** _(Reversed 2026-07-26 by [the-surface-cards.md](the-surface-cards.md): there is no build step and no toolchain; `web/static/app.js` is served as written. The reasoning below is kept as the record of what was decided and on what grounds.)_ Chosen over my recommendation of a zero-dependency file split, and the reasoning is sound: the repo is employer-facing and React is the strongest legible signal, it has the largest ecosystem, and it is where AI-written code is most reliable — which matters on a project where "the AI drifts and the human catches it" is a documented failure mode. **Binding constraints:** the build emits **static files served by the existing stdlib server**; **no runtime CDN fetches** (local-first would break); lockfile committed; and **zero new dependencies in `core/` or `product/`** — the ledger and verification path stay dependency-free. The toolchain is a UI-only concern.

## The original options (kept for the record)

**D1 — How the queue carries its answers.** Each retired card had an affordance: a correction form (held statement), Same/New (identity), confirm/reject (transfer), a category select (merchant). Options: **(a) inline** — every question answerable in place, richest but most code, and the held-statement correction form is genuinely complex; **(b) inline for the one-tap kinds** (identity, transfer, merchant, nature) **and an expandable detail for reconciliation**, which needs the statement's context. _My lean: (b)._ It keeps the queue scannable and gives the one genuinely complex case the room it needs.

**D2 — Custom categories: implicit or first-class?** Still open from [local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md), and this slice forces it because the picker needs a "+ New category". **(a) Implicit** — any string used in a ruling *is* a category; the picker offers the 16 primaries plus every category you've already used. No new event, consistent with *abstract the write side late*. **(b) First-class** — a `CategoryDefined` event so categories can be listed, renamed, coloured. _My lean: (a) now, (b) with the generic scoped ruling if renaming becomes a real want._

**D3 — Peer descriptors get per-transaction categorization.** This is what `/api/categorize` and `/api/assign-category` were built for and never wired. A peer question (`scope: "one"`) offers a per-transaction picker rather than "categorize everywhere" — so one Zelle can be a gift and the next a loan repayment. _No real fork; confirming it lands here._

**D4 — The stack.** Today: one self-contained `index.html` (~320 lines), stdlib server, zero dependencies. This slice roughly doubles it. Options: **(a) keep one file**; **(b) split into `index.html` + `app.js` + `app.css`, still zero-dependency, still no build step**, served by the same stdlib server; **(c) adopt a framework/build step**. _My lean: (b)._ (c) is against the grain of this project — supply-chain minimalism is a stated instinct (the inline-DCO decision), every dependency is a trust liability in a money app, and a build step breaks "works offline, no toolchain". But one 700-line file is not a virtue either.

## What gets built

- **The honesty line.** The spending figure carries a quiet "…and X I'm not certain about", expanding to `excluded_from_spending` grouped by the rung that excluded it (linked / own account / your ruling / a category hint). Uncertainty visible, not alarming (X2).
- **Holdings.** An investment account shows its positions — units, value, **as-of date**, and the mixed-vintage warning when a composed total rests on measurements from different dates. Unrealized gain is shown as a derived as-of view, never as a ledger figure (M1).
- **The queue** replaces the four cards, ranked, with the tail summarized ("plus N smaller items worth X") rather than hidden. **Amended 2026-08-01:** the payload also carries a `pending` count, and `/api/pending` returns the questions behind it — a set-aside question is opened, never pushed. An answer that would open an account now returns a proposal to confirm rather than applying in the same request. How pending *looks* is deliberately still this document's conversation to have.
- **Held documents that have no fix-it flow yet** (pay stub, brokerage) appear as questions saying what they are and why they're waiting — currently `other_holds` renders nowhere.
- **Subcategory** as an expansion of the spending breakdown.

## Done criteria / tests

The page itself has no unit tests today and this slice does not pretend otherwise: **the service layer is what gets tested**, and the page is verified by hand against a real vault. So —

- Every endpoint the server exposes is called by the page, and every overview field is either rendered or deliberately dropped (a test asserts the payload's keys are all consumed, so this gap cannot silently reopen).
- Service tests for the new payloads; existing `test_web.py` stays green.
- A held brokerage statement appears on the page (the invisibility bug, closed in the UI as well as the data).
- An investment account shows holdings with as-of dates, and a mixed-vintage total says so.
- Answering each question kind from the page routes to the existing writer and the question disappears.
- The page still works with an empty vault (progressive disclosure) and with no model configured.

## Deferred

Chat/NL entry (Slice 9 — the surface stays dashboard-first). Charts and trends (net worth comes first). Tap-to-source region highlighting on the document image (T1's full payoff; the provenance is carried today but not rendered as a crop). Mobile-specific layout. Any framework.
