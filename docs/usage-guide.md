# Using OrionViva

OrionViva turns financial statements into a local, evidence-backed financial
picture. The application separates currencies, shows what each figure rests on,
and exposes uncertainty rather than filling gaps silently.

## Explore safely with the sample vault

Choose **Open the sample vault** from the first screen. Everything inside it is
invented. A visible frame identifies the sample until it is closed.

Use the sample to explore Overview, Accounts, Transactions, Statements, Review,
Plans, Ask Viva, evidence drawers, and Trust & settings before adding personal
documents.

## Create or open a private vault

A vault is an encrypted local folder containing the financial record.

To create one:

1. Choose or enter an empty folder.
2. Enter a strong vaultphrase.
3. Select **Make a new vault in that folder**.
4. Choose **Make and open vault**.

To open an existing vault, choose its folder, enter its vaultphrase, leave the
creation option clear, and choose **Open local vault**.

After a successful open on macOS or Windows, OrionViva protects the folder and
vaultphrase in the operating system credential store. That private vault opens
by default on later launches. Opening or creating another private vault replaces
the default. The sample vault never replaces it.

Keep the vaultphrase somewhere independent. Moving the vault to another device,
using another operating-system account, or losing the protected credential
requires the vaultphrase again.

## Add statements

Use the always-available **Add statement** action or open **Statements**.

1. Choose one supported file.
2. Wait for the visible capture and reading job to settle.
3. Inspect the document row for its reading, resolution, and contribution
   state.
4. Add the next statement only after understanding the prior result.

OrionViva takes one document per capture. A saved document can remain waiting
when no reader is configured; saved and fully interpreted are different states.
A failed read does not mean the encrypted source was deleted.

Use **Rescan** when the interface offers it to revisit already captured
documents after relevant knowledge or configuration changes. Rescanning should
not create a second financial effect for the same source.

## Read the financial picture

### Overview

Overview presents net worth, accounts, current-period information, findings,
coverage, and exclusions supplied by the vault. Amounts from different
currencies remain separate; OrionViva does not invent an exchange rate or a
converted grand total.

Every material figure should be read with its:

- Currency and amount.
- Measurement date or period.
- Evidence grade.
- Coverage and exclusions.
- Evidence action, when supplied.

### Accounts

Accounts lists the instruments visible in the current read. Open an account to
see its account-scoped ledger, statement coverage, reconciliation state, month
groups, transaction evidence, and supported corrections.

A liability speaks as an amount owed rather than pretending to be a negative
deposit. A missing balance is different from a zero balance and should be shown
as unavailable.

### Transactions

Transactions provides search, authored filters, evidence, and only those
corrections the backend authorizes. Depending on the movement, available
actions can include classification, economic meaning, tags, and transfer
confirmation or rejection.

An action receipt is not itself financial truth. OrionViva rereads the vault
before replacing totals or rows after a correction. If that reread fails, the
last valid picture remains visible with a stale or reopen warning.

### Statements

Statements is the document index and capture workspace. It distinguishes files
that were saved, read, resolved, contributed to the financial picture, left
waiting, or failed. Select a row to inspect only that document's supplied
details.

### Review

Review contains explicit questions and transaction decisions that require a
person. Its navigation count describes actionable work supplied by the vault.
Opening an item should lead to the exact question or transaction it represents.

Answer only what is known. Deferring or declining is preferable to guessing.
Completed actions update the queue after an authoritative reread.

### Plans

Plans creates local goal drafts and reservations. Calculating a draft records
nothing. Holding a proposal moves no money. Persistence requires a separate,
explicit confirmation of the exact proposal shown.

## Inspect evidence

Use a figure's evidence action to see the source records supporting it. Check
that the drawer names the intended figure, currency, document, and page or
source region when supplied.

Evidence can establish where OrionViva obtained a claim. It does not make an
old, incomplete, or conflicting source current, so also read the figure's date,
grade, coverage, and qualifications.

## Ask Viva

**Ask Viva** is separate from Review. Ask questions about the records already
in the vault, such as:

- What is my net worth in each currency?
- Which balance is stalest?
- What evidence supports this account balance?
- What was counted as spending during this period?
- Which accounts or documents are excluded from this answer?

Answers should cite vault evidence and refuse unsupported combinations. Ask
Viva should not silently convert currencies, invent missing dates, or change
financial records merely because a question was asked.

When a configured model is required, relevant question or document data may
leave the machine. Trust & settings records the observed outbound activity.

## Trust, privacy, and settings

Open **Trust & settings** to inspect:

- The running engine identity and available lifecycle information.
- Observed outbound model activity and disclosed usage or cost.
- Verification display preferences.
- Model and presentation configuration proposals.
- Maintenance and privacy-filtered diagnostics when available.
- Vault export and restore controls.

Model configuration changes use a propose-and-confirm flow. Provider keys must
not be included in screenshots, reports, diagnostics, or shared configuration.

## Close, switch, export, and restore

Closing a vault removes its contents from the current screen. On macOS and
Windows it does not erase the protected default; the same vault opens on the
next application launch unless another private vault is successfully opened.

To switch defaults, open or create another private vault successfully.

Export writes an encrypted copy. Restore writes into an empty destination and
requires the vaultphrase. Neither operation makes an unencrypted copy, and an
export is not useful without the vaultphrase.

## Recovery behavior

If an ordinary surface read fails, OrionViva keeps the last valid picture rather
than replacing it with an empty vault. If the native bridge restarts, it may
retry a read only after reopening the exact active private vault from the
protected device credential. It never automatically replays a write.

A sample-vault failure must never open a remembered private vault. If automatic
unlock fails, OrionViva keeps the remembered folder selected and asks for its
vaultphrase again without displaying or logging the stored credential.

## Keyboard and accessibility

Primary actions and destinations are keyboard reachable. Use Tab and Shift+Tab
to move, Enter or Space to activate controls, and Escape to close modal drawers.
Focus should return to the action that opened a drawer or to the relevant page
heading after navigation.

If focus becomes trapped, invisible, or unable to reach a primary action, treat
that as a product defect rather than working around it with hidden controls.

## When something looks wrong

Do not correct a record until checking:

1. The selected vault and whether it is sample or private.
2. The figure's currency and measurement date.
3. Coverage, exclusions, and evidence grade.
4. The linked source evidence.
5. Whether a capture, rescan, or reread is still running.

Use safe labels when reporting a defect. Never include vaultphrases, API keys,
full account numbers, private document contents, or unredacted screenshots in a
public issue. Report security-sensitive issues through
[SECURITY.md](../SECURITY.md).
