# Document import

Use synthetic documents for routine runs. The private run may use the local
19-document set only under the safety rules in the suite README.

## IMPORT-001 — Select unknown documents without an answer key

**Actions:** Choose a mixed set of documents by opaque role label. Do not tell
the tester their institutions, expected types, totals, or dates.

**Pass:** The application accepts selection without requiring the tester to
pre-classify the files and clearly shows that work has started.

## IMPORT-002 — Progress and completion are honest

**Actions:** Import multiple documents and observe progress until it settles.

**Pass:** Progress does not declare completion early. The final state accounts
for every selected file as imported, needing review, unsupported, or failed.

## IMPORT-003 — Unsupported input is handled safely and explained

**Actions:** Add a safe synthetic file whose format or type is unsupported.

**Pass:** The application does not invent financial facts or silently discard
the input. It explains the limitation and provides a useful next action.

## IMPORT-004 — Duplicate import does not duplicate the financial picture

**Prerequisite:** A document has completed import.

**Actions:** Select the same document again.

**Pass:** The product recognizes or safely resolves the duplicate. Accounts,
transactions, balances, and totals are not counted twice.

## IMPORT-005 — Partial failure preserves successful work

**Actions:** Import a batch containing valid synthetic documents and one input
that will fail safely.

**Pass:** Successful documents remain available, the failed input is named by a
safe local label, and retry guidance does not require recreating the vault.

## IMPORT-006 — Imported state survives restart

**Prerequisite:** At least one import has completed.

**Actions:** Close and relaunch the application, allowing the vault to open by
its supported default-vault behavior.

**Pass:** Completed documents and their settled review state remain present;
work does not revert to an earlier transient state.

## IMPORT-007 — Private inputs stay within the declared boundary

**Actions:** Observe application destinations and outbound-activity records
during import. If model reading is enabled, approve only the intended request.

**Pass:** No document content appears in logs, reports, filenames created by the
tester, or unapproved network/model activity. Approved outbound activity is
visible and attributable to the user's action.
