# Doc-Type Registry & Format Profiles — how new statement types become data

**Status:** Implemented (Slice 2) · **Last updated:** 2026-07-24 · **Origin:** v0 hardcoded one projector (checking). To hold a whole financial life we need many statement types — but adding one must be *data*, not a code change. This doc sets the architecture for that, and it is deliberately written to serve *every* future type, not just credit card + savings.
**Invariants touched:** T1 (provenance per extracted field), T2 (verification identity per type, run by universal code), T4 (profiles are versioned; a re-read is an event, nothing overwritten), I5 (no country/institution-shaped tables — format specifics are profile data), X2 (types the model can't yet read are parked honestly). Serves the "code universal, specifics are data" doctrine.

## The architecture (decisions locked with Vishnu, 2026-07-23)

**1. Classify → select profile → extract per that profile.** We read *after*
classifying, because the shapes genuinely diverge (checking = balance +
transactions; brokerage = positions × price + cash; pay stub = gross −
deductions = net; 1099 = boxes; insurance = provisions). A single mega-prompt
gets worse at each type as more are added. So: a cheap classification, then the
type's own extraction profile. The balance family (checking/savings/card) shares
one *base shape* but each type contributes its own prompt *fragment* (what the
balance means, its completeness traps), composed at read time — so a card's
"payments live in a separate section" guidance never pollutes a checking read.
_As built (two model calls): a cheap **classify** pass (first page + embedded
text, no figures) names the type; then the **extract** pass runs the profile's
composed prompt. A type with no projector yet is parked after the cheap classify —
we don't pay for an extraction we can't use._

**2. We own the schema; the model owns the reading.** The ADR-010 / CaMeL split,
one level up: the model *perceives* (pixels/text → the fields WE asked for) and
never decides *what* to extract. We own the schema because deterministic
verification requires a known shape — you cannot reconcile or catch a silent
omission in a free-form extraction. The schema is **data** (a profile), not code.

**3. A schema may be model-*assisted* to author, then ratified.** A frontier
model reads a genuinely new format once and *proposes* a profile (fields,
identity check, labels); it is ratified the same way we break the answer-key
circularity (two model families agree, or a human rules) and frozen with a
**version**. The model helps write the schema; it never owns it at read time.

**4. The verification identity is universal code; the per-type formula is data.**
`opening + Σ(transactions) = closing` already covers checking/savings/**card** —
a card is just a *liability* whose balance is money owed (prev + charges −
payments = new is the same identity). Transaction sign is framed as **effect on
the printed balance** (A1), so it is account-kind-agnostic for reconciliation;
`kind` (asset/liability) is a separate interpretation attribute. Divergent
families supply their own identity (brokerage: positions×price + cash = total;
pay stub: gross − deductions = net) — still run by the one universal gate.

**5. Two kinds of learned data, kept strictly apart.**
- **Personal knowledge** — *your* accounts, identity aliases, categories,
  corrections. The moat. **Never leaves your machine.**
- **Format knowledge** — *how an institution formats a statement*. Impersonal
  (about the document, not the money). **Shareable.**
Profiles are format knowledge, which is why a commons of them is possible
without breaking local-first.

**6. Profiles are versioned, self-contained, and personal-data-free** — so the
format-commons (sharing format knowledge, never facts) is a later *addition*,
not a redesign. The claims layer already records which profile/prompt version
read each doc, enabling **surgical re-reads** (only the docs read by an outdated
profile) via `reingest-from-raw` (the raw-capture payoff) when a profile gains
fields.

## Implementation status (as built, 2026-07-24) — audit vs the six decisions

- **D1 (classify → per-type extract):** ✅ Built two-phase. `reader.classify`
  (prompt `classify-v1`, first page + text) names the type; `reader.read_statement`
  looks up the profile and runs the extract pass with the composed prompt; an
  unprojectable type parks after classify. _First implementation shipped a single
  combined call — corrected here to match the decision._
- **D2 (we own the schema):** ✅ The extraction shape lives in
  `prompt_library.EXTRACT_BASE` (our schema); the model fills it. The schema is
  data (a versioned prompt piece), not code.
- **D3 (model-assisted authoring, then ratified):** ⏳ Not built — a forward
  capability (format-authoring, a later slice). The versioning it depends on now
  exists; authoring a profile is still done by hand.
- **D4 (universal identity, per-type formula as data):** ✅ `opening + Σ(effect) =
  closing` runs for all three balance types via the A1 sign reframe; `identity`
  is a profile field, so a divergent formula (brokerage, pay stub) is a new
  profile, not new gate code.
- **D5 (personal vs format knowledge):** ✅ `registry.py` + `prompt_library.py`
  are format knowledge and carry **no personal data** (verified: profiles are
  type/prompt-version ids only). Personal knowledge (aliases, corrections) stays
  in the encrypted event log.
- **D6 (versioned, self-contained, personal-data-free profiles):** ✅ Prompts are
  retained, addressable versions (`prompt_library.resolve`, frozen-hash test);
  each read records its prompt version *per phase* (`ReadRecorded.phase`), so a
  read is reproducible and its profile version is known. ⏳ The *surgical* re-read
  (re-read only docs on an outdated version) is not yet built — `reingest` is
  still whole-vault; the per-doc version capture that unblocks it now exists.

## Notes for future slices (read these when you build them)

- **Slice 3 (transfer links):** a card *payment* corresponds to a checking
  *withdrawal* — that cross-account link is deferred to S3, built on the same
  graded-Finding + correction pattern. Card ingest in S2 must not try to guess it.
- **Slice 6 (brokerage / positions):** the first *divergent* profile — its own
  extraction schema and identity (`positions × price + cash = total`). Because
  S2 builds the classify→profile→extract structure, brokerage is a **new profile
  + a Position primitive**, not new plumbing. Carries the valuation-class
  discipline (measured/valued/estimated).
- **Slice 7 (net worth):** liability netting (assets − liabilities) is a
  **projection over posted data — zero data impact.** Card shows as "owed" in S2;
  net worth composes it in later, no migration.
- **Slice 8 (obligations):** card-specific fields (credit limit, minimum payment,
  due date) feed Obligations. When we need them, **bump the card profile version
  and targeted-re-read** the affected statements (claims layer says which were
  read with the older profile). Not a redesign.
- **Format commons (later slice):** profiles are already versioned, self-
  contained, personal-data-free units — the commons is a *sharing channel* over
  them: a frontier model distills a privacy-linted profile (structure, never
  values); cheap local models reuse it; self-healing when a format changes.
  Contributed opt-in. This is the network effect on top of the private core.
- **Format authoring (later):** creating a profile reuses the trust pattern
  (model proposes → cross-model/human ratifies → freeze + version).

---

## Slice 2 — Doc-type registry + credit card & savings

**Blocks seeded:** the **format-profile registry** (doc_type → {kind, extraction profile, identity}) + **account kind** (asset/liability) + the classify→profile→extract structure.

**Open state:** only checking posts; a card or savings statement classifies but parks (no projector). Transaction sign is "money in/out of the account," which is ambiguous for a liability. *Proof:* ingest a real credit-card statement → parked, no balance; a savings statement's interest line has no home (red tests).

**Implementation:**
- A **registry** mapping each `doc_type` to a profile: `{account_kind, extraction_profile_version, identity}`. The reconciliation gate code is unchanged; the profile is looked up from the registry (data).
- Classify → select profile → extract. Checking/savings/**card** share one **balance-statement profile** (the shapes match); the model classifies which of the three and returns the shared shape + the account kind.
- **A1 sign reframe (prompt → v3):** each transaction reports whether it **increases or decreases the printed balance** (universal across asset and liability), tying directly to `opening + Σ = closing`. Checking values are unchanged (a deposit increases the balance), so **no data migration** for existing checking reads.
- **Account kind:** `depository` (checking/savings, an asset) vs `liability` (credit card, balance = money owed). Kind drives display ("held" vs "owed") and, later, net-worth sign.
- **Reuse:** identity resolution (Slice 1.5) applies to cards unchanged (a card has a number, institution, holders). The universal gate, diagnosis, backfill, and the Ledger all apply as-is.

**Final state:** credit-card and savings statements post and reconcile; a card shows as **owed**; the same account is recognized across its statements (identity); adding another balance-shaped type is a **registry row**, not code.

**Done criteria / tests:** a real credit-card statement reconciles on `prev + charges − payments = new` (as `opening + Σ = closing` with A1 signs); a savings statement with an interest line reconciles; registering a **synthetic** new balance-type via *data only* (no gate-code change) posts it; a card balance is displayed as a liability ("owed"); existing checking tests stay green (A1 is value-preserving for checking).

**Why now + future use:** it proves "new type = data, not code" — the claim the whole architecture rests on — and it does so by **generalizing the gate we already have**, not by adding per-type logic. It unlocks multi-account (net worth, transfers), seeds the profile registry that brokerage/tax/insurance extend, and establishes account **kind** (asset/liability) that net worth composes. Every seam for the format commons and the divergent types is left open by design (see the notes above).
