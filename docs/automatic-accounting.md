# Automatic accounting and learning from corrections

**State:** implemented with synthetic verification; release and real-document acceptance remain open.
**Decision:** owner authorized implementation after approving automatic interpretation and correction learning.

Viva prepares working financial statements after document ingestion. Valid source amounts remain recorded exactly. Classification uncertainty does not create a review task or stop a report. The model applies its strongest available interpretation, and the user explains exceptions in conversation. The 80:20 direction means act and make correction easy; it is not a claimed accuracy rate.

## Ingestion and accounting

Capture, reconciliation, deduplication and supported document linking remain the financial admission boundary. The automatic stage runs after finalization, applies scoped learned rules, uses established merchant implications, and attempts one bounded model interpretation for unresolved or changed categorical evidence. A missing or failing model leaves recorded activity usable. Unverified interpretations may be reconsidered when their evidence changes; a human correction remains stronger.

Ordinary unexplained outflows become working expenses and inflows become working income, interpreted through the source account kind. Credit card purchases are expenses; repayments do not repeat the purchase expense. Supported transfers, borrowing, refunds and investment transactions retain their established meaning. The major category, minor category and merchant hierarchy groups reporting lines without counting the same money at each level.

The profit-and-loss report preserves exact decimal amounts and separate currencies. Its period includes both end dates. Amount evidence and classification evidence are distinct: a reconciled amount can have an inferred treatment. Provisional contributions are included and shown separately. The balance sheet uses measured balances and dated holdings, with inferred acquisitions marked as such. Missing opening debt balances, unknown compound allocations and held documents remain disclosed. No model can manufacture a balance, exchange rate, principal split or depreciation schedule.

Payroll decomposition retains the matched bank movement and currency. Legacy decompositions use only a unique matching deposit within the ingestion date tolerance. Explicit human or document-attested shares can allocate a known payment; a model-generated ratio cannot do so. Conversational percentages must occur explicitly in the user’s explanation. Unsupported monetary or verbal allocations stay unresolved. Learned treatment does not carry an installment’s proportions into other payments; each compound payment needs its own allocation evidence.

## Corrections and learning

From Activity, choose Explain accounting treatment and describe the selected transaction. An unambiguous explanation applies immediately, refreshes the reports and supplies an undo receipt. Existing legitimate target ambiguity is clarified; a second yes is not required for an already understood correction. Ordinary Ask remains available separately.

A learned rule matches party, privacy, payment direction, source role and purpose category context. Private descriptions remain local and require the source account. Future rules do not silently rewrite existing history. Explicit recurrence may apply to matching history; one-off corrections supply sanitized examples without a blanket merchant rule. Rule applications retain prior treatments, so undo appends restoration events and reverses the correction and its dependent rule applications while preserving later independent corrections.

The public question queue contains document admission/recovery problems only. Requested edit parsers remain available internally; merchant classification, nature, cadence, corroboration and account-interview uncertainty do not create proactive review questions.

## Model and privacy boundary

Automatic interpretation sends only public taxonomy categories and subcategories, source account role, direction, recognized categorical implications, link status, bounded sanitized correction examples and opaque batch references. Custom categories, private names/descriptions, actual accounts, dates and amounts do not cross this boundary. Corrections send the user's explicit explanation and selected count, with selection resolved locally.

Prompts are immutable versioned files. The automatic call processes at most 32 rows with 4,096 output tokens and a 45-second limit; it has no continuation loop. Raw model claims are captured before any treatment is applied. Applied rulings retain grounds, source references, prompt attribution and an evidence signature. Research capability is reported honestly: the currently configured extraction adapters do not expose public-search tools to this stage. Existing merchant enrichment is reused; automatic web research must not be advertised as delivered.

## Read model and interface

The canonical ledger and encrypted disposable SQL revisions compose the same financial statements, including correction and undo. The normalized source histories retain accounting controls, restoration records, model attribution and payroll association. Historical reads apply only eligible evidence. Bounded reads refuse overflow instead of truncating totals.

Overview leads with Balance sheet and Profit and loss. Categories and merchants expand beneath their totals, evidence opens captured source documents, incomplete coverage remains visible, and period changes are computed by the product. The interface formats no financial arithmetic. Document recovery is reachable through Documents.

## Validation and remaining acceptance

Synthetic tests cover fallback, card purchases and repayment, refunds, payroll linkage, multiple currencies, unknown loan components, attested splits, scoped future learning, one-off examples, undo, evidence replacement, model failure and intercepted outbound privacy. Canonical/SQL parity is required after corrections and undo. Browser acceptance and the independent acceptance pack are recorded separately; provider-free synthetic tests do not establish model accuracy on a real vault.

The fresh full product/core/merchant run passed 3,596 tests with two existing skips in 637.54 seconds. The full desktop suite passed 1,006 tests, together with production build, architecture and style checks. Subsequent bridge cases passed a separate six-test bridge run; the scalar/report checks passed 54 tests, and documentation and generated overview parity checks passed 48 tests. These separate runs are not added to the full-suite count. An isolated production browser journey verified selected correction, undo, period entry and keyboard focus using invented records and an offline fixture interpreter. Independent verification passed with findings and no implementation blocker; real-document Witness acceptance and model accuracy remain unverified.

The external acceptance pack still requires a conversational-correction journey in place of its question-led learning flow, a current product-base UI evidence packet and compatible browser tooling. Signed release packaging and real-document Witness cases remain open.
