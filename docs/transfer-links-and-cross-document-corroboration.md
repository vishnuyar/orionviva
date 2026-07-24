# Transfer Links & Cross-Document Corroboration — one movement, two witnesses

**Status:** Implemented (Slice 3, core) · **Last updated:** 2026-07-24 · **Origin:** Slice 2 lets a person hold several of their own accounts. The moment they do, an internal payment (checking → their own card) appears on *two* statements, so "how much did I spend" counts the same money twice. Real ingests surfaced a second, deeper case: a statement whose reconciliation gap is *exactly* a movement the counterparty document already attests (a card missing a payment that the checking statement plainly shows). Both are the same recognition — **two legs, one movement** — so this slice builds them together.

**Invariants touched:** T1 (every posting carries provenance — a link cites *both* source lines; a corroborated leg cites the issuer that actually attested it), T2 (verification: cross-document corroboration is a *second, independent* reconciliation identity, run by deterministic code), T4 (a link/correction is an append-only event, reversible, nothing overwritten). Principle 2 (**never bluff a number** — a gap is never closed on a non-decisive link) and principle 7 (autonomous where safe, deferential where it counts) are the load-bearing constraints. This is the verification layer — "the actual hard problem" — getting a new, cheap, strong rung.

## The architecture (decisions locked with Vishnu, 2026-07-24)

**1. Internal own-account transfers only.** The data-model spike found transfer-linking is really two jobs: **own-account netting** (both accounts are yours → the movement isn't spending) and **external Party attribution** (a mortgage servicer, a peer, an employer → a real outflow to someone else). This slice does the first — the load-bearing spending-accuracy fix. External counterparties ride the *same* entity-resolution block later (categorization / Party, S5).

**2. Netting is minimal here; the economic sign waits for S7.** Our postings sign each movement by its **effect on that account's printed balance** (Slice 2 / A1) — locally correct for reconciliation, but *not* globally additive across asset and liability (a checking outflow and a card payment can both read `-2400`). Making a transfer pair *self-net to zero* needs a kind-aware economic sign, and that is Slice 7's job. So here, `Transfers` is an **exclusion category**, not a self-balancing clearing account: both legs are recategorized out of Uncategorized into `Transfers`, and every aggregate (spending, external cash flow) **excludes** `Transfers`. The link additionally asserts the two legs are equal magnitude. That fully delivers "spending excludes moving your own money" without the sign machinery; the self-netting upgrade arrives with S7.

**3. Auto-link on decisive evidence; ask otherwise.** A wrong link double-counts or hides real spending, so autonomy is earned by evidence (principle 7). A **decisive** match auto-links (grade `corroborated`); anything softer surfaces as a **Finding** to confirm (grade `suggested` → `verified` on confirmation). A confirmed pattern is **learned**, so the next one of its kind auto-links — the ask-once-then-learn spine, reused.

**4. A transfer link doubles as a cross-document reconciliation witness.** This is the capability that makes the slice more than netting. When a statement fails to reconcile internally and its gap is *exactly* an unmatched movement on another of the user's own accounts, the counterparty's line **supplies the leg this document is missing** — closing the gap *and* completing the transfer pair. It is a new, cheap, strong rung in the repair ladder (see below). Gated by the same decisiveness as any link.

**5. v1 auto-links only when both legs are already ingested own accounts.** That is the decisive case (both sides are accounts we hold, exact amount, tight date, description hint). A transfer that *names* a destination we haven't ingested ("Payment to card …9876") cannot be auto-confirmed as internal — it becomes a Finding that doubles as the own-account question ("is …9876 yours?"), answered once and learned.

**6. A link references a stable movement key, not an event id.** Reingest mints new event ids (Slice 2), so a link points at `doc_id + a within-document movement fingerprint` (date + amount + normalized description + occurrence index) so it survives re-reads and heals rather than dangles. _Known risk: a re-read that reorders or merges lines can move a fingerprint; revisit if reingest-stability bites._

## Representation — an overlay, never a re-posting

Each leg must stay attached to its own statement, because **per-statement reconciliation still has to hold** — we cannot merge two statements' transactions into one balanced posting-set without breaking the gate that makes any of it trustworthy. So a transfer is an **overlay**:

- A **`TransferLinked`** event references the two movement keys, and carries the link's own **grade** and **evidence** (which signals fired). It is a graded *fact about a relationship*, exactly as the data model says (a transfer link is a graded fact with its own confidence and evidence).
- The two Uncategorized counter-legs are **recategorized** (a `CorrectionApplied`-style event) from `Expenses:Uncategorized` / `Income:Uncategorized` into a shared **`Transfers`** category. Aggregates exclude `Transfers`.
- **Reversible:** unlink is another event. Nothing is overwritten (T4); the full history stays replayable.

The projection gains a small candidate **index** (movements bucketed by amount and date) so matching is cheap, not O(n²) — the "watch performance" practice applied from the start.

## Detection — bipartite matching, calibrated against false positives

Signals for "these two movements are one internal transfer":

- **exact amount** (to the cent);
- **date proximity** (same day or a few days — a card payment often posts a day or two after the checking debit);
- **opposite direction** (one reduces an asset's balance; the other reduces a liability's owed or raises another asset);
- **description hints** ("Payment to Card", "Transfer to Savings", "ONLINE PAYMENT THANK YOU", a counterparty naming an own-account label/number);
- **both accounts are the user's own.**

Two unrelated $50 movements on the same day are the trap, so **decisive = exact amount + tight date + description/own-account evidence that pins the pair uniquely.** Decisive → auto-link (`corroborated`). Ambiguous (more than one candidate, or amount-only) → a **Finding** citing the candidates, `suggested`, awaiting a human. On confirmation, the ruling is learned as a pattern (keyed on the recurring description/counterparty), so "payments to …9876 are always my Amex" auto-links thereafter — the same *signals → graded match → ask → learn* block that Slice 1.5 built for account identity, pointed at transfer counterparties.

## Cross-document corroboration — the reconciliation witness

The repair ladder today (verification-findings-and-correction.md) is: **deterministic diagnosis → bounded re-read (a model call) → ask the human.** This slice inserts a rung *between* diagnosis and re-read, because it is both cheaper and stronger than a re-read:

> **Cross-document corroboration.** If a statement does not reconcile internally, and its gap **exactly equals an unmatched movement on another of the user's own accounts** that forms a *decisive* transfer partner, supply the missing leg from that counterparty. It closes the gap with **no model call** (cheaper than a re-read) and **two independent issuers** attesting the movement (stronger than one).

Concretely — the live case that motivated it: a credit-card statement is missing a payment, so it fails to reconcile by exactly the payment amount; the checking statement plainly shows that payment "to card." The checking line supplies the card's missing leg. The card now reconciles, and the two lines are the transfer pair.

Discipline on this rung:

- **Gated by decisiveness.** A gap closed on a *guessed* link is precisely the confident-but-wrong figure the project cannot survive (principle 2). Auto-close only on a decisive partner; anything softer is a Finding, not a silent repair. Cross-document evidence *raises* confidence — it never lowers the bar for closing a gap.
- **Provenance is honest.** The supplied leg's provenance points at the **counterparty document**, not this one, with a note that this statement did not state it — the other issuer did, and they agree. Grade `corroborated` (two independent observations agree). Marked this way it is a *strength*; merged silently it would be a lie about where the number came from.
- **Don't let the crutch hide the limp** (Taleb / fragility). Even when corroboration closes the gap, record that the primary read was **incomplete** (the claims layer already keeps the raw read; a marker notes "this leg was supplied by corroboration, not read from this document"). Reconciliation succeeds *and* the flywheel still learns the model has a recall problem to fix. We never want a silent crutch that lets extraction quietly rot.
- **Heals both ways.** The card may be gap-held first and rescued when the checking statement arrives, or the checking may already be present when the card lands. Same order-independence as `heal_gaps`.

Why this matters beyond robustness: "the other party vouches" is cross-**issuer** corroboration — two independent institutions attesting the same movement. That is the exact trust primitive the endgame is built on (a fact provable because independent parties agree, immune to any single source being wrong). It appearing this early, for free, out of transfer-linking, is the thesis working.

## Own-account membership — a learned set

Netting is only correct if both accounts are the user's. Most of this is already known: **every ingested account is, by definition, the user's** (Slice 1.5). The gap is a transfer that *names* a destination we haven't ingested. So own-account membership is a learned set: ingested accounts are automatic members; a named-but-unseen account is **asked once and learned** (an own-account confirmation event, reusing the identity block). Mislabeling an *external* payment as internal is the failure mode — it would hide real spending — so v1 auto-links only when **both** legs are ingested own accounts, and everything else asks.

## Grades & provenance

The link is a graded fact: **`verified`** (a person confirmed it), **`corroborated`** (auto-linked on decisive evidence, or closed by cross-document corroboration), **`suggested`** (a Finding awaiting confirmation). Provenance cites *both* source movements (each with its own document provenance); a corroborated repair additionally records the counterparty document as the attesting source and the "incomplete primary read" marker.

## Implementation status (as built, 2026-07-24)

Core built and tested (`ingest/transfers.py`, projection transfer overlay,
`pipeline._try_corroboration` / `heal_corroboration`, `answer_spending`):

- ✅ **Overlay link, never a re-post** — `TransferLinked` / `TransferUnlinked` /
  `TransferSuggested` events (append-only, reversible); each statement still
  reconciles on its own. Links reference the **stable movement key**
  (`doc_id|account|date|amount|description|occurrence`), which survives a replay
  (a reingest) — proven by a test.
- ✅ **Netting = exclusion** — `spending_by_currency()` excludes linked
  movements; `answer_spending` reports external spending with transfers removed.
  The kind-aware *economic sign* / self-netting clearing account stays deferred
  to S7 (only a minimal source/destination read is used, for matching).
- ✅ **Decisive auto-link, ambiguous asks** — decisive (unique magnitude+currency
  match within the date window, with a strong own-account hint) auto-links at
  `corroborated`; ambiguous/weak surfaces a `TransferSuggested`; confirm →
  `verified`, reject dismisses. Currency is matched, never a bare amount (I1).
- ✅ **Cross-document corroboration rung** — a decisive counterparty leg supplies
  what a statement's read dropped; the supplied posting cites the **counterparty
  document** (provenance) at grade `corroborated`, with an explicit
  incomplete-read note; heals in **either ingest order** (`heal_corroboration`).
  A gap with no decisive counterpart is **not** closed — it holds for a human
  (tested). This is the H-E-B missing-payment case, rescued.
- ✅ **Surfaces** — `debug_vault` and the web overview/review show transfers,
  suggestions, and transfers-excluded spending; confirm/reject endpoints wired.

Deferred (noted, not built — a clean v1 boundary):

- ⏳ **One-sided own-account ask + learned patterns.** v1 links only when **both**
  legs are ingested own accounts. A transfer that *names* an unseen destination
  ("payment to card …9876") is not yet turned into an own-account question, and a
  confirmed transfer is not yet **learned** so future look-alikes auto-link. The
  event vocabulary and the entity-resolution block it will reuse are in place;
  this is the next increment. Until then a one-sided transfer degrades gracefully
  (counts as spending until the other account is ingested, then auto-nets).

## Notes for future slices (read these when you build them)

- **Slice 5 (categorization + external Party):** external counterparty attribution (a payment to a mortgage servicer or a person is a *real* outflow, not a transfer) is the second half of transfer-linking, built on the same entity-resolution block. The **general** cross-document corroboration (a peer's or a third party's statement corroborating a movement your account dropped) uses the *same witness mechanism* as this slice, but the counterparty is external and the evidence is softer, so it needs the Party primitive and a lower default autonomy.
- **Slice 7 (net worth):** the kind-aware **economic sign** turns the `Transfers` exclusion category into a true **self-netting clearing account** (a linked pair nets to zero across assets − liabilities). The magnitude-match this slice records is the precondition; S7 supplies the sign.
- **Slice 11 (FX):** cross-currency internal transfers (a USD checking debit funding an INR account) have legs that differ by an FX rate, not equal magnitudes — matched by the answer-time cited rate, not by amount. Out of scope here; this slice is same-currency only.

---

## Slice 3 — Transfer links + cross-document corroboration

**Block(s) seeded:** the **Transfer link** (two postings = one economic non-event, graded, with evidence) and the **cross-document reconciliation witness** (a decisive counterparty leg closes another statement's gap). Both reuse Finding, correction-as-event, entity-resolution learning, grade, provenance, and the heal pass.

**Open state:** with two of the user's own accounts, an internal payment is counted on both — money seems to leave twice; and a statement whose gap is attested by a counterparty stays held even though the evidence to close it is already in the ledger. *Proofs (red tests):* (a) summed cross-account outflow overstates real spending by the transfer amount; (b) a card missing a payment that the checking statement attests stays held/unreconciled, and its balance is not answerable, though the corroborating line is present.

**Implementation:**
- A **movement key** (`doc_id` + within-document fingerprint) as the stable referent for links, surviving reingest.
- A candidate **matcher** over an amount/date index: exact amount + date proximity + opposite direction + description hints + both-own-accounts → a graded match.
- A **`TransferLinked`** overlay event (two movement keys + grade + evidence) and recategorization of both counter-legs into **`Transfers`**; aggregates exclude `Transfers`.
- A **decisiveness gate**: decisive → auto-link (`corroborated`); ambiguous → a **Finding** (`suggested`) → confirm as `verified`; the ruling is **learned** so matching future transfers auto-link.
- A **cross-document corroboration rung** in diagnosis: when a statement's gap equals a decisive unmatched counterparty movement, **supply the missing leg** (provenance → the counterparty document; grade `corroborated`; record the primary read as incomplete), closing the gap without a model call. Gated by decisiveness; heals both ingest orders.
- **Own-account membership** learning: ingested accounts auto-member; a named-but-unseen destination asks once and learns. v1 auto-links only when both legs are ingested own accounts.
- **Correction-as-event** for confirm / reject / unlink — reversible, replayable.

**Final state:** internal transfers are recognized and excluded from spending; "how much did I spend" reflects only real external outflow; a statement whose gap is attested by a counterparty is **rescued and posts `corroborated`** with dual-issuer provenance; wrong or ambiguous links **surface**, never silently applied; confirmed patterns auto-link thereafter.

**Done criteria / tests:**
- A checking→card payment is linked and **excluded from spending**; total spending equals the real external outflow (the once-red double-count test passes).
- A card missing a payment **reconciles and posts** when the checking statement is present (cross-document repair), and the supplied posting's provenance cites the **checking** document, graded `corroborated`, with the "incomplete read" marker recorded.
- The same works in **either ingest order** (card-then-checking and checking-then-card) via the heal pass.
- An **ambiguous** match (two same-amount, same-day candidates) surfaces a **Finding**, not an auto-link; a **non-decisive** gap is **not** auto-closed.
- A **confirmed** link is `verified` and **persists across reingest**; an **unlink** event reverses it.
- A transfer naming an **unseen** destination raises the own-account question and, once answered, **learns** it (the next one auto-links).

**Why now + future use:** without it, spending (S5) and cash flow are simply wrong — load-bearing for job-1 accuracy. It is the **first cross-account fact**, seeding the operational graph. The cross-document witness makes the **verification layer** materially stronger (a cheap, model-free, dual-issuer reconciliation rung) and is a live, early instance of the **endgame's cross-issuer corroboration** primitive. And it is a **composition proof** — almost entirely reuse (Finding + correction + entity-resolution + grade + provenance + heal), with only the `TransferLink` overlay, the `Transfers` category, and the matcher as new parts.
