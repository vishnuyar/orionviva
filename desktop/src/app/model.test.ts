import { describe, expect, it } from "vitest";
import { demoState, destinations, nextDestination } from "./model";
import { corpusCoverageLabel, syntheticCorpus } from "./synthetic";

describe("minimal shell model", () => {
  it("covers every first-slice destination", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "review", "trust"]);
    expect(destinations.map((item) => item.label)).toEqual(["Overview", "Accounts", "Activity", "Documents", "Review", "Trust"]);
    expect(destinations.map((item) => item.eyebrow)).toEqual(["Your picture", "Where money sits", "What moved", "What supports it", "What needs you", "How it works"]);
  });

  it("keeps the demo figure backend-shaped and exact", () => {
    expect(demoState.netWorth.exactValue).toBe("48240.18");
    expect(typeof demoState.netWorth.exactValue).toBe("string");
    expect(demoState.netWorth.coverage).toContain("statements");
    expect(demoState.netWorth.caveats).toHaveLength(1);
  });

  it("keeps the demo surface aligned with the current document and review slices", () => {
    expect(demoState.reviewCount).toBe(2);
    expect(demoState.documents.map((doc) => doc.state)).toEqual(["Verified", "Held", "Pending"]);
    expect(demoState.queue.map((item) => item.type)).toEqual(["Document review", "Merchant", "Transfer"]);
    expect(demoState.recent.map((item) => item.tone)).toEqual(["inflow", "outflow", "neutral"]);
    expect(demoState.trustNotes).toHaveLength(3);
  });

  it("projects the four-year synthetic corpus without inventing backend facts", () => {
    expect(syntheticCorpus.documentCount).toBe(176);
    expect(syntheticCorpus.range).toEqual({ from: "2022-08-01", to: "2026-07-31" });
    expect(syntheticCorpus.accountFamilies).toHaveLength(5);
    expect(syntheticCorpus.documents.at(-1)?.pages).toBe("2 pages");
    expect(corpusCoverageLabel(syntheticCorpus)).toContain("176 synthetic documents");
    expect(demoState.corpusSource).toContain("Synthetic local corpus");
  });

  it("does not reinterpret navigation state", () => {
    expect(nextDestination("overview", "review")).toBe("review");
    expect(nextDestination("review", "review")).toBe("review");
  });
});
