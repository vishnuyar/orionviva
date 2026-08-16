# Account Connection Research — getting bank, card, and brokerage data with the user's authorization

**Status:** Research (pre-decision) · **Date:** 2026-08-16 · **Scope:** US-first, with a survey of how the same architecture extends internationally
**Invariants touched:** T1 (provenance + confidence), T2 (deterministic arithmetic), T5 (no plaintext phase), T6 (nothing leaves silently), T8 (models never trusted — mostly by *absence* here), I1–I6 (connector extensibility), X1 (user skill: "can install an app"), X2 (visible uncertainty)
**Roadmap line this serves:** Phase 1 — "Account connection (aggregation) alongside manual upload."

---

## 1. The question, restated precisely

For users who are comfortable authorizing it, OrionViva should be able to receive their bank, credit-card, and brokerage data directly from the institution — the way tax software imports a 1099 — instead of relying only on manually dropped statements. The constraint that shapes everything: **OrionViva is open source and runs entirely on the user's device.** There is no company, no backend, and no ability to sign the B2B data-access contracts that power Mint-style aggregation. Whatever mechanism is chosen, the *user* must be the one holding the relationship (and, where there is a cost, paying for it), and every byte that leaves the machine must be visible (T6).

Two findings from this research reframe the question before any option is weighed:

**First, the tax-software import you're picturing is not an open mechanism.** TurboTax's "import from your institution" is Intuit's Financial Data Partnership program: each institution stands up a private endpoint (speaking OFX's tax extension or FDX) *under a bilateral contract with Intuit*, and W-2s are bulk-uploaded by payroll providers into Intuit's own data center before filing season. The protocol is standard; the access is contractual and closed. No third party — certainly no open-source app — can join it. So the goal is not "use what TurboTax uses"; it is "recreate that *experience* through mechanisms an individual user can authorize on their own."

**Second, the last three years have been a controlled experiment in what survives, run by the open-source finance community.** Every free B2B-ish tier that self-hosted apps depended on died between 2024 and 2026: Plaid's free Development environment (June 2024), Salt Edge's free tier (October 2025), GoCardless/Nordigen's free EU service (closed to signups, winding down). What survived and grew: services the **user pays for directly** (SimpleFIN Bridge), **open protocols** with multiple implementations (the SimpleFIN protocol itself), and **institutions' own individual-developer programs** (Schwab). Actual Budget, Firefly III, and Sure (the community fork of Maybe Finance) all independently converged on the same answer. That convergence is the strongest single signal in this document.

---

## 2. The regulatory backdrop (it matters more than usual)

US open banking is mid-upheaval, and several options' viability depends on where it lands.

The CFPB's **Section 1033 "Personal Financial Data Rights" rule** — finalized October 2024, which would have mandated free API access to consumer data and banned screen scraping — is **not in effect**. The CFPB under the new administration moved to vacate its own rule; a court enjoined enforcement in October 2025; the first compliance date (April 1, 2026) passed unenforced; and a **rewritten proposal went to OIRA on August 5–6, 2026**, expected to *permit banks to charge for data access* while keeping the API mandate. Realistic enforceable compliance is 2027–2028 at the earliest, likely followed by fresh litigation.

Meanwhile the banks moved unilaterally. JPMorgan measured 1.89 billion aggregator data pulls in June 2025 (only ~13% user-initiated), began charging aggregators for access, and signed a paid data-access deal with Plaid in September 2025. Fidelity now blocks third-party credential sharing outright and routes all programmatic access through Akoya, the bank-owned network it created. Jack Henry is phasing screen scraping off its platform serving hundreds of community banks.

Three consequences for OrionViva:

1. The era of free, scraped US bank data is closing. Anything built on it inherits a negative trajectory.
2. Models where the **user pays** and pulls are **user-initiated** are the regulatory-safe direction — which happens to be exactly the direction OrionViva's constraints force anyway.
3. The one durable local-first gift inside 1033 (both versions): data providers must give **consumers themselves** electronic access to their own data. Banks building "download my data" portals to satisfy this produce *files a user downloads* — which flow naturally into a watched folder. The no-middleman future, if it arrives, arrives as better downloads, not as open APIs for unregistered apps.

---

## 3. The option landscape

Every mechanism found falls into one of four families. Detailed per-option analysis follows in §4; this is the map.

**Family A — Commercial aggregators, product-holds-the-contract (Plaid, MX, Finicity/Mastercard, Yodlee, Akoya).** The Mint/Monarch/Copilot architecture: the app company signs a B2B contract, data flows through the app's backend. **Structurally unavailable to OrionViva** — there is no company to sign, and routing data through an OrionViva-operated server would break Promise 4 anyway. Included in this research because (a) their capabilities define what users expect, (b) two of them are reachable *indirectly* through user-pays doors, and (c) their statement-PDF products prove banks can serve the exact artifact the ingestion pipeline already reads.

**Family B — User-pays bridges and open protocols (SimpleFIN Bridge, Synci, Enable Banking).** The user personally subscribes to a bridge service; the bridge holds the aggregator relationship; the app speaks an open protocol to the bridge using a token the user pastes in. No developer contract, no developer payment, app-side code fully auditable. This is where the open-source ecosystem landed.

**Family C — Bring-your-own-credentials to a commercial service (Plaid personal account, Teller developer account, SnapTrade personal, Schwab Trader API, IBKR Flex, Coinbase keys).** The user signs up for a developer/individual tier themselves and pastes their own keys into their own instance. Proven pattern (Sure documents it step-by-step for Plaid), but it lives in tension with X1 — it requires knowing what an API key is.

**Family D — No middleman at all (watched folder + downloads, OFX Direct Connect, browser-extension statement harvesting, email-notification triggers).** Nothing between the user's device and the institution. Strongest privacy and provenance, weakest automation coverage — with one large exception (the extension route) that deserves serious consideration.

### The comparison at a glance

| Mechanism | Who signs up / pays | Coverage (US) | Data form | Investments | Statement PDFs | Fits X1 (default path)? | Effort to build |
|---|---|---|---|---|---|---|---|
| SimpleFIN Bridge | User, $1.50/mo or $15/yr | MX network (thousands of FIs, US/CA), 25 institutions/account | Transaction JSON, daily refresh | Weak | No | Yes — paste one token | **Small** (4-endpoint protocol) |
| BYO Plaid keys | User, free ≤10 institutions (Trial plan), then ~$0.30/inst/mo | ~12,000 FIs, best-in-class | Transaction JSON + investments + liabilities | Yes | Yes (~40% of depository accts) | No — power-user path | Moderate + heavy user friction (security questionnaire; Chase OAuth ≈3–4 months) |
| BYO Teller | User, free ≤100 connections | 7,000+ FIs, banks/cards only | Transaction JSON | No | No | No — mTLS cert handling | Moderate |
| SnapTrade (personal) | User, free | Brokerages (Robinhood, IBKR, E*Trade, Webull…) | Holdings + transactions | **Core strength** | No | Borderline | Moderate |
| Schwab Trader API | User, free (official individual program) | Schwab only | Positions, balances, transactions | Yes (Schwab) | No | Borderline | Moderate |
| OFX Direct Connect | User's bank login, usually free | Long tail: credit unions, community banks, Amex cards; majors have exited | OFX files (structured, bank-served) | Rare | No | Yes, where it works | **Small** (wrap ofxtools) + FI-list maintenance |
| Watched folder + CSV/QFX/PDF downloads | Nobody | **100% of institutions** | Documents + CSV | Yes | **Yes — the user downloads them** | Yes | Small–moderate (format registry) |
| Browser extension (statement harvesting) | Nobody | Any bank with a web portal, per-bank recipes | **The actual statement PDFs** | Yes | **Yes** | Yes — install extension, click | **High, permanent maintenance** |
| Email notification triggers (local IMAP) | Nobody | Most institutions send "statement ready" emails | Triggers/metadata only (PDFs rarely attached) | — | No | Yes | Small |

---

## 4. The options in detail

### 4.1 SimpleFIN — the protocol and the Bridge

SimpleFIN is two things, and the distinction matters architecturally. The **protocol** is an open, read-only financial-data-sharing spec ("RSS for banking"): four endpoints, JSON over HTTPS with Basic Auth, no write or payment operations anywhere in it. The **Bridge** (run by the maker of the Buckets budgeting app) is a hosted implementation that proxies **MX**, one of the major US aggregators — so an individual effectively buys MX-grade connectivity for **$1.50/month or $15/year** with no MX contract. Up to 25 institutions and 25 authorized apps per subscription.

The flow: the user subscribes at the Bridge, connects their banks there (credentials go to MX's vetted credential handling — "no bank account credentials ever touch our servers," and never touch OrionViva), then generates a **setup token** and pastes it into the app. The app claims the token once (a second claim attempt fails loudly — a nice tamper signal), receives an access URL, and from then on polls `GET /accounts` for balances and transactions. Refresh is roughly daily; the Bridge expects ≤24 requests/day and serves 90-day windows per request. Tokens are per-app and revocable by the user.

What makes this the standout option is who else chose it: **Actual Budget** (first-party integration since v24.10.0), **Firefly III** (Data Importer v1.7.0), **Sure**, Buckets, Skwad, and the beancount community — including hardcore privacy users who accepted it after its third-party security audit. And critically, the protocol now has a **second independent commercial implementation**: **Synci** (€39.90/yr) serves Europe and New Zealand over the same protocol. One client implementation reaches both bridges and any future one — the protocol has crossed from "one company's API" to "small open standard," which is exactly the kind of dependency an open-source project can afford to take.

Weaknesses, stated honestly: investment/holdings data is thin (MX transaction rails, not a brokerage product); no statement PDFs; data transits MX and the Bridge (see §5 on what that means for the promises); the Bridge is a small operation — though the open protocol is precisely the hedge against that, since another bridge can replace it without app changes.

**Effort:** the smallest of any live-sync option. The client is four endpoints, a token-claim flow, and a poller. The real work is downstream — what the ledger does with feed data (Fork 1, §6).

### 4.2 Bring-your-own-keys aggregator accounts (Plaid, Teller)

Plaid's Developer Policy forbids *sharing* keys — meaning OrionViva must never ship keys — but nothing forbids an individual signing up, and the **Sure** project documents the pattern end-to-end: user registers at the Plaid dashboard, requests production on pay-as-you-go, answers the ~25-question security questionnaire as "personal use, self-hosted software," then waits out per-institution OAuth registration — currently **~3–4 months for Chase**, ~2 for Schwab. The economics improved in 2026: accounts created after April 15, 2026 get a **Trial plan with 10 free live institution connections** including most OAuth banks pre-enabled — enough for many households, free.

Plaid's data breadth is the best available (transactions, investments, liabilities, and a **Statements API returning exact bank-branded PDFs** for ~40% of US depository accounts), which is why this path is worth supporting *for the users who can walk it*. But it cannot be the default path: it fails X1 by construction (dashboard signup, API keys, a security questionnaire, months-long waits), and Plaid can change individual-account terms at will — the 2024 death of the free Development tier stranded exactly this kind of user.

**Teller** is the easiest BYO signup in the industry (self-serve, individuals explicitly permitted, **100 free live connections**, no security review) and connects via banks' own mobile-app APIs rather than scraping. But its mTLS design means each user must generate and locally manage a client certificate, it covers only banks and cards (no investments), and returns no documents. A reasonable second BYO slot; same X1 caveat.

**Effort:** moderate per connector — OAuth/Link flows, key storage UX, and substantial *documentation* effort, because the product is walking a non-technical-adjacent user through a developer signup. The Sure and firefly-plaid-connector-2 codebases are working references.

### 4.3 Brokerage-direct (Schwab, SnapTrade, IBKR, Coinbase)

Brokerages turn out to be more open to individuals than banks. **Schwab runs a real individual-developer program** (successor to TD Ameritrade's API): a retail customer registers on the developer portal, OAuths against their own login, and gets accounts, balances, positions, and transaction history — free, officially sanctioned, with a mature open-source client ecosystem (`schwab-py` and others). This is the single best direct, no-middleman feed from any major US institution.

**SnapTrade** is a brokerage-side aggregator with self-serve signup where "personal users are currently completely free" — read-only OAuth across Robinhood, IBKR, E*Trade, Webull, Coinbase and more. **Interactive Brokers** offers individuals Flex Queries — scheduled, user-defined XML/CSV activity reports fetched with a personal token; institution-authored structured files, very close in spirit to a statement. **Coinbase** issues personal read-only API keys. **Fidelity and Vanguard offer individuals nothing** programmatic (Fidelity is Akoya-only and actively blocks credential sharing; both still provide CSV/OFX file downloads and PDFs — the watched folder covers them).

**Effort:** moderate per integration, low risk. Schwab + SnapTrade + IBKR covers a large share of the US retail brokerage surface with genuinely user-owned credentials.

### 4.4 OFX Direct Connect — alive only in the long tail

The old direct protocol (the user's own bank login, structured OFX responses served by the bank itself) is in terminal decline at majors — Chase ended it in 2022, Discover in 2022, Bank of America killed both Direct Connect *and* QFX downloads in September 2025, Vanguard's variant died February 2025 — but it survives at hundreds of community banks and credit unions, and **American Express reinstated it for cards in November 2023**. The `ofxtools`/`ofxget` Python library makes a client days of work; the cost is that the community institution directory (ofxhome.com) is defunct, so the project must curate its own institution-config registry and accept per-bank quirks and overnight shutoffs.

Worth shipping cheaply — for credit-union users it is the best mechanism that exists: no middleman, bank-served structured data. Never promise it for major banks.

### 4.5 The document routes — watched folder, browser extension, email triggers

These deserve more respect than "fallback," because they are the only routes that deliver **the actual statement documents** — the artifact the entire provenance pipeline (T1) is built around, and the strongest evidence class the product has.

**Watched folder + manual download** is the baseline and it is universal: every US institution offers statement PDFs plus some tabular export (worst case CSV; the majors' download formats and history windows are documented in the research — Chase silently truncates CSV exports at 1,000 rows, Capital One keeps only 90 days, etc.). The community has already solved CSV schema chaos once: **bank2ynab maintains 124 crowd-sourced bank-format configs** — a model (data-driven format registry, community-contributed, no hardcoded per-bank logic) that fits this project's "no hardcoding" instruction exactly. Cost: user discipline, monthly. That cost can be engineered down — which is what the next two mechanisms are.

**Email-notification triggers (local IMAP).** Most banks send "your statement is ready" emails that do *not* contain the PDF (a deliberate security posture), so email is not a document source — but read locally, with the user's own mail credentials never leaving the device, it is an excellent **freshness and completeness signal**: the product learns a statement exists before it has seen it, which feeds the "measure what you haven't seen" obligation directly, and can turn the quiet dashboard state ("June's card statement not yet seen") into a precise, timely one. Small effort, real value, fully on-device.

**Companion browser extension for statement harvesting.** The user is already logged into their bank's portal in their own browser, with MFA passed and a genuine device fingerprint; an extension, invoked by the user, navigates to the statements page and downloads the PDFs into the watched folder. This is materially different from headless scraping: it automates *the user's own attended session* rather than storing credentials and impersonating a browser, so enterprise bot-detection largely doesn't trigger and the legal posture is far cleaner (post-*Van Buren*, a consumer reading their own data with their own credentials is a weak CFAA target; the exposure is bank ToS, whose sanction is account closure — a risk the user knowingly accepts, and lower for attended automation). Precedents exist (`finance-dl`, various commercial statement-downloader extensions) but no healthy open-source ecosystem does this well today — which makes it both an opportunity and a warning. The cost structure is the whole decision: modest per-bank "recipes," but **permanent, forever maintenance** as banks redesign portals — viable only if it becomes a community-maintained registry (the bank2ynab model again), never a core-team obligation to keep N banks working.

This route is the only one in the entire landscape that delivers the tax-software *experience* (click, authorize, data appears) while yielding the *strongest* evidence class (bank-authored documents) with *no* middleman. It is also the most expensive to sustain. That tension is Fork 3.

### 4.6 What is structurally closed (and worth knowing why)

**MX, Finicity/Mastercard, Yodlee, Akoya** are enterprise-contract-only; no individual tier exists or is plausible. MX is reachable indirectly through SimpleFIN (§4.1) — the only legitimate individual door into any of them. **FDX** (now the de facto US open-banking wire format, 114M+ consumer connections, CFPB-recognized standards body) publishes its spec royalty-free — but every bank's FDX endpoint is gated behind bilateral, security-vetted, increasingly *paid* recipient agreements. Building an FDX **parser** is cheap future-proofing (any 1033-era consumer export or bridge feed in FDX JSON becomes ingestible); expecting FDX **endpoint access** is not realistic on any horizon this document covers. **Headless screen scraping** of US majors is a dead end: no maintained US scraper library exists in 2026, bot-detection is enterprise-grade, banks are actively closing it down, and a bundled credential-storing scraper is the one automation route that would genuinely deserve the "dark pattern" label this product forbids.

### 4.7 International survey (per I1–I6: designed-for, not built now)

The connector architecture should assume from day one that mechanisms are regional. **Europe:** GoCardless/Nordigen's famous free tier is closed and winding down; the ecosystem's replacement is **Enable Banking's free "restricted production" mode**, explicitly sanctioned for individual non-commercial use on one's own accounts (Firefly III shipped it February 2026, Actual Budget May 2026) — plus **Synci** speaking SimpleFIN. **India:** the Account Aggregator framework is RBI-licensed and B2B-only — no individual tier exists, which is why Indian local-first apps (e.g. Paisa) remain import-based; the watched folder is the India story for now. **New Zealand:** Akahu has a free personal-app tier. **Brazil:** Pluggy. The pattern worth encoding: *every region eventually offers either a user-pays bridge, an own-accounts free tier, or neither — and the document routes work everywhere.*

---

## 5. What connected data means for the trust model

This section is the part no vendor comparison can answer, and it is where the real design work lives. Everything above is plumbing; this is what the plumbing carries into a product whose whole thesis is provable trust.

### 5.1 A feed is a new evidence class, not a faster statement

Everything the product ingests today is a **document**: an artifact the institution authored, styled, and delivered to its customer — the thing a bank would stand behind if asked. A model reads it (introducing extraction risk, which the verification machinery exists to grade), but the *source* is the institution's own attestation.

A transaction from SimpleFIN or Plaid inverts both properties. There is **no extraction risk at all** — the data arrives structured, no model touches it on the way in, which means this entire route sidesteps the models-never-certify problem (T8) by simply having no model in the loop. But the *attestation* is weaker: the figure is an assertion by an intermediary chain (bank → MX → Bridge → app) with no bank-authored artifact behind it. Aggregator feeds are known to contain their own defects — merchant-name rewriting, pending-transaction mutations, occasional duplicates, sign conventions that vary by institution.

So documents and feeds fail in *opposite* ways: the document is strongly attested but read through a model; the feed is deterministically delivered but weakly attested. T1's grading vocabulary must learn this distinction rather than forcing one into the other's scale. A feed figure's provenance pointer is real but different in kind: "asserted by bridge B from institution X, retrieved at time T, request R" — traceable (the user can tap through to *what was received and when*), but tracing terminates at an intermediary's claim, not at a page image.

Vishnu's instinct in framing this task — "when we get it directly like this, it is indirectly already signed off by the bank" — is exactly right for **OAuth-consented** connections (the user authorized the bank to share; the bank chose to send it) and *not* right for the screen-scraped share of aggregator coverage, where the bank signed off on nothing. The connector cannot always tell which it got. The honest position: a feed figure is *evidence*, never *proof*, and the strongest thing the product can do with it is corroborate it against a document.

### 5.2 The reconciliation opportunity — feeds and statements verify each other

This is the most valuable design insight the research surfaced, and it converts the two-source awkwardness into a strength. A feed and a statement covering the same account-period are two independent witnesses to the same ground truth. Deterministically matching them (T2-friendly: exact-ID, then amount+date matching — Actual Budget's reconciler is a working reference) produces something neither source alone can:

- A feed transaction later confirmed by a statement line becomes the **best-graded figure in the entire system** — deterministically delivered *and* document-attested.
- A statement line the feed never showed, or a feed transaction the statement contradicts, is a *detected anomaly* — the product catching an error (or fraud) that single-source products structurally cannot see.
- The feed tells the product, precisely, **what it hasn't seen**: a connected account with no June statement in the ledger turns "measure your own incompleteness" from estimate into fact — and gives Viva something honest to say about it, quietly, on the dashboard.

Under this framing the feed's primary role is not "more transactions"; it is **freshness plus corroboration** for a picture whose durable substrate remains documents. That framing also happens to answer the Promise 2 requirement ("current through yesterday; June's card statement not yet seen") with real data instead of inference.

### 5.3 The promises, honestly applied

**Promise 4 / T5.** Connecting an account does not route the user's *documents* through anyone's servers, and the integrated picture still exists only on-device, encrypted. But it is not true that "no server sees your data": the bridge and its upstream aggregator see each connected account's transactions — roughly what the bank itself already sees, per institution, but a real disclosure. The product must say this plainly *at the moment of consent*, not in a policy: who will see what, per connector, in words. The defensible claim is precise: **"no additional server ever holds your assembled picture, and no server OrionViva operates ever sees anything."** Anything stronger would be a bluff, and bluffing about privacy in the consent screen would be the most corrosive possible place to do it.

**Promise 5 / T6.** Every connector is, by definition, a standing outbound channel — so every sync belongs in the outbound ledger: destination, when, what was requested, under which user-granted authority. T6 says new outbound bytes are a decision, never an implementation detail; a connector framework should make that structural — a connector *cannot* be registered without declaring its outbound surface, and the declaration is what the outbound panel renders. This is also where "user-initiated" matters: a sync the user (or the user's standing, visible schedule) triggers is defensible under every regulatory wind in §2; an invisible background poller is both a T6 smell and the exact behavior banks are now billing aggregators for.

**Promise 7 and the no-wizard rule.** The vision explicitly forbids a "connect all your accounts" onboarding ceremony. Account connection therefore arrives the way everything else does: as an *option, offered in context, declinable, remembered* — e.g., after the third monthly statement from the same institution, Viva may mention, once, that this account can keep itself current, and what it would cost and disclose. A decline is permanent until the user raises it. This also matches the observed reality that connection is fallible (aggregator outages, re-auth prompts): the document path must remain first-class forever, not become a neglected fallback — when a connector breaks, the product degrades gracefully to the path that always works.

**X1.** The mechanisms sort cleanly. Paste-one-token (SimpleFIN), install-extension-and-click, and OAuth-through-your-broker (Schwab, SnapTrade) sit inside "can install an app." BYO API keys (Plaid, Teller) do not — they are power-user paths, valuable, documented, and never on the default path. This single test is what disqualifies BYO-Plaid as the *primary* mechanism despite its superior data.

---

## 6. Decision forks

Four genuine forks, each with the viewpoints laid out in full. The recommendation, where one is offered, is a position to argue with, not a foreclosure.

### Fork 1 — What does feed data *become* in the ledger?

**Branch A: Feeds are a first-class source with their own grade.** Feed transactions post to the ledger like any other measurement, carrying a source-class-specific grade ("intermediary-asserted"); statements, when they arrive, corroborate and upgrade them via deterministic matching. *For:* one ledger, no shadow state; the freshness is real and usable immediately ("you spent $340 at restaurants so far this month" works); the grading vocabulary already exists to express differing confidence — this extends it rather than inventing a parallel mechanism; upgrade-on-corroboration gives users a visible experience of the product verifying itself. *Against:* feed defects (mutating pendings, renamed merchants, duplicates) become ledger events needing correction events, adding churn to an append-only log; T1's "set a figure was taken over" needs care when an account's history is part-feed, part-statement; the strongest objection — the ledger's identity scheme (T7 keys movements partly by description) meets a source whose descriptions *change* between pulls, which must be designed for, not discovered.

**Branch B: Feeds live in a provisional layer; only document-confirmed data posts.** A staging area holds feed data for display ("as reported by your bank this morning — unconfirmed") and reconciliation; the durable ledger remains document-only. *For:* the ledger's evidentiary story stays maximally clean — everything posted traces to a bank-authored artifact; feed churn never touches the append-only log; simplest honest answer to "what does this number rest on." *Against:* two stores showing different truths is precisely the kind of complexity that leaks into UX ("why does the dashboard say X but my answer say Y?"); accounts the user connects but never uploads documents for would *never* enter the picture, which for a card the user doesn't want to manage manually is a worse outcome than a fairly-graded feed figure; and it quietly demotes the product's freshest data to a display ornament the answering machinery can't stand on.

**Branch C: Feeds only ever *signal* (freshness, gaps, nudges), never carry figures.** *For:* zero trust-model disturbance; still captures the completeness-measurement win. *Against:* discards most of the user value that motivated this research; a user who authorized (and pays for) a connection reasonably expects the numbers to show up.

The research leans **Branch A** — it is what the grading vocabulary was built for, and Branch B's two-truths problem strains Promise 1 worse than Branch A strains T7 — but Branch A's cost is real design work on identity-under-mutation, and that work should be priced before committing.

### Fork 2 — Which mechanism ships first?

**Branch A: SimpleFIN protocol client.** *For:* smallest build in the landscape; open protocol with two independent bridge implementations (US/CA + EU/NZ) so the dependency is on a *protocol*, not a vendor; the entire self-hosted ecosystem's converged choice, meaning shared community knowledge and institutional pressure on the Bridge to stay healthy; user-pays aligns incentives (the customer is the user, so the tier can't be rug-pulled the way every free developer tier was); passes X1 via paste-one-token. *Against:* weak investments data; no documents; the Bridge is a small business; adds a $15/yr ask (though the user was always going to pay someone in every viable branch).

**Branch B: BYO-Plaid first.** *For:* best data breadth including investments, liabilities, and actual statement PDFs for ~40% of depository accounts — the only aggregator door to documents. *Against:* fails X1 hard (developer signup, security questionnaire, months of OAuth waits per bank); terms for individuals have been changed adversely before, recently; per-user approval isn't guaranteed. As a *first* mechanism it would make the headline feature a power-user feature.

**Branch C: Documents-first (extension + email triggers + format registry) before any live feed.** *For:* deepens the product's existing strength rather than adding a second evidence class; no new disclosure to any third party; every institution covered. *Against:* forgoes the freshness and the completeness-measurement wins for another cycle; the extension is the *most* expensive route to sustain, so leading with it front-loads the worst maintenance burden.

The research leans **A, with C's cheap halves (email triggers, format registry) alongside** — they are small, fully local, and make the manual path feel automatic — and Plaid/Teller as documented power-user connectors later, investments via §4.3 when Phase 1 breadth demands it.

### Fork 3 — Is the browser extension worth building at all?

**Branch A: Yes — as a community-recipe platform.** The only mechanism delivering the tax-software experience *and* bank-authored artifacts *and* no middleman. Viable only in the bank2ynab shape: a data-driven, community-contributed per-bank recipe registry (no hardcoded bank logic in core — which this project's own instructions would demand anyway), core team owning the engine, community owning coverage. *For:* unique differentiator no aggregator-dependent product can copy; strengthens the evidence class the trust model is built on; graceful failure (a broken recipe = user downloads manually, exactly as today). *Against:* permanent maintenance is a tax on a small project's attention; Chrome Web Store review of an extension touching bank pages is a real gate; bank ToS gray zone, borne by the user but worn by the project's reputation.

**Branch B: No — watched folder + email nudges is enough.** *For:* the monthly-download ritual with precise, timely nudges is honestly not bad, and costs nothing to sustain; the project's attention goes to intelligence, not portal-DOM whack-a-mole. *Against:* leaves the strongest idea in this research unbuilt, and leaves manual users with real friction that compounds across a dozen institutions × every month, forever.

This fork does not need deciding now. The honest sequencing: build the email-trigger nudges first (small, certain value); revisit the extension when there's evidence about how much friction the nudged-manual path still leaves. Deferring it costs nothing because it depends on nothing else.

### Fork 4 — Where does connectivity live in the architecture?

**Branch A: Connectors as a plugin surface with a narrow, declared contract.** Each connector declares what it provides (evidence class, data shapes, regions) and — mandatorily — its outbound surface, which T6 machinery renders in the outbound panel; core knows only the contract. *For:* T6 becomes structural rather than disciplinary; regional mechanisms (I1–I6) slot in without core changes; community can add connectors (and extension recipes) without touching trust-critical code; a dead vendor is a deleted plugin, not a core surgery. *Against:* plugin boundaries are speculative generality if only one connector exists for a year — the contract will be designed against one example and wrong in places; some friction for every future connector author.

**Branch B: First connector built directly into core; extract the boundary when the second one arrives.** *For:* the classic argument — boundaries extracted from two real examples beat boundaries designed from zero; faster first ship. *Against:* the *outbound-declaration* half of the contract is not speculative — T6 needs it on day one for even one connector, and retrofitting a trust-relevant boundary is exactly the kind of promise-breaking rework the vision warns about (see "retrofitted privacy is a promise already broken").

The research leans a deliberate middle: **the T6 outbound-declaration contract from day one (it is an invariant's mechanism, not architecture astronautics); the broader plugin packaging extracted when the second connector is real.**

---

## 7. Recommended shape, sequenced

Stated as a position for review, not a decision. Everything here is reversible except item 1's trust-model work, which is why it comes first.

1. **Design the evidence-class extension** (Fork 1, likely Branch A): how an intermediary-asserted figure is graded, keyed (T7 under mutating descriptions), reconciled against documents, and upgraded. This is a design doc + ADR before it is code, and it must state its invariants line per the standing rule.
2. **Ship the SimpleFIN protocol client** as the first connector, with the consent screen written per §5.3 (who sees what, in words), sync appearing in the outbound ledger, and the offer surfaced Viva-style — in context, once, declinable, remembered.
3. **Ship the local email-trigger nudges and the community CSV/QFX format registry** (bank2ynab model — data-driven, no hardcoded banks) to make the manual path feel near-automatic. Ship an OFX Direct Connect client cheaply (ofxtools) for the credit-union tail and Amex cards.
4. **Add brokerage-direct connectors** (Schwab individual API, SnapTrade personal, IBKR Flex) when Phase 1 instrument breadth reaches investments.
5. **Document the BYO-Plaid and BYO-Teller power-user paths** (off the default path, X1-safe) rather than building them first-class, until demand proves otherwise.
6. **Hold the browser extension** as a named, undecided option (Fork 3); revisit with evidence from the nudged-manual experience.
7. **Parse FDX and OFX-tax schemas opportunistically** so any 1033-era consumer export drops straight in; track the 1033 rewrite (OIRA now; NPRM imminent) — the consumer "download my data" mandate is the piece to watch, because it lands directly in the watched folder.

The through-line: the durable substrate stays documents; connections add freshness, corroboration, and honest completeness measurement; every mechanism the product blesses is one the *user* owns and can see; and nothing on the default path requires knowing what an API key is.

---

## 8. Sources

Consolidated from three parallel research passes (2026-08-16). Key primary sources; full trails preserved in the research transcripts.

**SimpleFIN / bridges:** [Bridge & pricing](https://beta-bridge.simplefin.org/) · [Protocol spec](https://www.simplefin.org/protocol.html) · [Security policy (MX upstream)](https://beta-bridge.simplefin.org/info/security) · [Developer guide](https://beta-bridge.simplefin.org/info/developers) · [Ecosystem](https://www.simplefin.org/ecosystem.html) · [Synci (SimpleFIN for EU/NZ)](https://synci.io/) · [Lunch Flow](https://www.lunchflow.app/)

**Aggregators:** [Plaid billing/plans](https://plaid.com/docs/account/billing/) · [Plaid Trial/Production tiers](https://support.plaid.com/hc/en-us/articles/16110110883479-How-are-Sandbox-Production-Trial-plan-and-Limited-Production-different) · [Plaid Developer Policy](https://plaid.com/developer-policy/) · [Plaid Statements](https://plaid.com/docs/statements/) · [Teller (pricing, free tier)](https://teller.io/) · [Teller mTLS auth](https://teller.io/docs/api/authentication) · [Mastercard Open Banking statements](https://developer.mastercard.com/open-banking-us/documentation/products/manage/account-statements/) · [Akoya](https://akoya.com/pricing) · [Yodlee developer FAQ](https://developer.yodlee.com/resources/yodlee/faqs/docs/building_testing) · [Stripe Financial Connections](https://stripe.com/financial-connections) · [Quiltt pricing](https://www.quiltt.io/pricing)

**Open-source precedents:** [Actual Budget bank sync](https://actualbudget.org/docs/advanced/bank-sync/) · [Actual SimpleFIN setup](https://actualbudget.org/docs/advanced/bank-sync/simplefin/) · [Firefly III SimpleFIN](https://docs.firefly-iii.org/how-to/data-importer/import/simplefin/) · [Firefly III on US providers (maintainer)](https://github.com/orgs/firefly-iii/discussions/7765) · [Sure BYO-Plaid guide](https://github.com/we-promise/sure/blob/main/docs/hosting/plaid.md) · [Sure SimpleFIN security discussion](https://github.com/we-promise/sure/discussions/157) · [maybe-finance/maybe (archived 2025-07-27)](https://github.com/maybe-finance/maybe) · [firefly-plaid-connector-2](https://github.com/dvankley/firefly-plaid-connector-2) · [bank2ynab format registry](https://github.com/bank2ynab/bank2ynab) · [Wealthfolio 2.0 HN thread](https://news.ycombinator.com/item?id=46006016) · [Ghostfolio sidecar pattern](https://github.com/agusalex/ghostfolio-sync)

**Regulatory:** [Section 1033 status timeline](https://www.openbankingtracker.com/guides/section-1033-status) · [CFPB sends revised 1033 proposal to OIRA (2026-08-06)](https://www.consumerfinancemonitor.com/2026/08/06/cfpb-sends-new-section-1033-open-banking-proposal-to-oira-for-review/) · [American Banker on the rewrite](https://www.americanbanker.com/news/what-we-know-about-the-cfpbs-forthcoming-open-banking-rule) · [JPMorgan–Plaid paid data deal](https://www.jpmorganchase.com/newsroom/press-releases/2025/jpmc-plaid-renewed-data-access-agreement) · [CNBC: JPMorgan fee fight](https://www.cnbc.com/2025/11/14/jpmorgan-chase-fintech-fees.html) · [FDX adoption / CFPB recognition](https://www.openbankingtracker.com/standards/fdx)

**Standards & document routes:** [Intuit tax-import technical overview](https://intuit.com/partners/financial-institutions/professional-services/tax-import/program-overview/technical-overview) · [ofxtools](https://github.com/csingley/ofxtools) · [GnuCash OFX Direct Connect settings](https://wiki.gnucash.org/wiki/OFX_Direct_Connect_Bank_Settings) · [BofA kills DC/QFX 2025-09-30](https://community.quicken.com/discussion/7966609/9-30-25-bank-of-america-web-connect-discontinued) · [finance-dl (statement downloader)](https://github.com/jbms/finance-dl) · [Per-bank CSV formats/limits](https://capyparse.com/blog/how-to-download-bank-statements-as-csv) · [Fidelity blocks credential sharing](https://newsroom.fidelity.com/pressreleases/fidelity-takes-steps-to-address-screen-scraping/s/2f33bc18-f16d-4b66-9868-626ada9ba32b)

**Brokerage:** [Schwab individual developer program](https://developer.schwab.com/user-guides/individual-developer/become-individual-developer) · [SnapTrade billing (personal free)](https://docs.snaptrade.com/docs/billing) · [Coinbase Advanced Trade API](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview)

**International:** [Enable Banking restricted mode](https://enablebanking.com/docs/api/linked-accounts/) · [GoCardless signups disabled / alternatives](https://dev.to/johnfrandsen/gocardless-bank-account-data-alternatives-what-to-use-when-signups-are-disabled-326d) · [Firefly III Salt Edge free-tier end](https://docs.firefly-iii.org/how-to/data-importer/import/salt-edge/) · [India Account Aggregator framework](https://financialservices.gov.in/beta/en/account-aggregator-framework)

