# Experience Vision — a day with Viva, and the machinery each moment demands

**Status:** Draft — core interaction decisions settled 2026-07-20; two flagged tensions open · **Last updated:** 2026-07-20
**Invariants touched:** T1 (every displayed figure carries grade + source), T6 (capture surfaces must not create hosted data), X1 (no surface requires technical skill), X2 (uncertainty visible), X3 (explicit yes for anything irreversible), I3 (capability honesty per locale surfaces in UI)

## The chosen shape (author decisions, 2026-07-20)

Four decisions define the product's personality:

1. **Dashboard-first.** Opening OrionViva shows the financial picture — net worth, accounts, trends — not a chat window. Viva is *summoned*, not ambient.
2. **Speak only when spoken to.** Maximum discretion: Viva never initiates. Anything she notices (anomalies, missing statements, low-confidence figures) becomes *visible quiet state* on the dashboard — a badge, a soft row — never a ping. The user pulls; the product never pushes.
3. **All four capture surfaces at launch:** drag & drop, watched folder, phone camera/share sheet, and email-based capture (flagged below).
4. **Text + voice from day one.** Talking to a butler is the natural register for this persona.

Together: a quiet, information-rich command center. The dashboard carries the state; Viva carries the understanding; nothing ever interrupts. This resolves the notification philosophy in the simplest possible way — there isn't one.

**Reconciling dashboard-first with "simple as a Google homepage":** progressive disclosure (principle 5). On day one the dashboard is nearly empty — a drop zone and a greeting. Panels *earn their existence* as data arrives: the first statement births an account card; the third month births trends. The rich command center is what the product grows into, not what it confronts a newcomer with. The Google-homepage simplicity is the day-one state; the Bloomberg-terminal density is the year-one state — and every user is at their own point on that path.

## The day, as decided

- **The glance.** Dashboard: your accounts, your numbers, a quiet completeness strip ("current through yesterday" / "June card statement not yet seen"). Anything needing eyes is a visible badge — the review queue — sitting silently until touched.
- **A document arrives** by any surface: dropped, landed in the watched folder, photographed on the phone, or captured from email. Pipeline runs (extract → verify → ledger events). Result appears as dashboard state: the statement's card shows "47 transactions, reconciled ✓" or "1 figure needs your eyes" — no notification.
- **The question.** Typed or spoken. The agent loop: the model *plans* which deterministic tools to call — `query_ledger`, `compute`, `get_provenance`, `check_completeness` — and composes the answer from tool results only. Every figure tappable to its exact source region; the answer's confidence language inherits the weakest grade it stands on (X2). The model never supplies a number from its own head — it only ever *routes* numbers from the ledger (ADR-010 at the UX layer).
- **The correction.** One sentence ("that's groceries, not dining") → an event: taxonomy updated, remembered permanently, error attributed to the model version that miscategorized (trust-policy feedback loop 2). Corrections are the memory moat's front door.
- **Viva noticing things.** Background deterministic checks (recurring-charge drift, fee anomalies, statement completeness) still run — but their findings go to a dashboard "noticed" panel, not to interruptions. When the user next talks to Viva, she may mention the panel exists: pull, never push.
- **The trust moment.** A standing dashboard element, not a buried setting: *what has ever left this machine* — every model call, every anchor fingerprint, complete and plain (ADR-006's UI requirement).

## The parts inventory (what the day demands)

| Part | Status |
|---|---|
| Capture surfaces (drag, watched folder, share sheet, email) | New; email flagged below |
| Extraction + verification pipeline | Embryos exist (viva-bench `models/`, `verify/`) |
| Event ledger + projections (accounts, net worth, completeness) | Specified (ADR-004); built in architecture phase |
| Agent runtime: planner + small deterministic toolset | New — the core new build |
| Memory: corrections, preferences, goals as events with provenance | Specified in principle (domain-model doc); needs design (A6) |
| Background check scheduler (deterministic insights → quiet panel) | New; checks themselves are verify/-style code |
| Dashboard with progressive disclosure | New (C4 made concrete) |
| Conversation surface: text + voice | New; voice = input/output layer on the same runtime |
| Provenance viewer (tap figure → source region) | Experiment 3 proves the plumbing |
| Transparency panel (outbound ledger) | Specified (ADR-006) |

## Two flagged tensions (honesty section)

**Email capture vs. the no-hosted-data stance.** A forwarding address (`you@orionviva...`) means a server somewhere *receives your financial documents in plaintext* — SMTP delivers plaintext; even an encrypt-immediately-and-delete design has a trust-us window. That's the first crack in "we hold no user data," and cracks widen (the ADR-006 creep argument). **The honest alternative that preserves the convenience:** the app, running on the user's machine, watches the user's *own* mailbox (IMAP/Gmail API, credentials in the OS keychain, or its own local label/folder). User forwards statements to themselves — or just lets the app watch for statements arriving naturally. Same gesture ("email it in"), zero new servers, nothing leaves. **Recommendation: local mailbox watcher ships as "email capture"; a hosted forwarding address only ever happens as an attested-enclave service (Q12 territory), if ever.** → Register Q19.

**Voice from day one — scope, honestly stated.** The architecture cost is genuinely low (the agent runtime is modality-blind; voice is a transcription layer in and a synthesis layer out, both available on-device on modern OSes — consistent with local-first). The *product* cost is real: voice UX for corrections, figures, and confidence language needs its own design pass (how does "tap the number to see its source" work when the answer was spoken?). Accepted as vision; v0 experiments remain text; voice lands with the first dashboard build, with spoken answers always mirrored in text so provenance stays tappable. → C-track item.

## What this unlocks

This doc makes the C-track concrete (C1 uncertainty language now has surfaces to live on; C3 persona now has an interruption policy — never; C4 onboarding = progressive disclosure of an empty dashboard) and gives the architecture phase its requirements spine: the parts inventory above *is* the component list the v0 architecture doc must cover. Next collaborative steps: (a) the agent runtime's toolset — enumerate the tools Viva may ever call and what each is forbidden to do; (b) the data model spike (A1/experiment 2), which the dashboard's projections now give concrete shape to.

## Open questions

- Q19: email capture — local mailbox watcher design (IMAP vs Gmail API vs local label conventions); hosted forwarding permanently deferred to attested-enclave territory.
- Voice interaction design for provenance and corrections (C-track).
- Dashboard progressive-disclosure choreography: exactly what earns a panel into existence (C4 design pass).
