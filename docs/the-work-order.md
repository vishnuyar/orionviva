# The Work Order

**State:** design-only
**Rules:** none

## Rules

This document defines no rule, amends none and retires none. It is a build
order: a sequence of items, each of which is a full design cycle with its own
brief and its own approval before any code is written for it. Every rule it
leans on is held somewhere else, and it names that place rather than restating
it, because a rule restated in a second document is a rule free to drift from
itself.

It also holds no priority order of its own. The priority order belongs to
[backend-capability-gaps.md](backend-capability-gaps.md) — the gap ledger —
and this document derives a sequence from it under a premise the
[surface charter](surface-charter.md) settled. **Where this document and the
gap ledger disagree about what the interface is owed first, the ledger wins**,
and the disagreement is a defect in this document rather than an amendment to
that one.

Two things follow from that, and they are the whole contract of the file. Every
item below **names itself in full**, in words a reader with only this repository
can act on. And every item's **placement names its tracked ground in one
clause** — a rank in the gap ledger's priority order, a sentence in the charter,
or a rule id that resolves in [the rules index](rules.md). A placement with no
tracked ground is not a placement; it is a preference, and this document has no
standing to hold one.

## What this is derived from

An outside review of this product's interface proposed a plan of backend items
and surface slices. That review is not tracked in this repository: no gate can
hold a claim written in it to anything, and a reader here cannot resolve one of
its labels. **Nothing below carries a label from it, and nothing below counts
its contents** — a count taken from a document nobody here can open is a
confident figure with no source anyone can check, which is the failure this
product exists to prevent. The charter is where the parts of it that were
accepted became rules and decisions this repository can see, and the charter is
what this document draws on.

The review's plan was sequenced on the premise that the near-term daily user
already has a vault built at the terminal. The gap ledger names the same
premise from the other side, in its own words: *"It rests on one answer: the
near-term first user starts with no vault at all"*, and the single condition
that would move it is the first real users arriving with vaults already built
at the terminal. The charter records the outcome of testing that condition:
*"That condition was tested and found unmet: a stranger comes first."* The
ledger's order therefore stands, document ingest keeps the lead, and the
review's staged order is not ratified.
What the charter records as owed is *"a re-derived work order, drawn from the
gap ledger's own priority list under the stranger-first premise."* This is that
document.

**The tension the order honours rather than smooths.** *A stranger comes first*
cannot mean a stranger arrives first. Three rules in
[implementation-roadmap.md](implementation-roadmap.md) make that impossible:
the first non-author user waits on the trust trial having closed; that trial
closes on an event and not on a date, the event being that the author believes
an answer without re-checking it; and no stranger tests the product until a
continuous honesty harness exists with the confidently-wrong rate as its
headline — which is recorded unmet. The charter states the resolution: the
ruling is *"about what gets built, and for whom — not about who opens the
application first."*

The finding that shapes the sequence is that these are the same work far more
often than either the review or the ledger noticed. The export that would
protect a stranger's documents protects the vault the author is being asked to
depend on. The harness that gates a stranger is what turns the author's belief
in an answer into evidence rather than mood. Neither is a detour from the loop;
both are on it, and both sit in a lane the loop does not queue behind.

## What already exists, so that nothing below is rebuilt

**The engine is built and the transport is not.** That is the gap ledger's
central claim, and it holds: every capability it classifies as existing
resolves, every one it classifies as absent does not. Upload parks correctly
with no reader configured and returns the held-and-unreadable sentence; the
reconciliation sweep returns identical counts on two runs and opens no network
socket; the reader factory parks in two of its three configurations; the
net-worth read returns a dated point with per-account lines and the hash each
proves against. **Every sentence in that list is a claim about the running
product, taken against a scratch vault of synthetic accounts** — no role in this
cycle opened a real vault, so none of it is witnessed, and an item that would be
sized differently if one of them were false says so in its own brief.

**The surface contract machinery is real and it is small.** One tuple in
`product/viva/surface/capabilities.py` names the capabilities carrying the
surface disposition. One tuple in `product/viva/surface/operations.py` declares
the read operations and derives one operation per registry-declared action.
Exactly one declared operation serves any contract at all, and it serves two,
which is why two capabilities read as mature and the rest do not.
`declared_contracts()` is a different function returning the contracts the
registry *declares*; reading it as the served set makes the table look far
richer than it is.

**What a person can actually do.** Six destinations are hand-written in one
array. Two reads are served live and one write is served; the declared but
unhandled actions for answering, uploading and maintenance all refuse as
operation-not-allowed, and declining a question answers properly. The desktop
declares no capabilities read at all, and its capability vocabulary shares no
term with the registry's. **Those refusals were driven against the built
sidecar** — real frames, real dispatch, no real vault behind them.

**The progress channel produces events and drops them.** Started, completed and
failed frames are written and every one falls through the host, which returns
only the frame matching a request id and carrying no event key. There is no job
registry, no cancellation and no retry. **That path was read in the code, and
its absences are recorded in the status document's own gap row and, for retry,
in the gap-ledger rank the job registry item cites**, rather than watched with a
person waiting on a screen.

**Four of the areas this order promotes have nothing behind them at all.**
Nothing exists for vault export, backup or restore. Nothing measures a
confidently-wrong rate over a vault and nothing computes a refusal rate at all.
Update lifecycle and a sidecar-reported build revision exist on neither side.
And voice exists nowhere: every audio, speech, recording and synthesis token
searched for returns nothing across every tree, and a session is text in and
text out end to end.

**The demo a person opens is not one of those four.** What a person opens today
is a hand-authored fixture module declaring its own boundary as a fixture — one
state, not the set the architecture document enumerates — but a fictional vault
already crosses the real dispatch, and that parity fixture is the seed the demo
item builds on. What is missing there is the remaining enumerated states and a
persistent on-disk home, not the machinery.

Two things already run, and the items that touch them are cheaper than they
look. **Packaging and signing exists**: release metadata validates for its
targets, fails closed without secrets, and the release workflow imports
certificates, notarizes and publishes a draft. And **a fictional vault already
crosses the real dispatch**: `scripts/generate_overview_parity_fixture.py`
builds a temporary vault from real event constructors over eight account
shapes, reads it through real bridge dispatch, and byte-compares against a
committed fixture that both suites read.

**Two standing blockers are already ruled and are not this order's to reopen.**
Direction filters and a transaction detail speaking direction may not ship
before the one site that derives direction from a posted sign closes — VOICE-111
holds that, and M2 is the invariant underneath it. And the per-panel admissions
are retired only when Trust can carry the full account and never ahead of it,
which is VOICE-137's fifth clause.

## What has landed

Every position in the table below has been built. The order stands as written —
positions are stable labels, and a reader tracing why a thing was built when
needs the sequence intact — but the table is now a record rather than a plan,
and the ground each item names is the ground it was actually built on.

Two placements turned out differently in the building, and both are recorded
where they happened rather than only here. The demo item was **larger** than
"the remaining enumerated states": making the demo a vault removed the reason
every screen had a second implementation of itself, so the item that added a
vault also deleted a dialect. And the last three positions were, as the
corrections below predicted, three different things — a green-field read model,
a comment turned into a check, and a check whose subject is the artifact rather
than the tree.

What remains open is what this document already lists as not scheduled, plus
what each item's own commit records as its shortfall.

## The order

Positions are stable labels inside this document. The sequence is carried by
the predecessor clause, not by the numbering, and the numbering is not a
schedule. **Every item is a full-lane cycle with its own brief and its own
approval**, because the roadmap requires each to be *"designed in detail with
the author before any code is written for it."* **This is a sequence of briefs,
not a licence to build.**

Inside the surface-contract lane described below, the strongest relation two
items can have is **immediately behind**. That lane has one writer at a time, so
no clause in this table ever places two of its items alongside each other, and a
clause that reads that way is a defect in this document rather than a licence.

The class column names an acceptance class, defined below. It is deliberately
not an acceptance criterion: criteria belong to an item's own brief at its own
approval, and a work order carrying them quietly becomes a set of pre-approved
briefs.

| Position | The item, named in full | Its tracked ground | Placement and predecessors | Class |
|---|---|---|---|---|
| **5a** | **The passphrase consequence, stated where a vault is created.** The desktop's vault-open form at `desktop/src/app/App.tsx:243` is also the creation path, because opening a vault creates the directory. | VOICE-112, unmet, whose third assertion is *"Passphrase recovery is stated as it exists: today, losing the passphrase loses the vault"*; and the encryption decision's own exception, which records no keychain wrap and no recovery phrase, so *"a lost passphrase is a lost vault"*. | Lands **with or before the capture item**, because that item is the invitation. No engine work; frontend only. | a |
| **5b** | **The vault round trip — export, and a restore that is verified on a copy.** | The same ground as 5a: the custody half of the encryption decision is outstanding, and the charter raises export to near-term because inviting a stranger's real documents while a forgotten passphrase means total exportless loss *"is a liability rather than a hiding decision"*. | After 5a. Engine half runs in the second lane; the moment it declares a capability it joins the single-writer queue. Its acceptance never touches the real vault in place. | b |
| **—** | **The craft slice** — type scale, spacing scale, motion rules including where motion is forbidden, dark mode, iconography, keyboard reach, accessible names, and focus retained when a control becomes busy. | VOICE-140, unmet, which fixes its own timing in its first clause: these exist as tokens *"before a new surface ships against them"*. The charter names the craft slice as the owner of the check. | Not a position. Lands **before the first item below that ships a new screen**, which is the capture item. | a |
| **1** | **Capture and park, through the designed path** — the upload handler returning immediately, the native picker at the host shim, bytes sealed by the sidecar and never transiting the webview, the documents composer, and the parked sentence on a screen for the first time. Drag and drop **decided**. | Gap-ledger rank one, *"Document ingest and its job channel"*; VOICE-114, whose exception records that the parked wording is owed by a Documents surface that does not exist. | No model, no configuration, no money. **This brief meets a reserved interface unknown first** — see below. If it must defer drag and drop, it parks the question and stops, rather than editing the charter or proceeding as though deferred. | a |
| **2** | **The figure and its citation complete the overview** — net worth on the live path and the coverage strings supplied by the backend. **Recent activity is deferred by decision to position 15** and is not narrowed out of this row: a gap that stops being reported because it was deferred looks exactly like a gap that was closed. Its ground is that every rendering the interface has for such a row speaks direction, which VOICE-111's second clause forbids while the direction site stands; that the glyph ratchet has no slack for a row marker; and that gap-ledger rank two reaches a figure and its citation and no further, activity being rank six — on which this document's own tie-break says the ledger wins. | Gap-ledger rank two, *"A figure reaches the screen with its citation — and this may not land later than the first"*; VOICE-137's fourth clause, that the coverage line is supplied by the backend rather than composed by the interface. | **Immediately behind the capture item, with nothing between them.** The ledger's clause is an obligation about what a person is shown, so neither reaches a person until both land. | b |
| **3** | **The job registry and the progress channel**, built with its first real producer, carrying the recorded channel defects: events produced and discarded, no job registry, no cancellation. | Gap-ledger rank one, which names the absent half — *"a job registry, cancellation, retry states and real progress granularity do not exist, and the progress channel is designed inside this work rather than ahead of it"*; the status record's own gap row at `product/viva/desktop_bridge/surface_read.py#JobProgressEvent`. | **Behind the figure**, third in the lane and never beside either item. Its ground is a design coupling rather than an ordering one: a channel designed inside the work of its first real producer is satisfied by a producer that landed a cycle earlier as well as by one landing beside it. Capture returns and parks, and the granularity this channel owes is owed to the reading half, which is far behind it either way. | a |
| **4** | **The desktop consumes the capability registry**, closes the `account` and `accounts` spelling split, derives navigation from a destination-level served-read signal, **and the sidecar reports its source revision in the handshake**. | Gap-ledger rank three, *"The surface stops claiming machinery the product does not have"*; VOICE-136, which the charter assigns to the registry cycle along with the destination gate; VOICE-110's exception, which already names the missing revision home. | Single-writer queue. The revision lands in `product/viva/desktop_bridge/handlers.py#_handshake`, so it is **not** parallel with other registry work. | a |
| **6** | **Rescan reaches a screen.** | Gap-ledger rank one, and the ledger's rescan entry beneath it, which labels rescan part of the document journey and records that it needs a reviewed read model over counts the sweep already returns. | Belongs to the document journey rather than to Activity, which does not wait on it. | a |
| **7** | **The outbound record** — a projection over recorded model calls, with the honest absences encoded in the read model rather than composed by the interface. | The fourth public promise of the promise inventory: *"the complete outbound record is always visible in the product"*; T6. Gap-ledger rank seven carries the rest of Trust. | **Hard predecessor of the configuration item.** Also unblocks retiring the scattered per-panel admissions, which VOICE-137's fifth clause forbids before Trust can carry them. | b |
| **8** | **Application configuration: model, locale and currency** — the permission to send bytes arriving as a proposal a person says yes to. | Named inside gap-ledger ranks one and four; X3, that an irreversible action waits for an explicit yes; X1, unmet, that no feature may require a terminal or knowing what an API key is. | After the outbound record. **Carve-out:** a locale-and-currency-only slice may precede it **only if** it introduces no code path by which an adapter or a credential reaches `product/viva/ingest/reader.py#build_reader`, with the parking behaviour in the unconfigured cases still holding. Structure, not a promise to behave. | a |
| **9** | **Ingest's reading half** — a configured reader posts a real statement, with the contribution shown on the row. | Gap-ledger rank one; T6, which the ledger says makes a configured reader *"a decision rather than an implementation detail"*. | After configuration. First window in which the product spends money. | c |
| **10** | **Review answering, and the vocabulary tokens it needs.** | Gap-ledger rank four, *"the review queue is the loop by which every figure on every other surface gets better"*. | No model. | a |
| **11** | **Review answering in a person's own words**, with the review composer supplying the stake sentence. | Gap-ledger rank four, which records that answering *"is now behind configuration rather than behind transport"*. | After configuration. | c |
| **12** | **The conversation crosses the bridge**, carrying the mirrored-text provenance design as its design half. | Gap-ledger rank five, whose conversation entry attaches the obligation there: *"a spoken answer has to be mirrored in text so its evidence stays inspectable, and that is design rather than plumbing"*; X2's second assertion. | After configuration. **Rejection condition:** a turn shape with nothing a second modality can attach to. See the corrections below. | c |
| **13** | **Voice, as one modality on one session.** | VOICE-34, unmet: *"Text and voice share one session and one runtime. Every spoken reply is mirrored in text so its evidence stays tappable."* | After the conversation item. The local path is sized first; a path reaching a remote provider is escalated and not decided in a run. | c / d |
| **14** | **The direction site closes** — implication derived from the account's kind, with a structural guard rather than a comment. | VOICE-111, unmet, and M2, whose exception names the one outstanding site. | Independent of everything else. Runs in the second lane at any time. | a / b |
| **15** | **Activity's unblocked half**, then its direction half once the direction site closes. | Gap-ledger rank six, *"Activity and organization, split, because half of it is blocked"*. | After the registry item; the direction half after the direction site closes. | a |
| **16** | **The honesty harness, made vault-facing — and the refusal rate, built once.** | SPINE-7, unmet, and its own exception: *"the harness exists on one surface only … Nothing measures the confidently-wrong rate over a live vault"*; the charter's note that the refusal rate *"is one missing capability, and it should be built once"*. | **Partial, not absent** — see the corrections below. After the conversation item, because there must be answers to grade. Gates the exit of everything above it. | c |
| **17** | **Trust's remainder** — the maintenance run, external anchoring stated as absent in plain words, and diagnostic export. | Gap-ledger rank seven, with its caveat that a promise surface built before the promises are all true is the failure its third rank exists to prevent. | After the outbound record. | a / b |
| **18** | **The demo vault a person opens** — the remaining enumerated states, and a persistent on-disk home for a fictional vault opened through the real sidecar. | Gap-ledger rank eight, whose slice is named for the installable shell and the demo vault; VOICE-139, dormant by its own fifth clause: *"While the demo is frontend fixtures rather than a vault opened through the sidecar, the qualifiers stay."* | **Not green-field** — see the corrections below. | a |
| **19a** | **Update lifecycle and recovery states.** | Gap-ledger rank eight; the fifth of the five properties the ledger says the backend owes the shell, explicit lifecycle and recovery states for native install and update. | Green-field on both sides. | a |
| **19b** | **Packaging and signing, finished.** | Gap-ledger rank eight, *"Correctly last: it turns a working product into a distributable one"*. | **Exists and runs** — finishing work, not a build from nothing. | d |
| **19c** | **Packaged-artifact validation.** | The architecture document's own specification: build clean, open the synthetic vault, exercise the real flows, and assert the installed build reports its revisions. | **Dependent rather than schedulable**: blocked on the demo vault for the vault it must open, and on the registry item for the revision it must assert. | d |
| **—** | **Vault-open failure typing** — a mistyped path currently answers with an opened state and hands the person a brand-new empty vault, which is a claim about running behaviour that no role in this cycle witnessed. | The gap ledger's Open section, which records the vault-open branch as a known gap with an owner; the charter's register, which establishes that a missing directory is not a failure at all. | Independent and cheap. Its intake is a filing, which is the product owner's alone. | d |
| **—** | **Unattended folder capture; email and phone capture; the suggestions channel; Settings as its own destination.** | The charter's ordinary deferrals, each with its return condition; the suggestions channel's return condition is a measurement — after a live answer path exists, and when the refusal ledger says how much the channel is owed. | Not scheduled. | — |
| **—** | **Per-term provenance on a composed figure.** | The gap ledger's *Not built* class, financial-picture family, at `product/viva/ledger/projection/positions.py#ComposedTerm` — an address of that class names where the capability would live and does not resolve today, unlike every other address in this document. | Stays open. Declining to name a page is the honest rendering of an absent capability, not a fault to be closed here. | — |

### The vault round trip is larger than a directory copy

What must travel is not a folder. It is an event log carrying its own key
derivation salt, a head file holding a count, a head hash and a message
authentication code, a raw-store header carrying a **second, independently
salted** derivation, and the content-addressed encrypted blobs beneath it. Two
keystreams and a chain head. A brief that sizes this as a copy will design the
wrong thing, and a restore that is not verified on a copy is not a restore.

### Why the outbound record precedes configuration

This is the one argument in the order that a later cycle would otherwise
re-derive from scratch, so it is written down rather than left in the sequence.

The promise inventory already makes a public promise: nothing leaves your
machine silently, only user-initiated model calls and anonymous anchor hashes,
and *"the complete outbound record is always visible in the product."* The
status record notes that the invariant behind it is currently kept by there
being nothing to show rather than by showing it. The day the desktop can
configure a model, bytes leave from inside the product, and on that day the
promise is broken unless the record is on a screen.

That is a structural predecessor, not a preference about polish. It promotes
**one read** — the outbound record — on the strength of a promise already made,
and it leaves the rest of Trust exactly where the gap ledger put it. The
carve-out on the configuration item exists so that the locale and currency half,
which sends nothing anywhere, is not held hostage to it; the carve-out is
written as a structural condition about what code path can exist, because a
carve-out written as a promise to behave is not a carve-out.

### Why voice's placement is fixed rather than chosen

The other argument worth writing down. VOICE-34 requires that text and voice
share one session and one runtime, which makes voice an input and output skin
over the same session, the same planner and the same citation gate — never a
second answering path. **So the session's shape is decided by the conversation
cycle whether or not that cycle notices.** Voice cannot be placed earlier
without inventing a second path, and it cannot be placed later without
inheriting whatever turn shape the conversation happened to produce. A turn
shape with nothing a second modality can attach to is therefore a rejection
condition for the conversation item now, rather than a discovery for the voice
item later.

## What the outside review planned for nowhere, and four corrections

**The mirrored-text provenance design is the design half of the conversation
item, not a new slot.** The gap ledger already attaches the obligation there.
The design content is sharper than it sounds, because **speech cannot carry a
receipt**: a figure on a screen opens a drawer that opens a document, and a
figure spoken aloud opens nothing. Meanwhile X2 requires that every answer
stating a graded money figure as a number in a sentence carries one line saying
how well what it stated is stood behind, and that the line is a whole reviewed
sentence rather than a frame with a word dropped into it. So the conversation
item must answer what a spoken answer owes when its evidence can only exist on a
screen: whether the grade line is spoken, whether the citation is announced or
only mirrored, and whether an answer may be spoken at all when its text mirror
is not in front of the person.

**Voice is its own item, and one constraint binds the conversation item now.**
The rejection condition above. **One warning belongs in that brief:** the
recorded exchange carries a modality field, and its values name the
model-calling protocol rather than an audio hook. A brief reading that field as
somewhere voice attaches would be wrong.

**The voice item's escalation is structural, not discretionary.** If voice
reaches a remote provider for transcription or synthesis, that is a new
outbound edge, and T6 is explicit that new outbound bytes of any kind are a
decision — a decision record plus a promise check — never an implementation
detail. The brief sizes the **local** path first, and the run expects to park
the item if a local path proves inadequate.

Four items are cheaper or different than an outside reading assumes, and a
later brief that misses one either rebuilds something that already runs or
schedules a collision it could have avoided.

**The honesty harness is partial, not absent.** An interpretation eval already
computes a confidently-wrong rate against a frozen synthetic key over a single
model call, and a separate benchmark grades candidate models on document
extraction. **Neither takes a vault.** Nothing computes a refusal rate. So the
item has two halves: make the harness vault-facing, and build the refusal rate
once. **PROG-25 is not evidence that the harness exists** — it is enforced over
the single-call surface, and citing it here overstates the position by exactly
the width of SPINE-7's own exception. PROG-27, that the eval runs on every
change to trust-critical code, is unmet: the build runs the harness's tests and
never the harness.

**The demo vault is not green-field.** A parity-fixture script already builds a
temporary vault from real event constructors over eight account shapes, reads it
through real bridge dispatch, and byte-compares against a committed fixture both
suites read, covering the overview and documents surfaces. That is the seed. The
item adds the remaining enumerated states and a persistent on-disk home.

**The packaging position is three different things wearing one label.**
Packaging and signing **exists and runs**, so that half is finishing work.
Update lifecycle is **green-field** on both sides. Packaged-artifact validation
is **dependent rather than schedulable**, blocked on the demo vault for the
vault it must open and on the registry item for the revision it must assert.

**The sidecar's build revision attaches to the registry item, not to Trust.** It
lands in the handshake handler, which is why it cannot run in parallel with
other registry work even though it reads like a separate errand.

## Lanes, collisions, and the contract fixture's single writer

**The exposure items are a queue, and this was proved rather than argued.**
Adding one action to one capability in a throwaway copy grew the derived
operation list with no edit to the operations table, and drove the contract gate
to a drift failure where a clean copy passes. **One line in
`product/viva/surface/capabilities.py` regenerates
`product/viva/surface/fixtures/surface-v1.json`.** Every item that adds a
capability or an action collides there.

**A standing constraint of this order, which declares no rule: the contract
fixture has exactly one writer at a time, and a merge of it is never
hand-resolved.** The reason is the project's own doctrine about checks. Two
writers hand-resolving that file produce a green-looking fixture nobody
generated, and the gate cannot distinguish it from a real one. A check that
reports a clean bill it could not have withheld is worse than no check. This is
a constraint on how the work is scheduled, not an assertion about the product,
which is why it is written here as a constraint of the order and not as a rule.

**The first lane — the surface contract lane, single-writer, in order.** Capture
and park, the figure and its citation, the job registry, the registry item, the
capability half of the vault round trip, rescan, the outbound record,
configuration, ingest's reading half, review answering and its free-text half,
the conversation, Activity, Trust's remainder, the demo vault, update lifecycle.
Beyond the registry and bridge files, every new **read** surface additionally
queues on the sidecar's frozen set of surface names in
`product/viva/desktop_bridge/vault_surface.py`, the surface-name type in
`desktop/src/bridge/contracts.ts`, the client beside it, and the desktop's
hand-written vocabulary — four more shared files.

**The second lane — engine and ledger work touching no surface contract.** The
direction site in full; the honesty harness, provided its first cycle keeps it a
command-line instrument rather than giving it a surface; the crypto and
round-trip machinery of the vault export; and the open per-term provenance work.
This lane is genuinely concurrent with the first for the whole run. It is also
where the charter's two promotions mostly live, which means **they cost the loop
very little calendar**, because they do not queue behind it.

**The third lane — frontend craft.** The craft slice, the passphrase
consequence, the outstanding rename of *evidence* to *receipt*, keyboard reach
and focus behaviour. It should lead a surface rather than follow one, which is
what VOICE-140's first clause already requires.

**Where a lane collides.** Any two items of the first lane at once. The build
revision with any other registry work. The vault round trip the moment it
declares a capability. The honesty harness the moment it is given a read model.
The direction site's guard touches the test tree that first-lane items also
extend, which is a nuisance rather than a hazard.

**The first cycle's specific shape.** The capture item meets a reserved
interface unknown immediately, so the run's very first build brief parks a
question rather than answering it. **Second-lane work fills that wait**,
starting with the direction site; the run does not idle.

## Acceptance classes

Four classes. This document names each item's class and **no acceptance
criteria**. Criteria belong to an item's own brief at its own approval, and a
work order carrying them quietly becomes a set of pre-approved briefs.

- **Class a — accepted by the suite alone.** No vault, no money, no person
  present.
- **Class b — needs the real vault and spends nothing.** The Witness runs it,
  because the Verifier does not open the vault and does not spend money on a
  model.
- **Class c — needs the real vault and real model calls.** A budgeted Witness
  window.
- **Class d — cannot be accepted by any role in a delegated run.** Signing
  verification with real credentials, anything reaching a remote provider, and
  any filing. **Without this class named, a green suite reads as acceptance of
  something no role in the run was ever able to accept**, which is the specific
  way a delegated run manufactures a clean bill it had no standing to give.

**The pacing consequence.** The windows that cost money cluster at ingest's
reading half, free-text review answering, the conversation, voice and the
honesty harness. Vault-only windows sit at the figure and its citation, the
vault round trip, the outbound record, the direction site's live flip, and
Trust's remainder. Everything else can be accepted while the product owner is
elsewhere. The figure item and the outbound record can be settled in a single
sitting, and the outbound record's window is also the charter's named case — a
count of recorded-read events by phase, the earliest and latest occurrence, the
distinct models and the summed cost — which would say whether the outbound
record has any history to show on the day it lands.

## Escalated, and ruled nowhere

Named here so they are record rather than memory. None of them is decided in
this document, and none may be decided in a delegated run.

- **Witness windows and their budgets.** Several are named above and several
  cost money. A window may be named here; it may not be authorised here.
- **Filing the vault-open defect** — a mistyped path silently returning an
  opened, brand-new empty vault. The issue gate is a fourth checkpoint and it
  belongs to the product owner, and relayed authorisation is not authorisation.
- **Any voice path reaching a remote provider**, which needs a decision record
  and a promise check before it is designed, not after.
- **The five reserved interface unknowns**, which the loop's own contract
  (`WORKFLOW.md`) reserves and this document does not reopen: where model
  configuration lives and whether configuring a reader is a recorded event;
  whether a conversation turn is a blocking request or a job; how a proposal
  crosses the bridge; a pre-baked demo conversation versus a live one; and
  whether the review, activity and documents surfaces read through the surface
  module directly or through the conversation's own block — which the
  architecture document explicitly declines to take, and which the capture item
  meets first, because the documents composer is the first module that has to
  choose.
- **Three passages in the charter are now false, and correcting any of them
  belongs to the product owner.** The first says that nothing in the gap ledger
  is edited because it is already correct as written; the register below
  establishes two places where it is not. The second is the charter's own list
  of what it leaves owed, which is introduced by a count of four and whose first
  entry is this work order — so the entry and the count both go false the moment
  this document is tracked, and a count is exactly the claim a later reader
  checks. The third says of this work order that it is owed as its own design
  cycle, which stops being true for the same reason. **This document records
  that all three corrections are owed and performs none of them**, and it does
  not edit the gap ledger either.
- **A clause in the loop's own contract goes false with them**, separately and
  for the same reason: the limit reserving anything that draws on the outside
  review's item order gives as part of its grounds that the re-sequencing work
  is owed. Rewriting the grounds of a limit is a decision about the contract
  rather than a documentation pass, so it is named here and left alone.

## The register of inherited error

This document carries its own short register, so that no later cycle inherits a
defect from a document it will reasonably trust. **The gap ledger is accurate
about the code in every one of its symbol claims.** It is wrong about *itself*
in two places, and neither is corrected here, because editing it is outside this
document's fence.

- **Its Trust-and-maintenance entry undercounts the methods the desktop bridge
  client declares**, and contradicts its own review entry two paragraphs
  earlier, where the decline route it records is the very method the count
  omits. The substance that survives the correction: there is no capabilities
  method, and the client's surface-name type admits three names.
- **Its Open section states that the ledger is named by no other document.** The
  [reading guide](reading-guide.md) names it and the
  [surface charter](surface-charter.md) names it — and the charter is the
  document that supersedes the passage in question. The half that survives is
  that it appears in no table of [the rules index](rules.md), which is correct,
  because it defines no rule.

One further fact bounds what any of this can be held to: **nothing in the build
reads the gap ledger.** No test, script or gate references it anywhere. Nothing
goes red on the day a symbol it classifies as absent is written, which is why
the guard its own Open section schedules matters more than it looks.

## Where this order would be wrong

**It rests on one answer: the author's vault is the only real vault, and the
trust trial is open.** Both halves are load-bearing, and each fails in its own
direction.

If a second real vault comes into existence — a stranger's, however informally
invited — then export, the honesty harness and the outbound record stop being
near-term work and become blocking work, everything on the loop moves below
them, and the first non-author user has arrived ahead of the rule that says they
wait.

And if the trial closes — if the author believes an answer about his own money
without re-checking it — then the harness stops being a precondition for a
stranger and becomes the stranger's own instrument, the demo vault and the
packaging positions rise, and everything below the harness is re-derived rather
than followed.

**If this order ever moves, it moves whole.** It is derived, and a derived order
cannot be patched at the point where its premise failed without becoming an
order nobody derived. The gap ledger says the same thing about itself, and this
document adds the consequence that follows from being downstream of it: **the
gap ledger's order moving is what voids this one rather than amends it.**
