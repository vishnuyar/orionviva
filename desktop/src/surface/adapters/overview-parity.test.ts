import { describe, expect, it } from "vitest";
// The same bytes the Python half reads, produced by running the real provider
// through the real dispatch. This side never authors them: a fixture written
// here would be a description of the contract this side wished for, and two
// sides each held to their own wish is the arrangement that let a figure and
// its citation stop crossing without a test going red.
import fixture from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
import { resolveEvidenceTarget } from "../evidence";
import type { DocumentsData, FeatureResult } from "../types";
import { adaptDocuments } from "./documents";
import { adaptOverview, adaptOverviewPanel } from "./overview";

const artifact = fixture as {
  artifact: string;
  protocol: string;
  reads: Record<string, { ok: boolean; result: { data: unknown } }>;
};

const overviewPayload = artifact.reads.overview.result.data;
// The rows as the backend wrote them, so every assertion below can compare
// what the interface shows against what it was given rather than against
// something restated here.
const payloadRows = new Map((overviewPayload as { accounts: Array<Record<string, any>> }).accounts.map((row) => [String(row.account), row]));
const documentsPayload = artifact.reads.documents.result.data;
const overview = adaptOverview(overviewPayload);
const documents: FeatureResult<DocumentsData> = { state: "ready", data: adaptDocuments(documentsPayload)! };
const MEASURES = ["balance", "owed"];
const LADDER = ["verified", "corroborated", "unverified", "conflicted"];

describe("the overview a real vault produces, read by the real adapter", () => {
  it("is the artifact this contract is written over", () => {
    expect(artifact.artifact).toBe("orionviva.overview-parity-v1");
    expect(artifact.reads.overview.ok).toBe(true);
    expect(overview).not.toBeNull();
    expect(overview!.accounts.length).toBe(8);
  });

  it("shows a person a number on every account", () => {
    for (const account of overview!.accounts) {
      expect(account.display.trim(), account.id).not.toBe("");
      expect(account.exactValue.trim(), account.id).not.toBe("");
      expect(account.currency.trim(), account.id).not.toBe("");
      expect(MEASURES, account.id).toContain(account.measure);
      expect(account.asOf.trim(), account.id).not.toBe("");
      expect(account.coverage?.trim() ?? "", account.id).not.toBe("");
      expect(account.exactness?.trim() ?? "", account.id).not.toBe("");
      expect(account.recordIds?.length ?? 0, account.id).toBeGreaterThan(0);
      expect(account.state, account.id).toBe("ready");
    }
  });

  it("writes no display string of its own", () => {
    for (const account of overview!.accounts) {
      expect(account.display).toBe(payloadRows.get(account.id)!.balance.display);
      expect(account.exactValue).toBe(payloadRows.get(account.id)!.balance.exact_value);
      expect(account.coverage).toBe(payloadRows.get(account.id)!.balance.coverage);
    }
  });

  it("gives every figure a route to the records the backend named, and claims nothing beside them", () => {
    for (const account of overview!.accounts) {
      const cited = payloadRows.get(account.id)!.balance.citations as Array<Record<string, string>>;
      expect(account.evidenceLinks.length, account.id).toBeGreaterThan(0);
      expect(account.evidenceLinks.length, account.id).toBe(cited.length);
      account.evidenceLinks.forEach((link, index) => {
        const target = resolveEvidenceTarget(documents, link.targetDocumentId);
        expect(target.state, `${account.id} → ${link.targetDocumentId}`).toBe("ready");
        // Every part of the citation is the backend's, including the parts it
        // left empty: a page or a label supplied here would be this side
        // saying where a number was printed.
        expect(link.targetDocumentId, account.id).toBe(cited[index].document_id);
        expect(link.relation, account.id).toBe(cited[index].relation);
        expect(link.page, account.id).toBe(cited[index].page);
        expect(link.label, account.id).toBe(cited[index].label);
      });
    }
  });

  it("shows the reviewed grade sentence the backend wrote, never one composed here", () => {
    for (const account of overview!.accounts) {
      const balance = payloadRows.get(account.id)!.balance;
      expect(LADDER, account.id).toContain(account.grade);
      // The ladder word and the whole reviewed sentence are two different
      // fields, and both are the backend's bytes. A sentence built here out
      // of the ladder word would differ from the one it was given, however
      // consistently it was built.
      expect(account.grade, account.id).toBe(balance.grade);
      expect(account.gradeLabel, account.id).toBe(balance.grade_label);
      expect(account.gradeDescription, account.id).toBe(balance.grade_description);
      expect(account.note, account.id).toBe(balance.grade_description);
      expect(account.gradeDescription.trim(), account.id).not.toBe("");
      expect(account.gradeDescription, account.id).not.toContain(`is ${account.gradeLabel}.`);
    }
  });

  it("states each figure's own boundary and no vault-wide count", () => {
    const coverages = overview!.accounts.map((account) => account.coverage);
    expect(new Set(coverages).size).toBe(coverages.length);
    for (const account of overview!.accounts) {
      expect(account.coverage, account.id).toContain(account.name);
      expect(account.coverage, account.id).toContain(account.asOf);
    }
  });

  it("lists no ledger bucket as an account", () => {
    for (const account of overview!.accounts) {
      expect(account.id.startsWith("Expenses:") || account.id.startsWith("Income:"), account.id).toBe(false);
    }
  });

  it("reports the panel state the read declared", () => {
    const withheld = overview!.accounts.filter((account) => account.state !== "ready");
    const panel = adaptOverviewPanel(overviewPayload);
    expect(panel.state).toBe(withheld.length ? "partial" : "ready");
    expect(panel.issues.length).toBe(withheld.length);
  });
});
