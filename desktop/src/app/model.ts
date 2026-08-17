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

export type SurfaceDocument = {
  name: string;
  state: string;
  phase: DocumentPhase;
  phaseLabel: string;
  detail: string;
  source: string;
  pages: string;
  provenance: string;
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
    { id: "everyday-checking", name: "Everyday checking", kind: "Depository", measure: "balance", exactValue: "8240.18", currency: "USD", display: "$8,240.18", grade: "verified", gradeLabel: "Verified", note: "Synthetic statement series current", asOf: "July 31, 2026", coverage: "Checking statements, Aug 2022–Jul 2026", state: "ready" },
    { id: "long-view-savings", name: "Long view savings", kind: "Depository", measure: "balance", exactValue: "40000.00", currency: "USD", display: "$40,000.00", grade: "corroborated", gradeLabel: "Corroborated", note: "Synthetic quarterly statements", asOf: "July 31, 2026", coverage: "Savings statements, Aug 2022–Jul 2026", state: "partial" },
    { id: "chase-sapphire", name: "Chase Sapphire", kind: "Credit card", measure: "owed", exactValue: "1842.77", currency: "USD", display: "$1,842.77", grade: "verified", gradeLabel: "Verified", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Chase statements, Aug 2022–Jul 2026", state: "ready" },
    { id: "citi-double-cash", name: "Citi Double Cash", kind: "Credit card", measure: "owed", exactValue: "620.14", currency: "USD", display: "$620.14", grade: "verified", gradeLabel: "Verified", note: "Monthly statement series", asOf: "July 31, 2026", coverage: "Citi statements, Aug 2022–Jul 2026", state: "ready" },
    { id: "taxable-brokerage", name: "Taxable Brokerage", kind: "Brokerage", measure: "balance", exactValue: "18137.09", currency: "USD", display: "$18,137.09", grade: "corroborated", gradeLabel: "Corroborated", note: "Quarterly statements with holdings", asOf: "July 31, 2026", coverage: "Brokerage statements, Aug 2022–Jul 2026", state: "partial" },
  ],
  queue: [
    { id: "held-statement-page", label: "Held statement page", detail: "May brokerage page is still waiting for a human check.", status: "Held", action: "Open document", type: "Document review", evidence: "Brokerage statement, page 4", state: "needs_input", outcome: "waiting" },
    { id: "merchant-category", label: "Merchant category", detail: "A grocery transaction needs a category decision.", status: "Needs you", action: "Answer now", type: "Merchant", evidence: "Card purchase on Jun 24", state: "needs_input", outcome: "proposal" },
    { id: "transfer-confirmation", label: "Transfer confirmation", detail: "A same-day transfer pair is ready to confirm.", status: "Proposal", action: "Review proposal", type: "Transfer", evidence: "Two ledger entries, same day", state: "partial", outcome: "proposal" },
  ],
  recent: [
    { id: "paycheck-jun-28", label: "Paycheck", exactValue: "4800.00", display: "+$4,800.00", measure: "income", detail: "Jun 28 · Everyday checking", tone: "inflow", state: "ready", provenance: "Synthetic checking statement · page 1" },
    { id: "home-utilities-jun-24", label: "Home + utilities", exactValue: "1420.76", display: "−$1,420.76", measure: "spending", detail: "Jun 24 · categorized", tone: "outflow", state: "ready", provenance: "Synthetic checking statement · page 1" },
    { id: "statement-gap-may-14", label: "Statement gap", exactValue: "0.00", display: "Needs attention", measure: "spending", detail: "May 14 · one page held", tone: "neutral", state: "needs_input", provenance: "Synthetic brokerage statement · page 4" },
  ],
  reviewCount: 2,
  documents: [
    { name: "silverline-checking-2026-07.pdf", state: "Verified", phase: "verified", phaseLabel: "Verified read", detail: "Synthetic corpus · 2026-07-01 to 2026-07-31", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · checking statement · page 1" },
    { name: "north-river-savings-2026-05-to-2026-07.pdf", state: "Held", phase: "held", phaseLabel: "Held for review", detail: "Synthetic corpus · quarterly statement awaiting review", source: "Generated locally", pages: "1 page", provenance: "Synthetic PDF · savings statement · page 1" },
    { name: "fidelity-brokerage-2026-05-to-2026-07.pdf", state: "Pending", phase: "queued", phaseLabel: "Queued for reading", detail: "Synthetic corpus · holdings page available for review", source: "Generated locally", pages: "2 pages", provenance: "Synthetic PDF · brokerage statement · pages 1–2" },
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
