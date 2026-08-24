import { describe, expect, it } from "vitest";
import moments from "../../../../product/viva/persona/pack-v33/moments.json";
import { gradePresentation, showCompactProof } from "../evidence";
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
    expect(adaptOverview({ accounts: [] })).toEqual({ picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [] });
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

  it("accepts only the complete empty routine invariant and fails every malformed variant visible", () => {
    const result = adaptOverview({ accounts: [
      { account: "routine", balance: { proof_presentation: { emphasis: "routine", reasons: [], qualifications: [] } } },
      { account: "required", balance: { proof_presentation: { emphasis: "required", reasons: ["conflict"], qualifications: ["The records disagree."] } } },
      { account: "routine-reason", balance: { proof_presentation: { emphasis: "routine", reasons: ["conflict"], qualifications: [] } } },
      { account: "routine-qualification", balance: { proof_presentation: { emphasis: "routine", reasons: [], qualifications: ["A required line."] } } },
      { account: "missing-reasons", balance: { proof_presentation: { emphasis: "routine", qualifications: [] } } },
      { account: "missing-qualifications", balance: { proof_presentation: { emphasis: "routine", reasons: [] } } },
      { account: "malformed-reasons", balance: { proof_presentation: { emphasis: "routine", reasons: "none", qualifications: [] } } },
      { account: "malformed-qualifications", balance: { proof_presentation: { emphasis: "routine", reasons: [], qualifications: ["kept", 3] } } },
      { account: "missing", balance: {} },
      { account: "unknown", balance: { proof_presentation: { emphasis: "invented", reasons: ["machine_only"], qualifications: ["Backend line."] } } },
      { account: "malformed", balance: { proof_presentation: "routine" } },
    ] });
    expect(result?.accounts.map((account) => account.proofPresentation)).toEqual([
      { emphasis: "routine", reasons: [], qualifications: [] },
      { emphasis: "required", reasons: ["conflict"], qualifications: ["The records disagree."] },
      { emphasis: "required", reasons: ["conflict"], qualifications: [] },
      { emphasis: "required", reasons: [], qualifications: ["A required line."] },
      { emphasis: "required", reasons: [], qualifications: [] },
      { emphasis: "required", reasons: [], qualifications: [] },
      { emphasis: "required", reasons: [], qualifications: [] },
      { emphasis: "required", reasons: [], qualifications: ["kept"] },
      { emphasis: "required", reasons: [], qualifications: [] },
      { emphasis: "required", reasons: ["machine_only"], qualifications: ["Backend line."] },
      { emphasis: "required", reasons: [], qualifications: [] },
    ]);
  });

  it("keeps reviewed qualifications visible off for caveat, inexact, mixed or stale, and missing-basis wire cases", () => {
    const fixtures = [
      { id: "caveated", reasons: ["caveat"], qualifications: ["A supplied caveat changes how this figure should be used."], extra: { caveats: ["A supplied caveat changes how this figure should be used."] } },
      { id: "inexact", reasons: ["inexact"], qualifications: [moments.proof_inexact], extra: { exactness: "rounded" } },
      { id: "mixed-stale", reasons: ["mixed_vintage", "stale_boundary"], qualifications: [moments.proof_mixed_vintage, moments.proof_stale_boundary], extra: { as_of: "2025-11-30" } },
      { id: "missing-basis", reasons: ["uncertain_basis"], qualifications: [moments.stood_behind_unverified], extra: {} },
    ];
    const result = adaptOverview({ accounts: fixtures.map((fixture) => ({
      account: fixture.id,
      balance: { ...fixture.extra, proof_presentation: { emphasis: "required", reasons: fixture.reasons, qualifications: fixture.qualifications } },
    })) });

    expect(result).not.toBeNull();
    result!.accounts.forEach((account, index) => {
      expect(account.proofPresentation.qualifications, account.id).toEqual(fixtures[index].qualifications);
      expect(showCompactProof(account.proofPresentation, false), account.id).toBe(true);
    });
    expect(result!.accounts[0].caveats).toEqual(fixtures[0].qualifications);
    expect(result!.accounts[1].exactness).toBe("rounded");
    expect(result!.accounts[2].proofPresentation.reasons).toEqual(["mixed_vintage", "stale_boundary"]);
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

  // The picture crosses whole and nothing on this side writes any of it: the
  // sentence, the two dates and every figure field are the backend's bytes.
  it("carries the picture block the read composed and writes none of it", () => {
    const coverage = "This total covers a set the backend named and this side did not.";
    const figureCoverage = "This part of the picture is over a boundary the backend declared.";
    const result = adaptOverview({ accounts: [], picture: { coverage, read_on: "2026-08-21", figures: [
      { id: "AAA", display: "AAA 1.00", exact_value: "1.00", currency: "AAA", measure: "net_worth", grade: "corroborated", grade_label: "corroborated", grade_description: "One reviewed sentence.", proof_presentation: { emphasis: "routine", reasons: [], qualifications: [] }, as_of: "2026-08-21", coverage: [figureCoverage], unmeasured: [{ account: "acct:unvalued", name: "An account written by the read", sentence: "The reviewed sentence for why it is not in this total." }, { account: "", name: "No identity", sentence: "About nothing." }, { account: "acct:no-sentence", name: "No sentence" }, { account: "acct:no-name", sentence: "No name." }], boundary: { unmeasured: [{ account: "acct:unvalued", reason: "unobserved", settled_by: "unreviewed ledger text" }] }, exactness: "exact", record_ids: ["acct:one", ""], caveats: [], citations: [{ document_id: "doc-1", relation: "attests", page: "", label: "" }], evidence_label: "A reviewed sentence naming the control.", evidence_heading: "A reviewed heading naming the drawer." },
    ] } });
    expect(result?.picture).toEqual({ coverage, readOn: "2026-08-21", withheld: [], unplaced: [], figures: [
      { id: "AAA", display: "AAA 1.00", exactValue: "1.00", currency: "AAA", measure: "net_worth", grade: "corroborated", gradeLabel: "corroborated", gradeDescription: "One reviewed sentence.", proofPresentation: { emphasis: "routine", reasons: [], qualifications: [] }, asOf: "2026-08-21", coverage: [figureCoverage], caveats: [], evidenceLinks: [{ targetDocumentId: "doc-1", relation: "attests", page: "", label: "" }], exactness: "exact", recordIds: ["acct:one"], evidenceLabel: "A reviewed sentence naming the control.", evidenceHeading: "A reviewed heading naming the drawer.", unmeasured: [{ account: "acct:unvalued", name: "An account written by the read", sentence: "The reviewed sentence for why it is not in this total." }] },
    ] });
  });

  // One figure per currency, kept apart by the identity the read gave each of
  // them. A figure with no identity, or measuring something this side has no
  // label for, is left out rather than shown with a hole in it.
  it("keeps one figure per currency and leaves out one it cannot name", () => {
    const result = adaptOverview({ accounts: [], picture: { figures: [
      { id: "AAA", measure: "net_worth" },
      { id: "BBB", measure: "net_worth" },
      { id: "", measure: "net_worth" },
      { id: "CCC", measure: "invented_measure" },
      { id: "DDD" },
    ] } });
    expect(result?.picture.figures.map((figure) => figure.id)).toEqual(["AAA", "BBB"]);
  });

  it("renders an unrecognised grade word as the unavailable state without guessing", () => {
    const result = adaptOverview({ accounts: [], picture: { figures: [{ id: "AAA", measure: "net_worth", grade: "invented_grade", grade_label: "" }] } });
    expect(result?.picture.figures[0]).toMatchObject({ grade: "unavailable", gradeLabel: "Evidence status unavailable" });
  });

  // One sentence per currency kept back, in the order the read wrote them and
  // never composed here.
  it("carries a sentence for each currency the read kept back, with the currency beside it", () => {
    const kept = [
      { currency: "AAA", sentence: "A sentence about one currency kept back." },
      { currency: "BBB", sentence: "A sentence about another." },
    ];
    // An entry carrying no sentence would render as a blank where a total
    // would have been, which says less than saying nothing.
    const supplied = [...kept, { currency: "CCC", sentence: "  " }, { currency: "DDD" }];
    expect(adaptOverview({ accounts: [], picture: { withheld: supplied } })?.picture.withheld).toEqual(kept);
  });

  // The accounts the read could not place under any currency. Each carries the
  // name it is written under and the sentence saying why it is in no total;
  // an entry missing any of the three is left out rather than shown as a name
  // with no reason or a reason about nothing.
  it("carries the accounts the read could not place", () => {
    const unplaced = [
      { account: "acct:one", name: "A Named Liability", reason: "a_machine_word", sentence: "The read's sentence about it." },
      { account: "acct:two", name: "No sentence" },
      { account: "acct:three", sentence: "No name." },
      { account: "", name: "No identity", sentence: "About nothing." },
    ];
    const result = adaptOverview({ accounts: [], picture: { unplaced } });
    expect(result?.picture.unplaced).toEqual([{ account: "acct:one", name: "A Named Liability", sentence: "The read's sentence about it." }]);
  });

  it("carries an empty picture where the read composed none", () => {
    expect(adaptOverview({ accounts: [], picture: { coverage: "", figures: [] } })?.picture).toEqual({ coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] });
    expect(adaptOverview({ accounts: [] })?.picture).toEqual({ coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] });
  });

  it("maps every reviewed grade and unknown explicitly", () => {
    expect(["verified", "corroborated", "unverified", "conflicted", "other"].map((grade) => gradePresentation(grade).label)).toEqual(["Verified", "Corroborated", "Not yet verified", "Conflicting evidence", "Evidence status unavailable"]);
    expect(gradePresentation(undefined).description).toMatch(/did not provide/i);
  });
});
