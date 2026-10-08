# Maintaining the user acceptance suite

Acceptance scenarios are product contracts. Changes should be reviewed with
the same care as user-facing behavior.

## Test identity

Every test has a stable identifier such as `VAULT-001`. Do not reuse an
identifier after a test is retired. Wording may improve without changing the
identifier when the user intent and pass condition remain the same.

Use these families:

- `VAULT` — lifecycle, persistence, switching, and recovery;
- `IMPORT` — document selection, ingestion, and failure handling;
- `PICTURE` — accounts, transactions, statements, periods, and totals;
- `TRUST` — evidence, uncertainty, correction, privacy, and outbound activity;
- `GUIDE` — Review, Plans, and Ask Viva;
- `ACCESS` — keyboard and understandable interaction;
- `RESILIENCE` — interruption, restart, and degraded states.

## Adding a test

1. Default to browser execution. Add a desktop requirement only when the
   asserted behavior is specific to the native application, and name that
   boundary explicitly. Choose the closest family and next unused identifier.
2. State one user outcome. Keep implementation details and click coordinates
   out of the test unless the control itself is the requirement.
3. Provide prerequisites, actions, and observable pass conditions.
4. Include a privacy check when the flow handles documents, figures, or model
   access.
5. Add the test to the catalog and place it in the appropriate scenario file.
6. Prefer a synthetic fixture. If only private data can exercise the behavior,
   describe document roles without describing their contents.
7. Run documentation checks and the affected acceptance paths before review.

## Changing a test

Keep the identifier when clarifying language or matching an intentional product
change that preserves the original outcome. Add a new test and retire the old
one when the expected user outcome changes materially. The product change and
acceptance-contract change should normally be reviewed together.

## Retiring a test

Do not delete an active test merely because it fails. A failing test is
evidence about the product. Retire it only when the capability is intentionally
removed, replaced, or proven redundant. Remove a test body from the repository
only when its complete retirement record will remain useful in
`scenarios/retired.md`; ordinary history in Git is not a substitute for that
visible record.

Move retired tests to `scenarios/retired.md` with the identifier, former title,
reason, replacement identifier if any, and the commit that made the decision.
Git remains the detailed change history. Never reuse the retired identifier.

## Review checklist

- The test can be followed without code knowledge.
- The result is observable and has one unambiguous pass condition.
- A blocked prerequisite cannot be confused with a failure.
- The scenario does not expose private data or teach the tester the answer.
- Platform-specific expectations are named explicitly.
- Links resolve and all referenced controls exist in the packaged application.
- Generated reports and private manifests remain outside Git.

## Required checks

Before merging a suite change, verify that:

- every active heading has exactly one unique ID and every catalog range
  matches the headings in its linked scenario file;
- no active ID also appears as a retired ID;
- the private-run example contains exactly 19 unique roles, `DOC-01` through
  `DOC-19`, and contains no filled local paths;
- every relative Markdown link resolves; and
- the repository documentation test and diff hygiene checks pass.

## Financial capability additions

`GUIDE-007`–`GUIDE-026` is an additive browser-first family: 17 capability checks plus three cross-family checks. Preserve the original 45 identities and pass conditions. The human inventory is 65; qualification is a separate 123-case contract and new automated browser declarations remain unverified until executed. Numerical evidence checks establish sources of numbers; do not add evidence approval for category or treatment. Keep [the retained document continuation](real-document-test.md) and complete scenario forms aligned with the active feature guide.

Run `python acceptance/check_catalog.py` for the human inventory and `python acceptance/test_catalog.py` for omission/false-coverage counterexamples. When reconciling the sibling pack, pass `--sibling-pack <public-pack-copy>` to the catalog guard.
