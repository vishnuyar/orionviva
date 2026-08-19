export type SyntheticDocument = {
  name: string;
  kind: string;
  family: string;
  institution: string;
  account: string;
  period: string;
  pages: string;
  merchants: string[];
};

export type SyntheticCorpus = {
  generatedAt: string;
  sourceCatalog: string;
  purpose: string;
  range: { from: string; to: string };
  documentCount: number;
  accountFamilies: string[];
  documents: SyntheticDocument[];
};

// Deliberately small UI projection of output/pdf/synthetic_statements_4y/manifest.json.
// The generator remains the source of truth; tests keep this snapshot honest.
export const syntheticCorpus: SyntheticCorpus = {
  generatedAt: "2026-08-17",
  sourceCatalog: "/Users/vishnu/Downloads/catalog.json",
  purpose: "four-year synthetic statement corpus for local UI and document-processing tests",
  range: { from: "2022-08-01", to: "2026-07-31" },
  documentCount: 176,
  accountFamilies: ["checking-monthly", "harborline-card-monthly", "meridian-card-monthly", "savings-quarterly", "brokerage-quarterly"],
  documents: [
    { name: "silverline-checking-2026-07.pdf", kind: "bank_statement", family: "checking-monthly", institution: "Silverline Bank", account: "Everyday Checking", period: "2026-07-01 to 2026-07-31", pages: "1 page", merchants: ["Ridgeline Servicing", "Harborline", "Meridian", "Saffron Grocers", "Valuemart", "Riverbend Market", "Voltway Charging", "Cityhop Ride"] },
    { name: "harborline-card-2026-07.pdf", kind: "credit_card_statement", family: "harborline-card-monthly", institution: "Harborline", account: "Harborline Signature", period: "2026-07-01 to 2026-07-31", pages: "1 page", merchants: ["Harborline", "Saffron Grocers", "Riverbend Market", "Voltway Charging", "Cityhop Ride"] },
    { name: "meridian-card-2026-07.pdf", kind: "credit_card_statement", family: "meridian-card-monthly", institution: "Meridian", account: "Meridian Everyday", period: "2026-07-01 to 2026-07-31", pages: "1 page", merchants: ["Meridian", "Lunchline", "Brightpath", "Clearwave", "Elmwood Dental"] },
    { name: "north-river-savings-2026-05-to-2026-07.pdf", kind: "bank_statement", family: "savings-quarterly", institution: "Silverline Bank", account: "North River Savings", period: "2026-05-01 to 2026-07-31", pages: "1 page", merchants: ["Interest", "Transfer from checking", "Redemption Credit"] },
    { name: "northgate-brokerage-2026-05-to-2026-07.pdf", kind: "brokerage_statement", family: "brokerage-quarterly", institution: "Northgate Investments", account: "Taxable Brokerage", period: "2026-05-01 to 2026-07-31", pages: "2 pages", merchants: ["Northgate Brokerage Services", "Cashlink", "Dividend"] },
  ],
};

export function corpusCoverageLabel(corpus: SyntheticCorpus): string {
  return `${corpus.accountFamilies.length} account families · ${corpus.documentCount} synthetic documents · ${corpus.range.from.slice(0, 4)}–${corpus.range.to.slice(0, 4)}`;
}
