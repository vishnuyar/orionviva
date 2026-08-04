# Transfer Links & Cross-Document Corroboration — one movement, two witnesses

**Status:** Implemented · **Last updated:** 2026-07-30 · **Origin:** the doc-type registry lets a person hold several of their own accounts. The moment they do, an internal payment (checking → their own card) appears on *two* statements, so "how much did I spend" counts the same money twice. Real ingests surfaced a second, deeper case: a statement whose reconciliation gap is *exactly* a movement the counterparty document already attests (a card missing a payment that the checking statement plainly shows). Both are the same recognition — **two legs, one movement** — so this slice builds them together.

**Invariants touched:** T1 (every posting carries provenance — a link cites *both* source lines; a corroborated leg cites the issuer that actually attested it), T2 (verification: cross-document corroboration is a *second, independent* reconciliation identity, run by deterministic code), T4 (a link/correction is an append-only event, reversible, nothing overwritten). Principle 2 (**never bluff a number** — a gap is never closed on a non-decisive link) and principle 7 (autonomous where safe, deferential where it counts) are the load-bearing constraints. This is the verification layer — "the actual hard problem" — getting a new, cheap, strong rung.

## The architecture (decisions locked with Vishnu, 2026-07-24)

**1. Internal own-account transfers only.** The data-model spike found transfer-linking is really two jobs: **own-account netting** (both accounts are yours → the movement isn't spending) and **external Party attribution** (a mortgage servicer, a peer, an employer → a real outflow to someone else). This slice does the first — the load-bearing spending-accuracy fix. External counterparties ride the *same* entity-resolution block later (categorization / Party).

**2. Netting is minimal here; the economic sign waits for net worth.** Our postings sign each movement by its **effect on that account's printed balance** (the doc-type registry / A1) — locally correct for reconciliation, but *not* globally additive across asset and liability (a checking outflow and a card payment can both read `-2400`). Making a transfer pair *self-net to zero* needs a kind-aware economic sign, and that is net worth's job. So here, `Transfers` is an **exclusion category**, not a self-balancing clearing account: both legs are recategorized out of Uncategorized into `Transfers`, and every aggregate (spending, external cash flow) **excludes** `Transfers`. The link additionally asserts the two legs are equal magnitude. That fully delivers "spending excludes moving your own money" without the sign machinery; the self-netting upgrade arrives with net worth.

**3. Auto-link on decisive evidence; ask otherwise.** A wrong link double-counts or hides real spending, so autonomy is earned by evidence (principle 7). A **decisive** match auto-links (grade `corroborated`); anything softer surfaces as a **Finding** to confirm (grade `suggested` → `verified` on confirmation). A confirmed pattern is **learned**, so the next one of its kind auto-links — the ask-once-then-learn spine, reused.

**4. A transfer link doubles as a cross-document reconciliation witness.** This is the capability that makes the slice more than netting. When a statement fails to reconcile internally and its gap is *exactly* an unmatched movement on another of the user's own accounts, the counterparty's line **supplies the leg this document is missing** — closing the gap *and* completing the transfer pair. It is a new, cheap, strong rung in the repair ladder (see below). Gated by the same decisiveness as any link.

**5. v1 auto-links only when both legs are already ingested own accounts.** That is the decisive case (both sides are accounts we hold, exact amount, tight date, description hint). A transfer that *names* a destination we haven't ingested ("Payment to card …9876") cannot be auto-confirmed as internal — it becomes a Finding that doubles as the own-account question ("is …9876 yours?"), answered once and learned.

**6. A link references a stable movement key, not an event id.** Reingest mints new event ids (the doc-type registry), so a link points at `doc_id + a within-document movement fingerprint` (date + amount + normalized description + occurrence index) so it survives re-reads and heals rather than dangles. _Known risk: a re-read that reorders or merges lines can move a fingerprint; revisit if reingest-stability bites._

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

Two unrelated $50 movements on the same day are the trap, so **decisive = exact amount + tight date + description/own-account evidence that pins the pair uniquely.** Decisive → auto-link (`corroborated`). Ambiguous (more than one candidate, or amount-only) → a **Finding** citing the candidates, `suggested`, awaiting a human. On confirmation, the ruling is learned as a pattern (keyed on the recurring description/counterparty), so "payments to …9876 are always my Amex" auto-links thereafter — the same *signals → graded match → ask → learn* block that the account matcher built for account identity, pointed at transfer counterparties.

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

Netting is only correct if both accounts are the user's. Most of this is already known: **every ingested account is, by definition, the user's** (account identity resolution). The gap is a transfer that *names* a destination we haven't ingested. So own-account membership is a learned set: ingested accounts are automatic members; a named-but-unseen account is **asked once and learned** (an own-account confirmation event, reusing the identity block). Mislabeling an *external* payment as internal is the failure mode — it would hide real spending — so v1 auto-links only when **both** legs are ingested own accounts, and everything else asks.

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
  to net worth (only a minimal source/destination read is used, for matching).
- ✅ **Decisive auto-link, ambiguous asks** — decisive (unique magnitude+currency
  match within the date window, with a strong own-account hint) auto-links at
  `corroborated`; ambiguous/weak surfaces a `TransferSuggested`; confirm →
  `verified`, reject dismisses. Currency is matched, never a bare amount (I1).
- ✅ **Cross-document corroboration rung (single AND multi-leg)** — a decisive
  set of counterparty movements supplies what a statement's read dropped; each
  supplied posting cites its **counterparty document** (provenance) at grade
  `corroborated`, with an explicit incomplete-read note; heals in **either ingest
  order** (`heal_corroboration`). A single missing payment is the size-1 case; a
  **whole missing payments section** (the Imprint case) is the size-N case —
  counterparty movements that each **distinctively name the account** and whose
  magnitudes **uniquely sum** to the gap (subset-sum, gated by uniqueness). A gap
  with no decisive counterpart is **not** closed — it holds for a human (tested).
- ✅ **Detection over an existing vault** — `sweep()` (stitch gaps → corroborate
  conflict-holds → link transfers) runs on web startup and via
  `python -m viva.rescan`, so statements ingested *before* transfer detection
  existed get linked without a re-upload. Idempotent.
- ✅ **Matcher tuned for real data** — date window 5 days; the strong hint
  recognizes a token that belongs to one of the two accounts and to **no other
  account the person holds**. The holder's name is deliberately not a token
  (shared across a person's own accounts). _Superseded in part on 2026-07-30 —
  the keyword tables this bullet used to describe are gone, and the printed date
  now breaks ties. See **[The evidence a link stands
  on](#the-evidence-a-link-stands-on)** below._
- ✅ **Clean confirmation** — within one scan a movement is *consumed* once linked
  and never offered again; `confirm_transfer` is a guarded no-op if either
  movement is already linked (a movement joins at most one transfer);
  `transfer_review` drops candidates/suggestions whose money is already linked,
  so confirming one suggestion removes that movement from all the others. Each
  suggestion is an independent per-source decision.
- ✅ **Surfaces** — `debug.vault` and the web overview/review show transfers,
  suggestions, and transfers-excluded spending; confirm/reject endpoints wired.
  `sweep()` reports net links/suggestions by diffing the projection (the nested
  corroboration scan is counted honestly).

Deferred (noted, not built — a clean v1 boundary):

- ⏳ **One-sided own-account ask + learned patterns.** v1 links only when **both**
  legs are ingested own accounts. A transfer that *names* an unseen destination
  ("payment to card …9876") is not yet turned into an own-account question, and a
  confirmed transfer is not yet **learned** so future look-alikes auto-link. The
  event vocabulary and the entity-resolution block it will reuse are in place;
  this is the next increment. Until then a one-sided transfer degrades gracefully
  (counts as spending until the other account is ingested, then auto-nets).

## The evidence a link stands on

**Amended 2026-07-30.** This section replaces the description of the matcher
above and is the authoritative account of what makes a pair decisive. It exists
in this document rather than in comments beside the code, so that the code can
say what it does and this can say why it does it that way.

### What was deleted, and why it must not come back

Five English word lists used to decide this: `STOPWORDS`, `_STOPWORDS`,
`_TRANSFER_WORDS`, `_CARD_WORDS`, `_DEPOSITORY_WORDS`. `_CARD_WORDS` was
load-bearing and **always true** — a credit card statement prints "card" on
nearly every line, so for any card destination the hint held for anything, and
the surviving constraints were equal amount and uniqueness alone.

A rule that is always true is not a loose rule. It is a rubber stamp that reads,
in the log, exactly like a check that passed. On a real vault it linked a cash
withdrawal to an unrelated card payment of the same amount a day apart, which
removed both legs from spending: real cash spending vanished from the figure,
and a card payment was recorded as a transfer that never happened. Two wrong
numbers from one word.

The replacement is a property of the data rather than of the language: a token
that belongs to one of these two accounts **and to no other account the person
holds**. Computed from the accounts themselves, so nothing has to guess which
words are generic — genericness is measured. One refinement earned by a failing
test: a *label* token must also carry a digit, because an account labelled
"Card 2222" otherwise donates the word "card" back to the very list that was
just deleted. The institution is exempt, being a name rather than a kind.

### Why the printed date, and why it can never link on its own

Removing the word lists left 29 matches the software could no longer decide.
Twenty-four were unanswerable only because nothing read the date the bank had
printed on the source line — one checking account paying one card four times in
eight days, every credit reading identically, the account evidence equally true
of all four candidates. The descriptor parser had been extracting that date as a
named slot the whole time (`{date}` under an induced grammar, `posting_date`
under the published rules); the matcher never looked.

`weigh()` scores every (source, destination) pair:

| signal | worth |
| --- | --- |
| account evidence (a distinctive token, or a proven `account_ref` slot) | 2 |
| the printed date matches the candidate's date | 1 |
| **floor — nothing links below this** | **2** |

The floor is the design. **A matching date can never create a link**; it only
separates pairs that already qualify. A rent payment whose description happens
to contain a date still scores 1 and is still asked about. The new signal had to
be strictly a discriminator and never a second way in, because the thing just
deleted was a signal that had quietly become a way in.

`decide()` requires both directions to be unambiguous — the source's best
candidate is strictly best, and the source is strictly the best claimant of it —
and refuses ties outright, so no outcome depends on the order a dict iterated.

**Dates are read without knowing the country.** Both orders are tried. Every
candidate is already inside the window, and two dates that close cannot be six
months apart, so at most one reading can ever match: the ambiguity that would
demand a locale setting is arithmetically unreachable. The year is never parsed
either, which is what lets a 12/31 line posting on 01/02 match with no year
arithmetic (I5).

### `DATE_WINDOW_DAYS` is not the dial

Two intuitions about it are both backwards, and both cost time before being
written down.

- **Narrowing it unlinks nothing.** `_candidates` only looks at movements where
  `linked` is false. The constant governs the next scan, never the last one.
- **A narrower window can produce MORE auto-links, not fewer.** Auto-linking
  needs exactly one candidate; a wider window finds more candidates and pushes
  pairs out of decisive and into questions. On the real vault, window 0 gave 9
  auto-links and window 1 gave 0.

The dial is the evidence, not the window.

### What a link records

`decided_by` names the **rule** that fired (`named_account+printed_date`), never
the value it matched. `account_ref` is a personal slot; the matcher lives inside
that boundary and may read it, but nothing it reads may reach anything shareable
(T9). The projection surfaces `decided_by` so a link can be audited later without
re-deriving it.

### Questions that cannot be answered stop being asked

A suggestion whose candidates have **all** since been linked elsewhere is
dropped on the read side. `confirm_transfer` refuses a movement already in a
transfer, so the only answer available was "no". Filtered rather than withdrawn
by an event: revoke the link that took the candidate and the question returns.

`sweep` used to report the *delta* of open questions and printed "-23" on a
sweep that answered twenty-three of them. Open questions are a level.

### Result on the real vault

Sixty-seven of sixty-eight existing links survived the stricter hint; the one
that did not was the ATM coincidence, and revoking it was correct. Of the 29
questions the deletion produced, 24 resolved on the printed date. The five that
remain are the five that should: the ATM again, a tuition payment that collided
by amount, a duplicated statement line, and two whose true counterpart is not in
the vault because that month's statement was never ingested.

## Notes for future slices (read these when you build them)

- **Categorization + external Party:** external counterparty attribution (a payment to a mortgage servicer or a person is a *real* outflow, not a transfer) is the second half of transfer-linking, built on the same entity-resolution block. The **general** cross-document corroboration (a peer's or a third party's statement corroborating a movement your account dropped) uses the *same witness mechanism* as this slice, but the counterparty is external and the evidence is softer, so it needs the Party primitive and a lower default autonomy.
- **Net worth:** the kind-aware **economic sign** turns the `Transfers` exclusion category into a true **self-netting clearing account** (a linked pair nets to zero across assets − liabilities). The magnitude-match this slice records is the precondition; net worth supplies the sign.
- **Slice 11 (FX):** cross-currency internal transfers (a USD checking debit funding an INR account) have legs that differ by an FX rate, not equal magnitudes — matched by the answer-time cited rate, not by amount. Out of scope here; this slice is same-currency only.

---

## Transfer links + cross-document corroboration

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

> _Amended 2026-07-25 (honest aggregates): this slice excludes a transfer from spending **only when a link was formed**. A real-vault run showed that internal movements which never linked — a card payment whose counterpart statement isn't ingested, a brokerage contribution — were still counted as spending, and that a *category* saying "transfers" did not exclude anything. The exclusion rule is generalized to **movement nature** in [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md); the auto-link bar here is deliberately **not** loosened._

**Final state:** internal transfers are recognized and excluded from spending; "how much did I spend" reflects only real external outflow; a statement whose gap is attested by a counterparty is **rescued and posts `corroborated`** with dual-issuer provenance; wrong or ambiguous links **surface**, never silently applied; confirmed patterns auto-link thereafter.

**Done criteria / tests:**
- A checking→card payment is linked and **excluded from spending**; total spending equals the real external outflow (the once-red double-count test passes).
- A card missing a payment **reconciles and posts** when the checking statement is present (cross-document repair), and the supplied posting's provenance cites the **checking** document, graded `corroborated`, with the "incomplete read" marker recorded.
- The same works in **either ingest order** (card-then-checking and checking-then-card) via the heal pass.
- An **ambiguous** match (two same-amount, same-day candidates) surfaces a **Finding**, not an auto-link; a **non-decisive** gap is **not** auto-closed.
- A **confirmed** link is `verified` and **persists across reingest**; an **unlink** event reverses it.
- A transfer naming an **unseen** destination raises the own-account question and, once answered, **learns** it (the next one auto-links).

**Why now + future use:** without it, spending and cash flow are simply wrong — load-bearing for job-1 accuracy. It is the **first cross-account fact**, seeding the operational graph. The cross-document witness makes the **verification layer** materially stronger (a cheap, model-free, dual-issuer reconciliation rung) and is a live, early instance of the **endgame's cross-issuer corroboration** primitive. And it is a **composition proof** — almost entirely reuse (Finding + correction + entity-resolution + grade + provenance + heal), with only the `TransferLink` overlay, the `Transfers` category, and the matcher as new parts.
