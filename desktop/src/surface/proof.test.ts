import { describe, expect, it } from "vitest";
import { showCompactProof } from "./evidence";

describe("compact proof visibility", () => {
  it("depends on emphasis and the local boolean, not machine reasons", () => {
    expect(showCompactProof({ emphasis: "routine", reasons: [], qualifications: [] }, false)).toBe(false);
    expect(showCompactProof({ emphasis: "routine", reasons: [], qualifications: [] }, true)).toBe(true);
    expect(showCompactProof({ emphasis: "required", reasons: ["verified", "routine"], qualifications: ["Backend line one."] }, false)).toBe(true);
    expect(showCompactProof({ emphasis: "required", reasons: ["conflict"], qualifications: ["Backend line two."] }, true)).toBe(true);
  });
});
