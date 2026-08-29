import { describe, expect, it } from "vitest";
import type { FeatureResult, SurfaceRegistry } from "../surface/types";
import { destinations, standingCopy, standingOf } from "./navigation";

const registry = (served: Partial<Record<string, boolean>>, undeclared: string[] = []): FeatureResult<SurfaceRegistry> => ({
  state: "ready",
  data: {
    served: { overview: false, accounts: false, activity: false, documents: false, trust: false, ...served },
    undeclared: undeclared as SurfaceRegistry["undeclared"],
  },
});

describe("what a place a person can stand is owed", () => {
  it("says nothing about a destination whose read reaches it", () => {
    expect(standingOf(registry({ overview: true }), "overview")).toBe("served");
    expect(standingCopy.served).toBe("");
  });

  it("marks a destination the registry says no read reaches", () => {
    expect(standingOf(registry({}), "activity")).toBe("unserved");
    expect(standingCopy.unserved).toBeTruthy();
  });

  it("marks a screen this shell has and the registry never declared, differently", () => {
    expect(standingOf(registry({}, ["trust"]), "trust")).toBe("unclaimed");
    expect(standingCopy.unclaimed).not.toBe(standingCopy.unserved);
  });

  it("says nothing at all before the question has been put", () => {
    // A mark that appears on every destination while the answer is on its way
    // is a mark that stops meaning anything.
    expect(standingOf({ state: "absent", reason: "not_asked" }, "overview")).toBe("unasked");
    expect(standingOf({ state: "failed", reason: "read_failed" }, "overview")).toBe("unasked");
    expect(standingCopy.unasked).toBe("");
  });

  it("has a standing for every place it offers", () => {
    const registryRead = registry({ overview: true, documents: true });
    expect(destinations.map((item) => standingOf(registryRead, item.id))).toEqual([
      "served", "unserved", "unserved", "served", "unserved",
    ]);
  });
});
