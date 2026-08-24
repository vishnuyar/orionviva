import { describe, expect, it } from "vitest";
import { accountEvidenceFigure, figurePrecision, gradePresentation, netWorthEvidenceFigure, resolveEvidenceFigure, resolveEvidenceTarget, type EvidenceFigureView } from "./evidence";
import type { AccountView, DocumentsData, FigureView, SurfaceSnapshot } from "./types";

const figure: FigureView = { id: "worth", display: "$10", exactValue: "10", currency: "USD", measure: "balance", grade: "verified", gradeLabel: "ignored", gradeDescription: "ignored", proofPresentation: { emphasis: "routine", reasons: [], qualifications: [] }, asOf: "today", coverage: ["all"], caveats: ["limit"], evidenceLinks: [], exactness: " EXACT ", recordIds: ["record-1"] };
const account: AccountView = { id: "account", name: "Card", kind: "card", measure: "owed", exactValue: "10", currency: "USD", display: "$10", grade: "conflicted", gradeLabel: "ignored", gradeDescription: "ignored", proofPresentation: { emphasis: "required", reasons: ["conflict"], qualifications: ["The records disagree."] }, note: null, asOf: "today", coverage: "month", provenance: "page 1", evidenceLinks: [], state: "ready", exactness: "rounded", recordIds: ["record-2"] };
const documents: DocumentsData = { documents: [{ id: "doc", name: "doc.pdf", state: "Verified", phaseLabel: "Verified", detail: "", source: "", pages: "1", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] };

function snapshot(accounts: AccountView[] = [account]): SurfaceSnapshot {
  return { disclosure: { title: "Private vault", subtitle: "Opened", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [figure], withheld: [], unplaced: [] }, accounts } }, documents: { state: "ready", data: documents }, review: { state: "absent", reason: "" }, activity: { state: "unavailable", reason: "not connected" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
}

describe("evidence figure projection", () => {
  it("classifies all precision states without exposing the raw token", () => {
    expect([" exact ", "ROUNDED", "estimate", "", null, undefined].map((value) => figurePrecision(value).state)).toEqual(["exact", "rounded", "unrecognized", "unavailable", "unavailable", "unavailable"]);
    expect(figurePrecision("secret-token")).not.toHaveProperty("value");
  });

  it("builds namespaced figures from typed views without exact values", () => {
    const built = [netWorthEvidenceFigure(figure), accountEvidenceFigure(account)];
    expect(built.map((item) => item.id)).toEqual(["net-worth:worth", "account:account"]);
    expect(built.map((item) => item.variant)).toEqual(["net-worth", "account-liability"]);
    expect(built.map((item) => item.label)).toEqual(["Net worth", "Card amount owed"]);
    expect(built.every((item) => !("exactValue" in item))).toBe(true);
    const contract: EvidenceFigureView = built[0];
    // @ts-expect-error evidence views cannot carry raw exact values
    contract.exactValue = "forbidden";
  });

  it("uses the calm fallback without formatting or calculating", () => {
    expect(accountEvidenceFigure({ ...account, display: "" }).display).toBe("Amount unavailable from this preview read.");
  });

  it("uses bounded base labels for blank account names while preserving measure meaning", () => {
    expect(accountEvidenceFigure({ ...account, name: "", measure: "balance" }).label).toBe("Account name unavailable balance");
    expect(accountEvidenceFigure({ ...account, name: " ", measure: "owed" }).label).toBe("Account name unavailable amount owed");
    expect(accountEvidenceFigure({ ...account, name: "", measure: null }).label).toBe("Account name unavailable");
  });

  it("preserves supplied financial grade copy and falls back independently", () => {
    const customLabel = "Backend attested — custom";
    const customDescription = "Verified by the private-vault attestation service.";
    expect(accountEvidenceFigure({ ...account, grade: "verified", gradeLabel: customLabel, gradeDescription: customDescription }).grade).toEqual({
      grade: "verified",
      label: customLabel,
      description: customDescription,
    });
    expect(netWorthEvidenceFigure({ ...figure, grade: "verified", gradeLabel: "", gradeDescription: customDescription }).grade).toEqual({
      grade: "verified",
      label: "Verified",
      description: customDescription,
    });
    expect(accountEvidenceFigure({ ...account, grade: "corroborated", gradeLabel: customLabel, gradeDescription: "  " }).grade).toEqual({
      grade: "corroborated",
      label: customLabel,
      description: gradePresentation("corroborated").description,
    });
    expect(accountEvidenceFigure({ ...account, grade: "unavailable", gradeLabel: customLabel, gradeDescription: customDescription }).grade).toEqual({
      grade: "unavailable",
      label: customLabel,
      description: customDescription,
    });
    expect(accountEvidenceFigure({ ...account, grade: "unavailable", gradeLabel: " ", gradeDescription: "" }).grade).toEqual(gradePresentation("unavailable"));
  });



  it("resolves document targets strictly by identity", () => {
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, "doc").state).toBe("ready");
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, " ").state).toBe("missing_identity");
    expect(resolveEvidenceTarget({ state: "unavailable", reason: "none" }, "doc").state).toBe("documents_unavailable");
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, "missing").state).toBe("missing_document");
    expect(resolveEvidenceTarget({ state: "ready", data: { ...documents, documents: [documents.documents[0], { ...documents.documents[0], name: "duplicate.pdf" }] } }, "doc").state).toBe("conflicted_identity");
  });
});
