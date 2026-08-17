import { describe, expect, it } from "vitest";
import { demoState, destinations, nextDestination } from "./model";

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

  it("does not reinterpret navigation state", () => {
    expect(nextDestination("overview", "review")).toBe("review");
    expect(nextDestination("review", "review")).toBe("review");
  });
});
