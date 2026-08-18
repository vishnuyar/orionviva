import { corpusCoverageLabel, syntheticCorpus } from "./synthetic";

export type Destination = "overview" | "accounts" | "activity" | "documents" | "review" | "trust";

export type FigureGrade = "verified" | "corroborated" | "unverified" | "conflicted";
export type PanelState = "absent" | "ready" | "partial" | "needs_input" | "unavailable" | "failed";
export type ActionOutcome = "completed" | "refused" | "proposal" | "waiting" | "stale";

export type FigureView = {
  id: string;
  display: string;
  exactValue: string;
  currency: string;
  measure: "balance" | "owed" | "spending" | "income";
  grade: FigureGrade;
  gradeLabel: string;
  asOf: string;
  coverage: string;
  caveats: string[];
};

export type DocumentPhase = "captured" | "queued" | "held" | "read_ready" | "verified" | "unresolved";

export type EvidenceLink = {
  documentName: string;
  label: string;
  relation: "same_period" | "same_account" | "settles_question" | "corroborates";
  page: string;
};

export type SurfaceDocument = {
  name: string;
  state: string;
  phase: DocumentPhase;
  phaseLabel: string;
  detail: string;
  source: string;
  pages: string;
  provenance: string;
  evidenceLinks: EvidenceLink[];
};

export type DocumentCapture = {
  id: string;
  label: string;
  state: "captured" | "processing" | "held" | "ready" | "sent";
  detail: string;
  source: string;
  note: string;
};

export type DocumentJob = {
  id: string;
  label: string;
  state: "running" | "paused" | "done";
  detail: string;
  progress: string;
};

export type OutboundRecord = {
  id: string;
  label: string;
  state: "queued" | "sent" | "blocked";
  detail: string;
  destination: string;
};

export type AccountView = {
  id: string;
  name: string;
  kind: string;
  measure: "balance" | "owed";
  exactValue: string;
  currency: string;
  display: string;
  grade: FigureGrade;
  gradeLabel: string;
  note: string;
  asOf: string;
  coverage: string;
  evidenceLinks: EvidenceLink[];
  state: PanelState;
};

export type ActivityView = {
  id: string;
  label: string;
  exactValue: string;
  display: string;
  measure: "income" | "spending";
  detail: string;
  tone: "inflow" | "outflow" | "neutral";
  state: PanelState;
  provenance: string;
};

export type ReviewView = {
  id: string;
  label: string;
  detail: string;
  status: string;
  action: string;
  type: string;
  evidence: string;
  state: "needs_input" | "partial";
  outcome: ActionOutcome;
  disposition: "answer" | "decline" | "proposal" | "confirm";
};

export type ConversationTurn = {
  id: string;
  speaker: "you" | "viva";
  text: string;
  state: "answer" | "refusal" | "citation" | "prompt";
  citation?: string;
};

export type ConversationPrompt = {
  id: string;
  label: string;
  detail: string;
  state: "ready" | "refusal" | "citation";
};

export type DemoState = {
  currentThrough: string;
  coverage: string;
  corpusCoverage: string;
  corpusSource: string;
  netWorth: FigureView;
  accounts: AccountView[];
  queue: ReviewView[];
  recent: ActivityView[];
  reviewCount: number;
  documents: SurfaceDocument[];
  captureQueue: DocumentCapture[];
  processingJobs: DocumentJob[];
  outboundRecords: OutboundRecord[];
  conversationTurns: ConversationTurn[];
  conversationPrompts: ConversationPrompt[];
  trustNotes: Array<{ title: string; detail: string }>;
};

export const demoState: DemoState = {
  currentThrough: "July 31, 2026",
  coverage: "5 account families · 48 months represented",
  corpusCoverage: corpusCoverageLabel(syntheticCorpus),
  corpusSource: "Synthetic local corpus · generated from the merchant catalog",
  netWorth: {
    id: "demo-net-worth",
    display: "$48,240.18",
    exactValue: "48240.18",
    currency: "USD",
    measure: "balance",
    grade: "corroborated",
    gradeLabel: "Corroborated",
    asOf: "July 31, 2026",
    coverage: "Synthetic checking and savings statements, Aug 2022–Jul 2026",
    caveats: ["One May statement page is still held for review."],
  },
  accounts: [
    { id: "everyday-checking", name: "Everyday checking", kind: "Depository", measure: "balance", exactValue: "8240.18", currency: "USD", display: "$8,240.18", grade: "verified", gradeLabel: "Verified", note: "Synthetic statement series current", asOf: "July 31, 2026", coverage: "Checking statements, Aug 2022–Jul 2026", evidenceLinks: [
      { documentName: "silverline-checking-2026-07.pdf", label: "Everyday Checking statement", relation: "same_account", page: "page 1" },
      { documentName: "north-river-savings-2026-05-to-2026-07.pdf", label: "North River Savings statement", relation: "same_period", page: "page 1" },
    ], state: "ready" },
    { id: "long-view-savings", name: "Long view savings", kind: "Depository", measure: "balance", exactValue: "40000.00", currency: "USD", display: "$40,000.00", grade: "corroborated", gradeLabel: "Corroborated", note: "Synthetic quarterly statements", asOf: "July 31, 2026", coverage: "Savings statements, Aug 2022–Jul 2026", evidenceLinks: [
      { documentName: "north-river-savings-2026-05-to-2026-07.pdf", label: "North River Savings statement", relation: "same_account", page: "page 1" },
    ], state: "partial" },
    { id: "chase-sapphire", name: "Chase Sapphire", kind: "Credit card", measure: "owed", exactValue: "1842.77", currency: "USD", display: "$1,842.77", grade: "verified", gradeLabel: "Verified", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Chase statements, Aug 2022–Jul 2026", evidenceLinks: [
      { documentName: "chase-card-2026-07.pdf", label: "Chase Sapphire card statement", relation: "same_account", page: "page 1" },
    ], state: "ready" },
    { id: "citi-double-cash", name: "Citi Double Cash", kind: "Credit card", measure: "owed", exactValue: "620.14", currency: "USD", display: "$620.14", grade: "verified", gradeLabel: "Verified", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Citi statements, Aug 2022–Jul 2026", evidenceLinks: [
      { documentName: "citi-card-2026-07.pdf", label: "Citi Double Cash card statement", relation: "same_account", page: "page 1" },
    ], state: "ready" },
    { id: "taxable-brokerage", name: "Taxable Brokerage", kind: "Brokerage", measure: "balance", exactValue: "18137.09", currency: "USD", display: "$18,137.09", grade: "corroborated", gradeLabel: "Corroborated", note: "Quarterly statements with holdings", asOf: "July 31, 2026", coverage: "Brokerage statements, Aug 2022–Jul 2026", evidenceLinks: [
      { documentName: "fidelity-brokerage-2026-05-to-2026-07.pdf", label: "Taxable Brokerage statement", relation: "same_account", page: "pages 1–2" },
      { documentName: "north-river-savings-2026-05-to-2026-07.pdf", label: "North River Savings statement", relation: "corroborates", page: "page 1" },
    ], state: "partial" },
  ],
  queue: [
    { id: "held-statement-page", label: "Held statement page", detail: "May brokerage page is still waiting for a human check.", status: "Held", action: "Open document", type: "Document review", evidence: "Brokerage statement, page 4", state: "needs_input", outcome: "waiting", disposition: "proposal" },
    { id: "merchant-category", label: "Merchant category", detail: "A grocery transaction needs a category decision.", status: "Needs you", action: "Answer now", type: "Merchant", evidence: "Card purchase on Jun 24", state: "needs_input", outcome: "proposal", disposition: "answer" },
    { id: "transfer-confirmation", label: "Transfer confirmation", detail: "A same-day transfer pair is ready to confirm.", status: "Proposal", action: "Review proposal", type: "Transfer", evidence: "Two ledger entries, same day", state: "partial", outcome: "proposal", disposition: "confirm" },
  ],
  recent: [
    { id: "paycheck-jun-28", label: "Paycheck", exactValue: "4800.00", display: "+$4,800.00", measure: "income", detail: "Jun 28 · Everyday checking", tone: "inflow", state: "ready", provenance: "Synthetic checking statement · page 1" },
    { id: "home-utilities-jun-24", label: "Home + utilities", exactValue: "1420.76", display: "−$1,420.76", measure: "spending", detail: "Jun 24 · categorized", tone: "outflow", state: "ready", provenance: "Synthetic checking statement · page 1" },
    { id: "statement-gap-may-14", label: "Statement gap", exactValue: "0.00", display: "Needs attention", measure: "spending", detail: "May 14 · one page held", tone: "neutral", state: "needs_input", provenance: "Synthetic brokerage statement · page 4" },
  ],
  reviewCount: 2,
  documents: [
    { name: "silverline-checking-2026-07.pdf", state: "Verified", phase: "verified", phaseLabel: "Verified read", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · checking statement · page 1", evidenceLinks: [
      { documentName: "chase-card-2026-07.pdf", label: "Chase Sapphire card statement", relation: "same_period", page: "page 1" },
      { documentName: "citi-card-2026-07.pdf", label: "Citi Double Cash card statement", relation: "same_period", page: "page 1" },
    ] },
    { name: "chase-card-2026-07.pdf", state: "Verified", phase: "verified", phaseLabel: "Verified read", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · Chase card statement · page 1", evidenceLinks: [
      { documentName: "silverline-checking-2026-07.pdf", label: "Everyday Checking statement", relation: "same_period", page: "page 1" },
    ] },
    { name: "citi-card-2026-07.pdf", state: "Verified", phase: "verified", phaseLabel: "Verified read", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · Citi card statement · page 1", evidenceLinks: [
      { documentName: "silverline-checking-2026-07.pdf", label: "Everyday Checking statement", relation: "same_period", page: "page 1" },
    ] },
    { name: "north-river-savings-2026-05-to-2026-07.pdf", state: "Held", phase: "held", phaseLabel: "Held for review", detail: "Synthetic corpus · quarterly statement awaiting review", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · savings statement · page 1", evidenceLinks: [
      { documentName: "silverline-checking-2026-07.pdf", label: "Everyday Checking statement", relation: "same_account", page: "page 1" },
      { documentName: "fidelity-brokerage-2026-05-to-2026-07.pdf", label: "Taxable Brokerage statement", relation: "corroborates", page: "pages 1–2" },
    ] },
    { name: "fidelity-brokerage-2026-05-to-2026-07.pdf", state: "Pending", phase: "queued", phaseLabel: "Queued for reading", detail: "Synthetic corpus · holdings page available for review", source: "Generated locally", pages: "2 pages", provenance: "Synthetic PDF · brokerage statement · pages 1–2", evidenceLinks: [
      { documentName: "north-river-savings-2026-05-to-2026-07.pdf", label: "North River Savings statement", relation: "corroborates", page: "page 1" },
    ] },
  ],
  captureQueue: [
    { id: "capture-envelope", label: "Envelope inbox", state: "captured", detail: "Local file drop queued for private import.", source: "Watched folder", note: "No network calls" },
    { id: "capture-read", label: "Read worker", state: "processing", detail: "Text and page images are being staged for the document reader.", source: "Desktop preview", note: "Retry-safe processing" },
    { id: "capture-held", label: "Held page", state: "held", detail: "A brokerage page remains parked until a human confirms it.", source: "Synthetic corpus", note: "Review stops posting" },
    { id: "capture-ready", label: "Ready to post", state: "ready", detail: "Verified documents can be turned into outbound records.", source: "Opened vault", note: "Outbound still explicit" },
  ],
  processingJobs: [
    { id: "job-parse", label: "Parse new statement", state: "running", detail: "Reader is extracting lines and dates from the dropped file.", progress: "62% complete" },
    { id: "job-recover", label: "Restart recovery", state: "paused", detail: "The previous session was interrupted and will resume from the saved job marker.", progress: "Waiting for relaunch" },
    { id: "job-verify", label: "Verification pass", state: "done", detail: "Arithmetic and provenance checks have already finished for the current batch.", progress: "All checks green" },
  ],
  outboundRecords: [
    { id: "outbound-ledger", label: "Ledger event", state: "sent", detail: "Verified document facts are ready to be posted back into the ledger.", destination: "Document ledger" },
    { id: "outbound-review", label: "Review prompt", state: "queued", detail: "A held page will ask for a human ruling before it becomes fact.", destination: "Review queue" },
    { id: "outbound-export", label: "Export bundle", state: "blocked", detail: "Outbound export stays blocked until the document is fully verified.", destination: "Local archive" },
  ],
  conversationTurns: [
    { id: "turn-1", speaker: "you", text: "Ask Viva what is still unclear about the current picture.", state: "prompt" },
    { id: "turn-2", speaker: "viva", text: "The picture is complete for the current month, but the held brokerage page still needs a human decision.", state: "citation", citation: "Brokerage statement, page 4" },
    { id: "turn-3", speaker: "you", text: "Can you tell me the exact answer to the merchant question?", state: "prompt" },
    { id: "turn-4", speaker: "viva", text: "I can point to the question and the evidence, but the category still needs your answer.", state: "refusal", citation: "Card purchase on Jun 24" },
  ],
  conversationPrompts: [
    { id: "prompt-1", label: "What changed this month?", detail: "Summarize the biggest movement with citations.", state: "ready" },
    { id: "prompt-2", label: "Why is this held?", detail: "Explain the refusal or uncertainty clearly.", state: "refusal" },
    { id: "prompt-3", label: "Show the evidence", detail: "Open the source that supports the answer.", state: "citation" },
  ],
  trustNotes: [
    { title: "Local by default", detail: "This synthetic corpus is generated and inspected on this device; it makes no network calls." },
    { title: "No silent inference", detail: "Uncertainty stays visible in the figure and the queue." },
    { title: "Anchoring status", detail: "The ledger is hash-chained in the full product; this preview only mirrors the contract." },
  ],
};

export const destinations: Array<{ id: Destination; label: string; eyebrow: string }> = [
  { id: "overview", label: "Overview", eyebrow: "Your picture" },
  { id: "accounts", label: "Accounts", eyebrow: "Where money sits" },
  { id: "activity", label: "Activity", eyebrow: "What moved" },
  { id: "documents", label: "Documents", eyebrow: "What supports it" },
  { id: "review", label: "Review", eyebrow: "What needs you" },
  { id: "trust", label: "Trust", eyebrow: "How it works" },
];

export function nextDestination(current: Destination, destination: Destination): Destination {
  return current === destination ? current : destination;
}
