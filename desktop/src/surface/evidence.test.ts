import { describe, expect, it } from "vitest";
import { accountEvidenceFigure, activityEvidenceFigure, figurePrecision, gradePresentation, netWorthEvidenceFigure, resolveEvidenceFigure, resolveEvidenceTarget, type EvidenceFigureView } from "./evidence";
import type { AccountView, ActivityView, DocumentsData, FigureView, SurfaceSnapshot } from "./types";

const figure: FigureView = { id: "worth", display: "$10", exactValue: "10", currency: "USD", measure: "balance", grade: "verified", gradeLabel: "ignored", gradeDescription: "ignored", asOf: "today", coverage: ["all"], caveats: ["limit"], evidenceLinks: [], exactness: " EXACT ", recordIds: ["record-1"] };
const account: AccountView = { id: "account", name: "Card", kind: "card", measure: "owed", exactValue: "10", currency: "USD", display: "$10", grade: "conflicted", gradeLabel: "ignored", gradeDescription: "ignored", note: null, asOf: "today", coverage: "month", provenance: "page 1", evidenceLinks: [], state: "ready", exactness: "rounded", recordIds: ["record-2"] };
const activity: ActivityView = { id: "activity", label: "Paycheck", exactValue: "10", display: "+$10", measure: "income", detail: "detail", tone: "outflow", state: "ready", provenance: "page 2", evidenceLinks: [], grade: "not_applicable", exactness: "mystery", recordIds: ["record-3"] };
const documents: DocumentsData = { documents: [{ id: "doc", name: "doc.pdf", state: "Verified", phaseLabel: "Verified", detail: "", source: "", pages: "1", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] };

function snapshot(accounts: AccountView[] = [account], activityItems: ActivityView[] | null = [activity], recent: ActivityView[] = [activity]): SurfaceSnapshot {
  return { mode: "live", disclosure: { title: "Private vault", subtitle: "Opened", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [figure], withheld: [], unplaced: [] }, corpusCoverage: "", accounts, recent } }, documents: { state: "ready", data: documents }, review: { state: "absent", reason: "" }, activity: activityItems === null ? { state: "unavailable", reason: "not connected" } : { state: "ready", data: { items: activityItems } }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
}

describe("evidence figure projection", () => {
  it("classifies all precision states without exposing the raw token", () => {
    expect([" exact ", "ROUNDED", "estimate", "", null, undefined].map((value) => figurePrecision(value).state)).toEqual(["exact", "rounded", "unrecognized", "unavailable", "unavailable", "unavailable"]);
    expect(figurePrecision("secret-token")).not.toHaveProperty("value");
  });

  it("builds namespaced figures from typed views without exact values", () => {
    const built = [netWorthEvidenceFigure(figure), accountEvidenceFigure(account), activityEvidenceFigure(activity)];
    expect(built.map((item) => item.id)).toEqual(["net-worth:worth", "account:account", "activity:activity"]);
    expect(built.map((item) => item.variant)).toEqual(["net-worth", "account-liability", "activity-income"]);
    expect(built.map((item) => item.label)).toEqual(["Net worth", "Card amount owed", "Paycheck income"]);
    expect(built.every((item) => !("exactValue" in item))).toBe(true);
    expect(built[2].grade).toEqual(gradePresentation("not_applicable"));
    const contract: EvidenceFigureView = built[0];
    // @ts-expect-error evidence views cannot carry raw exact values
    contract.exactValue = "forbidden";
  });

  it("uses the calm fallback without formatting or calculating", () => {
    expect(accountEvidenceFigure({ ...account, display: "" }).display).toBe("Amount unavailable from this preview read.");
  });

  it("uses bounded base labels for blank account and activity names while preserving measure meaning", () => {
    expect(accountEvidenceFigure({ ...account, name: "", measure: "balance" }).label).toBe("Account name unavailable balance");
    expect(accountEvidenceFigure({ ...account, name: " ", measure: "owed" }).label).toBe("Account name unavailable amount owed");
    expect(accountEvidenceFigure({ ...account, name: "", measure: null }).label).toBe("Account name unavailable");
    expect(activityEvidenceFigure({ ...activity, label: "", measure: "income" }).label).toBe("Activity label unavailable income");
    expect(activityEvidenceFigure({ ...activity, label: " ", measure: "spending" }).label).toBe("Activity label unavailable spending");
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
    expect(activityEvidenceFigure(activity).grade).toEqual(gradePresentation("not_applicable"));
  });

  it("refuses duplicate account and canonical activity identities", () => {
    expect(resolveEvidenceFigure(snapshot([account, { ...account }]), "account:account").state).toBe("conflicted");
    expect(resolveEvidenceFigure(snapshot([account, { ...account, display: "$11" }]), "account:account").state).toBe("conflicted");
    expect(resolveEvidenceFigure(snapshot([account], [activity, { ...activity }]), "activity:activity").state).toBe("conflicted");
    expect(resolveEvidenceFigure(snapshot([account], [activity, { ...activity, display: "+$11" }]), "activity:activity").state).toBe("conflicted");
    expect(resolveEvidenceFigure(snapshot(), "account:missing").state).toBe("missing");
  });

  it("uses the data-bearing activity surface as canonical and otherwise falls back to overview recent", () => {
    expect(resolveEvidenceFigure(snapshot([account], [activity], [activity]), "activity:activity").state).toBe("ready");
    expect(resolveEvidenceFigure(snapshot([account], null, [activity]), "activity:activity").state).toBe("ready");
    expect(resolveEvidenceFigure(snapshot([account], [], [activity]), "activity:activity").state).toBe("missing");
  });

  it("resolves document targets strictly by identity", () => {
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, "doc").state).toBe("ready");
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, " ").state).toBe("missing_identity");
    expect(resolveEvidenceTarget({ state: "unavailable", reason: "none" }, "doc").state).toBe("documents_unavailable");
    expect(resolveEvidenceTarget({ state: "ready", data: documents }, "missing").state).toBe("missing_document");
    expect(resolveEvidenceTarget({ state: "ready", data: { ...documents, documents: [documents.documents[0], { ...documents.documents[0], name: "duplicate.pdf" }] } }, "doc").state).toBe("conflicted_identity");
  });
});
