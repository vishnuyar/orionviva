# The Surface Charter

**State:** design-only
**Rules:** VOICE-136, VOICE-137, VOICE-138, VOICE-139, VOICE-140, VOICE-141

An outside review of this product's interface produced a long list of things
the interface should and should not do. That review is not tracked in this
repository, so nothing in the build can check a claim written in it and no gate
can hold anyone to one. This document is where the parts of it that were
accepted become rules and decisions the repository can see.

It carries three kinds of thing, and they are worth telling apart:

- **Six rules**, each with the argument that produced it directly beneath it.
  Five of them are about the interface's language and craft, which is not where
  this document's own subject would put them; they sit here because a person
  approves one artefact, and a stand-in reads one file to know its ceiling. The
  cost of that choice is that a rule sits away from the document that argues
  about its subject, and the price of the choice is that every rule here
  carries its argument with it rather than a pointer to one.
- **Decisions that are not rules** — what is deferred and what would bring it
  back, what was refused, what was found rather than ruled. A decision recorded
  here is not a checkable assertion about the product, which is exactly why it
  is prose and not a rule block.
- **A register of what the outside review got wrong**, so that no later cycle
  inherits an error from a document it cannot open.

**This charter is the ceiling of a stand-in's authority.** A delegated run may
rule inside what is settled here. A new or amended rule that is not ratified
here is escalated to the product owner, never decided in a run. The warrant
that grants a stand-in its checkpoints is the loop's business and belongs with
the loop's contract rather than here; what belongs here is the boundary it may
not cross, and this document is that boundary.

## Rules

### VOICE-136 — a destination and a control render only when the registry and a served read say so
**State:** contradicted
**Code:** `desktop/src/app/navigation.ts:3` hand-writes six destination memberships. Runtime standing is derived from the capability registry, but membership is not. The destinations table in [user-interface-implementation-status.md](user-interface-implementation-status.md) shows that `accounts` has neither its own live read nor a claiming capability and still ships; Activity and Trust now have both.
**Test:** none — the subject is what the interface renders, whose tests are TypeScript, and the rule index collects test names by parsing Python. The gate this rule wants is a comparison between the shipped destination list and the registry, and it belongs to the registry cycle.

1. Navigation is a projection of the capability registry. A destination appears when a surfaced capability claims it **and** its live read is served for this vault and this build.
2. An affordance appears only when the operation behind it is served and allowlisted. A control with nothing behind it does not render at all.
3. A destination whose live read already returns the person's own data stays visible, even where an action offered on that destination is unserved. The signal this rule tests is destination-level served-read, never per-capability maturity.
4. An empty vault's product is small and entirely alive. The absence of a destination is never explained in navigation.
5. The demo is a destination set of its own and does not widen the live product's navigation.

**Why a hand-written list is the wrong shape.** Six destinations are typed into
one array, and Accounts is not claimed as a destination by a surfaced
capability even though it is furnished from the overview read. A
person who opens Accounts is told the product has an accounts screen and then
told it has no accounts to put on it — twice, once by the door and once by the
room. Neither sentence is false and the pair is a lie about the product's size.
The rule's real content is that navigation stops being a promise somebody
typed and starts being a report of what is served.

**Why this is not covered by the rules that already exist.** VOICE-105 rules
that a read model declares a panel state and that *"A panel earns its existence
from data"*. That is the same argument one level down: it governs a panel
inside a screen and says nothing about the screen. VOICE-108 requires every
capability to have a destination or a recorded reason for not having one, and
is satisfied by a *declared* destination — a destination can be declared,
claimed by no capability, and shipped, which is exactly the state Accounts is
in. So neither rule can be stretched to cover this without changing
what it means; the assertion is new and needs its own id.

**Why maturity is the wrong signal, stated as clause 3 so it cannot be lost.**
The obvious implementation is to read per-capability maturity and hide what is
not `stable`. The architecture document says why that fails:
*"Reachable is the only thing maturity means."* Documents' action contract is
unserved, so its capability is not mature — and its live read works and shows a
person their own captured documents. A rule that hid Documents today would be
hiding the person's own data behind a signal about an action they were not
taking. The signal this rule needs is narrower than maturity and does not exist
yet: whether a destination's live read is served for this vault and this build.

**What building it will run into.** The two sides do not share a vocabulary.
The Python registry spells one destination `account`; the interface spells it
`accounts`. The maturity words on the Python side and the capability-state
words on the interface side have no term in common. A rule saying navigation is
a projection of the registry is a rule that the split has to close, and closing
it is the first work the gate needs. **The owner is the registry cycle.**

### VOICE-137 — one absence sentence per panel; the full account lives in Trust
**State:** contradicted
**Code:** Twenty-seven fields render as *"… not supplied by this read"* (twenty-six in the past tense, one in the present) across three interface modules: `desktop/src/features/review/Review.tsx`, `desktop/src/features/documents/Documents.tsx` and `desktop/src/components/EvidenceDrawer.tsx`. `desktop/src/features/documents/Documents.tsx:86` renders a six-item enumeration headed *"Unavailable in this preview"*. `desktop/src/app/App.tsx:277` carries a standing admission in the sidebar footer, on every destination at once.
**Test:** none — the subject is rendered copy and its tests are TypeScript. A count of absence sentences per panel is checkable against a rendered component, and that check has no owner until the craft slice.

1. A panel states at most one absence, in one plain sentence, and only when the absence changes what the person should do next.
2. Absent data that does not change what to do next does not render.
3. An enumeration of what this build cannot do lives on Trust and nowhere else.
4. The coverage line is the canonical absence sentence for the picture, and it is supplied by the backend rather than composed by the interface.
5. The per-panel admissions are retired only when Trust can carry the full account, and never ahead of it.
6. Nothing this rule suppresses may be a property of a figure. Grade, caveats, coverage, exactness and boundary are placed by the machine that holds them (X2), and they are not panel absence copy.

**Why honesty needs a budget.** The instinct behind twenty-six absence
sentences is right and its execution is self-defeating. Each sentence is true.
Together they make a screen where the loudest thing is the product apologising,
and a person reading eight consecutive apologies stops reading the ninth — which
is the one that mattered. Scattered honesty is spent honesty. The rule does not
reduce what is admitted; it moves the full account to one page whose whole job
is to carry it, and leaves in each panel the one sentence that changes what to
do next.

**Why the ordering clause is load-bearing.** Read without clause 5, this rule
authorises deleting the per-panel admissions immediately, and Trust does not
render live data today. That would trade scattered honesty for none at all, in
one commit, with this rule as the justification. Clause 5 makes the retirement
conditional on the destination that inherits the obligation being able to carry
it. It is also what makes this rule compatible with VOICE-112, *the surface
never claims machinery the product does not have*, whose second and fourth
assertions — that a Documents surface does not paper over capture being met on
originals and unmet on the ingest request, and that outbound accounting is not
claimed complete before it is — this rule **routes to one page rather than
abolishes**.

**Why clause 6 exists, and what happens without it.** X2 requires that a value
the arithmetic could not write exactly never reaches a person without the term
that says so, and that a property of a figure the machine holds is placed by
the machine. Read carelessly, this rule lets a panel suppress a figure's caveat
as one absence too many — the grade, the coverage line, the exactness term.
That is the one way this rule could make the product *less* honest than it is
now, and it is the reason clause 6 is a clause rather than a note. A property
of a figure is not absence copy and this rule never reaches it.

### VOICE-138 — the interface speaks about the person's money, never about its machinery
**State:** contradicted
**Code:** `desktop/src/app/App.tsx:212` tells a person *"Documents are not available in the current vault read."* `desktop/src/features/review/Review.tsx:94` tells them *"The contract supplies no mapping from this guidance to a specific question."* `desktop/src/features/review/Review.tsx:74` makes a raw question identifier a primary detail row. Four interface modules — `desktop/src/features/accounts/Accounts.tsx:37`, `desktop/src/features/activity/Activity.tsx:37`, `desktop/src/features/review/Review.tsx:28` and `desktop/src/features/trust/Trust.tsx:60` — render *identity conflicted* as a person-facing headline.
**Test:** none, and none is wanted in this shape. A build check for this rule would be a text match over component source, and that is refused; see the argument below.

1. Contract and delivery vocabulary does not reach a person on a primary surface: *read*, *supplied*, *contract*, *vault read*, *preview* used as a noun, *identity conflicted*.
2. No raw identifier is a primary label. Identifiers live behind an explicit details disclosure, where a person who wants one can ask for it.
3. The interface narrator and Viva are distinct voices. Viva's sentences stay persona-pack property (VOICE-10), and the narrator never speaks in the first person.
4. This rule bans the vocabulary and never the disclosure. A machine-placed property of a figure that today wears these words is rewritten in person-shaped words, never removed.
5. The word *surface* is outside this rule's reach. VOICE-133 already rules that it *"is never a word for something a person can see"*, and one rule holding that word is better than two that can drift apart.

**Why this is not a style preference.** The words in clause 1 are the names of
this product's own internals. When the interface says a read did not supply
something, it is explaining its delivery pipeline to a person who came to find
out about their money. The person cannot act on any of it: they do not have a
read, they cannot supply anything to one, and *preview* names a stage of our
work rather than a property of their vault. The test a sentence has to pass is
whether it says something about the person's money or something about how this
program is built.

**The collision that would otherwise delete a disclosure.**
`desktop/src/surface/evidence.ts:21` renders *"This read did not supply whether
the displayed figure is exact or rounded."* That sentence is a machine-placed
property of a figure, which X2 requires to be there, wearing exactly the
vocabulary this rule bans. A later cycle reading clause 1 alone would delete
it and believe it was obeying a rule. Clause 4 settles it in advance: such
sentences are rewritten in the person's own terms — what is known about the
figure, said plainly — and the disclosure survives the rewrite.

**What is refused, by name, so nobody adds it later believing it was
intended.** A copy rule that enumerates words this project must not print is
legitimate: it is a prohibition over our own output, not a classifier over
anyone's data. It stops being legitimate the moment it is enforced by grepping
component source for those words. The loop's own gate doctrine says why:
*"Matching text is always the cheaper way to write a check, and it fails in two
directions at once: a comment satisfies it, and a line break defeats it."* A
grep would pass on a paraphrase that says the same machinery thing and fail on
a code comment that says nothing to anyone. **Enforcement of this rule is a
person, not a pattern** — the Interface Designer, whose standing brief already
asks *"whether the app sounds like the product the site promised"*.

### VOICE-139 — the demo is a place, not a dialect
**State:** enforced
**Code:** product/viva/demo.py (`build_demo_vault`, `open_demo_vault`), product/viva/desktop_bridge/__main__.py (`_open_demo_vault`), desktop/src/surface/sources.ts (`sampleSource`), desktop/src/app/App.tsx (the frame)
**Test:** product/tests/test_demo_vault.py::test_the_sample_is_a_vault_the_engine_opens, ::test_the_frame_words_come_from_the_pack_rather_than_from_a_screen, ::test_a_private_open_carries_no_frame

1. The demo is entered deliberately, from one affordance, and inhabited inside one persistent, unmistakable frame.
2. Inside the frame, the copy is the product's own copy and the per-sentence fictional qualifiers are retired.
3. Institution and person names in demo data are self-evidently fictional.
4. Leaving the frame is one action, and nothing from the demo persists into a private vault.
5. **While the demo is frontend fixtures rather than a vault opened through the sidecar, the qualifiers stay.** Clause 2 waits on that, and on nothing else. The condition is met: the sample is a vault on disk, minted by the engine, opened through the sidecar and read by the same provider a private vault is, so the qualifiers are gone and the frame is true by construction.

**Why a dialect is the worse of two designs.** Qualifying every sentence makes
the demo unreadable as a product: a person evaluating whether they want this
thing is reading our disclaimers instead of the picture we are claiming to be
able to draw. A frame says the same thing once, permanently, and cannot be
scrolled past. It is also honest in a way per-sentence qualifiers are not — a
frame is a claim about the whole place, and a qualifier is a claim about one
sentence that quietly implies the unqualified sentences beside it are
different.

**Why clause 5 is a clause and not a plan item.** VOICE-121 rules that a
synthetic fixture proves rendering, never parity. While the demo is fixtures
composed in the interface, the per-sentence qualifiers are doing exactly
VOICE-121's work: they say, at each figure, that this number was authored
rather than read. Retiring them before a real demo vault exists would remove
the only honesty mechanism the demo has and replace it with a frame that says
*sample* while the numbers behind it were never read from anything. So the
condition is part of the rule: the frame becomes true by construction when the
demo is a vault the sidecar opens, and not before.

### VOICE-140 — craft is a gate: tokens, and keyboard reach
**State:** unmet
**Code:** The two stylesheets beside `desktop/src/styles/tokens.css` carry 145 raw `font-size` declarations between them — 30 in `desktop/src/styles/shell.css` and 115 in `desktop/src/styles/surfaces.css`. One literal `◎` stands in for an icon at `desktop/src/features/accounts/Accounts.tsx:34`.
**Test:** none the rule index can name — the index collects test names by parsing Python, and both gates this rule wants read the interface. The token gate exists: `desktop/scripts/check-style-tokens.mjs` runs in the desktop CI job, holds a stylesheet written against the token set to zero raw values, ratchets the two legacy stylesheets by a count that may fall and may not rise, and carries self-checks that each break one of its rules and assert it goes red. The keyboard check does not exist.

1. A type scale, a spacing scale, motion rules — including where motion is forbidden, which is near money and near grades — dark mode and iconography exist as tokens before a new surface ships against them.
2. A screen using a value its token system does not hold fails the interface check.
3. Every interactive control is reachable by keyboard and carries an accessible name.
4. Focus is not lost when a control becomes busy.

**This is the words document's confession made checkable.** That document ends
on the craft gap and says that naming it is not the same as closing it; now
that half the gate exists, it says which half. Nothing in the rule index covers
tokens, type, spacing, motion, dark mode, iconography or accessibility. This
rule is the whole of that territory, which is why it is the most expensive rule
in this document. The token file now holds a type scale, a spacing scale,
radii, motion durations and easings, a reduced-motion block, icon sizes and a
dark-mode block; what keeps the rule unmet is its second clause, because the
legacy stylesheets still carry raw values that would each have to find a token
to come from, and the gate reports how many rather than claiming the migration
is done.

**What was narrowed, and why the un-narrowed sentence is not a rule.** The
proposal was that *a surface a keyboard cannot fully drive fails*. That cannot
be a rule here, because *fully drive* has no mechanical definition and a gate
that cannot report a specific failure is not a gate — it is a sentence that
goes green forever. Clauses 3 and 4 are what a rendered-component check can
actually hold: reachable, named, and not blurred at the moment the control
becomes busy. Clause 4 generalises the reasoning VOICE-135 already made about
one attribute — a focused element that becomes unavailable empties a person's
hands at the moment a refusal needs them full — and makes it a property of
every busy control rather than of one attribute. The un-narrowed sentence
survives as the Interface Designer's standing question, asked of every diff
that touches the interface, and it is deliberately not a rule.

**The owner, named because otherwise this gate has none.** The other gate this
charter names belongs to the registry cycle, which is backend work. This one
does not: a token check and a keyboard check read the interface. **Its owner is
the craft slice**, which is a surface slice and not a backend item, and naming
it here is what keeps it from falling between the two.

### VOICE-141 — the receipt goes to the passage
**State:** unmet
**Code:** `product/viva/surface/models.py:48` declares `Citation` — the only figure-to-document route that crosses the surface contract — with `document_id`, `page`, `label` and `relation`, and no region of any kind. `product/viva/ledger/events.py:45` declares `Provenance.region`, and of the 38 `Provenance(...)` construction sites in `product/viva`, none passes it. `desktop/src/surface/evidence.ts:23-24` already resolves a figure into ready, missing or conflicted and a document into five named states, which is the second assertion already honoured by code this rule did not cause.
**Test:** none — the mechanism is not built, and the part that is missing is in the ledger rather than in the interface.

1. Where the ledger holds page and source-region data for a figure, the receipt terminates at the highlighted region of the document page rather than at the document.
2. A receipt that cannot resolve renders as a first-class failure state and never silently degrades.
3. Depth is layered: the grade badge, then the drawer carrying the reviewed sentence, coverage and caveats, then the source page.
4. **This rule waits on the ledger, not on the interface.** Clause 1's antecedent is satisfied nowhere today, and no interface work can satisfy it.

**Why the dormancy is written into the rule.** The proposal arrived with the
claim that the backend already models source regions. It does not. Pages are
modelled and regions are not: the contract's citation type has no region field
at all, and the ledger's provenance type has one that nothing writes.
ING-12 — *provenance anchors to measured character boxes where a text layer
exists* — is unmet, and PROG-9 is contradicted at the same seam, with page and
region written onto benchmark claims and read by nothing. So clause 1 is
vacuously true: it binds nothing, and it will keep binding nothing until an
ingest change that no plan currently names. Without clause 4 a later cycle
reads this rule as a surface task, opens it, and discovers the ledger cannot
supply what the rule asks the interface to render.

**Why it was kept rather than dropped.** A rule nobody can violate today is
still the design decision about where a receipt terminates, and that decision
is cheaper to make now than to re-argue when the ingest work starts. What it
costs is the risk of being read as available work, and clause 4 is the whole
of the mitigation.

**What it does not claim credit for.** Clause 2 describes behaviour the build
already has. It is stated here so that the property is held rather than
incidental, and the **Code** field says plainly that the code got there first.

## The two rules this charter amends elsewhere

Two of the accepted proposals are not new rules and do not live here. A reader
looking for them finds a pointer rather than an absence.

**A control that cannot act does not render** is an amendment to VOICE-135,
which [the-words-the-interface-uses.md](the-words-the-interface-uses.md) owns.
It keeps its id, because its subject — how a control tells a person it is
unavailable — has not changed; only the answer has. The amendment retires
VOICE-135's first assertion, that a control this screen cannot perform at all
carries `disabled`, and reserves `disabled` for nothing. A control that is not
here does not render at all, which is VOICE-136's business. The busy half of
VOICE-135 is untouched, including its third assertion, that a control carrying
`aria-disabled` refuses the second press in its own handler and says in words
that it did.

The amendment is made in that document, under the same id; the rule's name
follows its answer and now reads *`disabled` is reserved for nothing;
`aria-disabled` says a control is busy*. This charter does not hold the rule:
the index points at the words document, and the charter's own **Rules:** header
does not name VOICE-135.

**The interface names no capability a later phase will have, including as a
coming-soon** is an amendment to VOICE-112, which
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md)
owns. It arrived as a proposal for a rule of its own, about the trust arc
having no surface presence before its gate passes; three of its four sentences
were already ruled — VOICE-112 already forbids claiming anchoring, SPINE-9
already gates the phases past the product on earned trust, and ADR-008 already
establishes that nothing may promise more than it holds — and the fourth is the
sentence above. It lands as a fifth assertion on the rule whose name is
literally *the surface never claims machinery the product does not have*, which
is where a person would look for it.

That assertion is added in that document too, for the same reason: a rule is
held in one place, and this charter is not that place for either of them.

## The hide-list, and what each row rests on

The outside review proposed a list of things to remove or hide. It splits three
ways, and the split matters: recording a row that an existing rule already
settles would create a second copy of that rule, free to drift from the first.

### Already settled by an existing rule

This charter points and decides nothing.

| Row | The rule that already settles it |
| --- | --- |
| A converted grand-total net worth | MON-89, *subtotal per currency; never convert*, which is enforced by a test |
| Engagement mechanics, streaks, notification badges | VOICE-113, whose first clause removes push notifications, streaks, urgency badges and engagement mechanics from future consideration |
| Direction filters and direction in a transaction detail | VOICE-111, whose second clause forbids shipping either before the site that derives direction from a posted sign is closed |
| An "Ask Viva" affordance with nothing behind it | VOICE-136 above |
| Per-panel enumerations of what the build cannot do | VOICE-137 above |

### Ordinary deferrals

One ruling covers the set: none of these deviates from a promise the project
has made, none needs a rule, and each is a brief nobody has written yet. They
are deferred because they are unwritten, not because they were judged and
found wanting.

Email capture, watched-folder capture and phone capture; the demo's pedagogy
blocks; Settings as a destination of its own; and the capability table, which
stays where it is.

### Taken by name

**Voice is not deferred.** The proposal to defer voice whole was rejected. See
the section below.

**Drag-and-drop is decided in the open, in the capture brief.** It must be
decided rather than skipped: it is the gesture the site sells, and the vision
names it first among the capture paths. The technical answer is not knowable
today. The boundary checker, driven with synthetic sources, rejects `onDrop`
and `DataTransfer` along with every other file API, so the question is live
rather than theoretical: whether a window-level drop caught by the host and
routed through the same shim — with bytes never transiting the webview —
satisfies the fence's *purpose* is what the capture brief has to answer, with
the checker still passing as the acceptance test either way. This is a
procedural decision and not a rule, because *the next brief must not skip this
question* is not a checkable assertion about the product; the half that is
rule-shaped, that bytes never transit the webview, is already the checker's
job. **If the capture brief defers the question, it states the reason here.**

**The suggestions channel is deferred, with a measured return condition.**
VOICE-83, VOICE-84 and VOICE-85 are all unmet, so nothing claims otherwise
today and ratifying the deferral costs nothing. What it buys is that a stand-in
cannot be talked into building the channel early, and that its return condition
is a measurement rather than an opinion: **after a live answer path exists, and
when the refusal ledger says how much the channel is owed.**

**One thing to notice about that return condition.** The refusal rate appears
in three places wearing three hats: this channel's return condition, a criterion
of the staging the review proposed, and an acceptance condition for the
conversation work. It is one missing capability, and it should be built once.

## What this charter deliberately does not ratify

### The sequencing

The gap ledger says of its own priority order that *"If this order ever moves,
it moves whole"*, and names the single condition that would move it: it rests
on the near-term first user starting with no vault at all, and if the first
real users arrive with vaults already built at the terminal, the
figure-and-citation work leads and ingest moves down. **That condition was
tested and found unmet: a stranger comes first.** The ledger's order therefore
stands, document ingest keeps the lead, and the staged order the outside review
proposed is not ratified. Nothing in
[backend-capability-gaps.md](backend-capability-gaps.md) is edited, because it
is already correct as written. The finding is recorded here so that no later
cycle re-litigates it.

### The stage gate

With the order unratified, the operational shadows of the trust event that the
review proposed as a gate are unruled, and they are not in this charter. **A
stand-in may not treat them as a gate, and may not treat the two-stage
structure as ratified either.**

### The tension this ruling creates, named rather than smoothed

SPINE-9's first assertion is that *"The first non-author user waits on the
trust trial having closed"*. SPINE-8 says that trial closes on an event: the
author believes an answer about his own money without re-checking it. SPINE-7,
*the eval harness ships before the first user who is not the author*, is unmet.
Taken together, a stranger cannot actually precede the trust trial. So
*a stranger comes first* is a ruling about **what gets built, and for whom** —
not about who opens the application first.

Its direct consequence is that two items the review parked in the far tail rise
to near-term. **Vault export and backup**, because a public preview inviting a
stranger's real documents while a forgotten passphrase means total exportless
loss is a liability rather than a hiding decision. And **the honesty harness**,
because SPINE-7 gates any non-author user on measuring the confidently-wrong
rate, and no amount of distribution work satisfies that gate.

### What is owed, and whose it is

A re-derived work order, drawn from the gap ledger's own priority list under
the stranger-first premise. It is not this charter's to write. It is owed as
its own design cycle, and it lands **before the first build cycle draws from
the review's item order.**

### One case that survives the re-sequencing

The review's most consequential sequencing claim — that the builder's real
vault already holds recorded model egress, so the outbound ledger is owed now —
has verified machinery and an unverified fact. Terminal ingest writes one
recorded-read event per single-phase read and two per two-phase read; a
projection composed over those events rendered model, phase, prompt version,
cost, tokens, parse status and document, and survived a close-and-reopen.
Whether the *real* vault holds those events, how far back, and at what cost, is
a fact about encrypted contents that only the Witness may open, and two
conditions gate it in code: the writer fires only where a model actually ran,
and the reader factory parks unless the model environment is configured. The
Witness can settle it in one pass — a count of recorded-read events by phase,
the earliest and latest occurrence, the distinct models, and the summed cost.
**This charter records the case; it does not run it.**

## Voice is not deferred

The proposal to defer voice whole named itself a deviation from the vision's
*text and voice from day one* and from the architecture document's *first
public experience*. It was rejected. Three consequences are recorded here:

**The architecture document's sentence stays true and is not corrected.** It
reads: *"Text and voice both belong to the first public experience, with spoken
answers mirrored in text so their evidence stays inspectable."* VISION.md is
untouched, as it would have been either way.

**VOICE-34 stops being a return condition and becomes work that is owed.** It
reads: *"Text and voice share one session and one runtime. Every spoken reply
is mirrored in text so its evidence stays tappable."* It is unmet, and it is
owed rather than parked.

**The plan has a hole in it that the plan does not know about.** The outside
review planned for voice nowhere: its first stage excluded voice explicitly and
its second added no surface beyond distribution. Rejecting the deferral
therefore leaves voice, and the mirrored-text provenance design VOICE-34
requires, **owed and unbriefed**. No stand-in may close that hole by treating
the review's silence as a decision.

## The gates this charter does not build

Two gates are named in the rules above and neither is built by the cycle that
writes them. Each is named with its owner, because a gate with no owner is a
sentence.

- **The destination-level served-read comparison** that VOICE-136 wants —
  whether what the interface ships is what the registry and the served reads
  support. It is backend work and it needs the `account`/`accounts` split
  closed first. **Owner: the registry cycle.**
- **The token check and the keyboard check** that VOICE-140 wants. Both read
  the interface rather than the product. **Owner: the craft slice**, which is a
  surface slice and not a backend item.

No rule in this charter is enforced, and none may be promoted to enforced by
citing a desktop test: the rule index collects test names by parsing Python
files, so a rule about the interface either names nothing the index recognises
or names a test no Python file defines. **`by-review` is the ceiling these
rules can reach today**, and none of them has reached it, because each is
either contradicted or unmet.

## What the outside review got wrong

A short register, so that no later cycle inherits an error from a document it
cannot open. The review's audit of this repository was unusually accurate —
every structural claim that could be executed came back true, including the
hard ones about the bridge, the registry vocabulary and the direction site —
which is why the exceptions are worth naming precisely.

**Refuted — the vault-open failure triple.** The review says one failure code
covers a wrong passphrase, a missing directory and a corrupt vault alike. Two
of three are true. **A missing directory is not a failure at all**: opening a
vault creates the directory, so a mistyped path answers with an opened state
and silently hands the person a brand-new empty vault. That is a different and
arguably worse defect than the one the review names, and the acceptance
criteria it drafted for failure typing would not have caught it. **This is a
bug and not a charter question.** It is parked for the Reporter, and no fix
rides along with this charter.

**Refuted — source regions.** *The backend already models source regions and
pages* is half true. Pages, yes; regions, no. See VOICE-141 above, whose
dormancy is the consequence.

**Qualified — the ownership of the eval-harness rule.** The review attributes
SPINE-7 to `phases.md`, which explicitly handed SPINE-7, SPINE-8 and
SPINE-9 to [implementation-roadmap.md](implementation-roadmap.md) and whose own
rules header reads none. An honesty-harness item owned *where the eval designs
already live* points at a document that gave the rule away.

**Qualified — "purpose" is not a field.** The recorded model-call event carries
no field of that name. The nearest is `phase`, a closed three-value vocabulary.
Model, cost, verbatim response, tokens and parse status are all present as the
review claims.

**Qualified — the escape hatch's reach.** *Explore fictional sample data* is
present on three of six destinations rather than on nearly every empty screen.
It is on every live empty state that exists, which is the substance of the
claim; but a deletion pass touches less surface than the wording implies.

**Qualified — a duplication inside the proposals themselves.** Two of the
proposed rules asserted the same sentence, that a missing value renders as
absence. It lands once, as VOICE-137's first assertion.

## What this charter leaves owed

Nothing here blocks the build. Four things leave this cycle owed, and each is
named so that it is record rather than memory.

- **The re-sequencing cycle** — a work order re-derived from the gap ledger
  under the stranger-first premise, with vault export and the honesty harness
  risen to near-term. Owed before any build cycle draws from the review's
  order.
- **Voice, and the mirrored-text provenance design VOICE-34 requires** — owed
  and unbriefed, because the review planned for neither.
- **The publication of the stand-in's own role file** — it is untracked, so a
  warrant naming it points at something no clone, no build and no reviewer can
  read. That is half a rule until it is published, and more pressing now that
  the role may authorise a commit at all.
- **The vault-open defect above** — an intake for the Reporter, since filing is
  publishing and publishing is the product owner's gate.

Two smaller candidates, recorded and not scheduled: teaching the documentation
guard to recognise the desktop suite, so that these rules could one day exceed
`by-review` — whoever takes it starts from `product/tests/test_surface_contract.py`,
which already reads `desktop/src/bridge/contracts.ts` to compare two
declarations; and the Witness pass over the real vault's recorded model calls,
which the re-sequencing cycle will want.
