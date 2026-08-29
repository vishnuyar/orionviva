# User Interface Architecture and Delivery

**State:** partial
**Rules:** VOICE-100, VOICE-101, VOICE-102, VOICE-103, VOICE-104, VOICE-105, VOICE-106, VOICE-107, VOICE-108, VOICE-109, VOICE-110, VOICE-111, VOICE-112, VOICE-113, VOICE-114

The Tauri/React/sidecar direction is implemented; future slices still travel
through `WORKFLOW.md` and need their own approved brief. What is actually built
on the current branch is recorded in
[user-interface-implementation-status.md](user-interface-implementation-status.md).

## Rules

### VOICE-100 — the product is an installed desktop application, not a server
**State:** enforced-with-exception
**Code:** product/viva/desktop_bridge/rpc.py, desktop/src-tauri/
**Test:** product/tests/test_desktop_bridge.py::test_handshake_is_versioned_framed_and_says_which_build_answered

1. The shell and the bundled Python sidecar communicate over a small, allowlisted, typed JSON-lines protocol.
2. No localhost HTTP server is opened.
3. A person on a clean machine needs no terminal, no Python and no knowledge of API keys.

**Exception:** the repository builds the Tauri application and packaged sidecar,
and the release workflow builds, signs and notarizes the declared targets. A
clean-target installed startup has not been observed by a machine in this
repository, so assertion 3 remains a release validation claim rather than a
source claim. The bridge uses standard input/output rather than localhost; the
cited Python test covers the versioned handshake, while native packaging checks
cover sidecar identity before release.

### VOICE-101 — the dependency direction is one-way, and a test enforces it
**State:** enforced-with-exception
**Code:** product/viva/desktop_bridge/handlers.py, product/viva/desktop_bridge/rpc.py, desktop/scripts/check-ui-boundaries.mjs
**Test:** product/tests/test_surface_import_boundaries.py::test_product_tiers_import_only_along_permitted_edges, ::test_every_declared_tier_has_modules_in_it, ::test_core_does_not_depend_on_product_surface_or_desktop; `npm run check:architecture` in the desktop CI job

1. The desktop depends on the surface contract, never on event bodies or arbitrary projection methods.
2. `viva.surface` may depend on the engine, projections, the renderer and persona data; the engine and ledger never import the surface, the bridge or frontend code.
3. The bridge depends on `viva.surface`; `viva.surface` knows nothing about the bridge and imports no frontend dependency.
4. No Node, React, Tauri or browser dependency enters `core/`, `merchant/`, or the financial modules of `product/`.

**Which gate holds which half.** The Python half is a declared three-tier map: the engine, `viva.surface` and `viva.desktop_bridge` are named tiers, each module belongs to exactly one of them, and the permitted edges between them are declared as a set. The test parses every module in the product package into a syntax tree, resolves relative imports to the module names they name, and reports any edge that is not declared. The frontend tier is decided by resolution rather than by a name prefix: a module belongs to it when its top-level name resolves to a path inside the desktop tree, and the test refuses to run if that tree is not there. Assertion 3 is now the map rather than something it forbids: the bridge may import the surface and the engine, the surface may import the engine, and the engine may import neither. The TypeScript half belongs entirely to `desktop/scripts/check-ui-boundaries.mjs`, which drives the TypeScript compiler's own tokenizer, carries its own declared map of what each directory may import, and runs in the desktop CI job. No Python test reads TypeScript to decide an import boundary. Two protocol tests in `product/tests/test_surface_contract.py` do read `desktop/src/bridge/contracts.ts` and `desktop/src/tauri-host.ts`, on a different subject: each host declares the frame protocol version once, and those tests compare that declaration against the version the sidecar speaks. Comparing two declarations is not a boundary rule, and it belongs to the protocol rule rather than to this one.

**Exception:** the Node checker's map closes the import list for `desktop/src/features/**`, `components/**`, `surface/adapters/**`, `bridge/**` and `surface/fixtures/**`, forbids the native dialog import by name in the app shell and the documents feature, and permits `window` only under `bridge/` and at `tauri-host.ts`. It does not cover files sitting directly in `desktop/src/app/` other than the app shell, the top level of `desktop/src/surface/`, or root-level modules such as `main.tsx`; one of those could import a native plugin and no gate would say so. The documentation gate compares every operation the Python table declares with the literal operation names the TypeScript client consumes, and client tests pin payloads for current bounded calls, including every Activity correction. No cross-language gate derives every request payload schema from one authority. The remaining gaps belong to the Node checker and contract gates: extend the path map and replace checked payload examples with an exhaustive coupling when a registry can supply one.

### VOICE-102 — the interface renders values and computes no financial fact
**State:** enforced-with-exception
**Code:** product/viva/surface/models.py:27 (`FigureView`), desktop/src/app/data.ts
**Test:** product/tests/test_render.py::test_no_module_that_speaks_to_a_person_formats_money_itself

1. The interface never adds money, converts currency, chooses a grade, infers completeness, or derives direction from a sign.
2. It may plot backend-supplied points, but the exact tooltip is the backend's canonical display string.
3. This is a rule the surface derives from T2 rather than a restatement of it: arithmetic is deterministic *and* the interface does none of it.

**Exception:** the test covers Python modules that speak to a person. Nothing gates the TypeScript side — `desktop/src/app/` currently contains no money formatting or parsing, but it holds by inspection rather than by a check.

### VOICE-103 — every figure crossing the boundary proves itself
**State:** enforced-with-exception
**Code:** product/viva/surface/models.py:44 (`FigureView.__post_init__`), product/viva/surface/proof.py
**Test:** product/tests/test_surface_contract.py::test_figure_rejects_float_values, ::test_proof_presentation_is_closed_and_cannot_hide_a_required_reason

1. A figure carries an exact decimal string, never a float, and a float fails construction.
2. A figure without identity, measure, as-of date or coverage does not come into being.
3. A figure carries its grade, a reviewed plain-language grade label, exactness, record ids, provenance and named caveats.
4. Currency is present for money and absent for counts and rates; a blank currency is refused.
5. The model never supplies a number from its own head; it only ever routes numbers from the ledger, and an answer's confidence language inherits the weakest grade it stands on.
6. Every canonical figure declares compact proof `routine` or `required` from
   structured evidence state. Routine proof has no reasons or qualifications;
   required proof carries both machine reasons and reviewed qualifications, so
   suppressibility is never inferred from a grade word in the interface.

**Exception:** only the second clause of assertion 4 is enforced. `product/viva/surface/models.py` refuses a currency that is present and blank, and nothing ties currency presence to what the figure measures, though the measure it declares is now a word from the closed vocabulary (VOICE-104).

### VOICE-104 — the `measures` vocabulary a figure declares is closed
**State:** enforced
**Code:** product/viva/quantity.py:138 (`MEASURES`), product/viva/surface/models.py (`FigureView.__post_init__`)
**Test:** product/tests/test_surface_contract.py::test_figure_declares_a_measure_the_vocabulary_holds

1. A figure crossing to an interface declares what it measures from the closed vocabulary the answer path uses, so a debt cannot arrive declaring itself a balance and a raw sum cannot arrive declaring itself spending.
2. A figure declares from `MEASURES` and a magnitude hole asks from `KINDS`; `MEASURES` is `KINDS` plus `unmeasured`, which is why a figure may declare that nothing measured it and no hole may ask for it.
3. A word outside the vocabulary fails where the figure is built, not where it is read.

### VOICE-105 — every read model declares one explicit panel state
**State:** enforced
**Code:** product/viva/surface/models.py:10 (`PanelState`)
**Test:** product/tests/test_surface_contract.py::test_panel_states_and_action_outcomes_are_closed

1. The states are `absent`, `ready`, `partial`, `needs_input`, `unavailable`, `failed`, and the set is closed.
2. `absent` means do not render this panel; `failed` blames the component, not the vault.
3. This is progressive disclosure as a contract rather than a collection of frontend conditionals.
4. A panel earns its existence from data: net worth and trends do not render until they have something honest to say.

### VOICE-106 — an action returns what happened, never a bare `ok`
**State:** enforced
**Code:** product/viva/surface/models.py:71 (`ActionOutcome`)
**Test:** product/tests/test_surface_contract.py::test_panel_states_and_action_outcomes_are_closed

1. Every action returns one of: completed, refused, proposal, waiting, stale, `set_aside`.
2. A refused action requires a machine reason; construction fails without one.
3. The interface never infers what happened.

### VOICE-107 — the protocol refuses rather than guesses
**State:** enforced
**Code:** product/viva/surface/protocol.py:26 (`accepts`), product/viva/desktop_bridge/rpc.py:31 (`decode_frame`)
**Test:** product/tests/test_surface_contract.py::test_protocol_accepts_additive_minor_changes_only

1. Additive optional fields advance the minor version; removing a field or changing its meaning advances the major.
2. An unknown major refuses to open the product surface; it never continues with guessed semantics.
3. A newer minor is rejected without calling the handler, and a malformed frame fails closed.

### VOICE-108 — every capability has a destination or a recorded reason for not having one
**State:** enforced
**Code:** product/viva/surface/capabilities.py (`CapabilitySpec`), product/viva/surface/operations.py
**Test:** product/tests/test_surface_capability_coverage.py::test_non_surface_capabilities_have_explicit_disposition_and_reason, ::test_maturity_is_read_from_the_operation_table_and_never_typed

1. A surfaced capability requires a destination and a contract, and may not carry a reason.
2. A non-surfaced capability requires an explicit `developer_only`, `internal` or `deferred` disposition *and* a reason.
3. Every command entry point is classified, so a new command cannot enter unnoticed.
4. Each capability declares its trust effect: reads data, writes an event, may call a model, may egress.
5. A capability's maturity is what the operation table says and nobody types one. One declared table of bridge operations lives in the surface package; the bridge builds its handler map from it and the registry reads it to derive maturity. A capability whose contract is served by an operation in the table is `stable`; one whose contract is not served is `preview`. Reachable is the only thing maturity means — a capability that is reachable but not yet trustworthy would be a second reason, and a second reason is a second field.
6. Reachability is what the sidecar serves, never what a desktop client calls, because the registry may not depend on reading frontend source.

### VOICE-109 — the bridge is transport and nothing else
**State:** enforced-with-exception
**Code:** product/viva/desktop_bridge/handlers.py:17 (`BridgeDispatcher`)
**Test:** product/tests/test_desktop_bridge.py::test_unknown_operations_are_refused_by_the_allowlist, ::test_an_operation_the_registry_does_not_declare_is_refused_by_name, ::test_every_action_the_registry_declares_is_served

1. The bridge validates a protocol version, dispatches an allowlisted operation, emits job-state frames and serializes the result.
2. It computes no total, infers no grade, decides no movement's direction and manufactures no user-facing caveat.
3. The allowlist snapshot cannot be mutated after the dispatcher is created, and handler failures return safe error frames rather than raising.
4. Every action a capability declares reaches the sidecar as an operation of its own — `viva.conversation.decline`, not a generic `act` carrying an action name — derived from the registry rather than written by hand, so the operation table read on its own is the complete list of everything that can touch a vault. An action no handler serves is a declared operation the allowlist refuses; this build serves all of them, and declaring a new action without one fails a test rather than reaching a person as a button that says no.

**Exception:** document work now has a live job registry, progress records,
polling, and cancellation. The native request loop still does not subscribe to
the sidecar's event-frame stream; the desktop obtains job state through the
reviewed read instead. Separately, `bridge.open_vault` and
`bridge.open_demo_vault` are explicit sidecar branches before dispatcher
construction, so they are fenced operations but not members of a dispatcher
allowlist.

### VOICE-110 — compiled frontend output is never committed
**State:** by-review-with-exception
**Code:** .gitignore:95
**Test:** none

1. `desktop/dist/` is ignored and untracked; a generated bundle is never treated as source.
2. Installers are built from clean source.

**Exception:** Trust now shows the sidecar's reported revision and the lifecycle
read repeats its origin. The frontend does not report a distinct UI source
revision, so the two halves of an installed build cannot yet be compared by a
person.

### VOICE-111 — every direction shown comes from the account's kind, never a posted sign
**State:** enforced
**Code:** product/viva/ledger/projection/merchants.py:146 (`implication_of`), product/viva/ledger/streams.py:79 (`money_effect`)
**Test:** product/tests/test_direction_site.py::test_a_purchase_on_a_liability_is_money_leaving_not_money_arriving, ::test_a_movement_with_no_account_kind_raises_rather_than_guessing, ::test_the_site_reads_no_posted_sign_at_all

1. The site M2 named is closed: `implication_of` asks the one function that decides direction from the account's kind, and that function raises when it is handed no kind rather than falling back to the posted amount.
2. The guard is structural rather than a comment: a test parses the site and fails if it compares a movement's amount to anything but what that function returned.
3. Direction filters and a transaction detail speaking direction are therefore no longer held by this rule. What still holds them is that nothing supplies either.

### VOICE-112 — the surface never claims machinery the product does not have
**State:** unmet
**Code:** desktop/src/features/trust/Trust.tsx, desktop/src/features/documents/Documents.tsx, desktop/src/app/App.tsx
**Test:** none — the remaining gap is an end-to-end Documents claim rather than a Python symbol assertion.

1. Trust shows what is and is not externally anchored, rather than claiming anchoring: T4's chain is hash-chained but not anchored.
2. A Documents surface does not paper over T3 being met on originals and unmet on the ingest request.
3. Passphrase recovery is stated as it exists: today, losing the passphrase loses the vault.
4. Outbound accounting is not claimed complete before it is.
5. The interface names no capability a later phase will have, including as a coming-soon.

**Current condition:** Trust states that external anchoring is absent, renders
the backend's bounded outbound record and its absences, and shows build and
lifecycle identity. The vault-open path states passphrase loss plainly. The
rule remains unmet because the Documents journey does not yet distinguish what
the encrypted-original guarantee covers from what is and is not attested about
the ingest request itself.

### VOICE-113 — these options are removed from future consideration
**State:** untestable
**Code:** none found
**Test:** none

1. Not reconsidered unless the product vision changes: a hosted service holding readable financial data; chat-first navigation; a terminal as the end-user product; a localhost-browser UI as the shipped experience; Electron; a macOS-only UI without an explicit platform decision; a button for every command; raw event records exposed to the frontend; frontend calculation of totals, grades, direction or completeness; remote UI plugins or a component marketplace; a setup wizard requiring every account before value appears; push notifications, streaks, urgency badges or engagement mechanics; voice-only answers with no mirrored evidence; a separate UI repository.
2. The retained alternative is PySide6/QML, if a mostly-Python toolchain is later ruled to outweigh the frontend and distribution shape.

### VOICE-114 — with no reader configured, a document is saved privately and reading waits
**State:** enforced-with-exception
**Code:** product/viva/ingest/reader.py:198 (`_parking_reader`), :204 (`parking_reader`), :230 (`build_reader`), product/viva/ingest/pipeline.py:104 (capture first, always), product/viva/surface/documents.py (the sentence, composed from the pack)
**Test:** product/tests/test_reader_config.py::test_reader_factory_gates_on_env, ::test_a_parked_document_carries_the_reason_it_was_not_read; product/tests/test_capture_first.py::test_the_raw_blob_is_stored_before_the_reader_is_called, ::test_a_reader_that_raises_does_not_take_the_document_with_it; product/tests/test_surface_documents.py::test_a_document_nothing_has_looked_at_says_so_once_on_the_panel, ::test_a_document_that_was_read_and_yielded_nothing_is_not_one_nobody_read; product/tests/test_document_actions.py::test_a_captured_document_is_sealed_and_the_reply_says_reading_waits

1. With no reader configured, Documents says: "Saved privately. Reading will wait until you choose a reader."
2. The file is captured before anything reads it, then parked unread, and nothing leaves the machine.
3. A parked document names the reason it was not read, so one that never left the machine is not mistaken for one that was read and yielded nothing.

**Exception:** assertion 3 is held to the width of three words and no further. The vault records no reason a document went unread — `DocumentCaptured` carries an id, a name, a length, a type and a confidence, and nothing about why nothing looked — so what a row can say is derived from whether any reading was ever recorded against it: nothing looked, something looked and yielded nothing, something looked and made something of it. That separates the two states the assertion is about, which is what it asks for. It does not name a reason: a document nothing looked at because it was over the size ceiling and one nothing looked at because no reader has been chosen carry the same word, and only the panel's own sentence says which of those the vault is in.

Assertions 1 and 2 are held. The sentence is the persona pack's, composed in `product/viva/surface/documents.py` and rendered once per panel rather than once per row. The ordering is held by a named test that drives the capture path with a reader inspecting the raw store at the moment it is called, and by a second one whose reader throws; before those existed the whole suite stayed green with the capture moved after the read.

## Why

**The recommendation is a desktop-first installed application**: a Tauri shell,
a React and TypeScript presentation layer, the existing Python product bundled
as a sidecar, a small allowlisted typed IPC protocol between them, a
`viva.surface` package converting projections and actions into stable contracts,
a signed macOS Preview first with the structure portable from the first slice,
and a bundled, clearly synthetic demo vault so a new person can try the product
without an API key, model setup, or personal financial documents. It is not the
cheapest first-week implementation. It is the recommendation for the durable
product: the one a person installs, the team extends one vertical slice at a
time, and the repository keeps synchronized with the financial engine by
construction.

**The vision had already settled the load-bearing choices.** The target user can
install an app and should not need a terminal, a server, a configuration file or
knowledge of API keys. The product opens as a picture. Viva never interrupts, so
findings become quiet inspectable state. Day one is a greeting and a document
drop, and panels earn their existence. Every figure proves itself and names what
the product has not seen. Anything leaving the device has a visible reason and a
permanent record. Text and voice both belong to the first public experience,
with spoken answers mirrored in text so their evidence stays inspectable.

**The code had already prepared the right seam.** `viva.engine` sits beside the
vault rather than beneath a surface, returns JSON-safe values, and owns the
inbound actions. The question and pending queues are read-side projections
independent of any caller. What was missing is not another financial core; it is
a **presentation facade** that gives the interface a stable vocabulary and stops
it reaching through to arbitrary projection methods or event bodies.

**Why one repository.** A separate UI repository would make synchronization a
social promise when it needs to be checked. A product change and the surface
contract it affects belong in the same reviewable history, on short-lived
feature branches with one pull request per approved vertical slice — never
permanent backend and UI branches.

**Why the Tauri option won, and what it costs.** It produces an installed
application rather than a browser ritual, preserves the Python trust core, gives
the interface a mature typed component and testing ecosystem, makes the
shell-to-product boundary explicit and allowlistable, supports bundled external
programs and signed updates, and leaves a credible route to Windows and Linux.
It costs a Rust and a Node toolchain beside Python, a sidecar built per
architecture, and real product work in IPC, signing, notarization and updates.
Its one dangerous failure mode is the compiled frontend going stale — which is
exactly the failure a previous surface was rebuilt over — so the ruling closes
it in the build system rather than in anyone's memory: compiled output is never
committed, installers build from clean source, one protocol version spans both
halves, and the installed build reports both source revisions.

PySide6 with QML is the strong fallback if minimizing toolchains is ever ruled
more important than frontend ecosystem and long-term surface flexibility. The
others were discarded with reasons worth keeping: pywebview varies by platform
and has a weaker security and update story; a local web server leaves a person
managing a server-shaped product and complicates key custody, lifecycle, watched
folders, voice and OS integration; Electron brings a Chromium and Node runtime
where Tauri or Qt already fit; SwiftUI is Apple-only and duplicated the day
Windows arrives; Flutter adds Dart and still needs a Python boundary; and a
terminal cannot satisfy X1 or the picture-and-provenance experience, however
useful it is as development and recovery tooling.

**The surface contract is the central anti-staleness mechanism**, which is why
it is versioned, typed, validated on both sides, and represented by synthetic
fixtures. Three shapes carry it. A **figure** delivers exact value, canonical
display, currency, what it measures, grade and grade label, exactness, as-of
date, coverage, the records behind it, provenance available now, and named
caveats. A **panel state** is one of six explicit values, which turns
progressive disclosure into a contract instead of frontend conditionals. An
**action outcome** says what happened — completed, refused, proposal, waiting,
stale, `set_aside` — because an ambiguous `ok` forces the interface to infer,
and inference is where quiet wrongness lives.

**The capability registry is how a feature becomes visible, or deliberately not.**
It is both a backend inventory and the UI's progressive-disclosure input, and it
is deliberately *not* a dynamic plugin system: frontend feature modules stay
static and typed, and the backend manifest only says whether they are meaningful
and available for this vault and build. Two coverage rules follow — every
registered action has a destination or a recorded non-user disposition with a
reason, and every desktop feature consumes a registered capability and known
contract — and the command inventory is checked mechanically so a new command
cannot enter unnoticed.

**Why an action is its own operation.** The question that decides this is not
what the bridge should know but what a reader of the operation table can see.
The interface is a webview running JavaScript and its dependency tree, so *what
can be done to this person's vault?* has to be answerable from the sidecar's
side alone. With one generic `act` verb the answer is *whatever the registry
declares* — one indirection away, in a table that grows. With an operation per
action, the table is the answer. The blast radius is identical either way, since
the sidecar validates against declared actions in both; what differs is the
legibility of the write surface, which is the property this product should be
optimising. Deriving the operations from the registry rather than hand-writing
them keeps what the generic verb was for: the registry stays the authority,
adding an action stays a registry change, and a gate compares the two. It also
keeps `serves` precise, where a generic verb would serve five contracts at once
and tell the maturity signal nothing.

**What each product surface holds.** This map is the part a reader needs before
any of the rules above mean anything.

- **Overview — the opening picture:** a quiet completeness line of
  current-through dates and named gaps; net worth by currency, never a false
  converted grand total; account cards with kind-aware semantics; recent inflow
  and outflow summaries; the highest-consequence questions; a quiet "Viva
  noticed" area only when a real finding exists; and a persistent add-document
  affordance. An empty vault shows a greeting, a document drop, and "Explore
  with sample data".
- **Accounts — reached from the picture:** an account detail page carries its
  kind-specific headline, grade, date, omissions, activity, statements and
  questions. Depositories speak balance; liabilities speak owed and distinguish
  a credit balance; investments expose the statement's own composition and
  measurement dates; asserted assets speak cost and say when they rest on the
  person's word.
- **Activity:** a searchable movement view with account, merchant, category,
  tag, date, direction and nature filters; transaction provenance; category and
  tag corrections; and transfer relationships. It presents useful product
  meaning from the diagnostic reports without reproducing those reports as
  screens.
- **Documents:** the lifelong ingestion surface — drag and drop, file
  selection, the captured, read, verified, posted, held and parked states, what
  a document contributed, why something waits, and focused correction. With no
  reader configured it says so (**VOICE-114**).
- **Viva conversation:** summoned through a stable button, opening one side
  panel that holds durable turns, consequence-ranked questions, one
  natural-language answer path, evidence and scope, pending items, respected
  declines, and proposal confirmation where X3 requires it. Text and later
  voice share this one session, and every figure opens the same Evidence drawer
  used everywhere else.
- **Trust and settings:** every outbound event and its purpose; model calls and
  maintenance-call budgets; maintenance actions and outcomes; vault integrity;
  application and protocol versions; provider and network permission; locale and
  currency display; and vault export and backup. What it may say about
  anchoring, outbound completeness and passphrase recovery is **VOICE-112**.

**Not every command deserves a button.** The product shows outcomes and
decisions; it does not reproduce terminal output screen for screen. Asking goes
to the Viva conversation; upload goes to Documents, with rescan and
healing as background work reported there; the maintenance agent goes to
maintenance activity and Trust; merchant enrichment stays proposed maintenance
until its privacy boundary closes; grammar induction is private maintenance
audited in Trust; the diagnostic reports are developer tooling from which
selected findings become Activity or quiet state; rebuild, reingest, reset and
ruling diff are an advanced vault laboratory rather than ordinary settings;
ruling export is advanced data export with an explicit privacy warning; and
evals are CI and developer tooling only.

**The gates catch different failure shapes, which is why there are several.**
Contract drift regenerates the schema and synthetic responses from the Python
models and compares them with reviewed fixtures, failing on a changed field, a
changed closed vocabulary, a fixture that no longer validates, stale generated
types, or a protocol disagreement — and the schema is the review artifact, never
a generated bundle. Consumer completeness revives the strongest idea from the
deleted debug surface: every field a read model delivers is either rendered by
its owning feature or deliberately ignored with a reason in that feature's
adapter, through typed exhaustive adapters rather than by passing arbitrary
response objects into components. Capability coverage flags a *new addition*
even when no schema changed. The interface-impact declaration reads the diff
against a reviewed path map and lets an internal change pass by declaring
**interface impact: none** with a concrete reason the Verifier confirms — an
escape hatch that is essential, because requiring cosmetic UI churn for an
internal bug fix would train the team to bypass the gate, and an explicit
reviewed hatch beats a silent one. Frontend checks cover typecheck,
accessibility, fixture-driven states and a small set of visual snapshots, which
review layout drift and never certify financial meaning. And the packaged smoke
test builds from a clean checkout with no committed frontend output, opens the
synthetic vault, exercises the real flows, and asserts the installed build
reports its revisions — which directly answers the stale bundle, because CI
tests what a person will install rather than a neighbouring development server.

**Five worked cases, so the gates can be applied without guessing.** A
projection that adds `excluded_from_spending` fails contract drift: the Overview
adapter must render the caveat or deliberately reject the field with a reviewed
reason, its partial fixture changes, and the visual state is reviewed. A
reconciliation bug fixed without a response-shape change is interface-sensitive
but leaves the contract fixtures unchanged: the pull request declares that
values are corrected while the contract is unchanged, engine tests and a Witness
run where needed settle the claim, and no meaningless React edit is required. A
new command report fails command-inventory coverage until it is classified — a
diagnostic records `developer_only` and why, a product capability names its
destination and contract. And obligations arrive as a registry entry:
`obligations.read` with its availability rule, trust effect, contract and
Overview and Account consumers, so "Viva noticed" appears only once a real
obligation exists and no new shell or top-level navigation item is needed.
Finally, the progressive-proof case is now built. `AccountOverview.v2` gives
each canonical figure a closed `proof_presentation` declaration, and a local
versioned **Show verification details** preference hides only compact assurance
the backend marks `routine`. The adapter switches on that declaration, never
on a grade word; required backend-authored qualifications and caveats remain
visible, and changing the preference changes neither the payload nor anything
an authorised agent can inspect. The complete Evidence drawer remains
preference-independent for the canonical figures that already opened it; the
change does not turn Activity amount strings or recent-signal strings into
figures with receipts.

**The demo vault is a product requirement, not sample decoration.** Install,
choose sample data, see a clearly fictional but mature financial picture, try
the Viva conversation, evidence and documents, reset at will, and create a private
vault only when ready. Its fixtures cover empty, sparse, mature, stale,
conflicted, mixed-currency, held-document, provisional-spending and
missing-account states, and contain no transformed real financial data. Preview
builds carry a quiet Preview label, no telemetry, and a user-triggered
diagnostic export whose contents are shown before anything is written or sent.

**How this joins the loop.** The existing roles stay; interface parity becomes
part of what each asks. Every brief gains an interface-impact section — what a
person sees before and after, which destination owns it, when it appears, and
its absent, partial and failed states — where "no impact" is a claim to justify.
The Fact-checker checks claimed surface against code by running the contract and
coverage inventory. The Builder builds a vertical slice: product change, adapter,
contract, fixtures, consumer, tests — and an internal change records that
disposition instead of inventing a screen. The Verifier confirms the impact
declaration. The Witness runs when a changed surface tells a person something
about real money, because synthetic fixtures prove rendering and not truth. And
the Steward asks: *what did this cycle make newly visible, newly invisible, or
stale on an existing surface?*

**Later roadmap work arrives as vertical features rather than new shells.**
Obligations, fees, anomalies and subscriptions enter the quiet noticed state and
the relevant account detail. Budgets and goals earn a Plans destination only
after a first plan exists or someone asks for one. Loans, insurance, tax and FX
extend instrument and document modules and Viva's tools. Selective disclosure
becomes Proofs inside Trust; household support becomes a scope switch over the
same projections; multi-device sync becomes Devices under vault settings; and
account connections become another capture source under Documents.

**A change is not done** until its interface impact is declared, every new action
or command has a disposition, protocol and schema stay compatible or are
intentionally versioned, exact values and grades and dates and coverage and
caveats all come from the backend, the meaningful states are covered, the
desktop performs no financial arithmetic, the gates pass, the clean packaged
synthetic path passes, a Witness run exists where a person is told a changed
fact about real money, the status documents describe the final state, and the
Steward has answered the question above.

## Open

- Release ownership, protected-path review, and the first publicly supported
  platform still need explicit governance. The Tauri/React/sidecar shape,
  `viva.surface` boundary, capability registry, and impact gates are implemented
  decisions rather than pre-build questions.
- The earlier question about whether the question queue and conversation should
  be separate is settled: they are one `conversation` read and one installed
  interface. Overview consumes the question summary from that same read; it
  does not hold a parallel question snapshot. Activity remains its own
  list-shaped projection because it is a primary financial surface rather than
  conversational state.
- **Where a coverage claim belongs, settled for a figure that stands for the whole picture.** A figure over one account carries its own coverage line, naming the account it is over and the day it is good for. A figure standing for the whole picture is over none of the accounts it composed, so it may inherit none of their boundaries: it carries what the read itself declared — the currency it was cut to, how many accounts could not be valued, how many documents are not counted in it, the day the read was made and the oldest measurement beneath it — while **how far the picture reaches is one claim about the whole answer and is said once, at the panel, over the figures the panel actually shows.** That sentence answers *how many accounts* and a person reads it as *is this everything*, so where every account is counted it still says whether anything else is missing — chosen by the boolean the read declares about itself, and carrying its own resolution rather than handing off to the line after it — what else is short of whole is said on a figure, which is a different card and may be one of several, so a sentence that depends on what follows it depends on a layout it cannot see. What it is counted against is the union of the accounts the read ranged over and the accounts the vault holds, because a read is authoritative about what it valued and not about what a person has: an account a ruling brought into being that nothing has been posted to reaches no read at all. That panel sentence **counts and never names**: a list of account names is the one thing on that screen a person cannot un-share, and the names are already on the cards below it. MON-27 looks like it conflicts with that and does not — it requires that an account the point cannot value is named with the reason and never dropped, and it is: the unvalued accounts ride the figure's own declared boundary and reach the evidence drawer. **The point names and the sentence counts**, and that is the whole of the reconciliation, written here so a later cycle does not derive it again. The rule has one bound, and it is the ground the rule stands on rather than an exception to it: the panel counts rather than names **where the names are already on the screen**. An account no currency can be found for is beneath no figure, and so appears on no card, in no line and in no drawer — the redundancy the rule rests on does not reach it, and the panel names it, because a name nowhere is not privacy but concealment.
- What a breakdown looks like on a screen. A turn can enumerate in text — a name and an amount per line, the set's grade above, the read's tail sentence below — and that decides nothing about the visual form.
- The pull-request template, CODEOWNERS, and branch protection over the surface, schema, bridge, desktop and impact maps.
- Phone capture's design is separate and unheld.
- Each delivery slice leaves the application coherent, testable and usable against a synthetic vault, and a slice is a build order inside an approved brief rather than a license to bypass the project loop. The acceptance criteria those slices still owe:
  - The installed application is offline.
  - Restart is safe.
  - Capture occurs before reading, in the document journey a person sees.
  - A restart during document work recovers an honest job state.
  - No network call is silent.
  - The empty, partial, full, conflicted, stale, mixed-currency and overpaid-liability fixtures all render honestly.
  - Every figure exposes grade, date, evidence and omissions.
  - Every current question kind is answerable.
  - A stale question cannot write.
  - The queue re-reads after every ruling.
  - Every conversation turn re-reads current state.
  - Text and spoken output agree.
  - Refusal and gap states are explicit.
  - Document injection cannot grant a write.
  - Corrections survive restart and re-projection.
  - Totals agree with the surface read models.
  - Every existing outbound edge has a representation.
  - Maintenance history survives restart.
  - Install and update run on clean machines.
  - Updates have a recovery story.
  - A diagnostic export previews exactly what will leave.

## Related

`VISION.md` · [experience-vision.md](experience-vision.md) ·
[the-surface-cards.md](the-surface-cards.md) ·
[the-presentation-layer.md](the-presentation-layer.md) ·
[the-question-queue.md](the-question-queue.md) ·
[the-maintenance-agent.md](the-maintenance-agent.md) ·
[agent-toolset.md](agent-toolset.md) ·
[adoption-and-distribution.md](adoption-and-distribution.md) ·
[design-invariants.md](design-invariants.md) ·
[user-interface-implementation-status.md](user-interface-implementation-status.md) ·
`WORKFLOW.md`

External references supporting feasibility, not product decisions: Tauri
[sidecars](https://tauri.app/develop/sidecar/),
[updater](https://v2.tauri.app/plugin/updater/) and
[security](https://tauri.app/security/) ·
[Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html) ·
[Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security),
relevant to the discarded option.
