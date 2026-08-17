import { corpusCoverageLabel, syntheticCorpus } from "./synthetic";

export type Destination = "overview" | "accounts" | "activity" | "documents" | "review" | "trust";

export type FigureGrade = "verified" | "corroborated" | "unverified" | "conflicted";

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

export type DemoState = {
  currentThrough: string;
  coverage: string;
  corpusCoverage: string;
  corpusSource: string;
  netWorth: FigureView;
  accounts: Array<{ name: string; kind: string; display: string; grade: FigureGrade; note: string; asOf: string }>;
  queue: Array<{ label: string; detail: string; status: string; action: string; type: string; evidence: string }>;
  recent: Array<{ label: string; display: string; detail: string; tone: "inflow" | "outflow" | "neutral" }>;
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
    { name: "Everyday checking", kind: "Depository · balance", display: "$8,240.18", grade: "verified", note: "Synthetic statement series current", asOf: "July 31, 2026" },
    { name: "Long view savings", kind: "Depository · balance", display: "$40,000.00", grade: "corroborated", note: "Synthetic quarterly statements", asOf: "July 31, 2026" },
    { name: "Chase Sapphire", kind: "Credit card · owed", display: "$1,842.77", grade: "verified", note: "Monthly statement series", asOf: "July 31, 2026" },
    { name: "Citi Double Cash", kind: "Credit card · owed", display: "$620.14", grade: "verified", note: "Monthly statement series", asOf: "July 31, 2026" },
    { name: "Taxable Brokerage", kind: "Brokerage · balance", display: "$18,137.09", grade: "corroborated", note: "Quarterly statements with holdings", asOf: "July 31, 2026" },
  ],
  queue: [
    { label: "Held statement page", detail: "May brokerage page is still waiting for a human check.", status: "Held", action: "Open document", type: "Document review", evidence: "Brokerage statement, page 4" },
    { label: "Merchant category", detail: "A grocery transaction needs a category decision.", status: "Needs you", action: "Answer now", type: "Merchant", evidence: "Card purchase on Jun 24" },
    { label: "Transfer confirmation", detail: "A same-day transfer pair is ready to confirm.", status: "Proposal", action: "Review proposal", type: "Transfer", evidence: "Two ledger entries, same day" },
  ],
  recent: [
    { label: "Paycheck", display: "+$4,800.00", detail: "Jun 28 · Everyday checking", tone: "inflow" },
    { label: "Home + utilities", display: "−$1,420.76", detail: "Jun 24 · categorized", tone: "outflow" },
    { label: "Statement gap", display: "Needs attention", detail: "May 14 · one page held", tone: "neutral" },
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
