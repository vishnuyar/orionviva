# Adoption & Distribution — local-first without the friction tax

**Status:** Draft · **Last updated:** 2026-07-20 · **Origin question:** if data must stay local, who can actually run this? What user tech skill do we assume? Does local-first cost us the growth the vision needs ("I want this tool so that everyone uses it")?

## Naming the tension precisely

The fear is: local-first ⇒ installation ⇒ friction ⇒ nobody but hobbyists uses it. The research says the fear is real but mislocated. **Local-first and self-hosted are different things, and the friction lives almost entirely in the second.** "Your data stays on your device" does not require the user to run servers, edit config files, or know what an API key is — those burdens come from *implementation choices*, not from the principle. The design goal, stated as a promise to ourselves: **the required user skill is "can install an app from an app store." Nothing more, ever.**

Four distinct frictions get conflated, and they have different answers:

1. **Install friction** — getting the software running.
2. **Model-access friction** — connecting to intelligence (the API-key problem).
3. **Custody friction** — keys, recovery, backup.
4. **Multi-device friction** — phone + laptop without a server in between.

## What the research shows (mid-2026)

**Install is a solved problem — when you ship consumer software.** Signed installers and app stores make install one click; mobile app stores are the *easiest* software acquisition path normal people know. The cautionary tales are all from the self-host world: local AI's own commentators describe setup that "feels like a punishment for being curious" — terminals, CUDA, config. Yet even with that friction, Ollama went from 100K to 52M monthly downloads in three years — demand for local AI is enormous and the approachable packagings (LM Studio-style) win the mainstream end. Lesson: ship a consumer app, never a stack. Obsidian's file-first model shows a local-first product can feel completely ordinary to use.

**The API-key path is not just unfriendly — deployed naively, it's dangerous.** A 2026 study found 282 of 444 iOS AI apps leaking API keys in network traffic (worst-case exposure: ~$46K/day in stolen usage). The industry's standard fix is routing calls through a developer-run proxy — which for OrionViva is the one fix we can never use: a proxy that sees plaintext bank statements *is* the third party our core principle excludes. This kills the comfortable middle option and forces the interesting ones.

**"Bring your own subscription" is emerging as a real mechanism.** OpenAI is piloting *Sign in with ChatGPT* — users authenticate with their existing ChatGPT account, with moves toward requests running on the user's own plan rather than the developer's key. Anthropic has subscription OAuth in its own tools (and now an Agent SDK credit line), though it currently steers third-party products to API keys. Direction of travel is clear industry-wide: the user brings their existing AI subscription to your app the way they bring their Google account. For us this is close to ideal — billing solved, no key handling, and the data path runs *directly* user↔provider under the user's own account, with OrionViva never in the middle.

**On-device models crossed a threshold this year.** Apple's third-generation Foundation Models (WWDC 2026) include a 20B sparse model with image input, free for apps to call, doing structured extraction and classification on the phone; Gemini Nano is the Android counterpart. Desktop-class local VLMs (the agent-landscape doc) are stronger still. A bundled or OS-provided local model as the *zero-setup default* is now credible for a meaningful slice of documents — and our verification layer (which grades every model anyway) is exactly the machinery that can say honestly, per document, "the built-in model handled this" vs. "this one needs a stronger model."

**The "hosted but provably can't read" pattern now exists — the postulated pattern has a name.** Apple Private Cloud Compute established the consumer pattern: cloud inference where data is never stored, used only for the request, and the privacy claims are *cryptographically verifiable* (attested hardware enclaves; Apple now even runs PCC on Google Cloud with confidential GPUs). Startups like Tinfoil offer the same pattern as a service — open-source, auditable, attestation-gated, on confidential NVIDIA GPUs at 1–7% overhead. This is precisely "keeping data local means data not available to third parties — it might not mean no hosted anything": a hosted tier whose inability to read your data is a property you can verify, not a promise you must trust. It is the escape hatch if frontier-quality inference must ever be made zero-setup — and a candidate for the eventual business model (F1): the code free and open, the *verified-private convenience* paid.

## The onboarding ladder (proposed)

One product, four rungs; each rung is optional and the user climbs only for more capability. The Google-homepage simplicity lives at rungs 0–1.

- **Rung 0 — Try without installing.** A web page with *synthetic* sample data: meet Viva, ask questions, see provenance click-through. No real data ever touches it (it's a demo, not the product) — so it can be hosted freely, and curiosity costs nothing.
- **Rung 1 — Install and it just works.** One-click signed app (desktop; mobile later). A bundled/OS local model means it functions immediately: no account, no key, no setup. Drag a statement in; verification does its job; Viva is honest about which documents the built-in model handled confidently and which deserve a stronger model ("I could read this more reliably if you connect a model — want to?"). *This rung alone must deliver real value, or the ladder fails.*
- **Rung 2 — Connect your AI, without knowing what an API key is.** "Sign in with Claude / ChatGPT"-style OAuth as it becomes available to third-party apps: two clicks, uses the subscription they already pay for, data flows directly between their machine and their provider. Until those programs open: a guided BYOK flow that walks the user through key creation in-app (acceptable for early adopters, never the mainstream plan).
- **Rung 3 — Power user.** Choose/pin models, point at Ollama, raise or lower redundancy, export everything. The trust policy's knobs, exposed.
- **Future rung — verified-private cloud.** Attested-enclave inference (PCC-pattern) as an optional, paid, *verifiably* blind convenience tier for frontier quality with zero setup. Only when the attestation story can be explained honestly to a non-technical user — the ADR-006 legibility principle ("nothing leaves" is understandable; "ε-differential privacy" is not) applies squarely here.

**Who controls model swapping:** the model trust policy already answers this — the *system* grades and promotes models on evidence; the *user* consents at rung level, not per-model. Defaults follow benchmark evidence; changes are logged, visible, and reversible; rung 3 users can override anything. Nobody is ever asked "which VLM would you like?" as a condition of getting an answer.

## What this means for architecture (why this doc precedes it)

- The model layer must support **four access modes** from the start: bundled/OS local model, OAuth-brokered subscription, BYOK direct, and (future) attested-cloud — this hardens ADR-001's provider-abstraction requirement into a concrete interface shape.
- **Form factor:** rung 1 demands a real consumer app (signed, auto-updating, store-distributable) — strengthens the Tauri-class endpoint in the form-factor doc and effectively rules out "localhost web app" as the *end-user* product (fine for the experiment phase).
- **Mobile is not optional long-term.** Statements arrive on phones; AFM/Nano make on-phone extraction plausible; the data model must never assume single-device (the storage doc's encrypted-sync patterns get promoted from "later" to "designed-for from the start, built later").
- **Onboarding (C4) now has a concrete shape**, and the C1 uncertainty language gains a new sentence type: capability honesty ("this document deserves a stronger model") as distinct from extraction doubt.
- **Never ship a raw API key inside the app; never run a plaintext proxy.** Both now have documented failure precedents. These join the guardrails.

## Open questions (added to the register)

- Q11: When do subscription-OAuth programs (OpenAI, Anthropic, Google) open to third-party consumer apps, and on what terms? (Watching item; this gates rung 2's clean version.)
- Q12: Can attested-cloud inference be offered without weakening promise #3/#4 language — what wording survives ("your data is never *readable* by anyone but you — verifiably")? Needs its own analysis before the future rung is ever announced.
- Q13: Benchmark should include an on-device-class model (AFM-tier) to size rung 1's honest capability floor.

## Sources

- [TechCrunch: Sign in with ChatGPT](https://techcrunch.com/2025/05/27/openai-may-soon-let-you-sign-in-with-chatgpt-for-other-apps/) · [Codex issue: run on user's own plan](https://github.com/openai/codex/issues/10974)
- [Anthropic: account login / OAuth vs API-key guidance](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account)
- [Hacker News: 282 iOS AI apps leak API keys](https://thehackernews.com/2026/06/282-ios-apps-found-leaking-llm-api-keys.html)
- [Apple PCC on Google Cloud (InfoQ, July 2026)](https://www.infoq.com/news/2026/07/apple-pcc-google-cloud/) · [PCC privacy analysis (arXiv)](https://arxiv.org/html/2605.24239v1) · [Tinfoil](https://tinfoil.sh/technology) · [AppScale: confidential AI inference 2026](https://appscale.blog/en/blog/confidential-computing-ai-inference-tees-nitro-enclaves-nvidia-h100-h200-2026)
- [Apple Foundation Models 3 developer read (WWDC 2026)](https://ofox.ai/blog/apple-foundation-models-3-wwdc-2026-developer-read/) · [Newly: on-device AI apps 2026](https://newly.app/guides/on-device-ai-mobile-apps)
- [XDA: local AI has a friction problem, not a quality problem](https://www.xda-developers.com/the-biggest-thing-holding-local-ai-back-isnt-model-quality-its-friction/) · [Local AI in 2026: Ollama's growth](https://dev.to/pooyagolchian/local-ai-in-2026-ollama-benchmarks-0-inference-and-the-end-of-per-token-pricing-32e7)
