# Using OrionViva

OrionViva turns financial statements into a local, evidence-backed financial
picture. The application separates currencies, shows what each figure rests on,
and exposes uncertainty rather than filling gaps silently.

## Open in browser

In a build containing this feature, expand **Browser access** and choose **Open in browser** in OrionViva.
Keep the installed app running while you use the browser on the same computer.
The browser uses the same vault format and financial engine as the desktop.
If a private vault is already open, it remains active in the browser. You can
also create or open another vault using the controls below. A sample session
can be re-entered with **Try sample data**; it never opens a private default.

**Choose folder** and **Choose statement file** open operating-system dialogs supplied
by OrionViva. They may appear beside the app rather than inside the browser.
Select one document at a time. Browser drag-and-drop is not supported; use the
file action. The selected original is not moved or rewritten and the host does
not stage a plaintext upload copy.

Reloading the authorized tab reconnects when its previous page releases control.
Duplicated or additional tabs cannot take over. If a crash or interrupted reload
leaves access unavailable, stop browser access in the app and open a new session.
The vaultphrase is never saved in browser storage; a revocable session credential
is held in that tab's session storage until access ends.

Choose **Return to desktop** after current work finishes. **Stop browser access**
revokes the browser immediately; if a request was already admitted, it finishes
before desktop control returns. An interrupted display is not proof that an
import was cancelled: inspect the vault before repeating work. Quitting the app
closes its local service. This is not remote access or an installation-free website.

## If a request stops answering

The desktop app stops waiting at a bounded deadline instead of leaving a
spinner indefinitely. A timed-out read keeps the last valid information on
screen, or says that an initial read is unavailable and can be reopened. A
timed-out action that could have changed the vault is reported as outcome
unknown: check the vault before trying again. OrionViva does not automatically
repeat writes, paid model work, exports, restores, or vault opens after an
interruption.

## Explore safely with the sample vault

Choose **Try sample data** from the welcome screen. Everything inside it is
invented. A visible frame identifies the sample until it is closed.

Use the sample to explore Overview, Accounts, Transactions, Statements, Review,
Plans, Ask Viva, evidence drawers, and Trust & settings before adding personal
documents.

## Create or open a private vault

A vault is an encrypted local folder containing the financial record.

To create one:

1. Choose **Set up my vault** on the welcome screen, then choose or enter an empty folder.
2. Enter a strong vaultphrase.
3. Select **Make a new vault in that folder**.
4. Choose **Make and open vault**.

To open an existing vault, choose **Open existing vault** on the welcome screen, then choose its folder,
enter its vaultphrase, and choose **Open local vault**.

After a successful open on macOS or Windows, OrionViva protects the folder and
vaultphrase in the operating system credential store. That private vault opens
by default on later launches. Opening or creating another private vault replaces
the default. The sample vault never replaces it.

Keep the vaultphrase somewhere independent. Moving the vault to another device,
using another operating-system account, or losing the protected credential
requires the vaultphrase again.

## Add statements

A new private vault with no accounts shows a first-statement guide on Overview.
Use its settings link to review document-reading configuration, or its statement
link to begin adding a file. Saving an original and interpreting it are separate
steps: configuration can allow relevant document data to reach the chosen model.

Use the always-available **Add statement** action or open **Statements**.

1. Choose one supported file.
2. Wait for the visible capture and reading job to settle.
3. Inspect the document row for its reading, resolution, and contribution
   state.
4. Add the next statement only after understanding the prior result.

OrionViva takes one document per capture. A saved document can remain waiting
when no reader is configured; saved and fully interpreted are different states.
A failed read does not mean the encrypted source was deleted.

Expand **Check for matching records** and choose **Check records** to reconcile information already in
the vault, including matching transfers and resolving gaps. Rescan does not send
documents to a model or read their contents again, and should not create a
second financial effect for the same source.

If the app closes while reading a statement, reopen the vault and check
**Interrupted statements** in Statements. Match the **Import reference** to the
original attempt. When offered, **Read saved original again** uses the encrypted
copy already in the vault, so the source file need not still exist. Choosing it
authorizes another read by the configured service, which may send the document
and incur charges again. Nothing retries automatically.

The app checks the saved original and financial history before another read.
Cancelled jobs and uncertain or partial financial writes cannot use this retry.
Follow the displayed inspection guidance in those cases; do not assume a failed
job means nothing was saved. Older jobs without a saved recovery receipt may
not appear here.

## Read the financial picture

### Overview

Overview leads with net worth and its coverage. Review status appears when the
queue has been loaded, followed by upcoming obligations, spending,
current-period information, accounts, and findings. Detailed accounting reports appear
after the summary sections. Amounts from different
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
details. Optional file metadata is under **File and source details**. Import
receipts distinguish saving, reading, and financial contribution; an unknown
progress total is shown without a percentage. The upload reply does not identify
a resulting document, so the receipt does not guess a document to open.
Choose **View saved original** to open a supported saved source locally. PDF
previews show one page at a time; PNG/JPEG images and plain UTF-8 text are also
supported. Use Previous/Next page, the text alternative when available, zoom and
Close original. This does not invoke your document reader or verify the figures.
Highlighted source regions remain unavailable. Preview limits and current
platform support are described in [local source previews](original-source-preview.md).

### Review

Review contains explicit questions and transaction decisions that require a
person. Its navigation count describes actionable work supplied by the vault.
Opening an item should lead to the exact question or transaction it represents.

Answer only what is known. Deferring or declining is preferable to guessing.
Completed actions update the queue after an authoritative reread. After a
confirmed resolution, **Next item** opens the next available question or
transaction in the recorded order. A partial or failed refresh does not claim
that review is complete. Review answers have no general undo; supported
accounting corrections and transfer links have their own reversal controls.

### Plans

Plans creates local goal drafts and reservations. Calculating a draft records
nothing. Holding a proposal moves no money. Persistence requires a separate,
explicit confirmation of the exact proposal shown.

## Inspect evidence

Use a figure's evidence action to see the source records supporting it. Check
that the drawer names the intended figure, currency, document, and page or
source region when supplied. Follow a document link, then explicitly choose
**View saved original** to inspect supported saved content. The drawer and
document metadata alone do not display the original.

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

The Ask box starts a new conversation. After an authoritative answer or refusal,
the next question continues that conversation automatically. The context indicator
shows which mode will be used. Choose **New conversation** to keep earlier Ask
text out of the next request. Earlier turns remain saved in the timeline; this
is not deletion. Closing and reopening Ask Viva preserves the selected context,
including when an answer arrives while the drawer is closed. Opening another
vault, or reopening the current vault, starts with a new conversation boundary
on its next question. If readable saved Ask history is available, choose
**Continue previous conversation** to use it for the next question. This action
keeps your draft and focuses the question field; it submits nothing. It is
unavailable while a question is running or when explaining an accounting entry.
**New conversation** returns to a fresh question without deleting history.
The ledger and cited evidence are freshly read for each answer; conversation
text is not evidence. Question ideas fill the editable composer without sending
anything. Expand **Plan a savings goal** for the separate save-up plan draft action.

When a configured model is required, relevant question or document data may
leave the machine. Trust & settings records the observed outbound activity.

Numerical answers can expose a **Numerical receipt** through their figure's
evidence control. It shows exact values, quantities, currencies, dates, subjects
and population boundaries. Where supplied, it shows numerical sources,
recorded starting measurements, local goal activity, current-question premises
and calculation limitations. Local reservations are not bank transfers, and
hypothetical results carry no bank evidence grade. Older saved answers can lack
receipts; unavailable receipts are not reconstructed from answer text. See
[numerical answer receipts](numerical-answer-receipts.md).

## Trust, privacy, and settings

Open **Trust & settings** to inspect:

- The running engine identity and available lifecycle information.
- Observed outbound model activity and disclosed usage or cost.
- Verification display preferences.
- Model and presentation configuration proposals.
- Maintenance and privacy-filtered diagnostics when available.
- Vault export and restore controls.

Expand **Model connection settings** in Trust & settings to edit the provider,
exact model name, service address, and key. Current settings and any proposed
change remain visible outside that disclosure. Model configuration changes use
a propose-and-confirm flow. Provider keys must
not be included in screenshots, reports, diagnostics, or shared configuration.

## Close, switch, export, and restore

In the installed desktop and its browser interface, closing a vault releases
the active engine and removes its contents from the screen. Reloading or moving
between those interfaces does not reopen it; open a vault explicitly to resume.
On macOS and Windows, closing does not erase the protected default: the same
vault may open on the next application launch unless another private vault is
successfully opened. The development acceptance host has no native close
capability and clears only its interface.

To switch defaults, open or create another private vault successfully.

Export writes an encrypted copy. Restore writes into an empty destination and
requires the vaultphrase. Neither operation makes an unencrypted copy, and an
export is not useful without the vaultphrase.

In **Trust & settings**, choose **Choose backup location** to select a new
`.orionvault` file, then choose **Take a copy** to write it. **Choose backup
file** and **Choose restore folder** fill the restore paths; enter the backup’s
passphrase and choose **Bring it back** to restore. These chooser buttons appear
when the host supports them. You can always enter paths directly. Choosing a
path or cancelling a chooser never exports or restores a vault.

To recover when no vault is open, choose **Restore a backup** on the welcome
screen. Choose the `.orionvault` file and an empty destination folder, then
enter the backup's passphrase. File and folder choosers are available when the
host offers them; you can also enter the paths directly.

OrionViva verifies the backup in a private temporary folder before publishing
the recovered vault. A wrong passphrase or failed verification leaves the
destination available for a corrected attempt. Existing files are never
replaced. After a completed restore, choose **Open restored vault** and enter
its passphrase again. Restoring alone does not open the vault or save a device
credential. If a restore stops answering, inspect the destination before
trying again: it may already contain the restored vault.

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
