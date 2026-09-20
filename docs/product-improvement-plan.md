# Product reliability and usability implementation plan

**Approved:** by the owner in this task. **Status:** implementation complete locally;
release evidence remains incomplete.
**Branch:** `codex/product-reliability-usability`.

## Authorization and context-refresh instructions

The owner approved the preceding assessment: “I approve this plan. I would like
to prepare a document which will be useful for implementing what has been
suggested so that we do not lose track of this when context is refreshed and then
go ahead and implement them”. The owner subsequently instructed the coordinating
agent to orchestrate implementation through agents.

On refresh, read this document, `WORKFLOW.md`, `docs/TODO.md`, and the current
diff. Start with the remaining-evidence checklist below; update the execution register
with actual evidence and the next action before handing off. Implementation
within the approved scope does not need renewed approval. Public issues,
commits, pushes, releases, private-vault access, paid model calls, and changed
financial or privacy promises are not implied by this authorization.

Preserve unrelated starting edits in `docs/eval-harness-design.md`,
`docs/implementation-roadmap.md`, `product/tests/test_honesty_harness.py`, and
`product/viva/honesty.py`. Do not include them in this work's staging.

## Decision and purpose

Keep React, Tauri, Python, the encrypted local vault, the append-only financial
history, deterministic verification, and the existing frontend/backend boundary.
Improve them incrementally. There is no evidence justifying a complete rewrite.

The frontend is what a person operates. The backend is the local engine that
captures documents, verifies information, and stores financial history. The
native host connects them. Success means easier first use, understandable
failures, safe restart, and changes that are easier to maintain.

## Starting evidence and limits

The assessment ran 906 frontend tests and 113 focused backend tests, all passing,
plus the frontend build, architecture check, and style check. Passing style
checks still permit recorded legacy values. A bundle-size warning is not a
measured performance defect. No installed-app usability or security audit was
performed.

Code inspected at the starting revision `e04bf416`:

- `desktop/src/app/useSurfaceSession.ts`: 1,055 lines coordinating vault opening,
  reads, jobs, documents, questions, corrections, settings, and plans.
- `desktop/src/app/App.tsx` and `features/trust/Trust.tsx`: setup exposes vault
  directories, exact model identifiers, service addresses, locale codes, and keys.
- `product/viva/ledger/store.py`: unconditional Unix-only `fcntl` import and
  locks. Windows had not been executed. The disposable read store has a separate
  platform-aware lock.
- `product/viva/desktop_bridge/jobs.py`: interrupted receipts become failed;
  work does not automatically resume.
- `.github/workflows/quality.yml` and `release-desktop.yml`: native builds and
  packaged-sidecar validation exist, but no explicit native Rust test command.

## Invariants and scope fence

- Preserve evidence, dates, currency, and uncertainty on financial results.
- Models propose; deterministic code checks arithmetic.
- No automatic paid retries or new startup network calls.
- Reconcile uncertain outcomes against committed vault state before reporting
  success. Retrying must not duplicate financial entries.
- Preserve encrypted files and event formats; no storage migration as a side
  effect of reorganizing coordination code.
- Keep one authoritative active-vault identity and stale-response protection.
- Preserve keyboard access, focus restoration, consent, sample/private separation,
  and advanced configuration. New interface text must respect persona boundaries.
- Use synthetic data. Report unavailable OS, native-webview, and human checks
  honestly; local compilation does not prove cross-platform support.
- No new cloud service, bank connection, microservices, framework replacement,
  autonomous financial actions, or changed accounting meaning.

## Milestones and acceptance criteria

### 1. Baseline everyday journeys

Reuse current tests and the independent evaluator for create/open, import,
evidence inspection, correction, asking, backup/restore, and restart. Record
repeatable timing where available; do not substitute browser-unit-test timing for
native startup measurements.

**Complete when:** the journey table and baseline execution evidence are recorded,
with installed-app and human-observer gaps called out.

### 2. Portability and release reliability

Make ledger locking portable without weakening cross-process exclusion or
authenticated commit/recovery. Preserve Unix interoperability. Consider Windows
byte-range locks, newline conversion, and flush behavior. Check contention,
release on exceptions, concurrent writers, reopen, and interrupted writes.

Run native-host tests automatically and add target-specific storage checks. Keep
signed release and clean installed startup/recovery distinct from packaged-sidecar
validation. Reuse existing release infrastructure.

**Complete locally when:** regressions and native tests pass and executable
platform gates exist. Platform release proof remains outstanding until actual
target jobs and installed applications have run.

### 3. Frontend coordination

Separate coherent responsibilities in the large session hook into explicit units:
vault opening, reads/refresh, job observation, and feature actions. Keep one
session reducer and explicit shared request/source generations. Avoid introducing
a second state store or an unnecessary dependency.

**Complete when:** boundaries are understandable and existing session/screen tests
pass; late responses, switches, retry, and cancellation cannot update the wrong
vault. Smaller files alone do not prove an improvement.

### 4. First use and first statement

Make create/open choices, folder selection, privacy explanation, model setup,
and the first import easier to understand. Keep advanced settings available
through clear labels and progressive disclosure. Never silently select a model,
send data, change credential storage, or bypass confirmation. Retain ordinary
navigation for existing populated vaults.

**Complete locally when:** empty/loading/failure/success states and keyboard/focus
behavior pass tests and fresh interface review. An installed walkthrough and
unassisted representative-user trial remain separate evidence requirements.

### 5. Safe interrupted document recovery

Inspect actual capture/commit boundaries. Encrypted capture and a job receipt do
not prove whether financial posting completed. Reconcile ledger state, retain
the encrypted original, make potential paid retries explicit, and never silently
restart cancelled work or replay a generic financial mutation.

Reuse existing reread/maintenance capabilities where possible. A deterministic
rescan is not a model reread. Durable recovery metadata must not leak source
paths, content, credentials, or financial values. Any new persisted/bridge field
requires matching version/contract/consumer documentation and tests.

**Complete when:** interruptions before capture, after capture, and after commit
produce honest results; an explicit retry can use captured encrypted bytes
without the source file; retry cannot duplicate postings or bypass consent.

### 6. Measurement and final evidence

Run existing larger synthetic-vault checks; report first useful content,
navigation, import/recovery, and correctness where those measures exist. Fix
measured regressions within scope; do not invent a replacement project.

**Complete when:** affected full suites, independent review, and acceptance are
recorded, with local results distinguished from target OS, real-data, and human
validation still required.

## Journey and evidence register

| Journey | Existing checks to use | Additional proof |
| --- | --- | --- |
| Open/create | `App.vault.test.tsx`, `test_desktop_bridge_vault.py` | Installed fresh start, bad passphrase, manual fallback |
| Add statement | `App.documents.test.tsx`, `test_document_actions.py` | Interrupt capture/read/commit; clarity of first use |
| Inspect evidence | `useEvidenceDialog.test.tsx`, proof/component tests | Native keyboard/focus walkthrough |
| Correct transaction | Activity and bridge action tests | Preserve settled financial semantics |
| Ask | Conversation/session tests; acceptance pack | No new network permission; private truth needs Witness |
| Backup/restore | `test_vault_transfer.py` | Reopen restored vault on a clean installed target |
| Restart | Native-host, job registry, event-store tests | Termination at documented commit boundaries |

## Agent coordination and verification

The orchestrator owns this document, integration, scope, and final evidence.
Implementation agents own separate file sets. Fresh agents review rather than
grade changes they wrote. Interface changes receive an independent craft and
accessibility review. Run full affected suites, architecture/style/build checks,
native tests, privacy scans, and the independent evaluator. Demonstrate new gates
rejecting counterexamples. Never change evaluator assertions to turn a failure
green.

Preflight was ready: 45 maintained human scenarios, 11 declared evaluator cases;
their mapping is not verified. Passing 11 does not mean all 45 are automated.

```sh
python3 .codex/skills/orionviva-acceptance-repair/scripts/repair_loop.py preflight
python3 .codex/skills/orionviva-acceptance-repair/scripts/repair_loop.py run --mode working-tree
PYTHONPATH=.:product:core:merchant:bench .venv/bin/python -m pytest product core merchant bench -q
# From desktop/:
npm test
npm run build
npm run check:architecture
npm run check:styles
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

## Execution register

| Milestone | Status | Evidence / next action |
| --- | --- | --- |
| 1. Baseline | Recorded with explicit gaps | Original revision: ten declared cases have passing evidence across the full run and corrected browser-tool run; signed/clean-target compatibility remains incomplete |
| 2. Reliability | Implemented and verified locally | Portable locking/LF writes/durable head; three-OS quality matrix; native test gates; targeted storage checks and fresh packaged Mac checks passed |
| 3. Coordination | Implemented and independently reviewed | Single reducer with lifecycle, reads, jobs, intake and action hooks; late file-picker and old drop callbacks reproduced and fixed before upload |
| 4. First use | Implemented and independently reviewed | Explicit open/create, first-statement guide and model disclosure; settings remain reachable when Trust fails; final frontend suite: 923 passed |
| 5. Recovery | Implemented within bounded scope | Explicit encrypted-original retry before posting; partial-write refusal, consent, concurrency, cancellation and focus checks passed |
| 6. Final evidence | Local checks recorded; release gaps remain | Python suite result and corrected contract retest below; packaged tests pass; independent evaluator remains acceptance_gap |

Local implementation is complete. This is not a signed release or proof that all
target operating systems work. Changes are staged for evaluator visibility but
uncommitted; the four unrelated starting edits remain unstaged.

### Independent review findings so far

- Interface review exposed hidden settings on failed Trust reads, indistinguishable
  recovery attempts, lost focus on retry completion and missing accessible disabled
  explanations. All were repaired and independently checked: 204 focused tests
  passed. Import references identify actions without retaining source paths.
  Native assistive-technology validation remains external evidence.
- Reliability review: 92 focused platform/storage/release tests and 17 native
  tests passed on macOS. A workflow guard initially accepted a command followed
  by `|| true`; builder strengthened it to require the expected standalone
  command and reject failure suppression and masking shells. Thirty-six mutation
  cases now exercise the three protected steps; independent recheck passed and
  the original suppression counterexample is rejected.
- Independent verifier reproduced two stale-intake mutations with delayed file
  picker and obsolete drop callbacks, then confirmed both fixes and a normal-upload
  positive control. Recovery audit found no remaining actionable backend defect.

### Initial acceptance attempt

`repair_loop.py run --mode working-tree` produced an `acceptance_gap`, not a
pass or a deterministic product failure. All 11 declared cases were incomplete
and no deterministic oracles ran. Evidence:
`runs/acceptance-repair/20260920-135749-working-tree-e04bf416009f/trace.report.json`.
Agent edits were concurrent with this attempt; newly created untracked modules
also make later snapshot attempts ineligible until reviewed and staged. This is
not a valid before/after performance baseline. Rerun against a frozen integrated
snapshot after all agent edits are complete. The evaluator also requires native
application/artifact and clean-target evidence unavailable from source tests.

### Implementation ownership

- `backend_reliability`: event-store platform operations, regression tests, and
  quality/release workflow gates. Additional verified portability issue: the
  authenticated head's POSIX directory-sync code needs a Windows equivalent.
- `frontend_coordination`: session coordination hook and extracted modules;
  retain source/generation guards, reducer, and public control interface.
- `first_use`: App, Trust/Statements presentation, corresponding tests/styles;
  preserve consent and backend truth. Does not implement recovery.
- Orchestrator: integration, this register, acceptance execution, subsequent
  recovery assignment, and fresh reviews.

`docs/TODO.md` is locally ignored; it contains a convenience pointer. The tracked
reading-guide link and this tracked document are the durable handoff.

### Isolated original-version baseline

The original revision was checked out read-only in intent at
`/private/tmp/orionviva-improvement-baseline` (a disposable detached worktree).
The evaluator needed access to its own `.targets` bookkeeping outside the product
sandbox; after authorized execution, the report at
`runs/acceptance-repair/improvement-original-baseline-authorized/trace.report.json`
identifies the exact original revision without concurrent agent edits.

Five declared cases passed: obligation actions, the synthetic document journey,
catalog behavior, synthetic model-quality/recovery, and performance ceilings.
Five browser cases produced no browser report, and the compatibility case lacked
complete native/signed-target evidence. No deterministic product failure was
reported; the complete-pack classification remains `acceptance_gap`.

Synthetic performance baseline (three samples per load, on this Mac; this is
engine measurement, not native time-to-first-screen):

| Transactions | Median vault open | Median Overview read | Median Activity read |
| ---: | ---: | ---: | ---: |
| 10 | 707.131 ms | 1.436 ms | 1.095 ms |
| 100 | 708.144 ms | 7.866 ms | 26.351 ms |
| 1,000 | 708.022 ms | 74.863 ms | 258.037 ms |

Peak process RSS was 85,032,960 bytes. These are a baseline to compare against,
not a claim that the current changes improved speed.

Native validation caveat: the initial Rust run reported 17 passing tests, but
one existing packaged slow-vault test returns early without opt-in artifact
variables. Only 16 exercised ordinary tests in that initial run. The later fresh
packaged-app synthetic check exercised the opt-in test successfully, as recorded
in the verification ledger below.

The browser baseline gap was diagnosed as a local tool mismatch: system
ChromeDriver 139 could not start installed Chrome 153. A matching official
ChromeDriver 153.0.8010.52 was downloaded only into
`/private/tmp/orionviva-browser-driver/chromedriver-mac-arm64/chromedriver`.
With `EVALUATOR_CHROMEDRIVER` pointing there, the original revision passed all five
browser journeys. Their separate reports are under
`runs/acceptance-repair/baseline-browser-matched-driver/`. The original-version
baseline now has passing evidence for ten declared cases across those runs;
compatibility still lacks complete signed/clean-target evidence. No evaluator
assertion or product behavior was changed to fix this tooling mismatch.

Do not set `ORIONVIVA_NATIVE_APP_BINARY` merely to make the compatibility case
green: its generic smoke launcher would start the real application, which may
open the device's remembered private vault. Use the synthetic packaged-sidecar
tests until a deliberately isolated native user session is available.

## Implementation handoff

### What changed, in everyday terms

1. The screen and the local engine keep their existing foundations. The large
   screen coordinator is split into focused parts, making future repairs easier
   to contain. One shared session still decides which vault is active.
2. Creating a vault, opening one and adding a first statement have clearer
   guidance. Model connection details are available in an expandable settings
   section, including when another Trust read fails.
3. An interrupted statement can offer **Read saved original again**. It uses the
   encrypted original and requires a deliberate choice, because the configured
   reader may receive the document and charge again. The backend checks financial
   history under a document lock before reading. It refuses uncertain partial
   postings rather than risking duplicate money entries.
4. The ledger now uses operating-system-appropriate locking and durable file
   replacement. Automated workflows check storage and the native host on Mac,
   Windows and Linux. A configured workflow is not yet evidence of a successful
   run on those other systems.

### Recovery boundaries to preserve

Recovery is available for retained failed document jobs whose encrypted capture
and pre-posting reading stage were saved. Hard termination during reading,
source-file deletion and reopen are covered. Capture interruption before binding,
legacy or evicted receipts, cancelled jobs, corrupt originals, settling receipts
and arbitrary partial financial writes are not generally resumable.

The job list offers candidates without replaying the ledger or requiring SQL to
be healthy. The explicit recovery action authenticates the original and checks
ledger eligibility before invoking the reader. Newer receipts hide older offers;
a direct API caller may explicitly authorize an older still-eligible receipt,
which still undergoes all checks and does not silently restart a cancelled job.
Protocol 2.1 and persona pack-v45 record this additive behavior. Native transport
must never transparently replay the recovery mutation after an uncertain timeout.

### Verification ledger

| Check | Result and limits |
| --- | --- |
| Complete frontend | 923 tests passed across 54 files; build, architecture and style checks passed |
| Complete Python product/core/merchant/bench run | 3,295 passed, 2 skipped, 1 failed; sole failure was an omitted recovery payload entry in the integration test contract |
| Corrected Python integration contract | Test-only repair added exact fields, explicit consent, unknown/missing field refusal and no-transparent-replay checks; 103 affected tests passed, including 8 native contract tests independently rerun. Do not describe the preceding full run as uninterrupted green |
| Date-sensitive baseline test | Original revision reproduced the goal-binding failure as the calendar advanced; the existing test clock was fixed without changing financial calculations |
| Native Rust | 17 reported passing; 16 ordinary tests exercised, plus an opt-in test separately exercised by the packaged check below |
| Fresh macOS package | `.app` built successfully; packaged backend handshake, all ten surfaces, spending/review contracts and unknown-operation rejection passed |
| Packaged crash/encryption/timeout | Both opt-in tests passed, including real packaged slow-vault timeout. Disposable synthetic vaults only; the GUI and remembered private vault were never opened |
| Documentation | 23 consistency checks passed after handoff reconciliation; final report pointers are evidence-only edits |
| Privacy | All 60 staged implementation files passed 12 denylist patterns, including the final test-only contract addition |

The whole-repository privacy scan found 15 matches in the untouched
`merchant/merchantcore/data/catalog.json`. Its bytes match the starting revision.
No matching names or values are copied here. This pre-existing issue remains a
release blocker; the changed-file pass does not make the whole repository clean.
Numeric-shape review of staged files found synthetic contract/test fixtures and
documented line-count/performance measurements.

### Performance comparison

Standalone final synthetic measurement passed every existing ceiling. Report:
`runs/acceptance-repair/product-improvement-performance-diagnostic/performance-baseline.report.json`.
These are three-sample engine measurements on this Mac, not native startup or a
controlled performance experiment. They support no material observed change in
these paths, not a speedup claim.

| Transactions | Original / final median open | Original / final Overview | Original / final Activity |
| ---: | ---: | ---: | ---: |
| 10 | 707.131 / 706.664 ms | 1.436 / 1.388 ms | 1.095 / 1.082 ms |
| 100 | 708.144 / 705.201 ms | 7.866 / 7.864 ms | 26.351 / 26.131 ms |
| 1,000 | 708.022 / 708.739 ms | 74.863 / 74.950 ms | 258.037 / 258.670 ms |

Final peak RSS was 87,375,872 bytes, against an existing ceiling of 134,217,728.
Native time-to-first-content, large import duration and unassisted-user success
remain unmeasured. The existing bundle-size warning is not evidence of a slowdown.

### Independent acceptance and remaining evidence

The first integrated complete run at
`runs/acceptance-repair/product-improvement-final/trace.report.json` recorded eight
passes and three incomplete cases, with no failed deterministic oracle. Standalone
performance subsequently passed. Catalog diagnosis identified a hard-coded 2.0
handshake expectation in the independent evaluator, while the additive product
protocol is now 2.1. The source release-boundary diagnostic also rejected its UI
proof packet because its working-tree digest did not match. Neither evaluator
assertion nor packet was edited to obtain a pass.

The subsequent complete run at
`runs/acceptance-repair/product-improvement-final-frozen/trace.report.json` again
recorded eight passes and three incomplete cases, with no failed oracle.
Performance passed in that run. Obligation actions stalled in temporary-source
preparation (`git apply`), before product execution; the stalled child was stopped
and the runner completed with that lane incomplete. The preceding complete run
had passed obligation actions. Catalog and compatibility remained incomplete for
the documented reasons. Do not combine those reports into a single complete pass.

Final screenshot inspection also found oversized new radio controls inherited
from text-field CSS. The bounded style correction restores native 20px radios
while preserving the full 44px label target. Existing keyboard/vault tests (22),
build and style checks passed afterward. Desktop and 500px-wide screenshots
were independently reviewed; the controls measure 20px and labels retain at
least 44px hit areas. Evidence is under `runs/product-improvement/visual/`.
All five independent browser journeys passed again on the final CSS at
`runs/acceptance-repair/product-improvement-final-browser/`. The local macOS app
was rebuilt successfully with that correction. These checks are separate from
the earlier complete evaluator snapshots, not a complete release pass.

Remaining work before release:

- [ ] Independently maintain/review the evaluator's protocol expectation and
  current-revision UI proof, then obtain one complete passing report without
  temporary-source preparation failures.
- [ ] Resolve the existing catalog privacy findings in their own reviewed scope.
- [ ] Execute the added Windows/Linux jobs and actual supported release targets.
- [ ] Verify signed clean installation, launch, update/rollback, uninstall and
  vault preservation using isolated native environments.
- [ ] Run native keyboard/screen-reader checks and a first-use walkthrough with a
  representative person. No real-vault or paid-model run was authorized here.

Do not rebuild the frameworks or repeat completed implementation on a context
refresh. Continue these evidence items, preserving the recovery boundary above.
No commit, push, release or public issue was made.
