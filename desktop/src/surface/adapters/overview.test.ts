import { describe, expect, it } from "vitest";
import { gradePresentation } from "../evidence";
import { adaptOverview } from "./overview";

describe("overview adapter", () => {
  it("rejects malformed payloads", () => {
    expect(adaptOverview(null)).toBeNull();
    expect(adaptOverview([])).toBeNull();
    expect(adaptOverview({})).toBeNull();
    expect(adaptOverview({ wrong: [] })).toBeNull();
    expect(adaptOverview({ accounts: "not-an-array" })).toBeNull();
    expect(adaptOverview({ accounts: [{ name: "missing stable id" }] })).toBeNull();
    expect(adaptOverview({ accounts: [{ account: "a", balance: "invalid" }] })).toBeNull();
  });

  it("accepts only an explicit empty reviewed overview collection", () => {
    expect(adaptOverview({ accounts: [] })).toEqual({ currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "Opened local vault", netWorth: null, accounts: [], recent: [] });
  });

  it("uses stable returned ids and removes duplicates after reorder", () => {
    const result = adaptOverview({ accounts: [{ account: "b" }, { account: "a" }, { account: "b" }] });
    expect(result?.accounts.map((account) => account.id)).toEqual(["b", "a"]);
  });

  it("withholds incomplete raw amounts", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: { amount: "101.25", display: "SHOULD NOT RENDER", grade: "verified" } }] });
    expect(result?.accounts[0]).toMatchObject({ exactValue: "101.25", display: "" });
  });

  it("keeps a complete canonical display byte-for-byte", () => {
    const display = "Canonical backend display — USD 202.50";
    const result = adaptOverview({ accounts: [{ account: "a", balance: { amount: "202.50", display, measure: "balance", currency: "USD", dated: "2026-08-18", coverage: "Statement period", provenance: "document live-doc, page 7", grade: "verified" } }] });
    expect(result?.accounts[0].display).toBe(display);
  });

  it("prefers a non-empty reviewed grade label", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: { grade: "verified", grade_label: "Reviewed wording" } }] });
    expect(result?.accounts[0]).toMatchObject({ grade: "verified", gradeLabel: "Reviewed wording" });
  });

  it("falls back for empty grade labels without inferring from the label", () => {
    const result = adaptOverview({ accounts: [
      { account: "empty", balance: { grade: "unverified", grade_label: "   " } },
      { account: "unknown", balance: { grade: "unknown", grade_label: "Custom wording" } },
      { account: "unknown-empty", balance: { grade: "unknown", grade_label: "" } },
    ] });
    expect(result?.accounts[0]).toMatchObject({ grade: "unverified", gradeLabel: "Not yet verified" });
    expect(result?.accounts[1]).toMatchObject({ grade: "unavailable", gradeLabel: "Custom wording" });
    expect(result?.accounts[2]).toMatchObject({ grade: "unavailable", gradeLabel: "Evidence status unavailable" });
  });

  it("maps every reviewed grade and unknown explicitly", () => {
    expect(["verified", "corroborated", "unverified", "conflicted", "other"].map((grade) => gradePresentation(grade).label)).toEqual(["Verified", "Corroborated", "Not yet verified", "Conflicting evidence", "Evidence status unavailable"]);
    expect(gradePresentation(undefined).description).toMatch(/did not provide/i);
  });
});
