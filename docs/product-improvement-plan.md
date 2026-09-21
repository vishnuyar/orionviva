# Product reliability and usability implementation plan

**Approved:** by the owner in this task. **Status:** implementation complete locally;
release evidence remains incomplete.
**Integration branch:** `main`; original work branch: `codex/product-reliability-usability`.

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
target operating systems work. The initial implementation is committed as
`6737707`; the four unrelated starting edits remain outside that commit.

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
| Complete Python product/core/merchant/bench run | Exact implementation commit `6737707`: 3,290 passed, 3 skipped in a clean checkout. Earlier working-tree run had one omitted test-contract entry, subsequently repaired |
| Corrected Python integration contract | Test-only repair added exact fields, explicit consent, unknown/missing field refusal and no-transparent-replay checks; 103 affected tests passed, including 8 native contract tests independently rerun. Do not describe the preceding full run as uninterrupted green |
| Date-sensitive baseline test | Original revision reproduced the goal-binding failure as the calendar advanced; the existing test clock was fixed without changing financial calculations |
| Native Rust | 17 reported passing; 16 ordinary tests exercised, plus an opt-in test separately exercised by the packaged check below |
| Fresh macOS package | `.app` built successfully; packaged backend handshake, all ten surfaces, spending/review contracts and unknown-operation rejection passed |
| Packaged crash/encryption/timeout | Both opt-in tests passed, including real packaged slow-vault timeout. Disposable synthetic vaults only; the GUI and remembered private vault were never opened |
| Documentation | 23 consistency checks passed after handoff reconciliation; final report pointers are evidence-only edits |
| Privacy | All 60 staged implementation files passed 12 denylist patterns, including the final test-only contract addition |

The initial whole-repository privacy scan found 15 matches in the then-untouched
`merchant/merchantcore/data/catalog.json`. Its bytes match the starting revision.
No matching names or values are copied here. The subsequent authorized cleanup
below removes the three matching seed records; the full current-tree scan is now
clean. Historical commits still contain the former catalog.
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

- [x] Independently maintain/review the evaluator's protocol expectation and
  current-revision UI source proof.
- [ ] Obtain one complete passing acceptance report, including installed and
  native compatibility evidence on supported hosts.
- [x] Resolve current-tree catalog privacy findings: exactly three complete seed
  records removed, 132 retained unchanged; full-tree scan clean. Historical
  distribution/history are not erased by this cleanup.
- [ ] Execute the added Windows/Linux jobs and actual supported release targets.
- [ ] Verify signed clean installation, launch, update/rollback, uninstall and
  vault preservation using isolated native environments.
- [ ] Run native keyboard/screen-reader checks and a first-use walkthrough with a
  representative person. No real-vault or paid-model run was authorized here.

Do not rebuild the frameworks or repeat completed implementation on a context
refresh. Continue these evidence items, preserving the recovery boundary above.
The initial implementation was committed at the owner's explicit request. No push,
release or public issue was made.

## Authorized continuation after the implementation commit

The owner instructed: “commit whatever has been done and continue with the rest”.
Commit `6737707` contains the 60 reviewed
implementation files. The privacy hook flagged two hexadecimal validation
alphabets and an unchanged pack-v44 content hash appearing on a comma-only changed
line. A separate verifier recomputed the actual hash, checked its bytes against
HEAD, ran 30 version tests and scanned every staged file against all private
patterns. After that independent evidence, the hook's documented synthetic-hit
override was approved and the requested commit succeeded. The hook was not altered.

The catalog follow-up removes exactly three complete flagged seed records. A
separate audit established they came from the original seed introduction, when
the private-name check had been unavailable. Public/business classification does
not override an explicit privacy exclusion. All 132 other records and metadata
remain unchanged; taxonomy and installation-learned data are untouched. Removed
matches return to the existing unknown/local-enrichment behavior when no local
record exists. The builder ran 149 merchant and 87 related product tests. The
orchestrator independently verified exact preservation and the now-clean full-tree
privacy scan. No private matching name is stored in this record.

Evaluator maintenance is separate from changing financial expectations: requests
remain at protocol 2.0; only reviewed 2.0/2.1 responses are admitted. Unknown,
malformed or major-incompatible versions remain rejected. Four added regression
tests are wired into the evaluator's check command. No catalog truth assertion
was removed. A separate Interface Designer reviewed the seven existing UI cases
and 46 unchanged assertions against the clean implementation commit, including
all source hashes. That approval is a source behavior contract only; it does not
prove native keyboard, assistive technology or signed installation.

Exact-commit Python verification passed from the clean disposable checkout
at `/private/tmp/orionviva-implementation-verified`, excluding the four unrelated
edits: 3,290 passed and 3 skipped. Two skips are opt-in packaged tests; the third
was the ignored local denylist not being present in the clean checkout. A separate
in-memory check applied all 12 local patterns to that exact commit's evaluation
key, with no matches or values emitted. The checkout remained clean. Full log:
`/private/tmp/orionviva-6737707-python-suite.log`.

The committed-revision acceptance run at
`runs/acceptance-repair/6737707-committed/trace.report.json` executed all 11 cases:
ten passed, none failed, and compatibility remained incomplete. Catalog protocol
compatibility is now proved through its real packaged path. The evaluator's own
checks passed 181 Node tests, four Python transport regressions, pack validation
and its distribution boundary. The source-only release-fence diagnostic correctly refused an additional Tauri
macro failure alongside the expected fence. The cause was a missing frontend
build in the disposable evaluator checkout: direct Cargo invocation does not run
Tauri CLI's frontend build step. The evaluator preparation fix builds the real
frontend and preserves strict rejection of unrelated compiler failures. The
actual integrated source check passed on the clean implementation commit; log:
`/private/tmp/orionviva-release-boundary-integrated.log`. This proves the source
release fence, not an installed release. Windows command construction is covered
by regression tests, but actual Windows execution remains outstanding.

At the preceding checkpoint, native GUI checks were withheld on this everyday
user account: although the test build used a separate keychain service, that
runner inherited user
configuration/environment and locates keyboard targets by a shared process name.
An interim hard guard blocked the native WebDriver configuration before target
reads or application launch. Independent review replaced a weak source-text test with
an executed configuration test that traps downstream work and catches a removed
guard. A candidate disposable profile/environment utility is tested on macOS; it
is not a completed isolated launcher. An isolated native profile and exact
runner-owned process binding are needed before those checks are safe. No private configuration, remembered vault or paid
model was accessed during this work. Native source-contract approval does not
close this runtime gap.

Follow-up scope: the catalog cleanup and this evidence register. Evaluator
maintenance lives on its own `codex/orionviva-recovery-compatibility` branch.

## Completion continuation

The owner explicitly requested that the orchestrator invoke agents and complete
the remaining plan. The preceding product follow-up is committed as `e6e3388`;
evaluator maintenance is committed separately as `617d162`. The final complete
run at `runs/acceptance-repair/e6e3388-final/trace.report.json` passed ten of eleven
cases, with no failed case. Its source compatibility checks passed; installed
compatibility remained incomplete. All 195 evaluator tests and four protocol
regressions passed before this continuation.

The remaining implementation is being carried through these bounded lanes:

- A native runner that owns the exact child process, supplies an isolated
  environment and profile, and binds input and WebDriver operations to that
  process. Fresh review has now approved the authenticated replacement;
  unowned launches and unavailable physical input still fail closed.
- Executable synthetic release-lifecycle checks and platform artifact
  verification, with same-artifact restart distinguished from actual two-version
  compatibility and operating-system installation.
- Accurate evidence collection: source tests cannot certify native dialogs or
  accessibility, and a supplied executable cannot bypass the isolated launcher.
- Independent verification, final affected suites and durable run instructions.

A read-only host audit found that native Accessibility/event-post authorization
is unavailable, no usable foreign-OS runner or VM is installed, and the Docker
daemon is unreachable. Signing tools exist, but their presence does not prove a
signed artifact. These observations do not prevent implementing and testing the
runners. They do prevent claiming physical native input, other-OS execution, or
signed clean installation from this machine alone. No representative human trial
has been performed by an agent or substituted with an automated walkthrough.

### Representative first-use protocol

Run this only with the reviewed installed build, a fresh synthetic profile and a
person who has not been coached through the interface. Record the exact revision,
artifact digest, operating system, and whether assistive technology was used.
Do not collect personal documents or provider credentials.

1. Ask the person to explore the sample and explain which information is fictional.
2. Ask them to create a new empty vault and find where a first statement is added.
3. Ask them to find the model settings and explain what may leave the computer
   before approving anything. Stop before any paid or private-data request.
4. With approved synthetic import fixtures, ask them to identify a failure and
   explain the difference between refreshing a result and paying to read it again.
5. Ask them to locate evidence, close it, and resume the previous task using their
   ordinary keyboard or assistive technology.

Record completion, hesitation, recovery, and any assistance given for each task;
do not invent a passing time limit or treat an assisted completion as unassisted.
The resulting observations are usability evidence, not deterministic financial
correctness. Missing observation remains an explicit release-evidence item.

### Release validation implementation and evidence

`scripts/validate_sidecar_lifecycle.py` now runs the packaged backend through
synthetic vault creation, candidate reopen, baseline rollback, application-byte
removal and baseline reinstall. Artifact hashes are checked before and after
execution. Subsequent opens must use the existing vault; they cannot quietly
create a new sample. Canonical encrypted events, authenticated head and saved
originals must stay unchanged. The release workflow requires a clearly labelled
same-artifact restart/removal check on each target before signing.

`scripts/verify_native_signature.py` invokes actual macOS signature, publisher,
Gatekeeper and stapled-notarization checks, or Windows Authenticode and expected
publisher checks. It rejects unsupported signature policies and protects the
input artifact from output-path collisions. `RELEASING.md` gives the commands and
distinguishes these checks from actual OS installation and human observation.

Fresh independent review passed 112 affected release tests. It reproduced a
queued-progress deadline bypass in the initial checker; the fix and regression
now reject that case. The orchestrator separately built packaged backends from
clean commits `6737707` and `e6e3388` and ran the real distinct-artifact lifecycle
successfully. Evidence is
`runs/product-improvement-continuation/clean-commit-sidecar-lifecycle.json`.
These are distinct commit artifacts with the same application release version,
not proof of a future schema migration or an operating-system installer.

Independent evaluator review also removed an alternate caller-supplied native
launch path. Source file-dialog and accessibility checks now retain their source
results but report native runtime evidence as unverified. Four independent
counterexamples rejected source/runtime conflation, concealed source failure,
and actual execution through the prohibited alternate launch path.

### Native continuation verification

The evaluator now launches a child it owns with an allowlisted environment,
private disposable profile, fresh compiled credential service and bundle identity,
and non-persistent WebKit storage. A current-run authenticated manifest binds the
exact binary, backend and prepared source. The request gateway checks the child's
executable, kernel start identity and listening socket before forwarding each
WebDriver request; physical input uses the same owned identity. Process-name
selection has been removed from this path. Cleanup waits for the owned process
group, including children that ignore graceful termination.

Independent review passed 26 safety tests and additional invalid-target probes.
An integration run found an early UI-contract ordering regression; restoring the
existing approval gate before helper preparation passed 27 focused tests and the
complete evaluator suite: 215 Node tests plus four protocol regressions. The
orchestrator also tightened compatibility verdict handling: actual failures may
not be hidden as incomplete evidence, and native pass flags cannot replace
missing source proof. Seven new counterexamples fail against the old classifier.

The actual isolated observation run on the clean `e6e3388` source reached stable,
actionable content in 4,475 ms. This is one debug/WebDriver measurement, not a
release performance claim. No physical input was dispatched. The session closed
and its prepared target was removed. Evidence:
`runs/product-improvement-continuation/native-observation/native-startup-observation.json`.
The current UI approval binds the clean working-tree digest, so this run used
`observe --working-tree` on a clean disposable checkout. A mismatched identity
mode was correctly rejected before the app was built or launched.

The full product suite passed 3,320 tests with three skips in a clean checkout
containing the release implementation and excluding the four unrelated edits.
The skips remain two opt-in packaged tests and the ignored local denylist absent
from a clean checkout; the real distinct-artifact lifecycle was exercised
separately. The final additional manual-CI wiring passed 64 independent scoped
checks, including eight refusal mutations. Documentation checks passed 23 tests.
Quality now supports manual, unsigned runs with privacy checking and lifecycle
reports on all three desktop operating systems. No remote job has been started.

### Remaining external execution requirements

- Grant native Accessibility/event-post authority before physical-input tests;
  the read-only helper currently refuses those operations. A request for the
  owner to enable Accessibility is pending in this task.
- Push the reviewed branch and execute the prepared Quality matrix to obtain
  real Windows/Linux/macOS job results. A public push still needs explicit
  authorization under `WORKFLOW.md`; local test results cannot substitute.
- Supply actual signed baseline/candidate installers and clean supported hosts,
  then verify install, first launch, update, rollback, uninstall and preserved
  vaults. No clean-host installer orchestration or signed matrix ingestion is
  implemented here; sidecar replacement and signature checks cover narrower
  scopes and must not be promoted into that evidence.
- Run the representative-person and native assistive-technology walkthroughs.
  An automated startup observation is not either of those trials.

Do not call the entire plan or release acceptance complete while these remain.
The native runner and release check implementations above are independently
reviewed; the remaining unavailable execution and installer infrastructure are
explicit continuation requirements rather than passing checkboxes.

## Owner-authorized branch integration

The owner subsequently instructed: “merge all of them to main and delete all the
branches”. This authorizes integration and branch cleanup; it does not establish
signed-release or human-observer evidence. The four previously unrelated files
were identified by the owner as honesty-branch work and saved in `d607707`.
Independent review found two scoring edge cases, repaired in `72a7f6a`: a refusal
cannot silently satisfy expected figures, and an empty structured answer needs
explicit delivery review. All 28 focused tests passed; seven regression cases
independently failed against the previous code. The combined histories meet at
merge commit `9c85c04`.

Actual Windows and Linux jobs exposed test-fixture portability defects. The
repair in `6df8bf8` preserves exact ledger bytes in header-tampering tests and
uses a supported offset only for mocked Windows locks on non-Windows hosts.
The production Windows offset and real process-lock tests remain unchanged.
Independent verification passed all 86 affected tests and reproduced both old
fixture failures. The corrected remote run is the Quality run for `6df8bf8`.

Both Linux and macOS desktop jobs completed successfully on that corrected run.
Windows passed the formerly failing storage checks, but the packaged sample
revealed a read-store publication failure. The direct synthetic startup check
added in `2f93331` reproduced Windows rejecting a flush of a read-only descriptor;
the repair opens only the writer-owned, unpublished database with write access
before flushing. Flush errors still propagate, descriptors still close, and
published readers remain read-only. All 74 affected publication and sample tests
passed. Two new regressions independently failed against the old code and passed
with the repair, including preservation of the previous generation on failure.
Do not call Windows validated until the repair passes the real target job.

The combined local suite passed 3,345 tests with two opt-in tests skipped. The
Linux full suite separately found a historical-query test depending on an
ambient installed merchant profile. The test-only repair in `21ab180` supplies
an explicit synthetic profile; all 28 affected tests passed with an empty profile
directory, and both byte-guard refusal cases still reject an independently
introduced guard bypass. These findings reinforce why local results do not
replace clean-host execution.

Remote privacy checking refuses to
run because the repository's `DENYLIST` secret is missing or empty. The local
full-tree check passed all 1,069 tracked files against 12 private patterns.
Uploading that private list requires separate permission; do not bypass the
remote gate or describe the overall workflow as green while it is unresolved.

Historical statements above about no push and pending merge authority describe
their earlier checkpoints. The owner has now authorized publication and cleanup.
Keep signed installation, physical accessibility and representative-person
evidence open even after the branch merge.
