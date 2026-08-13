# The Conduit and the Counterparty — reading a descriptor as a record

**Status:** Built — see *What the build changed* at the end · **Date:** 2026-07-28 · **Invariants touched:** T1, T2, T5, T7, T9, I2, I5, X2

## What is wrong today

`VENMO TO JOHN SMITH` is refused at the boundary because `venmo` and `" to "` are
in a ten-item substring list. That list is the last survivor of the nine raw-text
keyword tables this project deleted, and it survived the purge by being filed
under **privacy** rather than **classification** — nobody audits a privacy guard
for being a word list.

It fails in both directions:

```
False  PAYMENT TO MERIDIAN CARD 2291       ← blocked: an ordinary card payment
False  TRANSFER TO NORTHBANK SAVINGS 8802  ← blocked: your own savings
True   UPI/DR/402938/JOHN S/HDFC           → crosses, carrying a name
True   PAGO A JUAN                         → crosses, carrying a name
```

Measured on the author's real vault: **183 of 492 merchant keys refused, behind
26% of every movement ever ingested.** Every English descriptor containing "to"
is excluded from enrichment; every non-English one carrying a name is admitted.

Two deeper faults sit under the list's length.

**The gate answers the question enrichment exists to answer.** *"Is this a peer
payment?"* is world knowledge, and `counterparty_kind` is the field that holds
it. The gate runs first, so it must guess — with substrings — the thing the model
would have told us.

**One function answers two questions.** `is_shareable` decides eight things:
what gets enriched, what exports to the commons, whether a question generalizes,
whether a ruling generalizes, and the attention tier. Some ask *"may this leave
the machine?"* and some ask *"does this describe a pattern?"* Several call sites
ask the second and receive an answer to the first, which is why a ruling about
your own savings transfer refuses to generalize.

## What the rails actually give us

The decisive fact, and the reason this is not the problem it appears to be:
**a descriptor is not free text.** It is the flattened tail of a pipeline that
carried typed, fixed-width fields.

**Card — ISO 8583 DE43 is positional, not delimited.** Visa lineage: merchant
name 1–25, city 26–38, state/country 39–40. Mastercard lineage: 1–23, 24–36,
37–38, 39–40. `PLANO TX` is not a phrase; it is two adjacent fixed-width
subfields. Also specified rather than conventional:

- **An asterisk at index 3, 7 or 12** separates a brand prefix from a product or
  sub-merchant — a processor-mandated layout (`AMNUTTS*HUNT&FISHCAT`).
- **Visa mandates the semantics of that split**: `PayFac*SubMerchant`,
  `Marketplace*Retailer`, `Wallet*Retailer`.
- **For card-absent transactions the 13-character city slot legally holds a
  phone number or URL instead** (`617-SERVICE`). A trailing `\d{3}-\S+` is
  therefore the city field, and its presence is a card-not-present signal.
- Airlines and fuel dispensers carry mandated positional layouts inside the name.

**ACH — NACHA record layouts are fixed-width.** `Company Name` (16 chars) is the
*platform*; `Company Entry Description` (10 chars) is a low-cardinality purpose
token; `Individual Name` (22 chars) is the *person*. Separate fields.

**Zelle is not ACH.** It runs over RTP, which is native ISO 20022, so the
counterparty arrives as a structured `Cdtr/Nm` and `ZELLE TO JOHN SMITH` is a
sentence the *bank composed* for display from data that was already typed.

**Europe never had the problem.** `camt.053` carries `RltdPties/Cdtr/Nm`,
`UltmtCdtr/Nm`, a three-level transaction taxonomy and structured remittance
info. PSD2 gives `creditorName`/`debtorName` as first-class fields; UK Open
Banking has `MerchantDetails/MerchantName` and `MerchantCategoryCode`.

**And the category we pay a model to guess was computed and discarded.** Every
card authorization carries the MCC in DE18. The issuer has it — it drives reward
tiers. No US consumer channel exposes it; neither does Plaid.

So: **the person is not hiding in ambiguous text. The person is in a known slot
of a known format.** We do not detect them and we do not ask about them. We parse
the format, and the name falls out of the position it always occupied.

## The reframe: recover a record, do not parse a string

The target is not a cleaned string. It is a **record with provenance on every
field**:

```
{ brand, sub_merchant, store_number, city, region, country,
  contact, mcc, counterparty, counterparty_kind, purpose, rail }
```

Each field carries how it was obtained — `structured` · `parsed` · `inferred` ·
`absent`. That one choice makes the work durable: a `camt.053` statement or a
future US enhanced-merchant feed fills the record **directly, with the parser
bypassed**, and nothing downstream changes. Mastercard's AN4569 already mandates
enhanced merchant data across Europe and Visa's equivalent lands in 2027, so the
parsing problem is shrinking. Build the consumer of structured data, and let
parsing be the fallback rather than the foundation.

## Four layers, each shrinking what the next one sees

**Layer 0 — network-universal, deterministic, no model, no profile.** The
asterisk convention, the trailing state code, store-number tokens, the
phone-in-city-slot rule, known processor prefixes, date fragments. These are
specified by the card networks and identical at every bank on earth. Free, and
the first thing to measure: *what fraction of descriptors does this alone fully
account for?* That number decides whether Layer 1 is a centrepiece or a
long-tail tool.

**Layer 1 — an induced grammar, keyed by (institution × rail × document type).**
Not per institution: a checking line and a card line from one bank have unrelated
grammars, and the ACH/Zelle templates are a third language. This is where
per-bank concatenation lives, and where the person's slot lives.

**Layer 2 — the merchant knowledge base.** Brand lookup; a model call only on a
miss. By this point the input is a short clean brand string, which is where a
model is accurate. Fed a raw descriptor it is not: the only public benchmark puts
naive frontier-model merchant normalization at **0.66**, against **0.87** for a
knowledge-base-backed system.

**Layer 3 — local.** The counterparty, from the slot Layer 1 identified.

## Induction from evidence, never recall

A profile is **never** obtained by asking a model *"how does this bank encode its
descriptors?"* That is a recall question about undocumented, drifting, per-bank
behaviour that no model was trained on — and it will be answered fluently anyway.

A profile is obtained by showing the model **real descriptors from the statement
in hand** — a few examples of each line shape it prints — and asking what grammar
produced them. Same call, same cost,
entirely different failure mode: the model perceives what is in front of it and
is never believed about the world. That distinction is the same one the whole
extraction path already rests on.

## The vocabulary is closed, and it is the same list twice

The model does not write a regular expression. It writes literal words and
**named holes drawn from a closed set**:

```
ZELLE TO {counterparty} {reference}
CARD PURCHASE {date} {brand} {city} {region}
```

Fifteen names, no more: `brand`, `city`, `region`, `store_number`,
`counterparty`, `institution`, `account_ref`, `reference`, `trace`,
`company_id`, `contact`, `date`, `amount`, `purpose`, `noise`. Each already
knows what shape of text it matches, so a hole is a *name*, not a pattern. The
expression is compiled **in our code**, from the template, which is what bounds
the grammar: a profile cannot express anything the vocabulary does not permit,
because the only thing the model ever supplies is which name goes where.

Three of those names were added by the first real statement rather than designed
in, and the corrections are worth recording because each one was invisible until
a bank's own lines were put next to the vocabulary. A real ACH line carries **two
ids at once** — the trace number for this movement and the originator's standing
company id — so `trace` and `company_id` are two names rather than one name used
twice. And a card-not-present line carries the merchant's phone number where the
city belongs, which Layer 0 already had a name for; `contact` keeps the two
layers speaking the same language.

That one list is used twice, and the two uses are what make it worth having.

**It is rule 1 of the induction prompt** — enumerated, with the instruction that
any template using another name is discarded. **It is also the validator**, which
refuses unknown slots, unknown shapes, a slot repeated inside one template, and a
template with no holes at all (a template that reproduces one line exactly is an
example, not a grammar). Prompt and validator cannot drift apart, because the
prompt is rendered *from* the vocabulary.

Two properties then fall out of the structure rather than being checked
afterwards:

- **Losslessness is structural.** The compiled expression is anchored at both
  ends. A template explains the whole line or it does not match. So there is no
  partial parse to mistake for a complete one — anything a profile claims is a
  line every character of which landed in a slot.
- **Privacy is a slot name.** `counterparty` and `account_ref` are personal *by
  declaration*, in the vocabulary, in code. Nothing downstream inspects the
  extracted text to decide whether it may travel; the slot it came from already
  said. This is what replaces the substring list — not a better list, but a
  different kind of thing.

## What the vocabulary cannot protect, and the shape refused because of it

A slot name is a promise about what is inside it. `{city}` holds a city;
`{trace}` holds a number the network assigned. That promise is what makes the
privacy boundary a schema instead of a filter — and it is exactly what a wire
transfer breaks.

A wire is not a descriptor with more fields in it. It is a Fedwire or SWIFT
message dumped into a display line: the beneficiary bank's routing number, the
beneficiary's account and name, and an **operator free-text `Ref:` field
carrying whatever the sender typed**. On a property purchase that is a street
address. On a family transfer it can be anything at all.

No slot name can honour a field whose contents are unconstrained. So the wire
shape is **refused a grammar outright** rather than parsed carefully: the line
stays local and whole, no template may ever claim it, and the refusal is checked
before templates are consulted rather than after — otherwise it would only be as
strong as the templates that happen to exist today. Refused lines are excluded
from the coverage denominator, not counted against it; they are a boundary
decision, not a grammar failure.

This is the honest version of a claim the design was about to overreach on. The
vocabulary protects fields whose *shape* is known. Where a rail hands us an
unbounded field, the answer is to keep the line, not to name it well.

## One thing the model writes that nothing above bounds

The literal text. Holes are bounded by the vocabulary, but the words between
them come from the model, and a template that ignored the rules could bake a
person's name into its literal text — `ZELLE PAYMENT FROM ARJUN {reference}` —
which would carry that name into a file whose entire premise is that it is
impersonal.

There is a deterministic check for this, and it needs no model and no list:
**a template literal is by definition text the bank prints on many lines.** A
literal word occurring in exactly one descriptor of the corpus is therefore not a
literal — it is a filler baked in. That single test catches both failures at
once: a copied example (rule 4) and a name in the wrong place (rule 7). It runs
before anyone reads the templates, which matters, because reading is the other
line of defence and reading is the one people skip.

The consequence for the report: an induced grammar is **not automatically safe
to paste**. It is *intended* to be impersonal, the check exists to say when it
isn't, and reading it is how that intention gets confirmed.

## Which lines to show — the part that is already solved elsewhere

Recovering a format string from the lines it produced is not a new problem. It is
**log template mining**, a field with a decade of parsers (Drain, IPLoM, SPELL,
LogMine), a public benchmark, and by now a body of work on doing it with a model.
Two of its results apply directly, and the first dry run against a real statement
violated both.

**Mask the variable parts before grouping, not after.** [*Preprocessing is All
You Need*](https://arxiv.org/html/2412.05254v1) measures exactly this: moving the
masking step ahead of the grouping step raises Drain's template-accuracy F1 by
**109%** and its grouping F1 by **48%** on the same data. Grouping on the raw
line does the opposite of what it appears to: twenty-one lines differing only in
a leading posting date become twenty-one groups, and one template eats half the
sample. (The same paper declines to recommend Drain's other trick, partitioning
by token count, so that is not adopted either.)

Two masks do the work here, and the second is the interesting one:

- **A token containing a digit is a filler.** Dates, trace numbers, masked
  account refs, confirmation ids.
- **A word occurring in exactly one distinct line is a filler.** Template
  literals repeat *by definition* — that is what makes them literals — while a
  merchant name printed once is the hole. Parameter-free, and it needs no list of
  known words, which is the whole point given what this design deleted.

What survives both masks is the line's literal spine, and lines sharing a spine
are lines one template produced.

**Within a group, show lines that are UNLIKE each other.** This is the one that
was backwards. The instinct is to show the most common line, and it is measurably
the worst choice: [LogBatcher](https://arxiv.org/html/2406.06156v2) measures
similarity-based selection at **7.7% worse** than diversity-maximizing selection,
and [DivLog](https://arxiv.org/pdf/2307.09950) finds that replacing diverse
sampling with random costs **11% parsing accuracy and 28% template precision**.
The reason is plain once stated: a model learns where a hole *is* by seeing one
template with different fillers. Three near-identical lines teach it nothing
about which part varies.

LogBatcher reaches diversity through DBSCAN over TF-IDF vectors and a
determinantal point process. None of that is needed here — application logs are
fuzzy, but bank descriptors are composed from literal templates, so exact spine
equality is a *stronger* clustering than density estimation and costs nothing.
Greedy farthest-first on token sets covers the diversity step.

Its batch size transfers directly, though: 5–10 lines per batch, with larger
batches slightly *worse*. So the sample is capped at five examples per shape. A
statement with three shapes sends fifteen lines, not a padded forty.

## The profile is a data pack — the fourth instance of a pattern already here

A profile is **data, versioned, and never edited once released**. That is not a
new convention; it is the fourth time this project has reached for the same one:

| pack | what it holds | why it is never edited |
|---|---|---|
| **prompts** (`prompts/<version>.txt`) | model-facing instructions | a recorded `prompt_version` must resolve to the exact text that produced a reading |
| **persona packs** (`persona/pack-vN/`) | how Viva speaks | a reply attributed to a pack must be reproducible from it |
| **expectations registry** (`expectations-v1.json`) | what a document kind should contain | a parked document must be re-judgeable under the rule that parked it |
| **profiles** (`profiles/<inst>-<kind>-vN.json`) | one bank's line grammar | a stored decomposition must re-derive from the grammar that produced it |

Same shape each time: the filename is the version, the content is the payload,
a change means a new file. A profile earns it for the strongest reason of the
four — it is applied to *every line a bank ever prints*, so a template accepted
and then quietly corrected would mean two different meanings share one id, and
every record stamped with that id becomes unreadable.

The store refuses to overwrite an existing version. Bumping is the only way to
change a grammar.

## Two calls, two frequencies, two payloads

The confusion worth heading off: this is not one model call moved around. It is
two calls that differ in everything that matters.

| | **grammar induction** | **merchant enrichment** |
|---|---|---|
| asks | "what templates produced these lines?" | "what is this brand?" |
| payload | ~40 raw descriptors from one statement | a brand string, plus impersonal slots |
| sees a person's name | **yes** — that is the point; the name is what teaches it where the `counterparty` slot is | **never** — the personal slots are removed before the call by slot name |
| frequency | once per (institution × kind). Five, in the author's vault. **Five calls, ever.** | once per brand never seen before, anywhere |
| result | a profile, impersonal, shareable, verifiable | a merchant record, impersonal, shareable |
| graded | passes or is discarded, by a deterministic check | `corroborated` |

The first call is where the descriptor goes whole — and it may, because ingest
already sent the model every page of the statement, including that line. The
second call is where the descriptor never goes at all: by then the line has been
decomposed, and only the slots the vocabulary declares impersonal are assembled
into the request. The privacy boundary moved from *"which strings look risky"* to
*"which slots are named personal"*, and it moved from a filter to a schema.

The order matters too: enrichment gets a **short clean brand plus typed
context** instead of a raw descriptor, which is the input on which the published
benchmark separates 0.87 from 0.66. Better privacy and better accuracy are the
same change.

## The lossless-parse invariant

A profile that mis-slots a field is wrong *consistently and confidently* for
every transaction from that institution — worse than one bad read. So a profile
is held to the same standard as a statement:

> **Every character of a descriptor must be claimed by a slot.** Brand, city,
> region, store number, product, counterparty, reference, or an explicit noise
> slot. Tokens that fall on the floor mean the profile is incomplete. A slot that
> is empty across the whole statement means it is wrong.

This is `opening + Σ = closing` for a parse: checked against the evidence it was
induced from, deterministically, with no model in the loop. A profile that cannot
account for its own statement is never applied to anything.

**Measured on held-out lines, never on the sample.** A few dozen descriptors are
shown to the model; coverage is scored against *every* descriptor the institution
ever produced, weighted by movements. A grammar that explains its own examples
and nothing else has learned the sample rather than the bank, and only the
held-out number can tell the difference. It is the same reason a reader is never
scored on the page it was tuned against.

**And the check is a loop, not a gate.** Whatever a round cannot explain becomes
the next round's sample, bounded at three. This is the shape log-template mining
converged on independently — LogBatcher compiles a returned template to a regex,
matches it against the corpus, and sends the unmatched lines back as a fresh
cluster — and it fits the material, because a bank's long tail is a *different
set of templates* rather than a vaguer version of the common ones. The cap is
there because the tail is finite but a one-off line is not: without it, forty
singletons would burn forty calls.

It also makes a **shared** profile safe in a way the merchant catalog is not —
a recipient can verify someone else's grammar against their own statement before
trusting it. A commons with a built-in check.

**And the same check is a drift detector, for free.** A bank changes its
composition — a new product line, a merged acquisition, a rail migration — and
the coverage of a pinned profile falls. Nobody has to notice the change, read a
release note, or diff a statement: the number that gated the profile on the day
it was induced keeps being computed on every ingest, and a drop is the signal.
Because profiles are versioned and never edited, the response is a new version
induced from the new lines, with the old one still resolving for every record
that was stamped with it. Drift becomes an ordinary version bump instead of a
silent, retroactive change of meaning.

## What the author's real vault measured

The three cheap steps ran before anything was induced, and two of them changed
the plan.

**The date-fragment fix collapsed 492 keys to 365.** 163 raw descriptors carried
a posting date, so a merchant seen in two months was two merchants; every purely
numeric head token disappeared with them. Read-side re-derivation, no re-ingest,
and it owed nothing to the rest of this architecture.

**Five grammars cover the vault.** Five (institution × kind) pairs across 1,076
movements, and the two largest cover **83%** of them. Five is small enough that
each grammar can be induced, read by a human, and gated by hand before any of it
is automated. That answers the question step 2 existed to ask.

**Layer 0 does not cancel Layer 1.** The deterministic parse says something about
**80%** of movements — but 88 keys get 0% coverage, and 83 more leave residue in
scattered runs rather than one, which is the parse announcing it fired in the
wrong places. Layer 0 removes structure it can prove; it cannot claim the brand,
because no published rule says where a brand ends. So it shrinks Layer 1's job
substantially and does not replace it.

**The NACHA layout is not a theory — it is visible, and it is truncated.** On the
largest depository grammar, six different originator names come back at *exactly
sixteen characters*, which is the width of the NACHA Company Name field. The
brand handed to Layer 2 is therefore hard-truncated, deterministically. Two
consequences, both actionable: a truncated brand is a perfectly good key, because
truncation is stable and repeats every month; and the enrichment prompt must say
the string may be cut off, or a model reads `Longcreek-Servic` as an odd brand
name rather than a clipped one. Meanwhile the SEC code — `PPD`, `CCD`, `WEB` —
needs no slot at all: it is literal text, so `PPD ID:` and `WEB ID:` are simply
two templates, which is what they are.

**Direction is in the literal words.** `ZELLE PAYMENT FROM` against `PAYMENT TO`.
The template carries which way the money went, for free, with nothing inferred.

**The fanning heads split cleanly in two**, which is the finding that decides the
design. Some are bank-composed sentence openers — a peer-payment verb heading 59
distinct tails, then card, you, atm, payment, online, refund. Those are not
merchants at all; they are the bank's own template text, and a template is
exactly what should absorb them. The rest are real merchants whose tails are
locations. One kind belongs in the grammar, the other in the knowledge base, and
before this they were the same undifferentiated string.

## Identity has two levels, and that is settled by consensus

Plaid, Spade, MX, Stripe Issuing and Heron independently converged on a
**brand-level identifier stable across all locations**, plus a **separate
location identifier**. Plaid states it outright: the merchant id *"will map to
the broader merchant, not a specific location or store."* Spade: every Walmart
location shares one counterparty id, against more than forty thousand merchant
ids coming through the networks.

So: **`costco` is one key however many cities appear.** Location is a typed field
on the occurrence, not part of the merchant's identity. Two hundred stores
produce one commons row.

## Three boundaries, not one

| boundary | what crosses | why |
|---|---|---|
| **the model call** | the whole descriptor | ingest already sent every page and the issuer's full embedded text; withholding one line protects nothing |
| **the local store** | the whole record, encrypted | including the counterparty |
| **the commons** | the merchant block and the grammar profile | both impersonal by construction |

Publication is a **schema, not a decision**: the export takes `merchant.key`,
`merchant.name`, `category`, `subcategory`, `counterparty_kind`, and the profile.
Occurrence attributes have no path to it. Not filtered — unreachable.

And a merchant key publishes only once **corroborated by independent vaults**,
which closes the residual risk of a model returning a person's name as a brand:
`costco` clears immediately at any scale, and a private individual never does.

## The Party

Built now. Enumerated in the data model since the spike, with three customers
waiting — peer counterparties, the employer thread from pay stubs, and the
counterparty of the endgame. *"Write side late"* means late enough that the shape
has stopped moving; this shape has not moved in weeks.

**It gets its own event type, for the reason tags did:** so *"a party never
leaves this device"* is an event-level rule rather than a field somebody must
remember. A person's name has a stronger claim to that than a tag.

It is an identity resolved from signals, so it inherits the existing machinery —
signals, graded match, ask only when genuinely ambiguous, record the ruling,
apply on the read side. Two requirements from day one: the same person across
conduits (`RulingRecorded(scope="party", same_as=…)`, which would be the
seventh scope — attribute became the sixth on 2026-08-01), and
meaning that generalizes (*"John is my landlord"* makes every payment rent).

**This is the one place the field has no answer.** Plaid types the platform
(`payment_app`) and has no `person` entity at all. Ntropy and Teller have
`person` but no multi-party model. Nobody publishes accuracy on it. The reason is
architectural: a shared knowledge base cannot hold a private individual, and
every vendor is building one. A user-scoped private namespace is unavailable to
them by construction.

## Considered and rejected

**Token fan-out as the privacy gate** — a token may cross only if it heads *K*
distinct descriptors. It was proposed here on 2026-07-27 and **falsified by the
author's real vault the same day**:

- 116 heads lead exactly one key — ordinary single-location merchants, all of
  which the rule would have blocked from the commons.
- It admits `02`, `01`, `12` — bare month numbers, which would have been
  published as shared knowledge.
- `the` heads three keys, so head-keying merges two unrelated retailers. `card`,
  `atm`, `you`, `non` and `refund` do the same.

188 heads is too coarse and 492 keys too fine; **neither is a merchant.** The
deeper error is that it was a statistical re-implementation of the reflex this
codebase keeps catching — computing locally a piece of world knowledge that could
simply be asked for. It is recorded because the failure is instructive, not
because the idea is worth revisiting.

## What not to build

**Not merchant coverage.** Plaid enriches 500M transactions a day into a
knowledge base built over years. The goal is *this person's* few hundred
merchants plus the commons for the tail — which is Monzo's model, and the only
approach that structurally beats the long tail.

**Not a business on the fallback.** Enhanced merchant data is becoming a
regulatory floor. Consume it where it exists; parse where it does not.

## Sequence, and what each step decides

1. ~~**The date-fragment normalizer fix.**~~ **Done.** 492 keys → 365; 163 dated
   descriptors; every bare-numeric head gone. Version bump to `merch-v2`,
   read-side re-derivation, no re-ingest.
2. ~~**Count (institution × rail) pairs in a real vault.**~~ **Done — it is five**,
   two of them covering 83% of movements. So five grammars get hand-checked
   before induction is automated.
3. ~~**Build Layer 0 and measure its coverage.**~~ **Done, and it did not cancel
   step 4.** 80% of movements touched, but 88 keys at zero and 83 with scattered
   residue.
4. ~~**Induce the largest depository grammar, alone, first.**~~ **Done.** It
   returned the person slot, and reading it found the vocabulary gaps that
   `trace`, `company_id` and `counterparty_handle` now fill.
5. **Then the others**, on a rebuilt vault, `--best-of 3`, gated on withheld
   lines. Four inducible pairs, not five: an investment statement names no party.

## Done criteria

- No token from any occurrence attribute can reach the commons — enforced by a
  test that walks the export, not by review.
- All three of the corpus's structural transfers reach enrichment, where today
  all three are blocked.
- `PAGO A JUAN` and `VIREMENT A MARIE` do not cross, with no Spanish or French in
  the codebase.
- ~~A merchant with locations in many cities produces **one** commons row.~~
  **Met.** Enrichment keys on the brand slot, and the context that travels is
  only what every occurrence agreed on — a shop seen in one city keeps its city,
  a chain seen in five has none.
- A profile that cannot account for every character of its statement is never
  applied.
- A ruling on a party applies to every movement through every conduit that
  reaches them, retroactively.

## What the build changed  (2026-07-28, from a real vault)

Design survived contact in its shape and lost several of its parts. Recorded
here rather than quietly corrected, because the corrections are the useful half.

**Layer 1 works, and the person slot is real.** One induction call on the
largest depository grammar returned `ZELLE PAYMENT TO {counterparty}
{reference}` and `… FROM {counterparty} {reference}` — and, on the same rail,
`ZELLE PAYMENT FROM {brand} {reference}`, separating an organisation paying by
peer rail from the people. That distinction is the whole argument of this
document and no keyword list could ever have made it. Two halves of one lending
relationship, previously two unrelated keys, became one stream of eighteen
movements. **Twenty-six people are now named locally and never leave.**

**A rule this document proposed was falsified and deleted.** Stripping "the
bank's own words" from a brand candidate, by counting how many counterparties
print each word. On 1,076 real movements the ranking interleaves three
populations — bank sentence words, city names, merchant names — so no threshold
separates them; a cut high enough to keep merchants misses `ppd`, `web`, `ccd`,
`atm`, and a cut low enough to catch those deletes real brands. The count was
circular besides: it counted normalized keys, and normalization fragments one
merchant into many, so a merchant with fifteen spellings looked like fifteen
counterparties agreeing. Separating the bank's sentence from the merchant's name
is Layer 1's job, done from evidence with a lossless check, and Layer 0 should
never have attempted it.

**A keyword table nearly went back in, at the centre.** The channel — half the
stream key — was first derived by matching `\bcard purchase\b`, `\batm\b`,
`\bpaper check\b` against the text. English, classifying, load-bearing: the
exact thing `is_shareable` was. It now comes from structure only — the NACHA
tail proves ACH, Fedwire tags prove a wire, a DE43 structure proves a card, a
`{counterparty}` slot proves a peer rail — and where nothing proves a rail the
answer is `unknown` and stays there. The ATM and cheque distinctions were lost
and recovered for free: two lines matching one template came off one rail by
construction, so the *template* separates them without this codebase containing
the word "ATM".

**The word list survives in one place, and the distinction is worth stating.**
Where no grammar exists there is no slot, so nothing can say a line holds a
person, and a peer payment is indistinguishable from a shop. `is_shareable`
remains as the fallback for exactly that case. It was wrong as a *primary
mechanism* — answering with substrings, in one language, the question enrichment
exists to answer. It is defensible as a conservative answer to *"we cannot
tell"*, because then its errors cost enrichment coverage rather than somebody's
name. **A rule that guesses in place of knowledge is a bug; the same rule
declining to send when nothing is known is a safeguard.** Inducing a grammar
retires it for that institution.

**The vocabulary grew by contact, not by design.** A real ACH line carries two
ids at once, so `trace` and `company_id` are two names rather than one used
twice. A peer payment addresses somebody by name, phone, email or username — a
vocabulary with only a name slot sent the model looking for somewhere else to
put a phone number, and it found `{contact}`, which is a *merchant's* public
number. `counterparty_handle` closes that, and a template naming no party at all
promotes whatever it does hold, so grammars frozen before the fix are covered
too.

**Induction is stochastic, which the pack rules did not know.** The same prompt
over the same forty lines returned 27 templates at 84% one run and 33 at 82% the
next — and the second was written, because the gate is absolute and `latest`
wins by version number. A version must now beat the one it succeeds on the same
measurement, and a fifth of all lines are withheld from sampling *and* from
choosing between candidates, so the number reported estimates rather than
flatters.

**The drift detector this document claimed did not exist.** Coverage was computed
once and frozen into the profile; nothing ever ran it again. Two numbers now,
and the second is the one that moves: lifetime coverage barely twitches when a
bank adds a shape, because old lines outnumber new, while **recent** coverage
collapses immediately. A grammar at 84% lifetime and 40% on the last quarter
stopped working three months ago, and only one of those figures says so.

**Not every movement has a counterparty.** The two largest streams by count were
a person paying their own cards, and dozens of singletons were brokerage
activity lines where a capital-gain phrase minted a key of its own. Marked
`internal` and `activity` rather than dropped. Investment lines are refused a
grammar outright for the same reason: every name in the vocabulary asserts
something about a party, and a trade against a security has none.

**Storage moved.** Grammars and the catalog were under the product's home, which
said they belonged to the product. They are merchantcore's: a shipped seed
inside the package, committed, and learned data outside any working tree — so a
grammar carrying a name that slipped past the checks cannot be committed by
accident rather than merely should not be.

### What is still true, and what is still open

The four layers hold. Losslessness is structural, privacy is a slot name, and
identity is brand-level. What has *not* been closed: every quality gate measures
whether a template **matched**, never whether it **slotted correctly** — a
grammar can cover 90% of lines while putting cities in `{brand}` and pass every
check. Reading it is the only thing that catches that. So a grammar may be
induced and used unattended, and publishing one to the commons waits for a
person. *Refined 2026-08-12 — see* What a slot name may be believed about *below:
privacy is a slot name where the slot says a person, and a corroborated slot
where it says a business.*

## What the rail measurement changed  (2026-08-11, the same vault)

**A template standing in for a rail over-separates one merchant.** The rule
above is unchanged where nothing is proven, but it was applied per line, so a
merchant reached one way acquired a rail per template: a card purchase, a
recurring payment and a refund of the same merchant on the same card arrived as
three streams. The rail now falls back to the channel that merchant's *other*
lines on the same account prove, when they prove exactly one, before it falls
back to the template. The inference is bounded to one account at one
institution, so the same brand paid on cards at two banks stays two streams;
widening it across institutions is a later decision, not this one.

**An institution is a conduit, and the code was reading it as a party in two
places.** `PARTY_SLOTS` counted `{institution}` as naming the other side, so a
template naming a bank and a `{contact}` was read as naming somebody, and the
contact stayed a shop's public number rather than being promoted as a person's.
And `_slot_from` fell back to the institution when a grammar named no brand,
which keys every party reached over that bank's rail under the bank. Neither now
holds: where a grammar names no brand, `merchant_key` falls back to the whole
line, which still carries whoever was on it.

**The gate that is open is the one this document already named.** A stream key
that drops the party is the one error direction this engine may not have —
fragmentation still yields true statements about a merchant, while two parties
in one stream is a rhythm nobody has. The two rules above close the mechanisms
the resolver controls, and a test asserts the property over every slot the
vocabulary can name a party with. Neither reaches the case this vault actually
holds: an induced template labelled a slot `brand`, an institution's name landed
in it, and the party's name went to two slots the vocabulary treats as
impersonal. No guard over slot *names* can see a party in a slot that does not
name one — this is the "matched, never slotted correctly" hole recorded just
above, and only a person reading the grammar catches it. Accepted and open, not
closed; closing it means re-inducing that grammar. *Amended 2026-08-12:* a
second route exists and was not taken — the crossing is now gated on
corroboration, and narrowing what counts as corroboration withholds the hint
without touching the grammar. At the setting built, this case still crosses.

## What a slot name may be believed about  (2026-08-12, the same vault)

**A slot name may say a hole holds a person. It may not, by itself, say a hole
holds a business.** Believing `{counterparty}` costs enrichment coverage and
never a name, so it is believed. `{brand}` is the claim that goes the other way,
and it was believed on a model's word alone: the hole the section above left open
— a party's name in a slot the vocabulary treats as impersonal — reaches the
enrichment boundary, the catalog and the pending queue with nothing between it
and the crossing but a label a forward pass wrote.

So the crossing is now gated. Where a grammar named the brand, a hint leaves only
if a published format **read from each line behind it** says the other side was a
business: an ISO 8583 DE43 structure fired, or a NACHA line's Company Name field
came back with a value. The unit withheld is the **whole hint** — brand and
context together — because a party's name lands in whatever slot the model called
impersonal, and a hint's example is the brand followed by its agreed context
slots. Withholding the brand value alone would have sent the name in `{purpose}`.
Corroboration is not inherited: a stream's rail may be a channel a *sibling* line
proved, and reading that would certify a line by association, so the gate
recomputes the Layer 0 reading per occurrence out of the raw line it already
holds. Nothing about local resolution moves — the stream still keys on the brand,
the merchant key still forms, categorization still works. Only what crosses is
gated, which is the boundary T9 draws.

**The gate applies to every grammar, not only to one that demonstrably carries
people.** A card-only grammar names nobody and still makes the brand claim.
Measured over this vault: **43 of 235 hints and 169 of 863 movements (18.3% /
19.6%) stop crossing**, against 11 / 80 if the gate fired only on grammars with a
person slot. The errors this gate makes all have one shape — a genuine business
on a rail that proves nothing loses its enrichment — and that asymmetry, coverage
rather than a name, is the reason to accept the price.

**What this does not close, stated plainly, because a fence believed to close
something it does not is worse than no fence.** The second clause is weaker than
the first, and it is weak in exactly the way this document warns about elsewhere:
the Company Name / Entry Description boundary is not printed on the display line,
so `split_ach_heads` recovers it from the statement as a whole — an inference over
this vault's own values. It returned a value for every ACH line measured here, so
**an ACH line whose head is a person's given name is corroborated by it and
crosses.** The mislabelled template this cycle began from still crosses, and so
does the sibling line whose `{purpose}` holds a name. The durable rule the
measurement argues for is stricter — corroboration read from a published boundary
on the line, never recovered from what other lines look like — and this build does
not implement it. What it implements is the weaker true sentence: **the crossing
is gated, and the gate's evidence includes one signal inferred from the corpus.**

Two consequences follow and are carried rather than resolved. The maintenance
agent's enrichment step stays **out of the autonomous set**: with the crossing
still open, letting an unattended run reach it re-opens exactly what the hold
exists for, and anything that restores it says first what closed the crossing.
And the shape is built to be re-pointed — what counts as corroboration is one
predicate, `corroborates_a_business`, so narrowing it is a change in one place
and a re-measurement rather than a redesign.

**Two limits worth knowing before reading a withheld share as a coverage
figure.** Both clauses are US-scope by construction, and every corroboration in
this vault came from them; on a rail proving neither — UPI, SEPA — this gate
withholds every brand-slot hint, and no third signal exists anywhere in the code
to rescue it (I3, I5). And the gate only sees what a brand slot produced: where a
grammar's template names no brand at all, the key falls back to the whole
normalized line, which crosses without passing through this gate or the
substring fallback either.

Induction gained a companion that decides nothing: `uncorroborated_brands` prints,
per template, how many distinct lines put a party in a brand slot with nothing
published agreeing, for the person reading a fresh grammar. It cannot reach a
grammar already in force, and the counts are lines rather than a measure of what
the boundary withholds. `induce-profile-v3` adds the inbound peer-rail examples
rule 8 never had — all four of its worked examples pointed outward, and the model's
error mirrored them — and remains a repair to the prompt, not a fence.

## What the declaration reaches, beyond the crossing  (2026-08-13)

A slot name saying a hole holds a person was, until now, read at one place: the
gate above, deciding what leaves for a model. The rhythm read measured every
counterparty it could key, person or not, and what kept a peer relationship out
of it was that no catalog record existed under those keys yet — an accident of
what had not been bought, not a fence. Measured on this vault: **58
`(merchant key, direction)` flows carry movements from a person's stream, and
three of them clear the cadence floor.** The enrichment that would give them a
record is the same one the gate stands in front of.

So the declaration now travels with the keys. A resolver returns the map of
lines to merchant keys **and** the lines a slot named a party on
(`MerchantKeys`), because person-ness is knowable only from an induced grammar,
which lives on disk rather than in the event log — the projection could not ask
the question at all. `merchants.is_person` reads that, the rhythm read drops
those movements before any flow is formed, and a person contributes no
hypothesis, no question and no subject a ruling could be recorded under. It is
the same declaration `hints.py` reads, never a second way of asking. A resolver
returning any other mapping raises rather than defaulting to silence: a shape
that lost the declaration and a resolver that declared nobody are
indistinguishable, and the default would fail towards measuring a person.

**This makes the rhythm path as safe as the enrichment gate and no safer.** A
person's given name sitting in a `{brand}` slot is declared a person by nothing,
reads `is_person == False` everywhere, and still forms a flow — so the two keys
this vault holds could raise a rhythm question once a record exists and their
spacing clears the cadence floor, which would render a person's descriptor into
a sentence proposing they are a merchant with a billing model. That is the
accepted consequence recorded above arriving on a third surface, not a new one.

## The parts the code decided, and this document did not

Seven rulings that live in `merchantcore` and were argued nowhere else. Each one
looks like an arbitrary constant or a missing feature until the reason is stated.

**Why an investment line is refused a grammar, in full.** The refusal is recorded
above; the reason is that every name in the closed vocabulary asserts something
about a party or a place, and an activity line — `You Sold … Short-term gain: …` —
describes a trade against a security and holds no party at all. A
grammar induced over such lines would file a realized gain as `{purpose}` and a
security as `{brand}`, consistently, on every line that institution prints. That
is a confident wrong answer manufactured at scale. Instrument events need their
own vocabulary — security, action, quantity, price, realized gain — which belongs
to the deferred `instrumentcore`. Until that exists the honest answer is that no
grammar applies, which matches the `activity` marking the stream engine already
gives those movements. `INDUCIBLE_KINDS` is narrower in name than in function: it
now gates both whether a grammar may be induced *and* whether the kind's
merchants may be enriched, and was left un-renamed deliberately.

**Why `#` is kept out of the `merchant` shape.** Admit it, and `{brand} {city}
{region}` matches `SPICE RACK # 03453 WEST MONROE LA` with brand `SPICE RACK #
03453 WEST` and city `MONROE` — a greedy brand eating a word of the city. A
template that writes `#` as literal text with `{store_number}` after it parses the
same line correctly and costs no vocabulary. The general form: **every shape added
to `SHAPES` is a shape a model can misuse**, so the set is kept small by policy
rather than by accident. Related, from `SLOT_SHAPE`: `counterparty` is left on the
narrow `words` shape on purpose — widening the slot the privacy guarantee rests on
would let it swallow punctuation.

**Why `_MARKS` is a hand-enumerated list of codepoint ranges.** Python's `re` has
no `\p{M}`, and `\w` excludes combining marks, so a Devanagari virama or vowel
sign fails any shape built from `\w` alone. The alternative to enumerating
general-category-M ranges by hand is a third-party regex engine, and this package
takes no dependencies. The constant looks like an accident and is not.

**Why induction waits for thirty lines and settles for 80% coverage.** Below
thirty distinct lines, the sample *is* the population: training coverage means
nothing and a 20% holdout is three or four lines. The cost of waiting is quality
rather than function — a pair with no grammar still resolves through Layer 0 and
the normalizer. And the coverage gate is not 1.0 because a bank's long tail
contains genuine one-off lines; a grammar that honestly covers most of a statement
is worth more than one that claims all of it by being vague.

**Layer 1′ — a grammar borrowed from another bank.** This document describes four
layers and no borrowing; the code borrows, and it matters most for exactly the
population `MIN_LINES_TO_INDUCE` creates — an account too small to induce from.
Four rules govern it. A borrowed match is recorded as layer `grammar`, not as a
weaker layer name: it is structurally the same claim — the same closed vocabulary,
the same compiled expression, the same rule that a person is whatever landed in a
slot named for one — and every downstream privacy check keys on that word. The
bank's own grammar always wins, because it was measured against its own lines and
a borrowed one was not; where the borrowed one came from rides in `borrowed_from`.
And borrowed grammars are tried in profile-id order, so the answer never depends
on how a collection happened to iterate.

**A better layer must not return less than a worse one.** A grammar usually
absorbs the NACHA Company Entry Description into its literal text (`{brand}
PAYROLL PPD ID: {company_id}`), so the field leaves the slots — where Layer 0 had
it. `_slot_from` re-adds it from the statement-level `ach_split`. The principle
generalizes past this case: a higher layer displacing a lower one must not drop a
field the lower one proved.

**`word_owners` survives as a diagnostic that decides nothing.** The
strip-the-bank's-own-words rule was falsified and deleted, as recorded above. The
counting function remains, for the streams report only, under an explicit
prohibition: no rule may key on these counts. The reasons are the ones that
falsified the rule — bank sentence words, place names and merchant names
interleave by frequency, and the count is over normalized keys, which fragment one
merchant into several, so a merchant with fifteen spellings looks like fifteen
counterparties agreeing. It is kept because looking at the interleaving is useful;
it is fenced because acting on it is not.

## Deliberately out of scope

Merchant-as-Party unification. Attributes of a party beyond a name. Any attempt
to identify a *person* from a name — the product learns that a party exists and
what you say they are, and asks nobody else. Contribution of profiles to a
commons, which waits until the lossless check has been measured on real
statements.
