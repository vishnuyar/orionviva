# Adoption & Distribution — local-first without the friction tax

**State:** design-only
**Rules:** PROG-35, PROG-36, PROG-37

## Rules

### PROG-35 — The required user skill is "can install an app"
**State:** untestable
**Code:** none found
**Test:** none

1. The default path never requires running a server, editing a config file, or knowing what an API key is.
2. Nobody is ever asked which model they would like as a condition of getting an answer.
3. A path that needs a developer signup or an API key is a documented power-user path, never the default.

### PROG-36 — No raw key ships in the app, and no plaintext proxy is ever run
**State:** by-review
**Code:** core/vivacore/models/spec.py:38-45 (keys come from a named environment variable and never from a config file), .gitignore (`.env`, `.env.*`)
**Test:** none

1. No API key is bundled with distributed software.
2. Model calls are never routed through a project-operated proxy that can read the request.

### PROG-37 — The model layer supports four access modes
**State:** unmet
**Code:** core/vivacore/models/spec.py:23 (a base URL plus an optional key-bearing environment variable, keyless where the server is local)
**Test:** none

1. A bundled or operating-system local model serves the zero-setup default.
2. An OAuth-brokered subscription runs calls on the user's own plan.
3. A directly-supplied key is supported for users who want it.
4. An attested-enclave tier is possible without changing the interface shape.
5. Supporting all four hardens [ADR-001](decisions/ADR-001-hybrid-model-strategy.md)'s provider-abstraction requirement into a concrete interface shape.

**Note:** what is built covers the direct-key and local-server cases through one configurable adapter interface. There is no bundled model, no subscription OAuth, and no attested tier.

## Why

The fear is that local-first implies installation, installation implies friction, and friction implies nobody but hobbyists. The fear is real but mislocated: **local-first and self-hosted are different things, and the friction lives almost entirely in the second.** Data staying on the device does not require anybody to run servers, edit config files or know what an API key is — those burdens come from implementation choices, not from the principle.

Four distinct frictions get conflated and have different answers: getting the software running; connecting to intelligence; keys, recovery and backup; and reaching a phone and a laptop without a server in between.

**Install is a solved problem when you ship consumer software.** Signed installers and app stores make install one click, and mobile app stores are the easiest software acquisition path ordinary people know. The cautionary tales all come from the self-host world, where local AI's own commentators describe setup that feels like a punishment for being curious — terminals, drivers, config. Even carrying that friction, one local runtime went from 100K to 52M monthly downloads in three years: demand for local AI is enormous and the approachable packagings win the mainstream end. The lesson is to ship a consumer app and never a stack.

**The API-key path is not merely unfriendly; deployed naively it is dangerous.** A 2026 study found 282 of 444 iOS AI apps leaking API keys in network traffic, with worst-case exposure around $46K/day in stolen usage. The industry's standard fix is routing calls through a developer-run proxy — the one fix this project can never use, because a proxy that sees plaintext bank statements *is* the third party the core principle excludes. That kills the comfortable middle option and forces the interesting ones.

**Bring-your-own-subscription is emerging as a real mechanism.** Providers are piloting sign-in flows where requests run on the user's own plan rather than the developer's key. The direction of travel is industry-wide: the user brings their existing AI subscription the way they bring a Google account. That is close to ideal here — billing solved, no key handling, and the data path running directly between the user and their provider with this product never in the middle.

**On-device models crossed a threshold.** Platform foundation models now include capable multimodal models free for apps to call, doing structured extraction and classification on the phone, and desktop-class local vision models are stronger still. A bundled or OS-provided local model as the zero-setup default is credible for a meaningful slice of documents — and the verification layer, which grades every model anyway, is exactly the machinery that can say honestly, per document, whether the built-in model handled it or it deserves a stronger one.

**The hosted-but-provably-blind pattern now has a name.** Attested-enclave inference established the consumer pattern: cloud inference where data is never stored, used only for the request, with privacy claims that are cryptographically verifiable rather than merely promised, at single-digit-percentage overhead. This is precisely what "keeping data local means data not available to third parties" leaves room for — a hosted tier whose inability to read your data is a property you can verify. It is the escape hatch if frontier-quality inference must ever be made zero-setup, and a candidate for the eventual business model: the code free and open, the verified-private convenience paid.

**The ladder, one product and four rungs**, each optional, climbed only for more capability.

*Try without installing* — a page with synthetic sample data: meet Viva, ask questions, see provenance click-through. No real data ever touches it, so it can be hosted freely and curiosity costs nothing.

*Install and it just works* — one signed app, and a bundled or OS local model means it functions immediately with no account, no key and no setup. Drag a statement in; verification does its job; Viva is honest about which documents the built-in model handled confidently and which deserve a stronger one. **This rung alone must deliver real value, or the ladder fails.**

*Connect your AI without knowing what an API key is* — subscription OAuth as it becomes available to third-party apps: two clicks, the subscription already paid for, data flowing directly between the machine and the provider. Until those programs open, a guided in-app key flow is acceptable for early adopters and never the mainstream plan.

*Power user* — choose and pin models, point at a local server, raise or lower redundancy, export everything. The trust policy's knobs, exposed.

*Future rung* — attested-enclave inference as an optional, paid, verifiably blind convenience tier, and only when the attestation story can be explained honestly to a non-technical person. "Nothing leaves" is understandable; a formal privacy parameter is not, and [ADR-006](decisions/ADR-006-zero-exfiltration.md)'s legibility principle applies squarely here.

**Who controls model swapping** is already answered by [model-trust-policy.md](model-trust-policy.md): the *system* grades and promotes models on evidence, and the *user* consents at rung level rather than per model. Defaults follow benchmark evidence, changes are logged, visible and reversible, and a power user can override anything.

**Sources:** [TechCrunch: Sign in with ChatGPT](https://techcrunch.com/2025/05/27/openai-may-soon-let-you-sign-in-with-chatgpt-for-other-apps/) · [Codex issue: run on user's own plan](https://github.com/openai/codex/issues/10974) · [Anthropic: account login vs API-key guidance](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account) · [282 iOS AI apps leak API keys](https://thehackernews.com/2026/06/282-ios-apps-found-leaking-llm-api-keys.html) · [Apple PCC on Google Cloud](https://www.infoq.com/news/2026/07/apple-pcc-google-cloud/) · [PCC privacy analysis](https://arxiv.org/html/2605.24239v1) · [Tinfoil](https://tinfoil.sh/technology) · [Confidential AI inference](https://appscale.blog/en/blog/confidential-computing-ai-inference-tees-nitro-enclaves-nvidia-h100-h200-2026) · [Apple Foundation Models 3 developer read](https://ofox.ai/blog/apple-foundation-models-3-wwdc-2026-developer-read/) · [On-device AI apps](https://newly.app/guides/on-device-ai-mobile-apps) · [Local AI has a friction problem, not a quality problem](https://www.xda-developers.com/the-biggest-thing-holding-local-ai-back-isnt-model-quality-its-friction/) · [Local AI: Ollama's growth](https://dev.to/pooyagolchian/local-ai-in-2026-ollama-benchmarks-0-inference-and-the-end-of-per-token-pricing-32e7)

## Open

- The whole shape is deliberately undecided while the first user is the author, so friction is not yet the binding constraint.
- Q11: when do subscription-OAuth programs open to third-party consumer apps, and on what terms? This gates the clean version of the connect-your-AI rung.
- Q12: can attested-cloud inference be offered without weakening the privacy promises — what wording survives? Needs its own analysis before the future rung is ever announced.
- Q13: the benchmark should include an on-device-class model to size the zero-setup rung's honest capability floor.
- Form factor: the install-and-it-works rung demands a real consumer app — signed, auto-updating, store-distributable — which effectively rules out a localhost web app as the *end-user* product, though it remains fine for the experiment phase.
- Mobile is not optional long-term: statements arrive on phones, on-phone extraction is plausible, and the data model must never assume a single device. The encrypted-sync patterns move from "later" to "designed-for from the start, built later".
- Onboarding gains a new sentence type: capability honesty ("this document deserves a stronger model") as distinct from extraction doubt.
