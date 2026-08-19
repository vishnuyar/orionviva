import { describe, expect, it } from "vitest";
import { gradePresentation } from "../evidence";
import { adaptOverview, adaptOverviewPanel } from "./overview";

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

  it("carries each supplied field on its own and leaves an absent one empty", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: { exact_value: "101.25", display: "USD 101.25", grade: "verified" } }] });
    expect(result?.accounts[0]).toMatchObject({ exactValue: "101.25", display: "USD 101.25", currency: "", coverage: null, provenance: null, measure: null });
  });

  it("keeps a complete canonical display byte-for-byte", () => {
    const display = "Canonical backend display — USD 202.50";
    const result = adaptOverview({ accounts: [{ account: "a", balance: { exact_value: "202.50", display, measure: "balance", currency: "USD", as_of: "2026-08-18", coverage: "Statement period", provenance: "Attested closing balance.", grade: "verified" } }] });
    expect(result?.accounts[0]).toMatchObject({ display, exactValue: "202.50", measure: "balance", currency: "USD", asOf: "2026-08-18", coverage: "Statement period", provenance: "Attested closing balance." });
  });

  it("carries a citation through as a route to its document", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: { citations: [
      { document_id: "doc-1", page: "7", label: "closing balance", relation: "attests" },
      { document_id: "doc-2", page: "", label: "", relation: "invented_relation" },
      { document_id: "", page: "3", label: "no identity", relation: "attests" },
    ] } }] });
    expect(result?.accounts[0].evidenceLinks).toEqual([{ targetDocumentId: "doc-1", page: "7", label: "closing balance", relation: "attests" }]);
  });

  it("carries exactness, record ids and caveats instead of dropping them", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: { exactness: "rounded", record_ids: ["acct:a", "doc-1", ""], caveats: ["One limit."] } }] });
    expect(result?.accounts[0]).toMatchObject({ exactness: "rounded", recordIds: ["acct:a", "doc-1"], caveats: ["One limit."] });
  });

  it("never composes the reviewed grade sentence out of the ladder word", () => {
    const sentence = "Read this answer as verified: the reviewed sentence the backend wrote.";
    const result = adaptOverview({ accounts: [{ account: "a", balance: { grade: "verified", grade_label: "verified", grade_description: sentence } }] });
    expect(result?.accounts[0]).toMatchObject({ gradeLabel: "verified", gradeDescription: sentence, note: sentence });
    expect(result?.accounts[0].gradeDescription).not.toContain(gradePresentation("verified").description);
  });

  it("marks a row whose figure the read withheld", () => {
    const result = adaptOverview({ accounts: [{ account: "a", balance: null }, { account: "b", balance: { exact_value: "1.00" } }] });
    expect(result?.accounts.map((account) => account.state)).toEqual(["partial", "ready"]);
    expect(result?.accounts[0].display).toBe("");
  });

  it("reads the panel state the read declares instead of assuming one", () => {
    expect(adaptOverviewPanel({ accounts: [] })).toEqual({ state: "ready", issues: [] });
    expect(adaptOverviewPanel({ state: "ready", issues: [] })).toEqual({ state: "ready", issues: [] });
    expect(adaptOverviewPanel({ state: "partial", issues: [{ code: "incomplete_figure", message: "Named reason." }, { code: "", message: "unnamed" }] }))
      .toEqual({ state: "partial", issues: [{ code: "incomplete_figure", message: "Named reason." }] });
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
