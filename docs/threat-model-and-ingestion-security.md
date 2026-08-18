# Threat Model & Ingestion Security (B1 + B2)

**State:** partial
**Rules:** ING-70, ING-71, ING-72, ING-73, ING-74, ING-75, ING-76
**Invariants touched:** T3 (raw capture aids forensics), T5 (encryption limits breach blast radius), T6 (zero exfiltration limits what an attacker can send out), T8 and the model-trust guardrails (the extraction model is powerless by design), X3 (irreversible actions gated)

## Rules

### ING-70 — The extraction model is a quarantined, powerless worker
**State:** by-review
**Code:** core/vivacore/models/base.py:139 (the extraction interface is `extract(pages, prompt) -> ModelResult` and takes no tools), core/vivacore/models/anthropic_adapter.py:26
**Test:** none

1. The extraction call receives a document and returns text; it is given no tools, no write access, no network reach of its own, and no memory of other documents.
2. A poisoned document can instruct the extraction model freely, because there is nothing for the instruction to actuate.

### ING-71 — Document content reaches the model as delimited, untrusted data
**State:** contradicted-by-code
**Code:** product/viva/ingest/reader.py:57 (`_with_embedded`)
**Test:** none

1. The document is delivered inside clear bounds that mark it as content to read, never as commands to follow.
2. Untrusted document text is never concatenated into the instruction channel.

**Contradiction:** this doc states that spotlighting is adopted in the extraction prompt. `product/viva/ingest/reader.py:57` appends the issuer's embedded text to the prompt string behind the line *"[The issuer's own embedded text for these pages follows; use it together with the image(s).]"* — a hint about provenance, not a delimiter, with no closing bound and no instruction that the enclosed text is data rather than commands. Neither `product/viva/prompts/extract-base-v1.txt` nor `product/viva/prompts/classify-v2.txt` contains any untrusted-content framing. The untrusted text lands in the instruction channel.

### ING-72 — Deterministic verification is the reference monitor
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:44, product/viva/ingest/pipeline.py:329-336 (a statement that does not reconcile is held at `conflicted`, not posted)
**Test:** product/tests/test_pipeline.py::test_unreconciled_statement_is_conflict_not_posted

1. A figure a model reports is checked by arithmetic that does not consult the model.
2. Fabricated numbers fail reconciliation and surface as a conflict rather than entering the ledger.
3. Verification does not trust the model, so it does not trust a compromised model either.

### ING-73 — Extraction and conversation are separate contexts
**State:** by-review
**Code:** core/vivacore/models/base.py:139 (`extract`, ingest), core/vivacore/models/openai_compat.py:138 (`converse`, the tool-using path), product/viva/tools/__init__.py:31 (assertion 3 — the six registered verbs are all reads, and `local_only` is a registration gate)
**Test:** none

1. Nothing the extraction model says auto-acts.
2. The agent that uses tools is a different call on a different interface; a document never reaches its instruction channel.
3. The tool surface cannot move money or open a network connection.

### ING-74 — The poisoned document and the exact exchange are retained
**State:** enforced
**Code:** product/viva/ingest/raw_store.py:51 (`put`, capture before judgment), product/viva/ledger/events.py:271 (`read_recorded`), product/viva/ingest/pipeline.py:769
**Test:** product/tests/test_pipeline.py::test_read_that_throws_is_recorded_not_orphaned, product/tests/test_raw_store.py::test_put_is_content_addressed

1. Every uploaded file is captured, encrypted and content-addressed before anything parses it.
2. Every model response is recorded verbatim with its model and prompt version, so an injection attempt is auditable afterwards.

### ING-75 — No provider SDK on the wire
**State:** enforced
**Code:** core/vivacore/models/anthropic_adapter.py:12, core/vivacore/models/openai_compat.py:21 (both call their provider over plain `httpx`)
**Test:** product/tests/test_docs_track_the_code.py::test_the_model_adapters_import_nothing_the_package_did_not_declare

1. A model adapter imports only the standard library, a dependency the package declares, and the project's own code.
2. No provider SDK and no multi-provider wrapper sits between a bank statement and the wire.

### ING-76 — One key, derived from one passphrase, stored nowhere
**State:** enforced
**Code:** product/viva/crypto.py:8-19, :30 (`VERSION` names the algorithm and the KDF), product/viva/ingest/raw_store.py:56
**Test:** product/tests/test_raw_store.py::test_nothing_readable_at_rest, product/tests/test_raw_store.py::test_wrong_passphrase_rejected, product/tests/test_raw_store.py::test_tampered_blob_fails

1. Data at rest is sealed with a versioned authenticated envelope; tampering is detected on open, never silently accepted.
2. The key is derived from the owner's passphrase with a memory-hard KDF and is never stored.
3. There is no second wrap of the key and no recovery phrase.

## Why

Trust is the whole product, so each threat is classified by whether its worst
case is **absorbing** — a leak of decryptable financial data, or a silently
corrupted ledger the person believes — or merely **a bad day**: a crash, or a
wrong figure verification catches and surfaces. Ruin threats dominate the design
budget regardless of probability; bad-day threats are handled proportionately.
The goal of every control here is to convert a ruin path into a bad-day path.

Against a **device thief**, encryption does that conversion outright: everything
at rest is ciphertext and the key derives from a passphrase that is not on the
device. Against **malware running as the user while the app is unlocked**, no
local-first application can fully protect data in memory — this is the hardest
residual and it is documented rather than pretended away. The mitigations are to
minimize the unlocked window, hold the passphrase no longer than needed, use OS
sandboxing where available, and rely on the tamper-evident log as the backstop
that makes *silent* corruption detectable even when prevention fails. Against a
**cloud model provider**, the exposure is exactly the document content sent for
extraction and nothing else — not the ledger, not the keys, not the history.
Against **legal compulsion of the project**, there is structurally nothing to
hand over, because there is no hosted backend and no user data. Against a
**network attacker**, TLS covers the wire and the at-rest envelope covers
everything else, which leaves traffic analysis. Against **compulsion of the
person themselves**, software has nothing to offer — whatever they can decrypt
they can be made to decrypt — and saying so plainly is the only honest move.
Against **the person's own mistakes**, every write is an event and therefore
reversible.
Against **future feature creep** — a telemetry endpoint, a hosted tier — the
promise inventory and the invariants are the only guard, and that threat is
classified as ruin for exactly that reason.

Two adversaries deserve their own argument. The **malicious document author** is
this product's signature exposure, because untrusted documents are fed into a
capable model *by design* — the precise setup indirect prompt injection targets.
And the **malicious contributor** to a shared registry is the largest new attack
surface the network effect buys: a poisoned format profile cannot move money,
since it only guides extraction and verification still grades the result, but a
malicious code change to the verification layer is a genuine ruin path.
Governance *is* the security boundary there, which is why adversarial review of
trust-critical code is a policy rather than a courtesy.

The state of the art on prompt injection converged on a defense pattern that
this design already embodied, because the model-trust policy was written with it
in mind. The single most important defense is structural rather than a prompt
plea: **the extraction model is a quarantined, powerless worker**. It receives a
document and returns structured claims. It holds no tools, no write access, no
network of its own, no memory of other documents. A poisoned PDF may instruct it
all it likes; there is nothing for the instruction to actuate.

Layered on that: **spotlighting**, which delivers the document as clearly
delimited data rather than concatenated into the instruction channel — a
lightweight, probabilistic, measurably effective control. **Out-of-band
deterministic verification as the reference monitor**, which catches even a model
fully hijacked into reporting false figures, because fabricated numbers fail
reconciliation and surface as a conflict: a bad day, not a breach. **Firewalled
contexts**, so the agent that actually does things is a different call from the
extraction worker and a document never reaches its instruction channel. And
**raw capture**, so the poisoned document and the exact exchange remain auditable.

The residual risk is named rather than solved: a *subtle* injection that nudges
a value to something plausible-but-wrong that still passes arithmetic — altering
a payee name, say, which no sum checks. Cross-model agreement blunts it, since
two models rarely mis-read the same way from the same injection unless it is
blatant enough for quarantine and spotlighting to catch, and human correction is
the final catch.

Provenance doubles as an injection tripwire: an extracted claim whose stated
source region does not contain the value is a signal something is off.

Key custody is where honesty costs something. The dual wrap this design once
assumed — the key wrapped once by the OS keychain and once by an offline
recovery phrase — is a requirement in the storage design and is **not built**.
One key is derived from one passphrase and nothing else unwraps it. Against the
device thief that is if anything stronger: nothing on the stolen device unlocks
the vault, because no wrap sits there to be attacked. The cost lands on the
owner instead, and it belongs in a threat model rather than only in a storage
doc — **a lost passphrase is a lost vault**, an unrecoverable loss of a person's
own data with no adversary in it at all. Recovery is deferred, not delivered.

### Why the model adapters are hand-written HTTP

Both provider adapters call their provider over plain `httpx`, not through a
provider SDK and not through a multi-provider wrapper. An SDK on this path is
third-party code sitting between a bank statement and the wire, and the point of
the adapter layer is that every byte sent is visible in the file you are reading.
The cost of writing it by hand is small: the two APIs involved are stable,
documented and narrow enough that roughly a hundred lines of inspectable code
cover them, and a provider's breaking change fails the admission exam loudly and
is repaired in exactly one file.

That is the narrow argument about the **model call adapters**. The separate and
larger argument for a hand-rolled tool loop over an agent SDK — about the
**agent harness** — is in
[agent-and-model-landscape.md](archived/agent-and-model-landscape.md). The two
are related and are not the same claim.

## Open

- Spotlighting implementation: the exact delimiter and framing for untrusted document content in the extraction prompt, plus a red-team benchmark mode that injects a known instruction into a test PDF and confirms it never actuates and is caught.
- Format-commons and knowledge-registry governance: the review bar and the privacy-lint specifics that make community contribution safe at scale.
- Live-session malware: how far OS sandboxing can shrink the unlocked-window exposure on each target platform.
- Key recovery: today a lost passphrase is a lost vault, and no recovery path exists.
- The chain head is not anchored to any external timestamp, so the tamper-evident log's value as the malware backstop rests on the chain alone.
- Nothing tests that the extraction call is toolless; it is true by the shape of the interface and unchecked by the build.

## Sources

- [Zylos: Indirect prompt injection — state of the art](https://zylos.ai/research/2026-04-12-indirect-prompt-injection-defenses-agents-untrusted-content/)
- [Defending against indirect prompt injection with spotlighting (CEUR)](https://ceur-ws.org/Vol-3920/paper03.pdf)
- [CaMeL / out-of-band defenses — adaptive evaluation (arXiv)](https://arxiv.org/html/2606.26479v1)
- [IPIGuard: tool-dependency-graph defense (arXiv)](https://arxiv.org/pdf/2508.15310)
- [Unit 42: web-based indirect prompt injection in the wild](https://unit42.paloaltonetworks.com/ai-agent-prompt-injection/)
