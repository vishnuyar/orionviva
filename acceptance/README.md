# OrionViva user acceptance suite

This directory is the maintained product-level acceptance contract. It tells a
human tester or an AI product tester what to do, what to observe, and what
constitutes a pass without requiring knowledge of OrionViva's implementation.

The suite complements automated unit and integration tests. It exercises the
installed desktop application as a user would, including the boundaries that
are difficult to prove below the interface: persistence across restarts,
keyboard access, useful failure states, evidence navigation, and a private
multi-document financial picture.

## Safety boundary

Commit test instructions, synthetic fixtures, safe manifests, and blank report
templates. Never commit:

- real financial documents or values copied from them;
- vaults, vaultphrases, credentials, API keys, or model-provider secrets;
- screenshots containing personal information;
- filled private-run manifests or raw/generated test reports;
- institution, merchant, employer, account, or person names learned from a
  private run.

The repository ignore rules cover common financial files and local run output,
but the tester remains responsible for inspecting every proposed commit.

## Suite map

- [Test catalog](scenarios/README.md) — ordered test inventory and result rules.
- [Lifecycle and onboarding](scenarios/vault-lifecycle.md) — first launch,
  create/open, remembered default, switching, restart, and recovery.
- [Document import](scenarios/document-import.md) — selection, progress,
  duplicate handling, unsupported files, and privacy.
- [Financial picture](scenarios/financial-picture.md) — accounts, periods,
  transactions, statements, figures, and consistency.
- [Evidence and trust](scenarios/evidence-and-trust.md) — provenance,
  uncertainty, corrections, outbound activity, and actionable destinations.
- [Review, plans, and Ask Viva](scenarios/guidance.md) — review queue, plans,
  cited answers, refusals, and model boundaries.
- [Accessibility and resilience](scenarios/accessibility-and-resilience.md) —
  keyboard operation, understandable status, failure recovery, and restart.
- [Private-run manifest example](manifests/private-19-document.example.yaml) —
  safe role labels for a local set of unknown documents.
- [Acceptance report template](templates/acceptance-report.md) — a scrubbed
  decision record.
- [Synthetic fixture guidance](fixtures/synthetic/README.md) — requirements for
  future committed test inputs.
- [Suite maintenance](MAINTENANCE.md) — adding, changing, retiring, and reviewing
  tests.

## How to run

1. Install a release build using the [installation guide](../docs/installation-guide.md).
   Test a packaged application, not a development web preview.
2. Start from the prerequisite named by each scenario. Do not reuse an old
   vault unless the scenario explicitly requires retained state.
3. Run the baseline scenarios in the catalog on each release platform in scope.
4. For a private-data run, copy the example manifest outside the repository,
   map each local document to an anonymous role, and keep the completed copy
   private. The tester should discover document type and meaning through the
   product rather than through filenames or an answer key.
5. Record only pass/fail/block status and sanitized observations in a copy of
   the report template. A blocker is an unmet prerequisite, not a product
   failure.
6. Stop a private run immediately if sensitive data appears outside the
   application, expected local folders, or an explicitly approved model call.

Use a fresh report for every tested build and platform. Do not combine passing
moments from different runs into one pass.

