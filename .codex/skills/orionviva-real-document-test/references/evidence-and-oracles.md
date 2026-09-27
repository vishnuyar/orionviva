# Evidence and source checks

Use records that another context can resume without inferring progress. These are logical fields, not a required implementation or new product schema.

## Private manifest

- Run ID and repository/candidate identity.
- Document ID, original and private-copy paths, SHA-256, pages, account group, statement period, currency and fixed upload position.
- Vault attempt ID, isolated learned-store path, actual serving host/build and creation/closure/deletion disposition.
- Provider/model configuration identifiers and observed cost totals, never secret values.

Keep secrets in the approved environment/credential mechanism. Do not copy the environment file into documents, reports or the skill.

## Per-document record

Record upload start/end, terminal state, contribution, source comparison, every review question and answer, proposal/decision, receipt, after-reload state and final verdict. Use durable question/transaction/proposal/document IDs when available rather than relying only on visible wording. Repeated identical labels may identify different transactions.

Compare transaction rows as a multiset, not a set: duplicate-looking legitimate rows must retain multiplicity. Separate transaction dates from posting dates and preserve the statement's convention. Do not silently correct a source to agree with the product. Save source ambiguities explicitly and render the page to resolve layout issues.

Check opening balance plus signed movements against closing balance using each account's accounting convention. Record card payments/refunds separately from positive purchases. Reconcile each statement independently before combining periods. Latest balances must be selected per account with their own dates, not by upload order.

For brokerage, reconcile statement summary and holdings separately, and document overlapping measures before calculating totals. Gross securities value, net account value, core cash, free credit and buying power are not interchangeable or automatically additive. Keep currency conversion unsupported unless a stated rate/date/source justifies it.

## Review truth

- Unknown personal purpose or arrangement: use unknown/set-aside and record that disposition.
- Candidate transfer: require source-supported account identity, dates and amount, and inspect competing matches before confirming.
- More statements: answer for the particular account and requested coverage; a remaining older document is not a newer statement.
- Fee/income/component proposal: verify what is actually proposed, including whether a value-holding account would be created and which movement(s) would change. A correct category does not excuse a wrong counteraccount or scope.
- Decline or confirmation: verify the durable effect and queue refresh, not just a success toast. Interpret audit records separately from financial writes.

Do not fabricate a real compound transaction or personal relationship just to cover a branch. Use synthetic tests for branches the actual documents do not support, and label that evidence accordingly.

## Question record

Save the exact prompt and conversational context, visible answer, monetary figures, labels/grades, cited records, source-navigation result, receipt, oracle/derivation, verdict and latency. Classify as correct, incorrect, partial with adequate qualification, clarification, honest unsupported capability, missing data or execution failure. A refusal can be a usability finding without being a wrong financial claim.

## Bug packet and public boundary

Private packet: full reproduction, source evidence, exact model capture if relevant, events before/after, UI state and build identity.

Scrubbed packet: synthetic reproduction, failed contract, expected/observed structure, affected layers, verdicts, test IDs, version/fingerprint and private evidence pointer. Never include real balances, names, institutions, account fragments, transaction dates, source text or secret values. Run repository privacy checks before sharing or committing scrubbed artifacts.

## Resume checkpoint

A useful checkpoint says: which attempt is authoritative; which documents are verified in that attempt; which review questions are unresolved versus intentionally unknown/waiting; what repair changed; whether the browser serves the rebuilt candidate; whether a replacement vault is ready; which checks genuinely passed; and the next UI action. Record blocked credential/unlock handoffs precisely. Temporary helpers and live process/tab IDs are hints requiring revalidation, not durable truth.
