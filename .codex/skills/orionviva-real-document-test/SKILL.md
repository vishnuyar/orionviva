---
name: orionviva-real-document-test
description: Test OrionViva with a collection of 19 real financial documents through the browser, uploading and reviewing one at a time, verifying against source records, repairing root causes, restarting in fresh vaults, and exercising financial conversations. Use for the complete real-document testing method or an explicit continuation of that campaign.
---

# OrionViva real-document testing

Run the whole acceptance journey as a user would. Completion means all 19 documents have been uploaded, reviewed and checked in the same final vault, followed by the financial-question campaign. Success from discarded vaults is evidence of earlier attempts, not completion of the final run.

## Establish the run

1. Locate the OrionViva repository and read `WORKFLOW.md`, applicable `AGENTS.md`, and `.codex/skills/orionviva-acceptance-repair/SKILL.md`. Apply the repository repair roles and approval boundaries. Do not assume a prior context's commit, branch, app build or test result is current.
2. Use the document directory supplied by the user and locate the current OrionViva repository. If continuing a prior campaign, recover its authorized locations from the private manifest. Inspect filenames and count documents without treating the environment file as an upload. Expect 19 financial documents; investigate a different count instead of silently dropping or inventing files. Respect a different location or count explicitly supplied by the user.
3. Establish authorization for the actual documents, destination/model provider and spending budget from the user's request. An environment file's presence does not itself authorize a provider or spending. For an explicitly resumed campaign preserve the user's existing scope, provider and spending instructions; do not treat historical permission as blanket authorization for unrelated future data or spending. Ask only for genuinely missing authorization. Keep keys/passphrases in memory, never in output or committed files.
4. Use a dedicated private run directory outside every repository, normally `~/.viva-runs/<run-id>/`, for document copies, hashes, source extracts, vaults, exact answers, screenshots, provider records and cost records. Use `runs/<run-id>/` only for scrubbed verdicts and machine facts. Read the repository Witness role before handling real data. Source originals remain untouched.
5. For a continuation, inspect the latest scrubbed status and private manifest before acting. Verify which vault is open, what build serves it, and whether a repair requires a new vault. A stale “passed” or “done” note does not establish current state. Never rely on process IDs, browser tabs, temporary helper scripts or vault paths from an old session without checking them.

## Orchestrate independent work

Use multiple agents when the user requests this workflow with delegation or the applicable repository instructions require it. The parent owns the real browser, documents, credentials and Witness evidence. Give repair agents only synthetic reproductions and scrubbed predicates.

Separate diagnosis/design, factual checking, authorized scope ruling, implementation, fresh verification and interface review according to `WORKFLOW.md`. A builder never grades its own fix. Parallelize independent bounded investigations or reviews; keep browser uploads and dependent repair steps sequential. Coordinate expensive full suites, builds and performance measurements so contention does not contaminate results.

## Inventory and independent truth

Assign stable neutral IDs D01–D19, retaining the private mapping to original filenames, hashes, page counts, statement periods and account identities. Order bank/card documents first and brokerage documents last. Preserve a deliberate order within each group and record it; do not silently change the order between restarts.

Before asking the product for answers, establish source truth independently of its extraction or classification:

- Read the actual PDF text; render pages when columns, signs, multiline rows or OCR are ambiguous. Use the available PDF skill when appropriate.
- Capture transaction date/amount rows with multiplicity, opening/closing balances, totals, periods and account identity. Record whether a date is the transaction or posting date. Check each statement's arithmetic.
- For brokerage statements, distinguish cash flows, trades, dividends/interest, fees, holdings, liabilities, market values and realized/unrealized gains. Do not substitute change in account value for investment gain or add overlapping cash measures.
- Keep account/date/currency boundaries explicit. Missing purpose, ownership or personal arrangements remain unknown unless the sources establish them.

See [evidence-and-oracles.md](references/evidence-and-oracles.md) for the record structure and comparison rules.

## Prepare the browser and vault

Build and validate the candidate as required before using it for final Witness evidence. Record the exact revision, dirty-tree fingerprint if applicable, prompt/persona versions, packaged artifact identities and browser host. Test shared document/review/financial behavior through the browser; native interaction is for file dialogs, app lifecycle and credential handoff.

Use the available supported browser/computer tools and read their documentation. Do not replace the user's browser journey with direct ingestion APIs, database writes or shell-driven UI automation. Read-only private snapshots and source comparisons may supplement the browser but cannot substitute for it.

For a new ingestion campaign, create a disposable test vault and an isolated learned merchant/catalog store. A fresh vault with a reused learned store is not a clean restart. Preserve the user's shared catalog and unrelated vaults. Record exactly which folders belong to this test.

If the Mac is locked, request an unlock and continue independent checks. If browser policy requires the user to enter a new vault passphrase, prepare the concrete new-vault form first and hand off only credential entry/submission. Do not print the passphrase or work around the handoff. Opening an existing vault uses the applicable existing-credential policy.

## The one-document loop

For each document, in the fixed order:

1. Upload exactly one document through the browser and its actual file chooser. Do not queue the next upload.
2. Observe import progress until terminal success or failure. Record the document identity, elapsed time, terminal state and any warnings. A transient refresh warning is not yet a diagnosed defect; inspect the eventual authoritative state. A click or timed-out browser wait does not prove the upload failed, so inspect before resubmitting.
3. Open the document contribution and relevant accounts/transactions. Compare the posted records with the independent source oracle. Check every transaction date/amount with multiplicity, signs, opening/closing balance, statement period and identity. Record missing, extra, duplicate or misassigned rows precisely.
4. Inspect every newly actionable review question, including questions that appear after an answer changes grouping. Read the full question, selected transaction scope and any proposed changes before responding.
5. Answer with source-supported facts. If purpose, recurrence, ownership, identity or an arrangement cannot be established, use the product's unknown/set-aside route. Do not invent facts to clear the queue. Confirm an own-account transfer only when both source records and surrounding evidence support it; equal amounts alone are insufficient. Answer document expectations truthfully for that account and period, not merely because more files remain overall.
6. Record the exact question, selected scope, answer, proposed treatment, confirm/decline decision, resulting receipt and resulting state privately. If a proposal changes financial treatment, inspect the actual named/default components, shares, account creation and scope before confirming. Decline unsupported proposals. These are test-vault bookkeeping decisions, not authority to move money.
7. Verify persistence and the authoritative queue after the answer. Where relevant, reload and check held proposal identity, declined state, remaining questions and receipts. The UI must agree with durable records. All review items must have an explicit disposition; honest unknowns and legitimate waiting-for-document states need not disappear.
8. Save a per-document verdict and checkpoint before moving to the next document. If a defect is established, enter the repair loop immediately.

Do not batch uploads, skip review because the importer says “Resolved,” or count a document as verified solely because its balance looks plausible.

## Diagnose, repair, and restart

A surprising outcome first earns evidence, not an immediate patch. A suspicious account name or expense label prompts inspection of the underlying financial role; the label alone is not proof of a defect. Preserve the private exact reproduction and derive a synthetic case that reproduces the same boundary without private values. Distinguish a wrong financial fact, wrong target/scope, unsupported claim, UI persistence issue, honest capability limit, test-oracle mismatch and environment failure.

Use the existing acceptance-repair skill and repository workflow for root-cause repairs. Check the whole path involved: source capture, interpretation, local validation, proposal/confirmation, financial application, projection/indexed reads and displayed wording. Fix the violated contract at its owning boundary. Do not add institution/merchant-specific patches, word lists, arbitrary delays, blind retries or weaker assertions to make one document pass.

Demonstrate a meaningful regression before the fix; verify it fails for the actual defect. Preserve raw captured replies, financial meaning, privacy and required confirmation. Use immutable prompt/persona versions where the product requires them. Require fresh independent verification, relevant interface review, affected-package checks and required acceptance/build/privacy checks. Inspect whole test output: a clean tail can conceal an earlier failure. Correct stale test contracts openly without weakening their substantive guarantees.

Distinguish stale prose, an obsolete run artifact and an independent evaluator contract: reconcile prose against current evidence, rerun an obsolete artifact, and preserve official evaluator results while requesting review of contract changes. Do not alter an independent evaluator merely to turn it green. Diagnose and report stale oracle/source packets separately, retain the official result, and obtain the appropriate evaluator review for any amendment. No release-ready claim while required evidence remains missing.

**After an ingestion, financial-application or learned-state bug fix, restart the entire document campaign.** For a read-only analysis, measurement, scenario or wording repair, honor an explicit owner-authorized retained-vault continuation after verifying current state; record carried-forward and newly repeated checks separately. Do not impose reupload for an unrelated non-ingestion repair. When a restart is required:

- Finish required checks, rebuild the app and verify what build the browser actually serves.
- Close the superseded test vault. Prepare the next empty vault and isolated learned store.
- Verify the replacement opens empty, then delete only the explicitly disposable old vault according to current authorization/tool policy. Retain private evidence, original documents and unrelated stores. Never delete first and hope the replacement opens.
- Begin again at D01, with brokerage last. All 19 documents and the conversation campaign must pass on the final candidate. Earlier partial successes do not carry forward as final-pass counts.

After three unsuccessful repair cycles for the same failure signature, stop speculative patching and report the evidence, attempted fixes and precise unresolved decision, following the existing repair skill. Do not turn that limit into abandonment of unrelated completed work.

## Ask financial questions after all 19

Read the product repository’s `acceptance/real-document-test.md` for the current feature campaign, complete scenario forms, cent/calendar conventions, numerical-source-only evidence rule and owner-deferred boundaries. Use [financial-questions.md](references/financial-questions.md) as a broad starting campaign, adapting names and periods to the actual source coverage. Ask one question at a time through the browser. Include follow-ups, paraphrases, exact transaction explanations, account-specific questions, missing-period questions and source navigation.

Check every answer's amount/sign, period, account/currency scope, uncertainty, derivation, citations and receipt against the pre-established oracle. Reconcile mixed-date net worth transparently; exclude own transfers from spending; distinguish deposits, investment purchases and returns. Record useful refusals and capability gaps separately from wrong answers. Inspect source links and persistence after reload. Do not invent real financial intent merely to exercise a synthetic edge case.

Any new product bug returns to the reviewed repair loop. Use the restart rule above; preserve an explicitly authorized retained-vault non-ingestion continuation when state remains suitable. Testing ends only after the final 19-document pass and the final question campaign are complete, or a specific unresolved blocker is reported honestly.

## Deliver and preserve continuity

Keep a current scrubbed checkpoint after each document, defect, fix and reset: exact candidate, current vault ID, document dispositions, source-verification counts, review dispositions, open issues, tests/evaluator results, current UI handoff and the next concrete action. Keep exact financial records in the private run directory. Report provider cost/usage with its attribution limits; never expose credentials.

Document-campaign completion and release readiness are separate claims. You may report a completed browser campaign against its exact tested candidate when every document and financial-question check has a truthful final disposition. That does not replace the repository's committed-revision or release gates; report those separately and never infer commit authority merely to finish testing. Required unresolved journey failures still make the campaign incomplete.

Final report: documents completed in the final vault, questions exercised, repairs and root causes, verification evidence, remaining limits, cost and private evidence location. State clearly when the 19-document campaign is incomplete. Commit, merge, push and release only within the user's explicit authority; a testing request or this skill alone does not grant publication authority.
