# Threat Model & Ingestion Security (B1 + B2)

**State:** partial
**Rules:** ING-70, ING-71, ING-72, ING-73, ING-74, ING-75, ING-76, ING-77, ING-78
**Invariants touched:** T3 (raw capture aids forensics), T5 (encryption limits breach blast radius), T6 (zero exfiltration limits what an attacker can send out), T8 and the model-trust guardrails (the extraction model is powerless by design), X3 (irreversible actions gated)

## Rules

### ING-70 — The extraction model is a quarantined, powerless worker
**State:** by-review
**Code:** core/vivacore/models/base.py:139 (the extraction interface is `extract(pages, prompt) -> ModelResult` and takes no tools), core/vivacore/models/anthropic_adapter.py:26
**Test:** none

1. The extraction call receives a document and returns text; it is given no tools, no write access, no network reach of its own, and no memory of other documents.
2. A poisoned document can instruct the extraction model freely, because there is nothing for the instruction to actuate.

### ING-71 — Document content reaches the model as delimited, untrusted data
**State:** enforced
**Code:** product/viva/ingest/reader.py:102 (`_with_embedded`), product/viva/prompts/extract-untrusted-frame-v1.txt (the frame itself)
**Test:** product/tests/test_ingest_boundaries.py::test_the_documents_own_text_is_closed_off_and_the_last_word_is_ours, product/tests/test_ingest_boundaries.py::test_a_transcript_cannot_close_the_block_it_is_inside

1. The document is delivered inside clear bounds that mark it as content to read, never as commands to follow.
2. Untrusted document text is never concatenated into the instruction channel.
3. The bounds close, and the trusted instruction is restated after them, so the last words a model reads are not the document's.
4. A transcript that spells the closing bound itself cannot end the block early: the occurrence is defanged rather than passed through.
5. The frame is a versioned prompt file and is named in the recorded `prompt_version`, so what enclosed a document is recoverable from the reading it produced.

**Why it was contradicted, and what settled it:** the embedded text used to be appended behind a provenance hint with no closing bound, which left it in the last position the model reads — the strongest place an instruction can sit. Driving a 551-byte PDF through the reader showed why "it does not look like an instruction" is not something a person can check: a line in PDF text render mode 3 is painted with neither fill nor stroke, so it contributed **zero** dark pixels to the rendered page while extracting in full. Two things this document did not previously cover are now covered by clause 1: the **classify** pass reads embedded text too, so an injection could steer routing before extraction ran, and it is framed identically. Still uncovered: arithmetic backstops amounts, and nothing checks payee names, institution or account names against anything, so a rewritten name is caught by no gate.

### ING-72 — Deterministic verification is the reference monitor
**State:** enforced
**Code:** core/vivacore/verify/arithmetic.py:44, product/viva/ingest/statement_projector.py:202-209 (a statement that does not reconcile is held at `conflicted`, not posted)
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
**Code:** product/viva/ingest/raw_store.py:51 (`put`, capture before judgment), product/viva/ledger/events.py:271 (`read_recorded`), product/viva/ingest/brokerage_projector.py:98
**Test:** product/tests/test_pipeline.py::test_read_that_throws_is_recorded_not_orphaned, product/tests/test_raw_store.py::test_put_is_content_addressed

1. Every uploaded file is captured, encrypted and content-addressed before anything parses it.
2. Every model response is recorded verbatim with its model and prompt version, so an injection attempt is auditable afterwards.

### ING-75 — No provider SDK on the wire
**State:** enforced
**Code:** core/vivacore/models/anthropic_adapter.py:12, core/vivacore/models/openai_compat.py:21 (both call their provider over plain `httpx`)
**Test:** product/tests/test_docs_track_the_code.py::test_the_model_adapters_import_nothing_the_package_did_not_declare

1. A model adapter imports only the standard library, a dependency the package declares, and the project's own code.
2. No provider SDK and no multi-provider wrapper sits between a bank statement and the wire.

### ING-76 — One key, derived from one vaultphrase, never stored in the vault
**State:** enforced
**Code:** product/viva/crypto.py:8-19, :30 (`VERSION` names the algorithm and the KDF), product/viva/ingest/raw_store.py:56
**Test:** product/tests/test_raw_store.py::test_nothing_readable_at_rest, product/tests/test_raw_store.py::test_wrong_passphrase_rejected, product/tests/test_raw_store.py::test_tampered_blob_fails

1. Data at rest is sealed with a versioned authenticated envelope; tampering is detected on open, never silently accepted.
2. The key is derived from the owner's vaultphrase with a memory-hard KDF and is never stored in the vault. The desktop application stores the default vault's directory and vaultphrase only in macOS Keychain or Windows Credential Manager, never in browser storage, ordinary configuration, or diagnostics.
3. There is no second wrap of the key and no recovery phrase.

### ING-77 — Where a document is sent is decided by this process, not by its surroundings
**State:** enforced
**Code:** product/viva/env.py:42 (`env_file`), product/viva/env.py:61 (`load_dotenv`), core/vivacore/models/anthropic_adapter.py:75 (`trust_env=False`)
**Test:** product/tests/test_ingest_boundaries.py::test_a_dotenv_in_the_working_directory_is_not_configuration, product/tests/test_ingest_boundaries.py::test_the_same_file_is_chosen_whatever_the_working_directory

1. Configuration is read from a fixed search order — an explicitly named file, the user's config home, then the installed package and its source tree — derived from the code's own location and the user's home, never from the working directory.
2. Which file configured a run is logged, because it decides where documents are sent.
3. An outbound call does not trust the ambient environment, so a proxy variable cannot put a third party between this process and the model.

**Why:** `load_dotenv` defaulted to the relative path `.env`, and 25 entry points called it with no argument. A file left in a cloned repository, an unpacked starter kit or a shared vault directory was therefore configuration: it could set the model base URL and `HTTPS_PROXY`, and every page image of every statement would be posted to a host of its author's choosing with the real API key in the header — with no prompt, no warning, and no line naming the file or the host. Both routes were live: the base URL is read from the environment, and `httpx` trusts `HTTPS_PROXY` by default, which reroutes even the hardcoded Anthropic URL.

### ING-78 — A document may not cost unbounded work to read
**State:** enforced
**Code:** product/viva/ingest/reader.py:41 (the limits), product/viva/ingest/reader.py:46 (`_render_and_read_text`)
**Test:** product/tests/test_ingest_boundaries.py::test_a_page_larger_than_any_statement_is_rendered_within_the_cap, product/tests/test_ingest_boundaries.py::test_too_many_pages_is_refused_rather_than_partly_read, product/tests/test_ingest_boundaries.py::test_a_file_over_the_byte_limit_never_reaches_the_parser

1. Page count, file size and rendered page geometry are each bounded before the work is done, and the render scale is clamped before a bitmap is allocated rather than after one exists.
2. Every document and page handle is closed on the way out, including when reading raises.
3. Exceeding a limit refuses the document whole and parks it with the limit named. A prefix is never read: a statement posted over a subset of its own pages would reconcile against nothing and be graded like any other.

**Why:** page *size* is not bounded by file size. A 263-byte PDF may declare the largest MediaBox the format allows, which at the render scale is a 28,800px square and 3.3 GB of bitmap; a 448 KB file may declare 5,000 pages, whose renders were all retained in one list. The process that runs out of memory is the one holding the vault key. `bench/vivabench/corpus.py` already capped its longest edge and closed its handles; the product copy had done neither.

## Why

Trust is the whole product, so each threat is classified by whether its worst
case is **absorbing** — a leak of decryptable financial data, or a silently
corrupted ledger the person believes — or merely **a bad day**: a crash, or a
wrong figure verification catches and surfaces. Ruin threats dominate the design
budget regardless of probability; bad-day threats are handled proportionately.
The goal of every control here is to convert a ruin path into a bad-day path.

Against a **device thief**, vault contents remain ciphertext and the vaultphrase
is protected by macOS Keychain or Windows Credential Manager. This protection
therefore inherits the operating system account's authentication and credential-
store security; theft of an already-unlocked user session is not equivalent to
theft of a powered-off device. Against **malware running as the user while the app is unlocked**, no
local-first application can fully protect data in memory — this is the hardest
residual and it is documented rather than pretended away. The mitigations are to
keep the credential out of browser storage, logs, and ordinary files, use OS
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

Key custody is where honesty costs something. The desktop now protects the
default vault's vaultphrase with macOS Keychain or Windows Credential Manager,
which provides automatic opening on that device. This is not a second portable
wrap and is not a recovery phrase: access on a different device still requires
the vaultphrase. If both the device-protected credential and the owner's copy of
the vaultphrase are lost, the vault remains unrecoverable.

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
- Portable key recovery: the protected device credential provides convenience on one device, but no offline recovery phrase or cross-device recovery path exists.
- The chain head is not anchored to any external timestamp, so the tamper-evident log's value as the malware backstop rests on the chain alone.
- Nothing tests that the extraction call is toolless; it is true by the shape of the interface and unchecked by the build.

## Sources

- [Zylos: Indirect prompt injection — state of the art](https://zylos.ai/research/2026-04-12-indirect-prompt-injection-defenses-agents-untrusted-content/)
- [Defending against indirect prompt injection with spotlighting (CEUR)](https://ceur-ws.org/Vol-3920/paper03.pdf)
- [CaMeL / out-of-band defenses — adaptive evaluation (arXiv)](https://arxiv.org/html/2606.26479v1)
- [IPIGuard: tool-dependency-graph defense (arXiv)](https://arxiv.org/pdf/2508.15310)
- [Unit 42: web-based indirect prompt injection in the wild](https://unit42.paloaltonetworks.com/ai-agent-prompt-injection/)
