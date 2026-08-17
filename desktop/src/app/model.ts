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

export type DemoState = {
  currentThrough: string;
  coverage: string;
  netWorth: FigureView;
  accounts: Array<{ name: string; kind: string; display: string; grade: FigureGrade; note: string }>;
  recent: Array<{ label: string; display: string; detail: string; tone: "inflow" | "outflow" | "neutral" }>;
  reviewCount: number;
  documents: Array<{ name: string; state: string; detail: string }>;
};

export const demoState: DemoState = {
  currentThrough: "June 30, 2026",
  coverage: "2 accounts · 91% of the period attested",
  netWorth: {
    id: "demo-net-worth",
    display: "$48,240.18",
    exactValue: "48240.18",
    currency: "USD",
    measure: "balance",
    grade: "corroborated",
    gradeLabel: "Corroborated",
    asOf: "June 30, 2026",
    coverage: "Checking and savings statements, Jan–Jun 2026",
    caveats: ["One May statement page is still held for review."],
  },
  accounts: [
    { name: "Everyday checking", kind: "Depository · balance", display: "$8,240.18", grade: "verified", note: "Current through Jun 30" },
    { name: "Long view savings", kind: "Depository · balance", display: "$40,000.00", grade: "corroborated", note: "Current through Jun 30" },
  ],
  recent: [
    { label: "Paycheck", display: "+$4,800.00", detail: "Jun 28 · Everyday checking", tone: "inflow" },
    { label: "Home + utilities", display: "−$1,420.76", detail: "Jun 24 · categorized", tone: "outflow" },
    { label: "Statement gap", display: "Needs attention", detail: "May 14 · one page held", tone: "neutral" },
  ],
  reviewCount: 2,
  documents: [
    { name: "everyday-checking-june.pdf", state: "Verified", detail: "Captured Jun 30 · 8 pages" },
    { name: "savings-may.pdf", state: "Held", detail: "Captured Jun 30 · page 4 needs review" },
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
