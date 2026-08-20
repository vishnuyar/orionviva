import type { ActivityView, SampleActivityFilterCatalog, SurfaceSnapshot } from "../types";
import { corpusCoverageLabel, syntheticCorpus } from "./synthetic-corpus";

const overviewActivityItems: ActivityView[] = [
  { id: "paycheck-jun-28", label: "Paycheck", exactValue: "4800.00", display: "+$4,800.00", measure: "income", detail: "Jun 28 · Everyday checking", tone: "inflow", state: "ready", provenance: "Synthetic PDF · checking statement · June 2026 · page 1", grade: "not_applicable", exactness: "exact", recordIds: ["demo-record-paycheck-jun-28"], evidenceLinks: [
    { targetDocumentId: "demo-doc-silverline-checking-2026-06", label: "Everyday Checking June statement", relation: "same_period", page: "page 1" },
  ], sample: { date: { id: "date-2026-06-28", label: "June 28, 2026" }, account: { id: "account-everyday-checking", label: "Everyday checking" }, merchant: { id: "merchant-orion-payroll", label: "Orion Payroll" }, category: { id: "category-income", label: "Income" }, tags: [{ id: "tag-payroll", label: "Payroll" }], nature: { id: "nature-compensation", label: "Compensation" }, direction: { id: "direction-incoming", label: "Incoming" } } },
  { id: "home-utilities-jun-24", label: "Home + utilities", exactValue: "1420.76", display: "−$1,420.76", measure: "spending", detail: "Jun 24 · categorized", tone: "outflow", state: "ready", provenance: "Synthetic PDF · checking statement · June 2026 · page 1", grade: "not_applicable", exactness: "rounded", recordIds: ["demo-record-home-utilities-jun-24"], evidenceLinks: [
    { targetDocumentId: "demo-doc-silverline-checking-2026-06", label: "Everyday Checking June statement", relation: "same_period", page: "page 1" },
  ], sample: { date: { id: "date-2026-06-24", label: "June 24, 2026" }, account: { id: "account-everyday-checking", label: "Everyday checking" }, merchant: { id: "merchant-city-utilities", label: "City Utilities" }, category: { id: "category-home-utilities", label: "Home + utilities" }, tags: [{ id: "tag-home", label: "Home" }, { id: "tag-recurring", label: "Recurring" }], nature: { id: "nature-household-bill", label: "Household bill" }, direction: { id: "direction-outgoing", label: "Outgoing" } } },
  { id: "statement-gap-may-14", label: "Statement gap", exactValue: "0.00", display: "Needs attention", measure: "spending", detail: "May 14 · one page held", tone: "neutral", state: "needs_input", provenance: "Synthetic brokerage statement · pages 1–2", grade: "not_applicable", exactness: "estimated", recordIds: ["demo-record-statement-gap-may-14"], evidenceLinks: [
    { targetDocumentId: "demo-doc-northgate-brokerage-2026-05-to-2026-07", label: "Taxable Brokerage statement", relation: "same_period", page: "pages 1–2" },
  ], sample: { date: { id: "date-2026-05-14", label: "May 14, 2026" }, account: { id: "account-taxable-brokerage", label: "Taxable Brokerage" }, merchant: { id: "merchant-statement-reader", label: "Statement reader" }, category: { id: "category-document-review", label: "Document review" }, tags: [{ id: "tag-held", label: "Held" }], nature: { id: "nature-statement-gap", label: "Statement gap" }, direction: { id: "direction-unavailable", label: "Direction unavailable" } } },
];

const activityItems: ActivityView[] = [
  ...overviewActivityItems,
  { id: "sample-transfer-out-jul-02", label: "Sample transfer out", exactValue: "250.00", display: "−$250.00", measure: "spending", detail: "Jul 2 · fictional transfer anatomy", tone: "neutral", state: "ready", provenance: "Synthetic PDF · checking statement · July 2026 · page 1", grade: "not_applicable", exactness: "exact", recordIds: ["demo-record-transfer-out-jul-02"], evidenceLinks: [{ targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "same_period", page: "page 1" }], sample: { date: { id: "date-2026-07-02", label: "July 2, 2026" }, account: { id: "account-everyday-checking", label: "Everyday checking" }, merchant: { id: "merchant-sample-transfer", label: "Sample transfer" }, category: { id: "category-transfer", label: "Transfer anatomy" }, tags: [{ id: "tag-related", label: "Related sample" }], nature: { id: "nature-transfer-example", label: "Transfer example" }, direction: { id: "direction-outgoing", label: "Outgoing" }, relationships: [{ targetActivityId: "sample-transfer-in-jul-02", label: "Sample transfer in" }] } },
  { id: "sample-transfer-in-jul-02", label: "Sample transfer in", exactValue: "250.00", display: "+$250.00", measure: "income", detail: "Jul 2 · fictional related movement", tone: "neutral", state: "ready", provenance: "Synthetic PDF · savings statement · July 2026 · page 1", grade: "not_applicable", exactness: "exact", recordIds: ["demo-record-transfer-in-jul-02"], evidenceLinks: [{ targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "same_period", page: "page 1" }], sample: { date: { id: "date-2026-07-02", label: "July 2, 2026" }, account: { id: "account-long-view-savings", label: "Long view savings" }, merchant: { id: "merchant-sample-transfer", label: "Sample transfer" }, category: { id: "category-transfer", label: "Transfer anatomy" }, tags: [{ id: "tag-related", label: "Related sample" }], nature: { id: "nature-transfer-example", label: "Transfer example" }, direction: { id: "direction-incoming", label: "Incoming" }, relationships: [{ targetActivityId: "sample-transfer-out-jul-02", label: "Sample transfer out" }] } },
];

const activityFilters: SampleActivityFilterCatalog = {
  dates: [{ id: "date-2026-05-14", label: "May 14, 2026" }, { id: "date-2026-06-24", label: "June 24, 2026" }, { id: "date-2026-06-28", label: "June 28, 2026" }, { id: "date-2026-07-02", label: "July 2, 2026" }],
  accounts: [{ id: "account-everyday-checking", label: "Everyday checking" }, { id: "account-taxable-brokerage", label: "Taxable Brokerage" }, { id: "account-long-view-savings", label: "Long view savings" }],
  merchants: [{ id: "merchant-orion-payroll", label: "Orion Payroll" }, { id: "merchant-city-utilities", label: "City Utilities" }, { id: "merchant-statement-reader", label: "Statement reader" }, { id: "merchant-sample-transfer", label: "Sample transfer" }],
  categories: [{ id: "category-income", label: "Income" }, { id: "category-home-utilities", label: "Home + utilities" }, { id: "category-document-review", label: "Document review" }, { id: "category-transfer", label: "Transfer anatomy" }],
  tags: [{ id: "tag-payroll", label: "Payroll" }, { id: "tag-home", label: "Home" }, { id: "tag-recurring", label: "Recurring" }, { id: "tag-held", label: "Held" }, { id: "tag-related", label: "Related sample" }],
  natures: [{ id: "nature-compensation", label: "Compensation" }, { id: "nature-household-bill", label: "Household bill" }, { id: "nature-statement-gap", label: "Statement gap" }, { id: "nature-transfer-example", label: "Transfer example" }],
  directions: [{ id: "direction-incoming", label: "Incoming" }, { id: "direction-outgoing", label: "Outgoing" }, { id: "direction-unavailable", label: "Direction unavailable" }],
};

export const demoSnapshot: SurfaceSnapshot = {
  mode: "demo",
  disclosure: {
    title: "Sample vault",
    subtitle: "Fictional sample data",
    detail: "Every name, document, and figure in this vault is fictional and stored with the app.",
  },
  overview: { state: "ready", data: {
    currentThrough: "July 31, 2026",
    coverage: "5 account families · 48 months represented",
    corpusCoverage: corpusCoverageLabel(syntheticCorpus),
    corpusSource: "Synthetic local corpus · generated from the merchant catalog",
    netWorth: {
    id: "demo-net-worth",
    display: "$48,240.18",
    exactValue: "48240.18",
    exactness: "exact",
    recordIds: ["demo-record-net-worth-2026-07"],
    currency: "USD",
    measure: "balance",
    grade: "corroborated",
    gradeLabel: "Corroborated",
    gradeDescription: "Supported by more than one source or matching record.",
    asOf: "July 31, 2026",
    coverage: "Synthetic checking and savings statements, Aug 2022–Jul 2026",
    caveats: ["One May statement page is still held for review."],
    evidenceLinks: [
      { targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "corroborates", page: "page 1" },
      { targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "corroborates", page: "page 1" },
    ],
  },
    accounts: [
    { id: "everyday-checking", name: "Everyday checking", kind: "Depository", measure: "balance", exactValue: "8240.18", currency: "USD", display: "$8,240.18", grade: "verified", gradeLabel: "Verified", gradeDescription: "Confirmed by a person or a completed verification step.", note: "Synthetic statement series current", asOf: "July 31, 2026", coverage: "Checking statements, Aug 2022–Jul 2026", provenance: "Synthetic PDF · checking statement · page 1", evidenceLinks: [
      { targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "same_account", page: "page 1" },
      { targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "same_period", page: "page 1" },
    ], state: "ready", exactness: "exact", recordIds: ["demo-record-everyday-checking"] },
    { id: "long-view-savings", name: "Long view savings", kind: "Depository", measure: "balance", exactValue: "40000.00", currency: "USD", display: "$40,000.00", grade: "corroborated", gradeLabel: "Corroborated", gradeDescription: "Supported by more than one source or matching record.", note: "Synthetic quarterly statements", asOf: "July 31, 2026", coverage: "Savings statements, Aug 2022–Jul 2026", provenance: "Synthetic PDF · savings statement · page 1", evidenceLinks: [
      { targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "same_account", page: "page 1" },
    ], state: "partial", exactness: "rounded", recordIds: ["demo-record-long-view-savings"] },
    { id: "harborline-sapphire", name: "Harborline Signature", kind: "Credit card", measure: "owed", exactValue: "1842.77", currency: "USD", display: "$1,842.77", grade: "verified", gradeLabel: "Verified", gradeDescription: "Confirmed by a person or a completed verification step.", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Harborline statements, Aug 2022–Jul 2026", provenance: "Synthetic PDF · Harborline card statement · page 1", evidenceLinks: [
      { targetDocumentId: "demo-doc-harborline-card-2026-07", label: "Harborline Signature card statement", relation: "same_account", page: "page 1" },
    ], state: "ready", exactness: "exact", recordIds: ["demo-record-harborline-sapphire"] },
    { id: "meridian-double-cash", name: "Meridian Everyday", kind: "Credit card", measure: "owed", exactValue: "620.14", currency: "USD", display: "$620.14", grade: "verified", gradeLabel: "Verified", gradeDescription: "Confirmed by a person or a completed verification step.", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Meridian statements, Aug 2022–Jul 2026", provenance: "Synthetic PDF · Meridian card statement · page 1", evidenceLinks: [
      { targetDocumentId: "demo-doc-meridian-card-2026-07", label: "Meridian Everyday card statement", relation: "same_account", page: "page 1" },
    ], state: "ready", exactness: "reported", recordIds: ["demo-record-meridian-double-cash"] },
    { id: "taxable-brokerage", name: "Taxable Brokerage", kind: "Brokerage", measure: "balance", exactValue: "18137.09", currency: "USD", display: "$18,137.09", grade: "corroborated", gradeLabel: "Corroborated", gradeDescription: "Supported by more than one source or matching record.", note: "Quarterly statements with holdings", asOf: "July 31, 2026", coverage: "Brokerage statements, Aug 2022–Jul 2026", provenance: "Synthetic PDF · brokerage statement · pages 1–2", evidenceLinks: [
      { targetDocumentId: "demo-doc-northgate-brokerage-2026-05-to-2026-07", label: "Taxable Brokerage statement", relation: "same_account", page: "pages 1–2" },
      { targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "corroborates", page: "page 1" },
    ], state: "partial", exactness: null, recordIds: ["demo-record-taxable-brokerage"] },
    ],
    recent: overviewActivityItems,
  } },
  review: { state: "ready", data: { queue: [
    { id: "merchant-category", label: "Merchant category", detail: "A grocery transaction needs a category decision.", status: "Fictional sample", action: "", type: "Merchant", evidence: "Card purchase on Jun 24", state: "needs_input", outcome: null, disposition: null, sample: { anatomy: "answer", evidenceLinks: [{ targetDocumentId: "demo-doc-silverline-checking-2026-06", label: "Everyday Checking June statement", relation: "settles_question", page: "page 1" }] } },
    { id: "duplicate-subscription", label: "Duplicate subscription", detail: "A fictional subscription question illustrates a set-aside boundary.", status: "Fictional sample", action: "", type: "Subscription", evidence: "Card statement, page 1", state: "needs_input", outcome: null, disposition: null, sample: { anatomy: "decline", evidenceLinks: [{ targetDocumentId: "demo-doc-harborline-card-2026-07", label: "Harborline Signature card statement", relation: "settles_question", page: "page 1" }] } },
    { id: "held-statement-page", label: "Held statement page", detail: "May brokerage page is still waiting for a human check.", status: "Fictional sample", action: "", type: "Document review", evidence: "Brokerage statement, pages 1–2", state: "needs_input", outcome: null, disposition: null, sample: { anatomy: "proposal", proposedValue: "Keep the fictional page held for review", evidenceLinks: [{ targetDocumentId: "demo-doc-northgate-brokerage-2026-05-to-2026-07", label: "Taxable Brokerage statement", relation: "settles_question", page: "pages 1–2" }] } },
    { id: "transfer-confirmation", label: "Transfer confirmation", detail: "A same-day transfer pair illustrates confirmation anatomy.", status: "Fictional sample", action: "", type: "Transfer", evidence: "Two fictional ledger entries, same day", state: "partial", outcome: null, disposition: null, sample: { anatomy: "confirmation", proposedValue: "Treat the fictional entries as one transfer", confirmationPrompt: "Confirm this fictional transfer proposal?", evidenceLinks: [{ targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "settles_question", page: "page 1" }] } },
  ], count: 4, meta: { total: 4, tail: { count: 0, amount: "0" }, pending: { count: 0 }, invite: "Tell me in your own words. This fictional sample cannot take one.", answeredByDocument: "A fictional document may illustrate supporting evidence" } } },
  documents: { state: "ready", data: { documents: [
    { id: "demo-doc-silverline-checking-2026-07", name: "silverline-checking-2026-07.pdf", state: "Verified", phase: "verified", phaseLabel: "Verified", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · checking statement · page 1", docType: "Checking statement", resolved: true, rawAvailable: true, sample: { region: "Page 1 · balance summary", contribution: "Fictional checking balance and July activity." }, evidenceLinks: [
      { targetDocumentId: "demo-doc-harborline-card-2026-07", label: "Harborline Signature card statement", relation: "same_period", page: "page 1" },
      { targetDocumentId: "demo-doc-meridian-card-2026-07", label: "Meridian Everyday card statement", relation: "same_period", page: "page 1" },
    ] },
    { id: "demo-doc-silverline-checking-2026-06", name: "silverline-checking-2026-06.pdf", state: "Captured", phase: "captured", phaseLabel: "Captured", detail: "Synthetic corpus · 2026-06-01 to 2026-06-30", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · checking statement · June 2026 · page 1", docType: "Checking statement", resolved: false, rawAvailable: true, sample: { region: "Page 1 · transaction table", contribution: "Fictional June paycheck and utility activity." }, evidenceLinks: [] },
    { id: "demo-doc-harborline-card-2026-07", name: "harborline-card-2026-07.pdf", state: "Reading", phase: "reading", phaseLabel: "Reading", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · Harborline card statement · page 1", docType: "Card statement", resolved: false, rawAvailable: true, sample: { region: "Page 1 · account summary" }, evidenceLinks: [
      { targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "same_period", page: "page 1" },
    ] },
    { id: "demo-doc-meridian-card-2026-07", name: "meridian-card-2026-07.pdf", state: "Parked", phase: "parked", phaseLabel: "Parked", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · Meridian card statement · page 1", docType: "Card statement", resolved: false, rawAvailable: true, sample: { waitReason: "This fictional sample has no supported way to continue reading it." }, evidenceLinks: [
      { targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "same_period", page: "page 1" },
    ] },
    { id: "demo-doc-north-river-savings-2026-05-to-2026-07", name: "north-river-savings-2026-05-to-2026-07.pdf", state: "Held", phase: "held", phaseLabel: "Held for review", detail: "Synthetic corpus · quarterly statement awaiting review", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · savings statement · page 1", docType: "Savings statement", resolved: false, rawAvailable: true, sample: { region: "Page 1 · quarterly summary", contribution: "Fictional savings balance.", waitReason: "A human decision is needed for the held statement." }, evidenceLinks: [
      { targetDocumentId: "demo-doc-silverline-checking-2026-07", label: "Everyday Checking statement", relation: "same_account", page: "page 1" },
      { targetDocumentId: "demo-doc-northgate-brokerage-2026-05-to-2026-07", label: "Taxable Brokerage statement", relation: "corroborates", page: "pages 1–2" },
    ] },
    { id: "demo-doc-northgate-brokerage-2026-05-to-2026-07", name: "northgate-brokerage-2026-05-to-2026-07.pdf", state: "Waiting", phase: "queued", phaseLabel: "Waiting for a reader", detail: "Synthetic corpus · holdings page available for review", source: "Generated locally", pages: "2 pages", provenance: "Synthetic PDF · brokerage statement · pages 1–2", docType: "Brokerage statement", resolved: false, rawAvailable: true, sample: { region: "Pages 1–2 · holdings", contribution: "Fictional brokerage holdings.", waitReason: "The captured original is waiting; this screen does not start reader work." }, evidenceLinks: [
      { targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07", label: "North River Savings statement", relation: "corroborates", page: "page 1" },
    ] },
    { id: "demo-doc-unresolved-tax-form-2026", name: "unresolved-tax-form-2026.pdf", state: "Needs resolution", phase: "unresolved", phaseLabel: "Needs resolution", detail: "Synthetic corpus · an identity field remains unresolved", source: "Generated locally", pages: "2 pages", provenance: "Synthetic PDF · tax form · page 1", docType: "Tax form", resolved: false, rawAvailable: true, sample: { region: "Page 1 · identity field", waitReason: "The sample says an issue remains unresolved." }, evidenceLinks: [] },
    { id: "demo-doc-read-complete-insurance-2026", name: "read-complete-insurance-2026.pdf", state: "Read complete", phase: "read_ready", phaseLabel: "Read complete", detail: "Synthetic corpus · a fictional read result is available", source: "Generated locally", pages: "3 pages", provenance: "Synthetic PDF · insurance summary · pages 1–3", docType: "Insurance summary", resolved: true, rawAvailable: true, sample: { region: "Pages 1–3 · policy summary", contribution: "Fictional policy summary." }, evidenceLinks: [] },
  ],
  captureQueue: [],
  processingJobs: [],
  outboundRecords: [] } },
  activity: { state: "ready", data: { items: activityItems, sample: { filters: activityFilters } } },
  conversation: { state: "ready", data: { turns: [], prompts: [], sample: { turns: [
    { id: "turn-1", speaker: "you", text: "Ask Viva what is still unclear about the current picture.", state: "prompt" },
    { id: "turn-2", speaker: "viva", text: "The sample includes July figures, and one brokerage statement page still needs a human decision.", state: "citation", citation: "Taxable Brokerage statement, pages 1–2" },
    { id: "turn-3", speaker: "you", text: "Can you tell me the exact answer to the merchant question?", state: "prompt" },
    { id: "turn-4", speaker: "viva", text: "I can point to the question and the evidence, but the category still needs your answer.", state: "refusal", citation: "Card purchase on Jun 24" },
  ], prompts: [
    { id: "prompt-1", label: "What changed this month?", detail: "Summarize the biggest movement with citations.", state: "ready" },
    { id: "prompt-2", label: "Why is this held?", detail: "Explain the refusal or uncertainty clearly.", state: "refusal" },
    { id: "prompt-3", label: "Show the evidence", detail: "Open the source that supports the answer.", state: "citation" },
  ] } } },
  trust: { state: "ready", data: { notes: [
    { id: "demo-trust-preview-boundary", title: "Preview boundary", detail: "This Trust destination describes the fictional sample and this interface’s current limitations. It is not a report about a private vault." },
    { id: "demo-trust-static-interactions", title: "Static interactions", detail: "Opening these rows changes only what is visible. It does not write a vault event, call a model, send data, or change a setting." },
  ], sample: { capabilities: [
    { id: "demo-trust-current-source-boundary", group: "source", label: "Current source boundary", state: "fictional_sample", detail: "This Trust destination is showing preview-owned explanations for the fictional sample. It is not a report about a private vault." },
    { id: "demo-trust-outbound-history", group: "outbound_models", label: "Outbound event history and purposes", state: "not_supplied", detail: "A complete outbound-event history and its purposes are not supplied by this preview. Missing history does not mean zero outbound events." },
    { id: "demo-trust-model-calls", group: "outbound_models", label: "Model calls and call budgets", state: "not_connected", detail: "Model-call history and call budgets are not connected to this Trust view." },
    { id: "demo-trust-provider-network", group: "outbound_models", label: "Provider and network permission", state: "not_connected", detail: "Provider identity and network permission are not connected to this Trust view." },
    { id: "demo-trust-maintenance", group: "outbound_models", label: "Maintenance actions, outcomes, and budgets", state: "not_connected", detail: "Maintenance history, outcomes, and budgets are not connected to this Trust view." },
    { id: "demo-trust-integrity", group: "integrity", label: "Vault integrity and hash-chain status", state: "not_supplied", detail: "No vault-integrity or hash-chain verification result is supplied. This preview cannot say a vault is intact." },
    { id: "demo-trust-anchoring", group: "integrity", label: "External anchoring", state: "not_implemented", detail: "External anchoring is not implemented by this preview, and no anchoring result is supplied." },
    { id: "demo-trust-export-backup", group: "continuity", label: "Vault export and backup", state: "not_connected", detail: "Export and backup status or actions are not connected. This screen cannot create either." },
    { id: "demo-trust-passphrase-recovery", group: "continuity", label: "Passphrase recovery", state: "not_supplied", detail: "Recovery capability is not supplied by this preview. Do not rely on recovery from this screen." },
    { id: "demo-trust-locale-currency", group: "continuity", label: "Locale and currency display settings", state: "not_connected", detail: "Locale and currency display values or controls are not connected to this Trust view." },
    { id: "demo-trust-build-versions", group: "build_support", label: "UI, sidecar, protocol, and build versions", state: "not_supplied", detail: "This Trust destination does not receive these versions. The Preview badge is not a version report." },
    { id: "demo-trust-update-recovery", group: "build_support", label: "Update recovery", state: "not_connected", detail: "Update status and recovery are not connected to this Trust view." },
    { id: "demo-trust-diagnostic-export", group: "build_support", label: "Diagnostic export", state: "not_implemented", detail: "A diagnostic export and its preview-before-writing flow are not implemented in this interface." },
  ] } } },
};
