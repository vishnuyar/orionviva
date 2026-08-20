# Backend Capability Gaps For UI Parity

**State:** design-only
**Rules:** none

## Rules

This document is a handoff list of capabilities the desktop interface is waiting
on. It states no behaviour the code can be held to. Every item in it is either a
capability that exists and cannot be reached (under *Not exposed*), a capability
that does not exist (under *Not built*), or a shaping principle for the work that
closes one (under *Why*). Rules arrive with the capabilities themselves, in the
documents that specify them.

The one sentence a handoff list may not carry is *this is broken today*. That is
a claim about running behaviour, and a document which declares that it states no
such behaviour cannot hold one without asking every reader to sort its sentences
into two contracts. A defect belongs in
[User Interface Implementation Status](user-interface-implementation-status.md),
where a checked claim about the running product is what the document is for.

Each item names, in backticks, the address of the symbol its claim is about, in
the form `path/to/file.py#symbol_name`. Under *Not exposed* that address
resolves, and every such address was put through the import system before it was
written. Most items go further and say so in their own words: the capability was
called on a scratch vault of synthetic accounts and the result read. Where an
item was imported and inspected but not driven, it says that about itself rather
than leaving the reader to assume otherwise. Under *Not built* the address does
not resolve, and the item says which search established the absence; a bare
"none found" says nothing anyone could check.

The seven interface slices are a label on each item rather than the outer
grouping, because exposure and absence are what a reader has to sort on first.

## Why

Five properties shape everything the backend owes the surface. **Versioned read
models**, so the shell can evolve without breaking older builds and an old client
meets a contract it understands rather than a shape it must guess at.
**Allowlisted actions**, so a surface that needs user input or mutation reaches a
named, enumerated set rather than an open door into the product. **Progress and
terminal states** for long-running document work, because a job with no
reportable state can only be rendered as a spinner or a lie. **Cited evidence,
provenance and refusal states** carried through the conversation and review
surfaces, because an answer stripped of its citation on the way to a screen is
the one failure this whole product exists to prevent. And **explicit lifecycle
and recovery states for native install and update flows**, which the backend owes
the shell as squarely as it owes it a read model.

**The distinction the two classes draw is the point of the list.** "This exists
and cannot be reached" means write a bridge operation and a reviewed read model.
"This does not exist" means write a brief. Those are different next actions, and
a flat list prices them identically — a reader then has to re-derive the
difference from prose, which is expensive enough that mostly nobody does. The
structure is what a person remembers, so the structure is where the distinction
has to live.

**Most of what looks like missing capability is missing transport.** That is the
central claim here and it is not read off the source. Driven on a scratch vault
of synthetic statements: the engine's write functions all resolve and run, a
document posted and a second one parked correctly with no reader configured, the
reconciliation sweep returned identical counts on two consecutive runs and opened
no network socket, and answering and declining questions moved the open-question
count down and refused an unknown id cleanly. The functions are there. One of
them now carries its result to a screen — setting a question aside — and the
rest do not.

**Synthetic state is not backend parity.** A preview that simulates a state
locally proves the rendering and proves nothing about whether the backend and the
interface agree, so treating a preview as evidence of a working surface bypasses
the gates that exist to catch exactly that.

**A machine-readable record of this subject already exists, and it now answers
part of this question better than prose can.**
`product/viva/surface/capabilities.py` names six capabilities as *surfaced*, each
with a destination and a named contract: `overview.accounts`
(`AccountOverview.v1`, Overview), `review.questions` (`QuestionQueue.v1`,
Review), `conversation.viva` (`ConversationTurn.v1`, Viva), `documents.ingest`
(`DocumentIngestResult.v1`, Documents), `documents.rescan` (`RescanResult.v1`,
Documents) and `maintenance.agent` (`MaintenanceRun.v1`, Trust). The destinations
the enum defines that no capability claims are account, activity and settings.
Trust *is* claimed — by `maintenance.agent` — so the honest thing to say about
Trust is that a capability points at it and nothing serves its contract.

Beside that registry there is now a declared table of the operations the sidecar
serves and the contracts each delivers, and each capability's maturity is derived
from it rather than typed by hand. Calling `served_contracts()` on that table
returns `AccountOverview.v1` and `QuestionQueue.v1`, so `overview.accounts` and
`review.questions` read `stable` and the other four read `preview`. That is worth
saying plainly, because it makes the central claim of this document checkable
without reading a word of prose: six capabilities are declared as things a person
should be able to reach, and the table says a declared operation delivers the
contracts of two of them. Both of those files belong to the capability-registry
and gates cycle. They are named here as the reason this document does not keep
its own copy of what exists: a checked record and a prose record of the same
facts will drift, and the checked one should win.

**Where the live surfaces stand today is not this document's claim to make, and
anyone planning Financial picture work should read the other document first.**
[User Interface Implementation Status](user-interface-implementation-status.md)
is where a checked claim about running behaviour belongs, and it is where the
account read's condition is recorded — what each account now arrives with, and
what that read still drops. Saying *this is met* or *this is broken* is a claim
about running behaviour, and this list has declared that it makes none; carrying
one here would give the document two contracts and hand every reader the job of
sorting its sentences into them. What follows for this document is an ordering
and nothing else: the Financial picture items below are written against what that
record says is still missing, not against the whole surface, and the priority
order carries a clause about where a figure and its citation sit relative to
everything else.

The source of truth for what is currently built is
[User Interface Implementation Status](user-interface-implementation-status.md);
this document is the complement, listing what is not.

## Not exposed

The capability exists and is callable today, and something between it and a
screen does not: usually a bridge operation and a reviewed read model, sometimes
only the reviewed model, once only a client method.

- **Document ingest posting** — *Document journey.*
  `product/viva/engine.py#upload`, `product/viva/ingest/reader.py#build_reader`.
  Both resolve and were driven. With no reader configured, `build_reader()`
  returns its parking reader and reports itself not live, and `upload` on a
  scratch vault returned `parked` — the correct outcome. With a reader supplied,
  `upload` captured a synthetic statement and returned `posted` with a
  corroborated grade and a reconciled closing balance. `build_reader()` was
  exercised in all three of its configurations: neither environment setting,
  adapter alone, and adapter with a pinned model — only the third returns a live
  reader. What is missing is transport: the declared operations table lists no
  operation serving `DocumentIngestResult.v1`. Three things nonetheless keep this
  a design cycle rather than plumbing. The sentence a parked document owes a person exists as a
  rule and on no screen. A configured reader may call a model and therefore may
  send bytes off the machine, which the standing invariant that nothing leaves
  silently makes a decision rather than an implementation detail. And `upload` is
  synchronous while the sidecar's loop reads standard input one line at a time,
  so a naive exposure freezes the bridge for the length of a real read.

- **Rescan** — *Document journey.* `product/viva/ingest/pipeline.py#sweep`,
  `product/viva/rescan.py#main`. Both resolve. `sweep` was run twice over one
  scratch vault and returned identical dictionaries of counts — gaps,
  corroborated, auto, suggested, resolved, open_before, links — with no socket
  opened during either run. `main()` is a command-line wrapper that opens a
  vault, calls it and prints the result; the reconciliation itself is all in
  `sweep`. So rescan needs nothing extracted; it needs a reviewed read model over
  those counts and a bridge operation. The registry names `RescanResult.v1` and
  the declared operations table lists no operation serving it.

- **Review actions, less the one that shipped** — *Review and learning.*
  `product/viva/engine.py#answer_question`,
  `product/viva/engine.py#confirm_proposal`,
  `product/viva/engine.py#apply_ruling`, and the queue read
  `product/viva/questions.py#open_questions`. All resolve. Driven end to end: a
  scratch vault opened two questions; answering one with a value drawn from the
  choice slot that question declared returned ok and left one open; declining the
  remaining one returned ok and left none; declining an id that is not open
  refused with a sentence for the person rather than doing something quiet. The
  confirmation gate is already a property of the shape rather than a rule to
  remember, so exposing these actions does not require inventing a guard.

  `product/viva/engine.py#decline_question` has left this list: it is reached by
  `viva.review.decline`, and `product/viva/surface/models.py#ActionOutcome` has a
  producer and a consumer, so the reviewed shape an action's result takes is no
  longer waiting for its first caller. `viva.surface.read` now serves
  `QuestionQueue.v1`. Answering is the item that remains, and what it waits on is
  not transport: with no model configured a free-text answer accepts only a bare
  vocabulary token, so it waits on the desktop application configuring its own
  model, locale and currency — a capability this product does not have anywhere.

- **Net worth on the live path** — *Financial picture.*
  `product/viva/ledger/networth.py#net_worth`. Resolves, and was called on a
  scratch vault: it returns a point carrying one line per account with the
  account, amount, currency, date, grade, origin and kind, the hash that line
  proves against, and separate lists of what was missing, skipped and held. The
  opened-vault surface provider never calls it, and the desktop overview adapter
  hardcodes a null net worth, so live mode shows none while the synthetic preview
  shows one.

- **The reviewed figure model on the reads that do not yet use it** — *Financial
  picture.* `product/viva/surface/models.py#FigureView`. Resolves. It refuses to
  build a figure without identity, measure, date and coverage, and carries
  display, currency, grade, grade label, grade description, exactness, record
  ids, provenance, citations and caveats — everything a figure needs in order to
  arrive on a screen standing on something. Searching product code for its
  constructor finds exactly one call site, `product/viva/surface/overview.py`, so
  it is the contract for the account overview and for nothing else; the documents
  and review reads hand raw projection dictionaries across the boundary.
  Composing those two reads through it is transport work, and the constructor is
  what makes it *safe* transport, because a figure that cannot be built is a
  figure that cannot be half-rendered.

- **The conversation** — *Ask Viva.* `product/viva/speak.py#Session`,
  `product/viva/speak.py#Turn`, `product/viva/tools/runner.py#RunResult`. All
  three resolve. `Session` carries a conversation across turns, feeds prior
  questions and answers to the planner as context, holds that figures never carry
  over between turns, and appends every model exchange to the vault as a recorded
  read. `RunResult` carries the shape a turn committed to before anything was
  read, what each of its holes was bound to, and what it wrote, so a surface
  showing a bound thing again shows the words the sentence used rather than
  deciding a second time how the thing becomes words. These symbols were imported
  and inspected rather than driven: a turn requires a configured model, so the
  claim made here is that the machinery is addressable, not that a live turn ran.
  Exposure is one bridge operation and a read model. It carries one obligation on
  top of the transport: a spoken answer has to be mirrored in text so its evidence
  stays inspectable, and that is design rather than plumbing.

- **Activity and organization, the unblocked half** — *Activity and
  organization.* Read models
  `product/viva/ledger/projection/movements.py#movements`,
  `product/viva/ledger/projection/movements.py#transfer_links`,
  `product/viva/ledger/projection/movements.py#transfer_suggestions`,
  `product/viva/ledger/projection/categories.py#spending_by_category`,
  `product/viva/ledger/projection/categories.py#spending_by_subcategory`,
  `product/viva/ledger/projection/categories.py#spending_by_tag`,
  `product/viva/ledger/projection/categories.py#tags_of`, and the mutations
  `product/viva/engine.py#tag`, `product/viva/engine.py#assign_category_to`,
  `product/viva/engine.py#assign_merchant`,
  `product/viva/engine.py#confirm_correction`,
  `product/viva/engine.py#confirm_identity`. All resolve. This half is exposure
  work and could land next.

- **Activity direction filters and transaction detail — blocked** — *Activity and
  organization.* `product/viva/ledger/projection/movements.py#transactions`,
  `product/viva/ledger/projection/merchants.py#implication_of`. Both resolve, so
  by this document's own classification they belong here rather than under *Not
  built*. They are nonetheless not the next thing to expose, and what stops them
  is not a missing bridge operation. It is a standing rule, **VOICE-111**, whose
  second assertion reads: *"Nothing that ships direction filters or a transaction
  detail speaking direction may land before that site closes, or the interface
  renders a known-wrong inflow, states it as a fact about a person's money, and
  carries a grade while doing so."* The rule names its own site and its own
  state, and it lives in
  [the interface architecture document](user-interface-architecture-and-delivery.md)
  where a claim about running behaviour can be held to the code. This list does
  not restate it. What this list says is the ordering consequence: this half of
  Activity is exposure work waiting on a correction underneath it rather than on
  transport above it, so it does not travel with the other half.

- **The capability registry itself** — *Trust and maintenance.*
  `product/viva/surface/capabilities.py#serialize_registry`. Resolves, and the
  operation that returns it is already on the sidecar's default allowlist,
  available before a vault is open. Nothing under `desktop/src/` ever calls it:
  the bridge client declares exactly five methods — open vault, pick vault
  directory, read overview, read documents, read review — and its surface name
  type admits only overview, documents and review. There is no method for
  capabilities and no place to put the answer. Meanwhile the desktop declares its
  own capability vocabulary in TypeScript, whose group and state values share not
  one term with the Python dispositions and destinations, and the Trust screen
  populates it only from a demo fixture, leaving it empty in live mode. This is
  the exposure class in its purest form: the capability is built, the transport is
  built, the operation is allowlisted, and the consumer both fails to call it and
  has independently reinvented a worse version of the same idea. It is also where
  this list previously misled — a reader would reasonably have budgeted backend
  work, and the backend work is done. What is needed is a client method and an
  adapter. The registry file belongs to the capability-registry and gates cycle;
  the mis-description belonged here.

- **The maintenance run** — *Trust and maintenance.*
  `product/viva/agent/run.py#wake`. Resolves. `maintenance.agent` names Trust as
  its destination and `MaintenanceRun.v1` as its contract, and the declared
  operations table lists no operation serving it. Exposure work, with the caveat
  that the surface it lands on is the one that proves the promises, so it should
  not arrive before the promises beside it are true.

## Not built

The capability does not exist. Each item names an address that does not resolve
and the search that established the absence. An address here takes one of two
shapes. Where a natural home already exists, it names that module and a symbol
absent from it, so the import succeeds and the lookup fails. Where the thing
would need a module of its own — the projection package keeps one module per read
family, for instance — it names the module that would hold it, and the import is
what fails. Either way the address is the anchor and the search is the
evidence.

- **A document ingest job registry** — *Document journey.*
  `product/viva/ingest/jobs.py#IngestJobRegistry`. Importing `viva.ingest.jobs`
  raises a module-not-found error. A case-insensitive search of `product/viva`,
  `core` and `merchant` for `jobregistry`, `ingestjob`, `class Job`, `def cancel`
  and `def retry` returns exactly one hit: the started/failed/completed progress
  event for a single surface read in
  `product/viva/desktop_bridge/surface_read.py`, which knows nothing about ingest
  and reports one step of one. So there is nowhere to hold a running document
  read, no cancellation, no retry state, and no progress granularity worth
  rendering. The progress channel is designed inside this ingest work, where its
  first real producer lives, rather than ahead of it; this document names the
  absence and does not design it.

- **Unattended folder capture** — *Document journey.*
  `product/viva/ingest/watch.py#watch_folder`. Importing `viva.ingest.watch`
  raises a module-not-found error, and a case-insensitive search of `product/viva`
  for `watched_folder`, `watch_folder`, `watchdog` and `def watch` returns
  nothing. Every document that enters the vault today enters through an explicit
  capture call.

- **Per-term provenance on a composed figure** — *Financial picture.*
  `product/viva/ledger/projection/positions.py#ComposedTerm`. The module imports
  and no such symbol is in it, and there is no other name for the idea: a
  case-insensitive search of `product/`, `core/` and `merchant/` for
  `per_term`, `term_provenance`, `provenances`, `proves_per`, `term_doc` and
  `doc_per` returns nothing at all.

  What *does* exist is `composed_values`, in the same module, and it works — an
  investment account's cash and the holdings its latest statement measured are
  summed into one figure, dated by the oldest measurement under it and graded by
  the weakest. The gap is narrower and more specific than a missing function.
  `ComposedValue` carries `account`, `amount`, `currency`, `dates`, `grade` and
  `proves`, and `proves` is a **single string for the whole sum**. Reading the
  composition shows why: each position term is appended with an empty string
  where its document would go, and the terms are then folded with `proves` taking
  the first non-empty document it meets. So the cash term's document becomes the
  document of the entire figure.

  Driven on a scratch vault, with an account whose cash was attested by one
  synthetic statement and whose single holding was measured by another: the
  composed figure came back correctly summed, correctly dated by the older part,
  and correctly flagged as resting on more than one day — and its `proves` named
  the cash statement alone. The holdings term still knew its own document; the
  composition had it in hand and dropped it.

  There is a second half to the absence, and it is the half a surface trips over
  first. Nothing in the balances read says a figure *is* a composition. That
  read's fields are account, amount, grade, as-of, provenance, reconciliation,
  explanation, currency and dated — no term count, no list of parts, nothing a
  client could branch on. So an interface cannot even detect the case in order to
  handle it carefully.

  This is what makes the item belong in a handoff list rather than a defect
  record. Faced with the choice, the honest move is to decline to name a page at
  all rather than attach one part's page to a whole it did not attest — so a
  person is routed to the right document and not told which page, and that is the
  correct outcome of the capability being absent rather than a fault in the read.
  Where the account read stands today is the status document's claim to make.
  What this list says is what closing the gap would take: a composed figure that
  can name where each of its parts came from, and a read that admits it is
  composed.

- **An outbound-history read model** — *Trust and maintenance.*
  `product/viva/ledger/projection/reads.py#outbound_history`. Importing
  `viva.ledger.projection.reads` raises a module-not-found error, and the modules
  the projection package actually holds are accounts, activity, balances,
  categories, core, coverage, merchants, movements, positions, rhythm, rulings
  and tiers — none of which composes anything over recorded reads. This is the
  middle case a flat list has no way to express, so it is worth being precise
  about. The events are already captured: the read-recording event writer in
  `product/viva/ledger/events.py` runs today and records the model, the prompt
  version, the input mode, the verbatim response, the cost, the token counts and
  the parse status. That writer is given no address under *Not exposed* because it
  is not what the interface is waiting on — the interface is waiting on something
  to compose those events into a read model, and that is what does not exist. The
  projection core acknowledges the event type only far enough to keep the latest
  reply text per document. The only readers are developer-only entries in the
  capability registry, each carrying its own reason for not being a product read
  model. Exposure here means composing a projection, not routing one.

- **Build identity and external anchoring for Trust** — *Trust and maintenance.*
  `product/viva/ledger/projection/integrity.py#build_identity`. Importing
  `viva.ledger.projection.integrity` raises a module-not-found error, and a
  case-insensitive search of `product/viva` for `build_identity` and `anchor`
  returns only unrelated senses of the word: a text anchor within a rendered page,
  a content-anchored movement key, and account identity anchored to an account
  number. The rule that governs the screen this would feed is **VOICE-112**, whose
  first assertion requires Trust to show what is and is not externally anchored
  rather than to claim anchoring. So until the capability exists, the absence is
  what the screen has to show — which is a cheaper obligation than it sounds, and
  a stricter one.

- **Diagnostic export** — *Trust and maintenance.*
  `product/viva/debug/export.py#diagnostic_export`. Importing `viva.debug.export`
  raises a module-not-found error, and a case-insensitive search of `product/viva`
  for `diagnostic_export`, `support_bundle`, `def export_diagnostic` and `redact`
  returns nothing. A ruling export does exist and is classified developer-only
  precisely because it contains personal data; a diagnostic a person could safely
  hand to someone else is a different thing and is not built.

- **Install, update and recovery lifecycle state** — *Installable shell and demo
  vault.* `product/viva/surface/models.py#UpdateLifecycleView`. The module
  imports and the symbol is absent, and a case-insensitive search of
  `product/viva` for `installer`, `notariz`, `update_manifest`, `def sign_` and
  `def publish` returns nothing. Packaging, target and release configuration do
  exist as reviewed contracts under `scripts/` and the desktop tree. What does not
  exist is a backend read model the shell can render for install, update and
  recovery states, which is what the fifth of the five properties above names.

## The priority order

This is the order in which the interface is owed things, argued on what the
product owes a person rather than on what is cheap to build. It is a different
question from the order in which work is sequenced, which the roadmap holds. If
this order ever moves, it moves whole.

It rests on one answer: the near-term first user starts with **no vault at all**.

1. **Document ingest and its job channel.** For a person starting empty there is
   no figure to render and no picture to be honest about until a document lands.
   The posting half is exposure — `upload` parks correctly with no reader and
   posts with one, and `sweep` is idempotent. The absent half is real design: a
   job registry, cancellation, retry states and real progress granularity do not
   exist, and the progress channel is designed inside this work rather than ahead
   of it.

2. **A figure reaches the screen with its citation — and this may not land later
   than the first.** That clause is not decoration. A person who has just dropped
   their first document looks at the overview next, and whatever the overview says
   to them is the first thing the product ever tells them — which makes an
   overview that overstates itself worse for that person than for someone who
   built a vault at the terminal. The rest of live mode is already honest: the
   live snapshot builder says of activity, conversation and trust that they are
   not connected, which is the correct thing to say. Overview is the one surface
   this is a live question about, and the question is answered in the status
   document rather than here. This item is owned by the figure-and-citation
   cycle.

3. **The surface stops claiming machinery the product does not have.** The rule
   for this already exists and is unmet: Trust shows what is and is not externally
   anchored rather than claiming anchoring; a Documents surface does not paper
   over capture being met on originals and unmet on the ingest request;
   passphrase recovery is stated as it exists, which today means losing the
   passphrase loses the vault; and outbound accounting is not claimed complete
   before it is. The registry today advertises six surfaced capabilities, and
   the declared operations table says an operation delivers the contracts of two
   of them. It ranks third because a product that overstates itself in its own
   registry will overstate itself on a screen, and because it is cheap. That file
   belongs to the capability-registry and gates cycle.

4. **Review actions.** Exposure work, proven end to end. It ranks here not
   because it is cheap but because the review queue is the loop by which every
   figure on every other surface gets better — a person answering a question is
   the mechanism that moves a grade from unverified to verified. Setting a
   question aside has landed. Answering has not, and it is now behind
   configuration rather than behind transport, because an honest free-text
   answer needs a model and configuring one has never existed in this
   application.

5. **The conversation.** Also exposure: session, turns, refusals, per-turn
   grounding and the recorded exchange all exist. It is the product's headline
   experience and one bridge operation plus a read model away. It ranks below
   review because an answer inherits the vault's staleness and review is what
   keeps the vault honest, and because a conversation surface carries the stricter
   obligation of mirroring a spoken answer in text.

6. **Activity and organization, split, because half of it is blocked.** The read
   models and the category and tag mutations are exposure work and could land
   next. The direction filters and the transaction detail cannot, and what blocks
   them is **VOICE-111**, the rule that every direction shown comes from the
   account's kind and never from a posted sign. The rule names the site and holds
   its own state; this order only records that the blocked half does not travel
   with the unblocked one.

7. **Trust and maintenance.** Mostly exposure, with honest exceptions: outbound
   history has events and no projection, and build identity, external anchoring
   and diagnostic export are not built at all. It ranks here because it is the
   surface that proves the promises, and a promise surface built before the
   promises are all true is the failure the rule in item three exists to prevent.

8. **Packaged desktop lifecycle, installers and signing.** Correctly last: it
   turns a working product into a distributable one and has nothing to distribute
   until the steps above hold.

## Open

- **This document's reading-guide slot is placed, and its other absences
  stand.** [The reading guide](reading-guide.md) now lists it under the
  interface section. It is still in no table of [the rules index](rules.md),
  which is correct — it defines no rule — and no other document names it, so the
  standing rule that a status claim is checked before it is repeated reaches it
  only through the guide.

- **A symbol-resolution guard is scheduled, not deferred: it is the first item of
  the next cycle, and the decision is taken rather than open.** This document
  adopts the anchor grammar the status document introduced, and that document's
  anchor evaluator is extended to cover this one; nobody re-argues it. It will
  live in
  `product/tests/test_docs_track_the_code.py`, which exists for exactly this kind
  of check and enumerates nothing: read this document, extract the backticked
  addresses under each class, and ask the import system. Under *Not exposed* the
  named symbol must resolve, so the test goes red if a symbol is renamed or
  removed while this document still says it exists. Under *Not built* the named
  symbol must not resolve, so the test goes red on the day someone writes it —
  and that second direction is the one that would have caught the rot this
  rewrite repaired. The case for building it is stronger than it looks. Several
  claims in this document changed classification while the document was being
  written — capability landed, a contract was declared, a field appeared — and
  nothing anywhere went red; the corrections were made by a person re-running the
  imports by hand. A handoff list is exactly the kind of document that goes stale
  fastest, because the work it points at is work someone is actively doing. That
  measured rot rate, and the fact that the grammar has now had a first run
  elsewhere, are the evidence the decision rests on. It does not travel in the
  cycle that rewrote this document because that cycle is documentation-only, and
  a code change inside one is the scope leak the fence exists to stop. Every item
  here is already written with its address in backticks, so adopting the grammar
  is an addition rather than a rewrite. Two limits, so nobody reads the guard as
  wider than it is: it would catch a *named* capability arriving, not every way
  one could arrive, since a job registry could be built under a name this
  document never guessed; and it says nothing about
  whether an exposed capability works, which is what a parity check and a live run
  are for.

- **The vault-opening operation is declared but not dispatched like the others.**
  It now appears in the declared operations table beside the handshake, the
  capability read and the surface read, so it is no longer outside the inventory.
  It is still not in any dispatcher's handler map: it is intercepted before
  dispatch, because opening a vault swaps the dispatcher for a wider one, and the
  interception is a hand-written branch rather than an allowlist entry. Driven
  against the real sidecar, that branch accepted a protocol value that is not the
  current one, accepted a protocol value that is not a string, and accepted a
  request with no protocol field at all — each opening the vault — while the same
  unsupported protocol sent through the dispatcher was refused as an unsupported
  major version. The honest reading is narrower than an open door: the payload is
  fenced to exactly a vault directory and a passphrase, both required non-empty
  strings, and an extra field is rejected, so nothing arbitrary gets through. What
  it is, is an allowlist-of-one expressed as a branch that skips the protocol
  check, on the one operation that carries a passphrase. It is a known gap with an
  owner and a cycle of its own, tracked outside this repository; this document
  records that it exists and does not design the fix.

- **Whether the inventory half of this document belongs in prose at all.** The
  capability registry is already a machine-checked record of what exists and
  where it goes. If the registry becomes the authoritative inventory — with a
  coverage check that fails when a capability claims a contract no bridge
  operation serves — then the *Not exposed* class here becomes a second copy of a
  checked fact, and two copies drift. The argument would then be to retire this
  document into the status document plus the registry, keeping only the priority
  order and the reasoning in prose. That is not proposed now, and it is not
  proposed before the registry has earned it.

- **What would change the order.** It rests on the near-term first user starting
  empty. If the first real users arrive with vaults already built at the terminal,
  the figure-and-citation item leads and ingest moves down.
