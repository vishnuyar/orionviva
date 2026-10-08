# Acceptance test catalog

Run tests in the order below unless a focused regression run is requested.
Each detailed scenario includes its prerequisites, actions, and pass condition.

## Result vocabulary

- **Pass** — every stated outcome was observed in one continuous run.
- **Fail** — the application was available, but an expected outcome was absent,
  incorrect, inaccessible, misleading, or unsafe.
- **Blocked** — a prerequisite outside the behavior under test was unavailable.
  Name that prerequisite in the report. If OrionViva itself prevented the
  prerequisite, record that earlier product behavior as a failure; do not use
  `Blocked` to hide it.
- **Not run** — the test was intentionally outside this run's scope.

Record the first point of divergence. A transient correct screen followed by a
wrong final state is a failure. Refreshing, reopening a vault, or restarting may
be used only when the scenario instructs the tester to do so.

## Baseline inventory

| Order | Tests | Purpose |
|---|---|---|
| 1 | [`VAULT-001`–`VAULT-008`](vault-lifecycle.md) | Establish, remember, reopen, switch, and safely recover vault state. |
| 2 | [`IMPORT-001`–`IMPORT-007`](document-import.md) | Add unknown documents without loss, leakage, or misleading success. |
| 3 | [`PICTURE-001`–`PICTURE-008`](financial-picture.md) | Verify that the durable financial picture remains visible and internally consistent. |
| 4 | [`TRUST-001`–`TRUST-007`](evidence-and-trust.md) | Trace figures to evidence and inspect uncertainty and privacy boundaries. |
| 5 | [`GUIDE-001`–`GUIDE-006`](guidance.md) | Exercise Review, Plans, and Ask Viva without unsupported claims. |
| 6 | [`ACCESS-001`–`ACCESS-004`](accessibility-and-resilience.md) | Operate essential paths with the keyboard and understandable labels. |
| 7 | [`RESILIENCE-001`–`RESILIENCE-005`](accessibility-and-resilience.md) | Confirm failures preserve context or provide explicit recovery. |
| 8 | [`GUIDE-007`–`GUIDE-026`](financial-capabilities.md) | Exercise eight analysis, six measurement/projection and three scenario families, numerical sources, useful limits and browser receipts. |

The private 19-document run uses the same tests. It is not a separate standard
with weaker pass conditions.

The baseline inventory contains 45 unchanged tests. The additive financial
capability inventory adds 20 checks: 17 families and three cross-family checks.
The active human inventory contains 65 tests. A release report must list every test
in scope as Pass, Fail, Blocked, or Not run; omitted rows are not passes.

These 65 human checks are separate from the mandatory 123 hosted qualification cases (73 canonical plus 50 supplemental) and from automated browser coverage. New declarations remain unverified until observed on the named candidate. See [retained real-document continuation](../real-document-test.md).
