# User Interface Architecture and Delivery

**Status:** Proposed — a direction for review, not a claim about what is built.
Each implementation slice still travels through `WORKFLOW.md` and requires its
own approved brief. · **Opened:** 2026-08-16

**Invariants touched:** **T1** (every figure states what it rests on, how its
arithmetic came out, and what set it covers) · **T2**, applied to the surface
(arithmetic is deterministic and models never certify — from which this document
derives a *new* rule, that the interface computes no financial fact either;
dependency rule 5 in section 5 is that rule, not a restatement of T2) · **T3**
(capture-first — and T3's 2026-08-15 amendment says it is met on originals and
**unmet on the ingest request**, which a Documents surface must not paper over) ·
**T4** (state is a projection of an append-only log — and T4's 2026-08-15
amendment says the chain is hash-chained but **not anchored**, which is why the
Trust destination in section 8 says *what is and is not externally anchored*
rather than claiming anchoring) · **T5** (no plaintext phase, anywhere, ever) ·
**T6** (nothing leaves silently) · **T8** (models remain replaceable and
untrusted) · **T9** (the personal/impersonal boundary is drawn at package edges
— the reason section 9 holds merchant enrichment as proposed maintenance rather
than a button) · **I1–I6** (currency, locale, and regional capability honesty) ·
**M1–M2** (cash-flow semantics and kind-aware direction) · **X1** (the default
user can install an app) · **X2** (uncertainty is visible, never decorative) ·
**X3** (an irreversible action waits for an explicit yes).

---

## 1. The decision this document recommends

Build OrionViva as a **desktop-first installed application**:

- **Tauri 2** is the desktop shell.
- **React + TypeScript** is the presentation layer.
- The existing Python product is bundled as a **sidecar executable**.
- The shell and sidecar communicate through a small, allowlisted, typed IPC
  protocol. No localhost HTTP server is opened.
- A new Python package boundary, `viva.surface`, converts product projections
  and actions into stable interface contracts.
- The first distributable target is a signed macOS Preview build; the structure
  remains portable to Windows and Linux from the first slice.
- A bundled, clearly synthetic **demo vault** lets a new person try the product
  without an API key, model setup, or personal financial documents.

The application opens as a financial picture. Viva is summoned when wanted.
Features appear only when the data makes them useful.

This is not the cheapest first-week implementation. It is the recommendation
for the durable product: the one a person installs, the team can extend one
vertical slice at a time, and the repository can keep synchronized with the
financial engine by construction.

## 2. Why this direction fits OrionViva

The product vision has already settled the experience's load-bearing choices:

1. The target user can install an app and should not need a terminal, server,
   configuration file, or knowledge of API keys.
2. OrionViva opens as a picture, not a chat.
3. Viva never interrupts. Findings become quiet, inspectable state.
4. Day one is a greeting and a document drop; panels earn their existence as
   the financial picture grows.
5. Every figure proves itself and names what the product has not seen.
6. Any bytes leaving the device have a visible reason and a permanent record.
7. Text and voice belong to the first public-user experience; spoken answers
   remain mirrored in text so their evidence is inspectable.

The code has also prepared the correct seam. `viva.engine` sits beside the vault
rather than beneath a surface, returns JSON-safe values, and already owns the
inbound actions: answering a question, confirming a proposal, uploading a
document, correcting a held read, assigning a category, and tagging. The
question and pending queues are read-side projections independent of a caller.

What is missing is not another financial core. It is a **presentation facade**
that gives the interface a stable vocabulary and prevents it from reaching
through to arbitrary projection methods or event bodies.

### State checked when this document was opened

Checked against the tree on 2026-08-16:

- There is no web or desktop surface in `product/`.
- `viva.ask` is the terminal surface for Viva asking a person.
- `viva.speak` is the terminal surface for a person asking Viva.
- `viva.agent`, enrichment, induction, rebuild, reingest, reports, and evals are
  separate command entry points.
- `.github/workflows/` contains the DCO check only.
- `.githooks/pre-commit` is a privacy gate over staged additions. It does not
  run product or interface checks.
- No hard gate currently detects a backend capability that has no interface
  disposition or a changed backend contract whose interface consumer is stale.

These are present-state claims, not promises. A later status amendment must
re-check them before repeating them.

## 3. Form-factor options considered

### Option A — Tauri + React/TypeScript + Python sidecar

**Advantages**

- Produces an installed desktop application rather than a browser ritual.
- Preserves the existing Python trust core.
- Gives the interface a mature typed component and testing ecosystem.
- Makes the shell-to-product boundary explicit and allowlistable.
- Supports bundled external programs, including a packaged Python executable.
- Supports signed application updates.
- Leaves a credible route to Windows, Linux, and later companion-device work.

**Costs and risks**

- Adds Rust and Node build toolchains beside Python.
- The sidecar must be built per operating-system architecture.
- IPC, signing, notarization, and update infrastructure are real product work.
- A compiled frontend can become stale if generated artifacts are treated as
  source or builds occur outside a clean, reproducible pipeline.

**Ruling recommended:** choose this option and close the stale-artifact risk in
the build system: compiled frontend output is never committed, installers are
built from clean source, the UI and sidecar carry one protocol version, and the
installed About/Trust view exposes both source revisions.

### Option B — PySide6 + Qt Quick/QML

**Advantages**

- Keeps the runtime mostly in Python.
- Can call the product directly without a sidecar transport.
- Has an official cross-platform deployment tool.
- Offers strong desktop and operating-system integration.

**Costs and risks**

- QML is still a second presentation language.
- The contributor and testing ecosystems are smaller than the web stack's.
- Update distribution needs additional machinery.
- Rich document, evidence, chart, and conversation interactions will be more
  specialized to build and test.

**Disposition:** the strong fallback if minimizing toolchains is later ruled
more important than frontend ecosystem and long-term surface flexibility.

### Other options

- **pywebview + Python:** fast to prototype, but packaging and behavior vary by
  platform and the security/update story is weaker. Prototype only.
- **Local web server + browser/PWA:** fast development, but it leaves the user
  managing a server-shaped product and complicates key custody, lifecycle,
  watched folders, voice, and OS integration. Internal harness only.
- **Electron:** mature and predictable, but it brings a Chromium/Node runtime
  and larger dependency and patch surface where Tauri or Qt already fit.
  Discard.
- **Native SwiftUI:** excellent on macOS, but Apple-only and duplicated when
  Windows arrives. Discard unless OrionViva explicitly becomes macOS-only.
- **Flutter:** attractive platform reach, but adds Dart and still needs a Python
  boundary. No decisive advantage here. Discard for now.
- **Terminal/TUI:** valuable development and recovery tooling, but cannot
  satisfy X1 or the picture/provenance experience. Never the user product.

## 4. Repository and module structure

Keep the financial product, its presentation facade, and the desktop shell in
the **same repository and the same change history**. A separate UI repository
would make synchronization a social promise when it needs to be checked.

Recommended structure:

```text
orionviva/
├── core/                         existing verification/model core
├── merchant/                     existing impersonal merchant knowledge
├── product/
│   └── viva/
│       ├── engine.py             existing product actions
│       ├── ledger/               existing log and projections
│       ├── surface/              NEW: transport-independent UI boundary
│       │   ├── __init__.py
│       │   ├── protocol.py       version and compatibility rules
│       │   ├── models.py         common figure/panel/action contracts
│       │   ├── capabilities.py   capability/disposition registry
│       │   ├── overview.py       opening financial picture
│       │   ├── accounts.py       kind-aware account read models
│       │   ├── activity.py       movement exploration read models
│       │   ├── documents.py      capture, state, and review read models
│       │   ├── review.py         question/pending/proposal contracts
│       │   ├── conversation.py   Viva sessions and cited turns
│       │   └── trust.py          outbound, maintenance, integrity state
│       ├── desktop_bridge/       NEW: transport only
│       │   ├── __main__.py       packaged sidecar entry point
│       │   ├── rpc.py            framed request/response protocol
│       │   ├── handlers.py       allowlisted surface calls
│       │   └── jobs.py           long-running job progress
│       └── schemas/
│           └── surface-v1.json   NEW: versioned wire contract
├── desktop/                      NEW: Tauri application
│   ├── package.json
│   ├── lockfile
│   ├── src/
│   │   ├── app/                  shell, navigation, error boundaries
│   │   ├── bridge/               typed IPC client and handshake
│   │   ├── components/           Figure, Evidence, PanelState, Proposal
│   │   ├── features/             overview/accounts/activity/documents/...
│   │   ├── fixtures/             synthetic interface states
│   │   └── generated/            types generated during the build
│   ├── src-tauri/                shell, permissions, sidecar config
│   └── tests/                    unit, accessibility, visual states
├── scripts/
│   ├── check_surface_contract.py NEW: schema/fixture drift gate
│   └── check_surface_impact.py   NEW: backend-change impact gate
└── .github/
    ├── pull_request_template.md  NEW: interface-impact declaration
    └── workflows/
        └── quality.yml           NEW: product + surface + desktop checks
```

The names are recommendations, not implementation rulings. The boundaries are
the important part.

### `viva.surface` belongs with the product

`viva.surface` is not React support code and does not import Tauri. It is the
product's presentation vocabulary:

- It reads projections and calls existing `viva.engine` actions.
- It decides which exact values and caveats a surface receives.
- It formats through the product's locale-aware renderer.
- It carries exact decimal strings and never floats.
- It contains no frontend dependency.
- It can be exercised from tests or a future non-desktop surface.

### `desktop/` belongs beside, not inside, the trust core

The desktop application owns navigation, layout, focus, accessibility, charts,
document viewing, and OS integration. It never re-implements ledger rules. No
Node, React, Tauri, or browser dependency enters `core/`, `merchant/`, or the
financial modules of `product/`.

### `desktop_bridge` is transport and nothing else

The bridge validates a protocol version, dispatches an allowlisted operation,
streams job state, and serializes the result. It must not compute a total, infer
a grade, decide a movement's direction, or manufacture a user-facing caveat.

## 5. Dependency rules

1. `desktop/` depends on the surface contract, never event bodies or arbitrary
   projection methods.
2. `viva.surface` may depend on `viva.engine`, projections, the renderer, and
   persona data.
3. The engine and ledger never import `viva.surface`, `desktop_bridge`, or
   frontend code.
4. The bridge depends on `viva.surface`; `viva.surface` knows nothing about the
   bridge.
5. The interface renders values. It never adds money, converts currency,
   chooses a grade, infers completeness, or derives direction from a sign.
6. The UI may plot backend-supplied points, but the exact tooltip is the
   backend's canonical display string.
7. A component failure is reported as a component failure. It never replaces
   the application with a claim that the ledger failed.

An import-boundary test should enforce rules 1–4.

## 6. The surface contract

The contract is the central anti-staleness mechanism. It is versioned, typed,
validated on both sides, and represented by synthetic fixtures.

### Common figure

Every financial figure delivered to the UI carries, at minimum:

```text
FigureView
  id                 stable identity inside the response
  exact_value        decimal string, never a float
  display            canonical locale-aware words shown to the person
  currency           present for money; absent for counts and rates
  measures           balance | owed | spending | income | cost | ...
  grade              verified | corroborated | unverified | conflicted | ...
  grade_label        reviewed plain-language rendering
  exactness          exact | rounded | ...
  as_of              date the figure is good for
  coverage           attested set/period/account scope
  record_ids         records standing behind the figure
  provenance         document/page/region references available now
  caveats            named limits and omissions
```

The closed `measures` vocabulary is the same rule the answer path already uses:
a debt cannot arrive declaring itself a balance, and a raw sum cannot arrive
declaring itself spending.

### Common panel state

Every feature read model has one explicit state:

```text
absent        not enough data for this panel to be useful; do not render it
ready         useful and complete for the scope it declares
partial       useful, with named gaps
needs_input   a person or document can resolve the named gap
unavailable   the product does not support this case yet
failed        this component failed; the vault is not blamed
```

This is progressive disclosure as a contract rather than a collection of
frontend `if` statements.

### Common action outcome

Every action returns one of:

- completed, with the state it changed;
- refused, with a reviewed explanation and machine reason;
- proposal, stating what would change and awaiting explicit confirmation;
- accepted but waiting for a document, model, or background job;
- stale, because the action's subject is no longer open.

An action response never returns an ambiguous `ok` that forces the interface to
infer what happened.

### Protocol compatibility

- The shell and sidecar exchange protocol major/minor versions at startup.
- Additive optional fields advance the minor version.
- Removing a field or changing its meaning advances the major version.
- An unknown major refuses to open the product surface and explains the
  incompatible build; it never continues with guessed semantics.
- Trust/About displays the UI revision, sidecar revision, and protocol version.

## 7. Capability registry: how a feature becomes visible or deliberately not

Every user-relevant capability has one registry entry. The registry is both a
backend inventory and the UI's progressive-disclosure input.

```text
CapabilitySpec
  id                 stable capability name
  owner              product module that decides it
  maturity           preview | stable
  disposition        surface | developer_only | internal | deferred
  destination        overview | account | activity | documents | review |
                     viva | trust | settings | none
  availability       rule that earns its appearance
  contract           response schema name and version
  actions            allowlisted writes, if any
  trust_effect       reads data | writes event | may call model | may egress
  reason             required when not surfaced
```

This is deliberately not a dynamic plugin system. Frontend feature modules are
static and typed. The backend manifest says whether they are meaningful and
available for this vault and build.

Two coverage rules follow:

1. Every registered product action has a surface destination or a recorded
   non-user disposition and reason.
2. Every desktop feature consumes a registered capability and known contract.

The command inventory can also be checked mechanically: every Python module
under `viva` with a `main()` entry point must be classified as user surface,
background maintenance, recovery/advanced, diagnostic, or evaluation. A new
command therefore cannot enter unnoticed.

## 8. Information architecture

### Overview — the opening picture

- A quiet completeness line: current-through dates and named gaps.
- Net worth by currency, never a false converted grand total.
- Account cards with kind-aware semantics.
- Recent inflow/outflow summaries.
- The highest-consequence review items.
- A quiet “Viva noticed” area only when a real finding exists.
- A persistent add-document affordance.

An empty vault shows a greeting, a document drop, and “Explore with sample
data.” Net worth and trends do not render until they have something honest to
say.

### Accounts — reached from the picture

An account detail page contains its kind-specific headline, grade, date,
omissions, activity, statements, and questions. Depositories speak balance;
liabilities speak owed and distinguish a credit balance; investments expose the
statement's own composition and measurement dates; asserted assets speak cost
and say when they rest on the person's word.

### Activity

A searchable movement view with account, merchant, category, tag, date,
direction, and nature filters; transaction provenance; category/tag
corrections; and transfer relationships. It presents useful product meaning
from diagnostic reports without reproducing those reports as screens.

### Documents

The lifelong ingestion surface: drag/drop, file selection, captured/read/
verified/posted/held/parked state, what a document contributed, why something
waits, and focused correction. With no reader configured: “Saved privately.
Reading will wait until you choose a reader.”

### Review

The surface for `viva.ask`: consequence-ranked questions, a summarized tail,
one natural-language answer box, evidence and scope, focused reconciliation,
pending items, respected declines, and proposal/confirmation where X3 requires
it.

### Viva

Summoned through a stable button or shortcut, opening a side panel or dedicated
workspace. Text and voice share one session. Spoken replies are mirrored in
text. Every figure opens the same Evidence drawer used everywhere else.

### Trust and settings

- Every outbound event and its purpose.
- Model calls and maintenance-call budgets.
- Maintenance actions and outcomes.
- Vault integrity.
- Application and protocol versions.
- What is and is not externally anchored.
- Provider/network permission.
- Locale and currency display.
- Vault export and backup.
- Passphrase recovery stated as it exists. Today, losing the passphrase loses
  the vault.

The interface must not claim anchoring, recovery, or complete outbound
accounting before the product machinery exists.

## 9. Where the current commands go

Not every command deserves a button.

| Current capability | Product disposition |
|---|---|
| `viva.ask` | Review |
| `viva.speak` | Viva |
| upload/ingest | Documents |
| rescan and healing | post-ingest background work, reported in Documents |
| `viva.agent` | maintenance activity and Trust |
| merchant enrichment | proposed maintenance until its privacy boundary closes |
| grammar induction/reinduction | private maintenance, audited in Trust |
| stream/transfer/pattern/tier/gap reports | developer diagnostics; selected findings become Activity or quiet state |
| rebuild/reingest/reset categorization/ruling diff | advanced vault laboratory, not ordinary settings |
| ruling export | advanced data export with an explicit privacy warning |
| evals and `viva-bench` | CI and developer tooling only |

The product shows outcomes and decisions. It does not reproduce terminal output
screen for screen.

## 10. Delivery slices

Each slice leaves the application coherent, testable, and usable against a
synthetic vault. A slice is a build order inside an approved brief, not a license
to bypass the project loop.

### Slice 0 — surface contract and parity machinery

No desktop yet. Introduce `viva.surface`, protocol/version rules, common figure,
panel, action, capability contracts, synthetic fixtures, import-boundary tests,
and **gates A, C and D** from section 12 — contract drift, capability coverage,
and the interface-impact declaration. Those three are pure Python, cost nothing
to run, and are the ones that catch drift. Gates B, E and F govern a consumer
that does not exist yet and arrive beside `desktop/`; writing them now would be
machinery guarding an empty room.

**Done when:** current user-facing and command capabilities all have a
disposition; representative contracts validate; regeneration is deterministic;
a deliberate drift makes CI fail.

### Slice 1 — installable shell and demo vault

The user installs a signed macOS Preview build, opens the synthetic demo, or
creates/unlocks a real vault. The empty Overview is real and useful.

**Done when:** a clean machine needs no terminal or Python; the app is offline;
restart is safe; the build exposes UI/sidecar/protocol revisions.

### Slice 2 — document journey

Drag/drop, file selection, processing progress, document list, held/parked
states, and a minimal outbound record.

**Done when:** capture occurs before reading; restart during work recovers an
honest job state; no network call is silent.

### Slice 3 — the financial picture

Completeness line, net worth, account cards, and the shared Evidence drawer.

**Done when:** empty, partial, full, conflicted, stale, mixed-currency, and
overpaid-liability fixtures render honestly; every figure exposes grade, date,
evidence, and omissions.

### Slice 4 — review and learning

Question and pending queues, natural-language answers, focused details,
declines, proposals, and explicit confirmation.

**Done when:** every current question kind is answerable; a stale question
cannot write; a proposal cannot apply without a read yes; the queue re-reads
after every ruling.

### Slice 5 — ask Viva

Text conversation first inside development; voice joins before the first public
user milestone. Figures and sources use the shared components from Overview.

**Done when:** every turn re-reads current state; text and spoken output agree;
refusal and gap states are explicit; document injection cannot grant a write.

**Was blocked on Viva being unable to speak a list; unblocked 2026-08-16.** An
answer shape is a fixed set of clauses authored before any read and a binding
named exactly one thing, so no turn could say more than one row of a kind —
which stood in front of four of the seven unbuilt read verbs (`find_patterns`,
`list_obligations`, `search_documents`, `recall`). A binding may now name a
whole read, and the machine writes a line per figure that read took over a named
slice, so **a conversation turn can enumerate**, in text, today. What it writes
is the minimum a text answer needs — a name and an amount per line, the set's
grade once above, the read's own tail sentence below — and it decides nothing
about what a breakdown looks like on a screen.

**What that leaves open, and it is still not ruled here:** whether Review,
Activity and Documents read list-shaped projections through `viva.surface`
directly, or through the conversation's own block. The question was never really
about capability; it is about which of the two is the source of a list a person
sees, and this document does not take it.

### Slice 6 — activity and organization

Movement exploration, filters, categories, tags, transaction detail, and
transfer relationships.

**Done when:** corrections survive restart and re-projection; the UI performs no
financial arithmetic; totals agree with surface read models; **and every
direction shown comes from the account's kind, never a posted sign.**

That last condition is not a formality. M2 names one site still outstanding as
of 2026-08-16 — `implication_of` in the merchants projection picks a
counterparty's implication from the posted sign, so on a liability it reads a
purchase as an inflow. Checked against the tree on 2026-08-16: the site is
still open. This slice ships direction filters and a transaction detail that
speaks direction. **It must not land before that site closes**, or the interface
renders a known-wrong inflow, states it as a fact about the person's money, and
carries a grade while doing so — which is the quiet-wrong-answer failure the
whole surface contract exists to prevent.

### Slice 7 — trust and maintenance

Full outbound history, model permissions, maintenance history and budgets,
vault integrity, and build identity.

**Done when:** every existing outbound edge has a representation; maintenance
history survives restart; the surface cannot claim unbuilt anchoring or
recovery.

### Slice 8 — distribution and capture comfort

Watched folder, Windows packaging, signed updates, diagnostic export, and the
separate design of phone capture.

**Done when:** install and update run on clean machines; updates have a recovery
story; a diagnostic export previews exactly what will leave; no readable
document passes through an OrionViva server.

## 11. A new user's path during development

The demo vault is a product requirement, not sample decoration:

1. Install a signed Preview build.
2. Choose “Explore with sample data.”
3. See a clearly fictional, mature financial picture.
4. Try Review, ask Viva, inspect evidence, and browse documents.
5. Reset the demo at any time.
6. Create a private vault only when ready.

The fixture set covers empty, sparse, mature, stale, conflicted, mixed-currency,
held-document, provisional-spending, and missing-account states. It contains no
transformed real financial data.

Preview builds have a quiet Preview label, no telemetry, and a user-triggered
diagnostic export whose contents are shown before writing or sending. Stable,
Preview, and development are release channels, not separate feature branches.

## 12. Git and CI workflow: keeping the interface current

The repository needs hard gates as well as review practice. One check cannot
prove parity; these layers catch different failure shapes.

### Gate A — generated contract drift

`check_surface_contract.py` regenerates the versioned schema and synthetic
responses from Python surface models into a temporary directory and compares
them with reviewed contract fixtures.

It fails when:

- a field is added, removed, renamed, or changes type without an intentional
  contract update;
- a closed vocabulary changes without a protocol decision;
- a fixture no longer validates;
- generated frontend types are stale;
- UI and sidecar disagree on protocol versions.

The schema is the review artifact. Generated application bundles are not.

### Gate B — consumer completeness

Reintroduce the strongest idea from the deleted debug surface's contract test:
every field delivered by a surface read model is either rendered by the owning
feature or deliberately ignored with a reason in that feature's adapter.

Use typed exhaustive adapters and fixture tests. Passing arbitrary response
objects directly into components is forbidden.

### Gate C — capability coverage

`test_surface_capability_coverage.py` checks:

- every registered product action has a surface destination or recorded
  `developer_only`, `internal`, or `deferred` disposition with a reason;
- every command entry point is classified;
- every surfaced capability has a contract, owning feature, and fixtures;
- every frontend feature names a registered capability.

This gate flags a **new addition** even when no existing schema changed.

### Gate D — backend interface-impact declaration

`check_surface_impact.py` reads the pull-request diff against a reviewed path
map. Changes under the engine, question builders, projection families, renderer,
quantity vocabulary, persona packs, ingestion results, or agent logs are
interface-sensitive.

An interface-sensitive change passes only when one is true:

1. surface contract/adapter code and fixtures changed;
2. tests prove the existing surface contract is deliberately unchanged; or
3. the pull request declares **interface impact: none** with a concrete reason,
   and the Verifier confirms it.

The third path is essential. Requiring cosmetic UI churn for an internal bug fix
would train the team to bypass the gate. The escape hatch is explicit and
reviewed, not silent.

### Gate E — frontend correctness and visual states

For a change affecting `desktop/` or a surface contract:

- TypeScript typecheck and frontend unit tests.
- Accessibility checks on primary flows.
- Fixture-driven tests for absent, partial, ready, conflicted, and failed
  states.
- Visual snapshots for the small set of load-bearing states.
- A test proving one failed feature boundary does not take down the shell or
  blame the ledger.

Visual snapshots review layout drift. They never certify financial meaning;
product tests do that.

### Gate F — clean packaged smoke test

On the primary development platform for interface-changing pull requests, and
on every target platform for a release:

- build from a clean checkout;
- use no committed frontend output;
- package sidecar and shell;
- open the synthetic vault;
- exercise handshake, Overview, Documents, Review, and shutdown;
- assert that the installed build reports its source revisions.

This directly answers the previous stale compiled bundle: CI tests what a person
will install, not a neighbouring development server.

### Proposed required checks

| Check | Runs when | What it prevents |
|---|---|---|
| existing core/product/merchant/bench suites | every pull request | financial-engine regressions |
| privacy hook equivalent in CI | every pull request | local hook as the only privacy fence |
| surface contract drift | every pull request | backend/consumer mismatch |
| capability coverage | every pull request | new commands/actions with no disposition |
| interface-impact guard | backend-sensitive diff | silent interface debt |
| desktop type/unit/accessibility | desktop or contract diff | broken consumer behavior |
| fixture/visual states | desktop or contract diff | missing progressive-disclosure states |
| packaged smoke | interface-changing PR; full matrix on release | stale or unlaunchable installer |
| DCO | every pull request | existing contribution requirement |

Keep the existing pre-commit hook fast and privacy-focused. Do not put the
desktop build or full suite into pre-commit; required CI is the hard gate for
slower checks.

## 13. Pull-request and branch practice

Use short-lived feature branches and one pull request per approved vertical
slice. Do not create permanent backend and UI branches. A product change and the
surface contract it affects belong in the same reviewable history.

The pull-request template should require:

```text
Interface impact
  [ ] none — reason:
  [ ] existing surface changed — destinations:
  [ ] new capability — destination and availability rule:
  [ ] deliberately developer-only/deferred — reason:

Contract
  protocol/schema change:
  fixtures added or changed:
  backward compatibility:

States exercised
  [ ] absent/empty
  [ ] ready
  [ ] partial/needs input
  [ ] conflicted/failed, where applicable

Trust effects
  writes an event:
  may call a model:
  may send bytes:
  requires explicit confirmation:
```

Branch protection should require the checks in section 12 and review from both
product/trust and interface owners for changes to the surface, schema, bridge,
desktop, or impact maps. A CODEOWNERS file can express those reviewers once
team identities are known.

## 14. How this joins the existing OrionViva loop

The existing roles remain; interface parity becomes part of what each asks.

- **Design Partner:** every brief gains an Interface impact section: what a
  person sees before and after, which destination owns it, when it appears, and
  its absent/partial/failed states. “No impact” is a claim to justify.
- **Fact-checker:** checks the claimed surface and current capability inventory
  against code by running the contract and coverage inventory.
- **Builder:** builds a vertical slice: product change, adapter, contract,
  fixtures, consumer, and tests. An internal change records that disposition
  instead of inventing a screen.
- **Verifier:** runs engine and surface suites, checks the packaged synthetic
  path when the interface changed, and confirms the impact declaration.
- **Witness:** runs when a changed surface tells a person something about real
  money. Synthetic fixtures prove rendering, not truth on the live vault.
- **Steward:** checks capability inventory, reading guide, status claims, and
  Preview notes, and asks:

> **What did this cycle make newly visible, newly invisible, or stale on an
> existing surface?**

This workflow amendment should land in `WORKFLOW.md` only when the product owner
approves it. This document recommends it; it does not silently change the
current process.

## 15. Examples of the gates working

### A projection adds `excluded_from_spending`

Contract drift fails. The Overview adapter must render the caveat or deliberately
reject the field with a reviewed reason. Its partial fixture changes, and the
visual state is reviewed.

### A reconciliation bug is fixed without a response-shape change

The diff is interface-sensitive, but contract fixtures remain unchanged. The
pull request declares that values are corrected while the contract is unchanged;
engine tests and a Witness run where needed settle the claim. No meaningless
React edit is required.

### A new command report is added

Command-inventory coverage fails until it is classified. A diagnostic records
`developer_only` and why. A product capability names its destination and
contract.

### Obligations are added

The registry gains `obligations.read`, its availability rule, trust effect,
contract, and Overview/Account consumers. “Viva noticed” appears only once a
real obligation exists. No new shell or top-level navigation item is needed.

## 16. Definition of done for an interface-affecting change

A change is not complete until:

- its interface impact is declared;
- every new product action or command has a disposition;
- protocol and schema remain compatible or are intentionally versioned;
- exact values, grades, dates, coverage, and caveats come from the backend;
- absent, ready, partial, and failure states are covered where meaningful;
- the desktop performs no financial arithmetic;
- contract, capability, engine, frontend, accessibility, and relevant visual
  checks pass;
- the clean packaged synthetic-vault path passes;
- a Witness run exists when a person is told a changed fact about real money;
- status documents and capability inventory describe the final state;
- the Steward answers what became newly visible, invisible, or stale.

## 17. How later roadmap work integrates

- Obligations, fees, anomalies, and subscriptions enter Overview's quiet noticed
  state and the relevant account detail.
- Budgets and goals earn a Plans destination only after the first plan exists or
  a person asks to create one.
- Loans, insurance, tax, and FX extend instrument/document modules and Viva's
  tools; they do not create new shells.
- Selective disclosure becomes Proofs inside Trust.
- Household support becomes a scope switch over the same projections.
- Multi-device sync becomes Devices under vault settings.
- Account connections become another capture source under Documents.

The capability registry and panel-state contract let each arrive as a vertical
feature rather than a command waiting for the interface to notice it later.

## 18. Options removed from future consideration

Unless the product vision changes, stop reconsidering:

- a hosted service holding readable financial data;
- chat-first navigation;
- terminal/TUI as the end-user product;
- localhost-browser UI as the shipped experience;
- Electron when Tauri and Qt both satisfy the need;
- a macOS-only UI without an explicit platform decision;
- a button for every command;
- raw event records exposed to the frontend;
- frontend calculation of totals, grades, direction, or completeness;
- remote UI plugins, microfrontends, or a runtime component marketplace;
- a setup wizard requiring every account before value appears;
- push notifications, streaks, urgency badges, or engagement mechanics;
- voice-only answers with no mirrored evidence;
- a separate UI repository.

The retained alternative is PySide6/QML if the product owner later rules that a
mostly-Python toolchain outweighs the recommended frontend/distribution shape.

## 19. Decisions required before Slice 0 becomes a build brief

1. Approve or reject Tauri + React/TypeScript + Python sidecar.
2. Approve or reject `viva.surface` as the presentation boundary.
3. Decide whether macOS is the first Preview platform, with Windows following.
4. Approve the capability registry and explicit non-surface dispositions.
5. Approve the CI escape hatch: “interface impact: none” with a reason,
   verified rather than automatically trusted.
6. Approve amending `WORKFLOW.md` with section 14's interface duties and
   Steward question.
7. Name the team identities that own surface and desktop review.

Once ruled, the first implementation brief should cover **Slice 0 only**. It
proves contracts and tripwires before colors, chart libraries, or chrome.

## External implementation references

Checked 2026-08-16; these support feasibility, not product decisions:

- Tauri sidecars: <https://tauri.app/develop/sidecar/>
- Tauri updater: <https://v2.tauri.app/plugin/updater/>
- Tauri security: <https://tauri.app/security/>
- Qt for Python deployment alternative:
  <https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html>
- Electron security checklist, relevant to the discarded option:
  <https://www.electronjs.org/docs/latest/tutorial/security>

## Related project documents

- `VISION.md` — product promises and experience.
- `docs/experience-vision.md` — dashboard, discretion, capture, and voice.
- `docs/the-surface-cards.md` — surviving instrument semantics.
- `docs/the-presentation-layer.md` — the deleted debug surface and lessons.
- `docs/the-question-queue.md` — Review's ranking, scope, and declines.
- `docs/the-maintenance-agent.md` — quiet upkeep, budgets, and audit history.
- `docs/agent-toolset.md` — deterministic read verbs and forbidden list.
- `docs/adoption-and-distribution.md` — installation and model-access friction.
- `docs/design-invariants.md` — trust, locale, accounting, and experience rules.
- `WORKFLOW.md` — current roles, gates, and commit authority.
