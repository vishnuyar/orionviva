# Accessibility and resilience

## ACCESS-001 — Essential onboarding works by keyboard

**Actions:** Starting from first launch, use only the keyboard to move through
controls and activate the sample-vault action.

**Pass:** Focus reaches every essential action in a logical order, remains
visible, and the sample action can be activated without a pointer.

## ACCESS-002 — Core navigation works by keyboard

**Actions:** With a vault open, use only the keyboard to visit Overview,
Accounts, Transactions, Statements, Review, Plans, Ask Viva, and Trust.

**Pass:** Each destination is reachable and selected state is understandable.
Focus is not trapped or lost after navigation.

## ACCESS-003 — Import and review work by keyboard

**Actions:** Use only the keyboard for the in-app portions of adding a synthetic
document and resolving a review item.

**Pass:** All decisions and confirmations are operable, focus returns to a
useful location after dialogs, and no pointer-only control blocks completion.

## ACCESS-004 — Status is conveyed without relying only on color

**Actions:** Inspect success, warning, review-needed, failure, selected, and
disabled states encountered during the suite.

**Pass:** Text, labels, icons with accessible names, or other non-color cues
communicate meaning. Controls have understandable names.

## RESILIENCE-001 — Surface read failure retains the active vault

**Actions:** Using a safe test harness or reproducible condition, cause one
financial surface read to fail after a vault is open.

**Pass:** The application securely retries only the same eligible private vault
or keeps it selected and gives a clear reopen/unlock instruction. It never
switches vault identity or silently falls back to “No vault open.”

## RESILIENCE-002 — Recovery cannot cross from sample to private data

**Prerequisite:** A private vault is remembered and sample mode is active.

**Actions:** Cause or observe a sample-surface failure through an approved safe
test mechanism.

**Pass:** Recovery remains in sample context and never opens or displays the
remembered private vault.

## RESILIENCE-003 — Interrupted import has a truthful final state

**Actions:** Interrupt a synthetic multi-document import through a supported
cancel or application-close path, then relaunch.

**Pass:** Completed, incomplete, failed, and retryable work is distinguished.
The product does not claim the interrupted batch completed.

## RESILIENCE-004 — Repeated navigation does not erase settled state

**Actions:** Repeatedly move among core surfaces after data has loaded, including
period changes and evidence destinations.

**Pass:** Settled data does not disappear, vault identity does not change, and
controls remain actionable.

## RESILIENCE-005 — Error messages provide a safe next action

**Actions:** Observe errors encountered in the suite.

**Pass:** Each user-facing error says what did not complete and what the user
can safely do next. It does not expose a vaultphrase, private document content,
internal command output, or irrelevant infrastructure fallback noise.

