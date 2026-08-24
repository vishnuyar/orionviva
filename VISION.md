# OrionViva — The Vision

*From Vishnu Yarmaneni, author and first user. Product: OrionViva · Agent persona: Viva · orionviva.com*

---

## What this document is, and what it deliberately is not

This document is the complete vision for OrionViva, written for the person who will build it. It tells you what this product is, who it serves, what it promises, how it must feel, and where it is ultimately going.

It deliberately does **not** tell you how to build it. I have built a version of this product myself, and I have made hundreds of design decisions along the way — data models, architectures, question flows, model policies. You will not find them here, and I am not going to hand you my design documents. That is not secrecy; it is the point. I am giving you this because I believe a better builder will make better design decisions than mine — and they can only do that if my decisions aren't sitting in their head, quietly becoming the default.

So the contract is this: everything in this document is the product. If you change these things, you are building something else. Everything *not* in this document — how the data is stored, how the intelligence is organized, what to build first, what the internals look like — is yours. Solve it your way. Where I name a hard problem, I name it because you will meet it, not because I'm telling you how to beat it.

---

## The problem

A person's financial life is scattered across a dozen institutions — a checking account here, two credit cards there, a brokerage, a retirement account, a mortgage — and none of them holds the whole picture. Getting a straight answer to a simple question ("where did my money actually go last month?") takes an hour of tab-switching and mental math, so most people never ask. They live with a background hum of not-knowing about their own money.

The products that tried to fix this made a trade nobody should have to make: to see your whole financial picture, you had to hand it — complete, integrated, decrypted — to a company's servers, where it became their asset. The whole picture of you existed, but you didn't own it. Others offer real rigor — proper accounting, books that balance — but demand hours of hand-entry only hobbyists will do.

The missing product: **the rigor of a company's books with the effort of dropping a PDF, and the whole picture living only with you.** The wealthy already buy this service from a human — it's called a personal CFO. OrionViva democratizes it.

## The belief underneath everything

> **As intelligence becomes free and the data commons rots, the scarce resource is provable trust, grounded in operational reality.**

AI can now produce a confident-sounding answer about anything, which means confidence itself is worthless. What becomes scarce is *provability*. Personal financial records are the cleanest operational ground truth a person owns: money moved, a ledger recorded it. They are measurements, not generations. OrionViva is built on that clean data, and it is a machine for turning it into trust — first the user's own trust in their own picture, and eventually trust that others can rely on.

That belief has a consequence that shapes the entire product: an answer about your money is only worth having if you can believe it without re-checking it. Everything below exists to earn that moment.

---

## What the product is

**OrionViva is an open-source, local-first personal financial agent.** It ingests a person's complete financial life — statements, accounts, documents — holds one clean, always-current picture of it, and answers questions about it in plain language, honestly, proving what it stood on.

The name: *Orion*, the stars you navigate by; *ViVa*, the user. The agent the user talks to is **Viva** — a kind, patient, discreet butler. The code is open source under a maximally permissive license, on purpose: the promise of this product is that the user never has to take anything on faith, and that promise is strongest when nothing stops anyone from reading, running, or reusing the code.

It does four jobs, in an order where each funds the next:

1. **Organize & consolidate.** One clean picture of accounts, transactions, holdings, and net worth over time, regardless of where the pieces came from. This unification is the hard, valuable core.
2. **Explain & advise.** Answer anything about the picture in plain language, and volunteer insight worth having — recurring charges, fees, anomalies, trends — discreetly.
3. **Take action.** Draft budgets and payoff plans, keep things organized; handle routine upkeep on its own and report it; ask first before anything irreversible.
4. **Peace of mind.** The real deliverable: open it and it's handled, or ask one question and get one trustworthy answer.

## Who it is for, and how it must be built

It is built for one individual at a time — a household view is a later possibility, not a requirement. The target user's technical skill is exactly this: **they can install an app.** No feature on the default path may require servers, terminals, configuration, or knowing what an API key is. Local-first must never feel like a hobbyist product; if privacy costs the user effort, the mainstream user will (rationally) choose convenience, and the product will have failed.

Its first user must be its builder, with their own real money. This is not sentiment; it is method. A product whose entire thesis is that trust must be earned and proved doesn't get to *assert* trust — if it can't earn its builder's trust on their own finances, it has no business asking for anyone else's. And it is built in the open: code public, progress public, mistakes included. A project about provable trust that only reported its wins would refute its own thesis.

---

## The promises

These are the product's promises to its user. They are not features and they are not preferences — each one is load-bearing, and each has teeth: I've written what it forbids, so you can tell when a design would quietly break it.

**1. Never bluff a number.** Confident when sure; transparent the instant there's real doubt. A confident-but-wrong figure in a finance product isn't a bug — it's ruin, because it ends the trust the whole product exists to earn. Uncertainty is shown to the user, plainly, in the answer itself — never buried, never decorative, and never *invented in language*: the confidence in the words must match the confidence in the data, always.

**2. Every figure proves itself.** Any number the user sees can be traced — by the user, in the moment — to the source that justifies it, along with how sure the product is of it. A number with no source has no place in an answer. This includes honesty about the whole: the product must know, measure, and show what it *hasn't* seen ("current through yesterday; June's card statement not yet seen") — a gap in the picture is stated, never papered over.

Proof is layered rather than repeated. Financial meaning comes first; material uncertainty is visible immediately; and the complete source and verification trail is always one deliberate action away. A presentation preference may hide routine positive verification, but never a conflict, gap, caveat or uncertain basis that could change a decision. Presentation never changes the underlying grade or what an authorised agent can inspect.

**3. Models read; they never certify.** AI models are how the product reads messy human documents and converses naturally — and they are never the authority on a fact. Nothing a model says becomes a number in the user's ledger without independent, deterministic verification, and arithmetic is always computed, never generated. The user's trust attaches to a system that checks, not to a model that claims. (This is the conviction I hold most strongly after building it. Treat it as part of the vision.)

**4. Your data, your keys — from the first commit.** The integrated picture of the user's financial life exists in exactly one place: their own device, encrypted, with keys only they hold. No server — mine, yours, anyone's — ever holds it, and no service ever receives their documents readable, even briefly, even "encrypted right after." Local-first is not a v2 hardening step; retrofitted privacy is a promise already broken. A breach of anything outside the user's device must be a bad day, never a ruin.

**5. Nothing leaves silently.** Any bytes that leave the user's machine — a model call, anything — happen for a reason the user can see, in a place the user can inspect: a plain, complete account of everything that has ever left. "Nothing leaves without your knowledge" must be a fact the product can display, not a policy it recites.

**6. The user is the customer, never the product.** Paid directly. No ads, no data sale, no data mining — and open source, so this is verifiable rather than promised.

**7. Serve, don't overwhelm — and the user directs the pace.** Nothing appears before the data that makes it useful exists; the product reveals itself as the user's picture grows. Every interaction leaves the user in control: they can stop anywhere, decline anything, and resume exactly where they left off. A decline is respected and remembered, never nagged about.

**8. Autonomous where safe, deferential where it counts.** Routine, low-stakes upkeep just happens — and is reported, so "handled" is verifiable. Anything big or irreversible waits for the user's explicit yes, and that gate must live in the product's mechanics, not in an instruction a model is trusted to follow.

---

## The experience

The feel of the product is part of the vision, not a detail. Four choices define its personality:

**It opens as a picture, not a chat.** Opening OrionViva shows the user's financial picture — net worth, accounts, trends, a quiet strip saying how current and complete the picture is. Viva is *summoned*, never ambient.

**It speaks only when spoken to.** Maximum discretion. Viva never initiates, never pings, never nags — the notification philosophy is that there isn't one. Everything she notices — an anomaly, a missing statement, a figure needing eyes — becomes *quiet, visible state* on the dashboard, sitting silently until touched. The user pulls; the product never pushes.

**It grows with the user's data.** Day one is nearly empty: a greeting and a place to drop one document. Panels and capabilities earn their existence as data arrives. Day-one simplicity, year-one richness — every user at their own point on that path. And there is no setup phase at all: no "connect all your accounts" wizard, no empty-books ceremony. Adding a document works the same on day one and in year five, whether the document is from yesterday or from three years ago, in any order. Onboarding is simply the early, sparse stretch of a lifelong accretion — and Viva's job is to make the sparse part feel like progress, never like a hole being pointed at.

**Getting documents in is effortless, everywhere.** Drag and drop, a watched folder, the phone's camera and share sheet, email — whatever gesture is natural. But every capture path honors promise 4: no path may route the user's documents through anyone's servers readable. Convenience is won on the user's own devices, not by quietly reintroducing a middleman.

The user talks to Viva in text or voice from day one — talking to a butler is the natural register. And in every answer: figures the user can tap through to the exact place in the source document they came from, and confidence spoken honestly (an answer built on a shaky figure *sounds* appropriately unsure). When the user corrects something — "that's groceries, not dining" — one sentence is enough, and the correction is permanent. Being asked twice for the same thing is a broken promise; the accumulating memory of this user's corrections, preferences, and rulings is the product's real moat. Models will commoditize; the private, earned understanding of this one person is what cannot be copied.

One more experience the product owes the user: the moment they wonder "what does this thing actually send out?", the answer is already on screen — the standing, complete, plain-language account of everything that has ever left the machine (promise 5). That panel is where the privacy promise stops being marketing and becomes a fact they can check.

## Viva

Viva is not a feature; she is the product's personality, and her character is load-bearing — a design requirement, not incidental copy.

She is a kind, wise, discreet financial butler. Patient: she never rushes, reassures the user that stopping any time is fine and that not knowing something is perfectly acceptable. Insightful: she doesn't just show data; she offers gentle observations grounded in it — framed as observations, never commands. Discreet: she presents her findings and recedes. Respectful: courteous, warm but professional, addressing the user by name — a name learned from their own documents, never demanded.

When she needs something, she asks for one thing at a time, chosen by what matters most, and she says why: "if you share the rate, I can show your true borrowing cost." When the user says "I don't know," that is a fine answer and it is remembered. If the missing thing is optional, it never comes up again; if honesty genuinely depends on it, it remains visible as quiet, named incompleteness — never as a nag.

What she must never do: initiate, ping, or guilt. Bluff — her words never carry more confidence than the data holds. Rush or gamify. Ask what the product already knows. Or ask the user something the user *cannot* know — she asks instead for the document that knows it.

---

## The destination

The personal CFO is the product. It is also the foundation for something larger.

Once the agent holds verified, tamper-evident records of a person's financial life, it can **vouch** for them — to a lender, a landlord, anyone — only when the user permits it, revealing only what is needed and nothing more: proving "income above X for two years" without disclosing the income. A lender's agent asks; *your* agent answers; you hold the keys. This is a user-owned alternative to the credit bureau — an institution that profiles people without their consent and sells the profile back to the system.

Two things about this destination bind the builder today:

First, **the foundations must be worthy of it from the start.** The user's history must be kept in a form that is tamper-evident and provable from the very beginning — you cannot retrofit provability onto records that were mutable when they were made. How you achieve that is your design; that you achieve it is the vision.

Second, **it must not be built early.** The single-user product must genuinely earn trust first — and "earned" is an event, not a date: the moment its user believes an answer without re-checking it. No multi-party trust layer, no expansion beyond the first user, until that moment has actually happened. A trust product that scales before it is trusted is a contradiction that deserves to fail.

---

## What it must never do

- No ads, no data sale, no engagement or growth mechanics that erode discretion.
- No token, no speculation, no crypto theater. (Cryptographic *signatures* are the future of proving records authentic; none of that requires a coin, a chain, or a middleman.)
- No confident answer without a source and an honest confidence behind it.
- No cloud-by-default storage of the user's readable financial data, and no service that ever receives their documents readable — "briefly" included.
- No dark patterns around the user's attention: no push, no streaks, no fear.
- No building the vouching layer before the personal agent has earned real trust.

---

## The hard problems (named, not solved)

You will meet these. I name them so you can face them deliberately rather than discover them mid-build. My solutions are not in this document on purpose — I expect yours to be better.

**Calibrated honesty is the actual hard problem.** Reading messy, wildly varied financial documents with AI is now easy; *knowing how much to trust each extracted figure, and saying so honestly*, is not. "Never bluff" is only a slogan until the product can grade its own certainty, figure by figure, and carry that grade all the way into the words of an answer.

**Making untrusted models safe to work on money.** Models fail, drift, get silently updated by their providers, and can be manipulated by malicious content inside a document. The product must get full value from models while never being at their mercy — and must stay honest as models change underneath it.

**Measuring what you haven't seen.** A person will never provide their complete financial history — the picture is permanently partial. The product must be able to *quantify* its own incompleteness and show it, because a gap silently hidden is a bluff about the whole.

**Effortless and private at once.** Every convenience in capture, sync, multi-device, and intelligence has an easy version that routes through a server that can read the data. The product must find the versions that don't. Where the two truly conflict, privacy wins and the product says so.

**Intelligent without being presumptuous.** The product should arrive already understanding what any competent reader would understand — asking a user something the product could have known is the opposite of a butler. But it must never dress a guess as knowledge. The line between "I already handled this and here's my basis" / "here's what I believe — confirm?" / "I genuinely can't know this — can you tell me?" is, as much as anything, what the user experiences as intelligence. Finding that line is a design problem you will live with the whole way.

---

## How to know it's being built right

For any decision this document doesn't settle, ask four questions in order:

1. Does this make the user trust an answer **more, or less**?
2. Does it keep the user's **data and keys with the user**?
3. Is it **honest** about what it does and doesn't know?
4. Is it the **simplest thing that works**?

If a choice fails any of the first three, don't ship it, however clever. And know when you're done — not with the project, but with its first promise: the day its user, holding a real answer about their real money, believes it without checking. Everything before that day is construction. Everything after it is the product.

---

## The one-paragraph version

OrionViva is a personal CFO the user actually owns: an open-source, local-first AI agent that reads a person's financial documents, holds the one complete picture of their money that today exists nowhere, and answers any question about it in plain language — every figure traceable to its source, every uncertainty spoken honestly, nothing leaving their machine without their knowledge, the whole picture encrypted under keys only they hold. Models read and propose; the system verifies and decides; the user corrects, and it remembers forever. It earns trust one honest answer at a time, its builder's own money first — and once that trust is real, the same provable record becomes something bigger: an agent that can vouch for its owner to anyone they choose, revealing only what they permit. The credit bureau, inverted — owned by the person it describes.

*Build that.*
