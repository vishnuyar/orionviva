import { describe, expect, it } from "vitest";
import { demoState, destinations, nextDestination } from "./model";

describe("minimal shell model", () => {
  it("covers every first-slice destination", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "review", "trust"]);
  });

  it("keeps the demo figure backend-shaped and exact", () => {
    expect(demoState.netWorth.exactValue).toBe("48240.18");
    expect(typeof demoState.netWorth.exactValue).toBe("string");
    expect(demoState.netWorth.coverage).toContain("statements");
    expect(demoState.netWorth.caveats).toHaveLength(1);
  });

  it("does not reinterpret navigation state", () => {
    expect(nextDestination("overview", "review")).toBe("review");
    expect(nextDestination("review", "review")).toBe("review");
  });
});
