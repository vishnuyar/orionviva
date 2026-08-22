# OrionViva User Interface Implementation Status

**State:** partial
**Rules:** VOICE-120, VOICE-121, VOICE-132

This document is almost entirely status by its own name, and status rots. So
what was a snapshot table now lives under **Open**, as standing questions about
what is not yet true. Three things in it do not rot: the rule about when a slice
may be called complete, the rule about what a fixture can and cannot prove, and
the rule about how a gap is written down so that it fails when it stops being
true. Those are below. Everything else is a claim to re-check against the tree
rather than to repeat, and the design authority is
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).

## Rules

### VOICE-120 — a slice is complete only against the live boundary it claims
**State:** untestable
**Code:** none found
**Test:** none

1. A slice may be marked complete only when its architecture acceptance criteria pass against the live boundary it claims to use.

### VOICE-121 — a synthetic fixture proves rendering, never parity
**State:** untestable
**Code:** product/viva/surface/fixtures/surface-v1.json
**Test:** none

1. Fixtures prove presentation states; they cannot by themselves prove backend/UI parity.
2. A packaged, signed, installable application is a separate claim from a compiling one, and neither is proven by the other.

### VOICE-132 — a gap carries the address its measurement is re-taken at
**State:** enforced
**Code:** docs/user-interface-implementation-status.md — the tables under **Open**
**Test:** test_docs_track_the_code.py::test_an_anchored_gap_resolves_at_the_address_it_names, test_a_gap_states_an_anchor_and_a_refusal_is_counted_as_one, test_a_destination_table_is_the_destinations_the_registry_holds, test_a_bridge_operation_table_is_the_operations_the_sidecar_serves

1. Every gap this document states opens with a direction and an address at which its measurement can be re-taken, and a gap whose address stops resolving fails the build.
2. A gap no machine in this repository can hold says so in place of an address, gives a concrete reason, and is counted on the document's face.
3. Where a registry already holds the answer, the document restates nothing: its table is compared against the registry, and the comparison fails when the registry moves and the table does not.

## Why

The architecture document is the design authority and deliberately keeps its
proposed-state language. Something still has to record what is actually true on
a branch, or the proposal quietly reads as a description. That is this
document's whole job, and it is why the rules above are the only durable
sentences in it: everything else is a measurement, and a measurement repeated
without being re-taken is a false claim wearing the authority of a checked one.

The distinction the rules protect is the one that is easiest to blur under
pressure. A React shell that renders an account spotlight from a fixture is a
real presentation slice and proves real things about states, focus and layout.
It proves nothing about whether an opened vault produces those numbers. A
sidecar that smoke-tests locally proves the process boundary works; it proves
nothing about a signed installer on a clean machine. Naming which boundary a
claim was checked against is the difference between a status document and a
press release.

The same reasoning explains why the verification snapshot and the branch name
are gone rather than updated. A count of passing tests is true for the minute it
was taken and re-derivable by running the suite; carrying it forward invites
someone to repeat it without re-running anything, which is exactly the failure
this project has a standing rule against.

That is also what reconciles this document with a machine reading it. An anchor
is not a recorded measurement; it is the *address at which the measurement can
be re-taken*. Under that reading the document carries no result, keeps its own
rule, and becomes checkable at the same time — because "done" has no machine
definition, while an absence is the cheapest question a machine can answer.

## Open

What is not yet true on this branch. Each gap opens with an **anchor**: a
direction and an address, re-evaluated on every run.

What that buys, stated exactly, because the difference matters. An anchor
written as an **absence** — `no-file`, `no-name` — goes red on the day the work
lands, which is the property this document was rewritten to get. An anchor
written as a **presence** — `has-file`, `has-name` — goes red only when its
subject is renamed, moved or deleted: it holds the address, not the gap, and
whether the sentence beside it is still true stays a person's job. Most gaps
below are presences, because most of them have no address the tree's own
conventions make obvious, and inventing one would produce a row that could
never go red at all. Where an absence-shaped address does exist it is used, and
those rows are the ones that close themselves.

A gap no machine in this repository can hold says so in place of an address and
gives its reason. Those sit in their own table, counted, so "untestable" is a
short list with reasons rather than a blanket over the whole document.

### Destinations (10)

Where the registry and the interface agree about where a capability lands, and
where they do not. The first three marked columns are derived from the code on
every run and compared against this table; the last is stated, because its
source is TypeScript. A marked cell reads `yes` or `no` and nothing else — any
other word is reported as unreadable rather than guessed at. Every destination
the code declares has a row here; a row the code does not declare has to claim
the interface ships it, or it is rejected as invented.

| Destination | Live read | Registry destination | Claimed by a surfaced capability | Shipped in the interface |
| --- | --- | --- | --- | --- |
| `overview` | yes | yes | yes | yes |
| `accounts` | no | yes | no | yes |
| `activity` | yes | yes | yes | yes |
| `documents` | yes | yes | yes | yes |
| `jobs` | yes | no | no | yes |
| `review` | yes | yes | yes | yes |
| `viva` | no | yes | yes | no |
| `trust` | yes | yes | yes | yes |
| `settings` | no | yes | yes | no |
| `none` | no | yes | no | no |

The two sides still disagree, but no longer about spelling: the registry used
to declare `account` while the interface shipped `accounts`, and nothing but
this table held the two together. They are one word now, and the interface
derives what it says about a destination from the registry's own signal rather
than from a vocabulary of its own. `viva` and `settings` are registry
destinations with no place in the interface; `accounts` is a shipped
destination no surfaced capability claims, which the interface now marks on the
destination itself. `activity` became live-readable and claimed once the site
that read direction off a posted sign was closed — until then, a row saying
which way money went would have said it backwards on a card. `trust` became live-readable when the outbound
record landed there, and it reads as ready for a vault that has sent nothing —
that emptiness is the record rather than an absent panel. `settings` is now
claimed by a surfaced capability and is still no place in the interface: the
charter defers Settings as its own destination, so the controls that reach that
capability sit on Trust until it lands. That is a stated deferral rather than a
gap, and the row says so by reporting no shipped destination. `none` is how the registry
says a capability has no destination at all. `jobs` is a live-readable surface
name that is no registry destination and no screen of its own: what the sidecar
is doing is shown on the documents screen, beside the work that started it,
and the capability that declares the read is filed under `documents` for that
reason. The day a surface becomes live-readable, or a destination is declared,
or a capability's destination moves, this table is wrong and the build says
so.

### Bridge operations (16)

Every operation the sidecar will answer, and whether an allowlist admits it.
The operation set and the allowlist column are derived; whether the desktop
calls an operation is stated, because that is a fact about TypeScript. A marked
cell reads `yes` or `no` and nothing else.

The reads are declared; the actions are one per action the capability registry
declares, so this table read on its own is the whole of what can touch a vault.
An action with no handler is refused by the allowlist rather than by silence,
and the ones in that state are marked below — `viva.maintenance.run` is the one
left in it.

| Operation | Allowlisted | Where it is served | Consumed by the desktop |
| --- | --- | --- | --- |
| `bridge.handshake` | yes | the allowlist a sidecar starts with, before any vault is open; it names the build that answered, read from a file a packaging step writes or from the tree this module lives in | yes — asked once when a vault opens, and what it says about the build is shown on Trust. The desktop still never checks the `protocol` field the sidecar stamps on every response, so the version is asserted per frame and checked by nobody |
| `bridge.open_vault` | no | intercepted by `Sidecar.handle` as a branch before dispatch runs, so it reaches no allowlist and has no protocol major validated; it makes no vault unless the request says to, and answers a folder holding no vault, a path that is not a folder, and a vault the passphrase will not open as three different refusals | yes |
| `viva.surface.capabilities` | yes | the allowlist a sidecar starts with, before any vault is open; it answers with the reviewed registry and with which destinations a read reaches, derived where the rule lives | yes |
| `viva.surface.read` | yes | added to the allowlist when a vault opens | yes |
| `viva.review.answer` | yes | added to the allowlist when a vault opens; it is the single inbound door, and the question is looked up in the live queue rather than taken from the caller, so a stale screen cannot answer something that is no longer being asked | yes |
| `viva.review.decline` | yes | added to the allowlist when a vault opens | yes |
| `viva.documents.upload` | yes | added to the allowlist when a vault opens; the handler takes one path, opens the file itself and captures it, then reads it with the reader this machine's configuration builds — which cannot read until somebody has said yes to naming a model, so no model runs on this route until then | yes |
| `viva.documents.cancel` | yes | added to the allowlist when a vault opens; it names a job the registry minted, never a document, and is the one operation a running job may be interrupted to serve | yes |
| `viva.maintenance.run` | no | derived from the action the maintenance capability declares; no handler is registered for it, so an opened vault refuses it | no |
| `viva.settings.read` | yes | the allowlist a sidecar starts with, before any vault is open; it is not a surface read, because a surface read opens a vault and this question has an answer before one exists | yes |
| `viva.settings.propose` | yes | the allowlist a sidecar starts with; it describes what would change, changes nothing, and carries the digest a yes has to name | yes |
| `viva.settings.confirm` | yes | the allowlist a sidecar starts with; it applies exactly the proposal that was shown, and is the one request an API key ever travels in | yes |
| `viva.conversation.ask` | yes | added to the allowlist when a vault opens; one session lives as long as the vault does, so turns share context and voice would read the same turn a screen does. A turn is a blocking request rather than a job, which is one of the five reserved interface unknowns answered the narrow way | yes |
| `viva.documents.rescan` | yes | added to the allowlist when a vault opens; it stitches gaps, closes holds a counterparty now attests and links transfers among movements already posted, reads no document, and answers with a reviewed read model rather than the counts the sweep returns | yes |
| `viva.vault.export` | yes | added to the allowlist when a vault opens; it writes every file this vault is made of into one archive without decrypting any of them, and never replaces an archive that is already there | yes |
| `viva.vault.restore` | yes | added to the allowlist when a vault opens; it writes into a directory that holds nothing, never over a vault in use, and reports only what opening the copy and reading it through established | yes |

### Gaps (33)

| Anchor | Gap |
| --- | --- |
| `has-file desktop/src/surface/adapters/snapshot.ts` | The live snapshot is composed here, and it returns `unavailable` for activity, conversation and trust by construction. Only the destinations marked live-readable above get any live read at all, and the browser path stays fixture-backed. |
| `has-file desktop/src/surface/adapters/overview.ts` | Each account now arrives with a rendered amount, a grade and the reviewed sentence behind it, a coverage line, and citations carrying a page. The picture arrives too: one net-worth figure per currency, the day the read was made, and one reviewed sentence saying how far the total reaches — composed by the backend rather than by this adapter, and counting rather than naming. Each figure also arrives with the words its evidence control announces and the words the panel it opens is headed with, so the adapter names no control itself: one total per currency is one control per currency, and two announcing the same words conflate two figures nothing may relate, for the person who cannot see which card the control sits on. It arrives with the boundary the read declared as well, and beside it one reviewed sentence per account the total could not value, naming the account and saying why — the panel counts them and never names them, and that is only honest because this half names them where a person can go and read it, and the reason is what tells them whether anything is theirs to do. The reason token itself never reaches a person: a token the surface has no reviewed line for fails the build rather than rendering bare, rendering the token, or falling through to a generic line. There are two such reasons and the read declares which — one where something would settle the gap and one where nothing can be pointed at — and a figure says which of the two it is without saying what would settle it, because that text is the ledger's own words rather than reviewed copy. That a remedy exists is asserted safely because a boundary refuses to be built where a gap of that reason names nothing that would close it. A currency whose total was kept back arrives as its own entry, carrying the currency beside the sentence so no reader ever has to learn which currency it was by reading the words. Each account left out arrives with the name it is written under as well — and with the sentence rather than the machine token that chose it, at every site without exception, because a token beside its own output is a field nothing reads and a standing invitation for a surface to branch on a machine's word instead of rendering what it was handed — so the account is written once, on this side: two sides each resolving a ledger path is two systems describing one fact, and they disagree first on exactly the accounts a name cannot tell apart. Everything a figure carries — its records, its citations, what it could not value and the sentence counting them — is kept to that figure's own currency by one decision, so a total in one currency never speaks about an account held in another. Where no currency can be found for an account at all, it is beneath no figure, and the panel names it: such an account is on no card, in no line and in no drawer, so counting it and naming it nowhere would not be privacy but concealment — a person cannot verify, act on, or discover something the product recorded and calls nothing. It stays in the denominator, because a panel that dropped it would report a smaller thing covered whole instead of a larger thing covered in part. The denominator itself is the union of two declared sets — the accounts the net-worth read ranged over and the accounts the vault holds — because **the point is authoritative about what it valued and is not authoritative about what is held**: a ruling can bring an account into being that nothing has yet been posted to, and no read meets it at all, so a denominator taking the point's word for it would call a person's picture complete while something they hold sat outside it. A read that refused would arrive as nothing but the panel's no-total line, and that is deliberate: driven across every constructible vault shape, this read constructs no refusal at all, and its aggregate branch constructs none by inspection either — so a reviewed sentence for it would be a pack line that cannot be said, and the tool's own machinery words would otherwise render where a person's net worth goes. **What holds that is not the comment but a test pinning the call's arguments**, because widening them opens refusal tags with no reviewed sentence. The panel-level `caveats` field now carries what **every** read this composer made declared, in the order the reads were made: it gathered from the balances read alone while a second read was declaring one of its own, which is a disclosure lost in transport rather than a decision not to render. Nothing merges two of them — two reads saying the same words say it of two different sets. The field still reaches no screen this cycle. How old the evidence beneath a total is rides on each figure, in words, and is carried as no panel field: over the whole picture it would be a date true of one currency's lines and false of another's. What this read still drops: `recent` is always empty, and that is a **decision rather than a defect** — recent activity is deferred to position 15 of the work order, because every rendering the interface has for such a row speaks direction and VOICE-111's second clause forbids that while the direction site stands. Both corpus-coverage strings are still returned blank, and the demo-only one stays that way. |
| `has-file desktop/src/styles/contrast.test.ts` | The contrast gate measures the screens a cycle authored, so a paint nobody re-authored is never walked. Measured with the gate's own algorithm, over every page-gradient stop the token file declares, on the tree this cycle started from: `.coverage-card p` at 2.572:1 and `.hero-meta` at 2.449:1, both below the 4.5 floor at the eleven and ten pixels they render at, and both carrying person-facing sentences this cycle replaces — so both are repainted here rather than filed. `.figure-footnote`, `.figure-footnote span`, `.overview-read-context` and `.account-date` have **no user in the interface at all** after this cycle: nothing renders text into them, and the last of the four was orphaned by this cycle's own diff rather than found that way. Their numbers are filed **as measured on the day they had one** — `.figure-footnote` 2.878:1 at ten pixels, `.figure-footnote span` 4.837:1 at eleven, `.overview-read-context dt` 2.806:1 at ten and `.overview-read-context dd` 5.755:1 at thirteen, both against the coverage card they sit on rather than the hero card beside it, and `.account-date` 2.494:1 at ten against the account card's own ground — which its button leaves transparent, so the card shows through. **Every number here names the ground it is of**, because the same paint measures 2.186:1 against the bare page and a ratio without its ground is not a measurement of anything. Twice in this cycle a filed number turned out to be of a ground the paint does not sit on — and **a cycle that gives any of them a user measures again rather than inheriting the number**, because a ratio attached to a paint nobody has looked at since is exactly the shape of the defect found at HEAD here. What is unheld is not any one number but that the gate walks what a cycle wrote and not what a person reads. |
| `has-file desktop/src/surface/adapters/documents.ts` | The live read now also carries the name a document arrived under, how far its reading got, and the panel's one sentence about reading. What still does not survive it: the capture queue, the processing jobs and the outbound records are empty on every row, and the phase label is a fixed "Not supplied". Rescan and held states and outbound accounting are not wired into the document journey. |
| `has-file desktop/src/surface/adapters/review.ts` | Every live review row still reads as read-only: the row itself carries no action, no outcome and no disposition, and proposal and confirmation anatomy is synthetic. What the row no longer decides is whether anything can be done — setting a question aside is wired beside the queue rather than onto a row, and the read that follows a write re-reads review alone. Answering is not wired at all: it waits on the desktop application configuring its own model, and a free-text answer with no model behind it accepts only a bare vocabulary token. |
| `has-file desktop/src/features/activity/Activity.tsx` | Activity ships as a destination and has no live read model at all. Filters, corrections, categories, tags, transfer relationships and live totals exist only as fixture-authored sample facets in demo mode. |
| `has-file desktop/src/features/conversation/ConversationDrawer.tsx` | The conversation surface is unavailable in live mode by construction. Cited turns, refusal states and protection against document-driven writes all remain. |
| `has-file desktop/src/features/trust/Trust.tsx` | Trust is a shipped destination with a component and a test, and it has no live read model. The live snapshot returns unavailable for it, and its capability rows render only in demo mode, from fixtures. |
| `has-name product/viva/desktop_bridge/handlers.py#_surface_capabilities` | The sidecar serves the reviewed capability registry from the allowlist that exists before a vault is open, and nothing in the desktop calls that operation. Closing this is owned by no cycle yet; the bridge-operation table above keeps it recorded. |
| `has-file desktop/src/surface/types.ts` | The whole surface vocabulary is re-declared here by hand, with no generator and no check holding the two sides together — including a capability vocabulary of groups and states corresponding to nothing the registry declares. Both sides now close their measure vocabulary and the two closed sets are not the same one: this side names a handful of measures, the backend's vocabulary holds many more and rejects anything outside it. **VOICE-104** is `enforced` on the backend, so what is unheld is not either side's vocabulary but the absence of anything comparing them. Measured rather than recalled: this side names five measures, `quantity.MEASURES` names twenty-one, no file under `desktop/` mentions `quantity`, no Python file mentions `types.ts`, and the one generated artifact that crosses the boundary — `surface-v1.json` — carries no measure name at all. **Nothing holds the two sets against each other.** The consequence is now live rather than latent: a figure's measure chooses a label in the evidence drawer, so a word the backend emits and this side has not been taught falls through to a machinery sentence with nothing going red. Pre-existing, and not painted into by the cycle that made it reachable. |
| `has-name product/viva/tools/ledger_tools.py#MIXED_VINTAGE` | The one caveat the overview read declares is a module-level Python literal rather than a reviewed pack sentence, and both reads the picture composer makes declare it. Nothing renders the caveat field today, so no unreviewed words reach a person — but the field is now complete and correct, which means **the first cycle that renders it must move this sentence into the persona pack before it does**, or the flagship figure's own disclosure ships as a string nobody reviewed. The same cycle settles what two reads declaring identical words should do, which this cycle deliberately left alone: they are carried as two entries, because folding them into one would assert that two claims about two sets are one claim. |
| `has-name product/viva/surface/models.py#ActionOutcome` | Setting a question aside constructs one on every reply and the Review screen renders it, so the contract has a producer and a consumer. Two of its five words are reached: `completed` and `refused`. `waiting` is reachable through the mapper and no verb this build serves produces it. `stale` has no producer, because nothing versioned answers yet. `proposal` has none either, and deliberately: a reply held for a confirmation is transient by design and cannot cross the bridge, so the mapper raises rather than reading it as the nearest word. Capture does not widen this either: the upload handler maps the two engine actions its own route can reach and raises on every other one, rather than mapping the ingest states a terminal-written vault can hold onto `waiting`. |
| `has-file product/viva/surface/documents.py` | The documents surface has a composer, at the address the overview surface set: a pure function of a projection, the set of originals the vault still holds and whether this machine names a reader, imported by the bridge's vault reader. It composes no figure, no grade and no coverage boundary, which is what a read listing paperwork rather than money owes. What it still cannot say is *why* a document was not read: the vault records no reason, so the three states it derives — nothing looked, something looked and yielded nothing, something looked and made something of it — are the whole vocabulary, and a document nothing looked at because it was over the size ceiling is the same word as one nothing looked at because no reader is chosen. |
| `no-file product/viva/surface/review.py` | The review surface has no composer either, for the same reason and at the same kind of address. Its live read hands back the open-question builder's dictionary directly. |
| `has-file scripts/check_surface_contract.py` | This regenerates the contract artifact from the registry and the dataclass field names and byte-compares it. That is real drift protection for the artifact, and it is not a fixture gate: every fixture payload it writes is a capability id beside a contract name, so no fixture validates against any contract. |
| `has-name product/viva/surface/capabilities.py#TrustEffect` | Whether a capability that may call a model can ever honestly claim it may not egress is unsettled. The document-ingest capability now declares both, but the general question — whether the one should structurally imply the other — is left open. |
| `has-name product/viva/surface/capabilities.py#maturity` | Maturity is derived from reachability alone: a capability whose contract some operation serves reads stable, everything else reads preview. The surface read now declares the two contracts it delivers, so the field separates two capabilities from the rest and the signal is live. It stays uninformative for a capability with no destination, where it can only repeat "nothing serves this" — already true by construction — and it says nothing about how well a contract is served, only that something serves it. That is the accepted price of the field having one meaning, and no second field is added to fix it. |
| `has-name product/viva/desktop_bridge/surface_read.py#JobProgressEvent` | Started, completed and failed events are built here and written to standard output as frames marked as events. The host returns only the frame whose request id matches and which carries no event key, so every event frame falls through and is dropped: the events are produced and discarded. There is still no job registry and no cancellation. The wire is deliberately unchanged; the channel is designed in [jobs-and-the-progress-channel.md](jobs-and-the-progress-channel.md), where its first real producer lives. |
| `has-name product/tests/test_desktop_bridge.py#test_progress_event_frames_are_json_safe_and_preserve_order` | Three demonstrated defects travel with that channel. The request id is carried inverted — the progress sink is bound to the vault-open request, so a later read's events are stamped with the open's id. The job id silently defaults to a literal when a caller omits it. And this test builds its frames by hand and exercises the frame encoder, not the progress contract its name claims. |
| `has-name product/viva/desktop_bridge/__main__.py#_open_vault` | One typed failure code covers a wrong passphrase, a missing directory and a corrupt vault alike, with one message. The desktop discards even that: the client throws a generic error and the session catches it into a bare open-failed state, so the code never reaches a person. Malformed requests and handler exceptions are already bounded at the bridge boundary. |
| `no-name product/viva/desktop_bridge/handlers.py#BRIDGE_OPEN_VAULT` | This file imports the name of every operation it serves; it does not import this one. The open-vault operation is intercepted in `Sidecar.handle` as a branch before dispatch is ever called, so it never has its protocol major validated and it is in no allowlist. This is not an open door — its payload is fenced to a directory and a passphrase, both required non-empty strings, and anything else is rejected. It is an allowlist-of-one expressed as a branch, on the one operation that carries a passphrase, so **VOICE-109** has a hole at its most sensitive point. Recorded here and fixed in its own cycle. |
| `has-file desktop/src-tauri/src/main.rs` | Automatic recovery exists at the host level and is not user-facing: the request loop retries once after a clean reset, and only for the two operations it is safe to repeat. During a vault open what a person actually sees is the submit button relabelled and marked `aria-disabled` — still focusable, refusing a second press in words beside it; the reading notice appears only after the open returns. |
| `has-file desktop/src-tauri/src/main.rs` | The host has no operation allowlist. It is a transparent proxy: the operation it matches on gates retry safety only, and nothing on this side refuses an operation the sidecar would decline. The refusal lives entirely in the sidecar. |
| `has-file desktop/src/tauri-host.ts` | The frontend installs its bridge transport when the host runtime is present, and the entry point calls it. Whether that holds in a packaged application has never been observed. |
| `has-file desktop/scripts/check-ui-boundaries.mjs` | Drag and drop ships, and the fence around it is what makes that acceptable: the window never receives a file. The native layer takes the drop and hands over a path, the host shim opens nothing, and the sidecar reads the file. So this checker still forbids drop and drag handlers, the file-reading primitives, network fetch and file inputs in the shell and the documents feature; it now covers the host shim as well, with a named list of the two packages that shim may import; it forbids the `disabled` attribute anywhere in the tree; and it reads the Tauri configuration and fails if window drag-drop capture is ever switched off, because the day that becomes false, browser drop events return and the hole reopens in silence. It also constrains how the code it reads is written: it drives the TypeScript scanner with no parser above it, so a regular-expression literal leaves the scanner standing on one character, and a module under `desktop/src` writes its patterns as `new RegExp` instead. The ban is the checker's rather than the language's, and it is retired by teaching the scanner the construct, not by exempting a file. Reading any of it as an unfinished feature would turn a "fix" into a gate failure. |
| `has-file .github/workflows/quality.yml` | Every job the documents credit to the build is declared here and the file now loads, so the jobs exist. What no gate holds is that they *ran*: nothing in this repository reads a run's result, so a job that is declared, loadable and silently skipped or never triggered would look identical from inside the tree. |
| `has-file .github/workflows/release-desktop.yml` | Signing and notarization run on tag across every target the release manifest declares, and no updater artifact is published — nothing compiles an updater plugin into the application, so a signed update manifest would advertise a channel no installed copy can read, and the quality workflow builds the sidecar and the desktop bundle. What is outstanding is validation: no startup, shutdown or recovery check runs against a produced artifact in either workflow. |
| `has-file desktop/src/surface/fixtures/demo-snapshot.ts` | Diagnostic export exists only as a demo-mode capability row labelled not implemented. Watched-folder capture exists nowhere at all — no host permission, no product entry point, no interface for it. |
| `has-name product/viva/desktop_bridge/vault_surface.py#_review` | This read calls the open-question builder, which assembles every question family over the whole projection and ranks the result before applying the caller's limit — so its cost tracks the size of the ledger and the page size bounds nothing. No timing is carried here: this address is where a timing is taken, and a figure taken over a vault of uncategorised transactions on a single account is an upper bound for that shape of vault rather than a measurement of a real one. |
| `has-name product/viva/vault.py#open` | Opening a vault pays two independent key derivations under one passphrase, one for the ledger and one for the raw store, and whether two are necessary has never been examined. Each is memory-hard and its cost does not depend on how much is in the vault, so the pair is a fixed floor paid even opening an empty one. Because a memory-hard derivation has no intermediate state by design, that floor is also the part of vault-open that can never report progress. |
| `has-file docs/user-interface-architecture-and-delivery.md` | **VOICE-110**'s Exception says the installed build reporting its interface and sidecar revisions has nowhere to live because no Trust surface exists. A Trust surface exists. The requirement is still unmet and the stated reason is now false; correcting it belongs to that document's own cycle. |
| `has-file desktop/src/styles/surfaces.css` | The display face every figure and heading is set in is named eleven times across this file and `shell.css`, and is shipped nowhere: no `@font-face` rule, no font file under the desktop tree, no link in `index.html`. It resolves only on a machine that already has the face installed, and every other machine renders the fallback. That lands hardest where this cycle put the flagship figure — the fallback's numerals descend below the baseline, so the underline the figure carries as its route to its evidence is cut around the descenders and crosses the digits instead of sitting under them. The style gate asserts the family contains `serif`, which the fallback satisfies, so nothing goes red on it. Whether a given machine has the face is not a fact about this tree. |
| `has-name product/viva/surface/overview.py#_picture` | Five of the picture's paths are exercised by the parity fixture and by nothing else: the per-currency arithmetic above one currency, a currency whose total is withheld, an account no currency can be found for, the second arm of the reason vocabulary, and citation scoping per figure. The one real vault this product has reaches none of them — one currency, nothing unvalued, nothing withheld, nothing unplaced — and a settling sentence is structurally unreachable on it, because the envelope ties one to a refused gap and that vault declares no gaps. This is **VOICE-121** at its own address: the fixture proves the shape of these paths and nothing about what a person meets on them. |

### Gaps no machine in this repository can hold (8)

| Refusal | Gap |
| --- | --- |
| `unaddressable — whether a workflow has ever run to success is a claim about a run, not about the tree, and nothing in this repository observes a run.` | Running the release workflow with real platform signing credentials, publishing installer artifacts, and validating target-specific distribution. Update recovery is not outstanding work but a capability this build deliberately does not ship. This is **VOICE-121**'s second half exactly. |
| `unaddressable — whether an installed application started is a claim about a machine this repository has no access to.` | Packaged offline startup and automatic user-facing recovery on a clean machine. A compiling application and an installed one are separate claims and neither proves the other. |
| `unaddressable — which destinations the interface ships is declared in desktop/src/app/navigation.ts, and no guard in this repository reads TypeScript.` | The last column of the destinations table is stated rather than derived, so it can go stale silently — and so can the presence of a row the backend never declares, such as the interface's own spelling of the accounts destination, which nothing would notice being deleted. The checkable address is one the frontend boundary checker would have to serve, and it does not serve one yet. |
| `unaddressable — whether an operation is consumed is a fact about the desktop bridge client, which is TypeScript, and no guard in this repository reads TypeScript.` | The last column of the bridge-operation table is stated rather than derived. An operation can quietly become consumed while this document still says it is not, and the same frontend checker is where a derived answer would come from. |
| `unaddressable — the absence of a view is a claim about a capability, not about a name. The only machine spelling available would be that a word does not appear under a directory, and it returns the wrong answer: the word occurs under the trust feature while the capability does not exist.` | No outbound history. Every outbound edge the product has is unrepresented in the interface, so **T6** is currently kept by there being nothing to show rather than by showing it. |
| `unaddressable — a build-identity view would live in TypeScript, and no guard in this repository reads TypeScript.` | No build identity view. The installed build does not report the revisions it was made from anywhere a person can see. |
| `unaddressable — whether the picker is folder-only, and whether a cancellation stays distinct from a failed host call, are claims about TypeScript behaviour.` | The native folder picker's behavioural contract is held by nothing. The Python contract test asserts only that the host declares the dialog plugin and that the frontend shim exists; the frontend checker names the shim as the permitted site for the host package, which is a prohibition elsewhere rather than an assertion about the picker. Owned by that checker's next cycle. |
| `unaddressable — whether a figure reads correctly is a claim about type rendered in the application's own window, and nothing in this repository opens one.` | No layout claim about the picture has been checked against the running application. Every one of them — the sizes, the spacing, the separation between one currency's block and the next, and how the figure's underline meets its digits — was measured on a tree rendered by a headless browser from the same stylesheets, which shares the browser and not the window, the platform's own font stack or the packaged build. |

What *is* implemented is not restated here. A positive implementation claim
belongs in the rule block that carries it, beside its state and the evidence
for it: the rule blocks in
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md),
indexed with every other rule in [rules.md](rules.md). A summary of those claims
in this document would be a second copy of them, and two copies drift — which is
how this document came to describe a failing gate as working.

The capability registry deliberately keeps developer-only and deferred
operations — rebuild, reingest, reset, diagnostics, merchant enrichment, grammar
induction and evaluation — out of ordinary navigation, and that is a decision
rather than an omission.
