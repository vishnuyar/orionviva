import { describe, expect, it } from "vitest";
import { documentById } from "../evidence";
import type { FeatureResult, SurfaceDocument } from "../types";
import { demoSnapshot } from "./demo-snapshot";
import { corpusCoverageLabel, syntheticCorpus } from "./synthetic-corpus";

function dataOf<T>(result: FeatureResult<T>): T {
  if (result.state === "ready" || result.state === "partial" || result.state === "needs_input") return result.data;
  throw new Error(`Expected fixture data, received ${result.state}`);
}
const overview = dataOf(demoSnapshot.overview);
const documents = dataOf(demoSnapshot.documents);
const review = dataOf(demoSnapshot.review);
const activity = dataOf(demoSnapshot.activity);
const conversation = dataOf(demoSnapshot.conversation);
const trust = dataOf(demoSnapshot.trust);

describe("minimal shell model", () => {
  it("keeps the demo figure backend-shaped and exact", () => {
    expect(overview.picture.figures[0]?.exactValue).toBe("48240.18");
    expect(typeof overview.picture.figures[0]?.exactValue).toBe("string");
    expect(overview.picture.figures[0]?.coverage[0]).toContain("statements");
    expect(overview.picture.figures[0]?.caveats).toHaveLength(1);
  });

  it("keeps the demo surface aligned with the current document and review slices", () => {
    expect(review.count).toBe(4);
    expect(documents.documents.map((doc) => doc.state)).toEqual(["Verified", "Captured", "Reading", "Parked", "Held", "Waiting", "Needs resolution", "Read complete"]);
    expect(review.queue.map((item) => item.type)).toEqual(["Merchant", "Subscription", "Document review", "Transfer"]);
    expect(review.queue.map((item) => item.sample?.anatomy)).toEqual(["answer", "decline", "proposal", "confirmation"]);
    expect(activity.items.map((item) => item.tone)).toEqual(["inflow", "outflow", "neutral", "neutral", "neutral"]);
    expect(documents.captureQueue).toEqual([]);
    expect(documents.processingJobs).toEqual([]);
    expect(documents.outboundRecords).toEqual([]);
    expect(conversation.turns).toEqual([]);
    expect(conversation.prompts).toEqual([]);
    expect(conversation.sample?.turns.map((turn) => turn.state)).toEqual(["prompt", "citation", "prompt", "refusal"]);
    expect(conversation.sample?.turns.find((turn) => turn.id === "turn-2")).toMatchObject({
      text: "The sample includes July figures, and one brokerage statement page still needs a human decision.",
      citation: "Taxable Brokerage statement, pages 1–2",
    });
    expect(conversation.sample?.turns.some((turn) => turn.text.includes("picture is complete") || turn.citation === "Brokerage statement, page 4")).toBe(false);
    expect(conversation.sample?.prompts.map((prompt) => prompt.state)).toEqual(["ready", "refusal", "citation"]);
    expect(trust.notes).toEqual([
      { id: "demo-trust-preview-boundary", title: "Preview boundary", detail: "This Trust destination describes the fictional sample and this interface’s current limitations. It is not a report about a private vault." },
      { id: "demo-trust-static-interactions", title: "Static interactions", detail: "Opening these rows changes only what is visible. It does not write a vault event, call a model, send data, or change a setting." },
    ]);
    expect(trust.sample?.capabilities).toHaveLength(13);
    expect(new Set(trust.notes.map((note) => note.id)).size).toBe(trust.notes.length);
    expect(new Set(trust.sample?.capabilities.map((capability) => capability.id)).size).toBe(trust.sample?.capabilities.length);
    expect(new Set(trust.sample?.capabilities.map((capability) => capability.group))).toEqual(new Set(["source", "outbound_models", "integrity", "continuity", "build_support"]));
    expect(new Set(trust.sample?.capabilities.map((capability) => capability.state))).toEqual(new Set(["fictional_sample", "not_connected", "not_supplied", "not_implemented"]));
  });

  it("keeps capture, reading, and verification as separate document phases", () => {
    expect(documents.documents.map((doc) => doc.phase)).toEqual(["verified", "captured", "reading", "parked", "held", "queued", "unresolved", "read_ready"]);
    expect(documents.documents.map((doc) => doc.phaseLabel)).toEqual(["Verified", "Captured", "Reading", "Parked", "Held for review", "Waiting for a reader", "Needs resolution", "Read complete"]);
    expect(documents.documents.every((doc) => doc.provenance.includes("Synthetic PDF"))).toBe(true);
  });

  it("uses backend-shaped read models for each financial surface", () => {
    expect(overview.accounts.every((account) => account.exactValue === account.exactValue.trim())).toBe(true);
    expect(overview.accounts.map((account) => account.measure)).toEqual(["balance", "balance", "owed", "owed", "balance"]);
    expect(overview.accounts.every((account) => ["ready", "partial"].includes(account.state))).toBe(true);
    expect(activity.items.map((item) => item.measure)).toEqual(["income", "spending", "spending", "spending", "income"]);
    expect(activity.items.every((item) => item.grade === "not_applicable")).toBe(true);
    expect(activity.items.every((item) => item.recordIds?.length)).toBe(true);
    expect(overview.accounts.every((account) => account.recordIds?.length)).toBe(true);
    expect(overview.picture.figures[0]?.recordIds?.length).toBeGreaterThan(0);
    expect(activity.items.every((item) => item.provenance.length > 0)).toBe(true);
    expect(activity.items.every((item) => item.sample?.date && item.sample.account && item.sample.merchant && item.sample.category && item.sample.tags?.length && item.sample.nature && item.sample.direction)).toBe(true);
    expect(review.queue.every((item) => item.outcome === null && item.disposition === null)).toBe(true);
  });

  it("keeps evidence links explicit and navigable by document identity", () => {
    const brokerage = documentById(documents.documents, "demo-doc-northgate-brokerage-2026-05-to-2026-07");
    expect(brokerage?.evidenceLinks).toHaveLength(1);
    expect(brokerage?.evidenceLinks[0]).toMatchObject({
      targetDocumentId: "demo-doc-north-river-savings-2026-05-to-2026-07",
      relation: "corroborates",
      page: "page 1",
    });
    expect(documents.documents.every((doc) => doc.evidenceLinks.every((link) => link.targetDocumentId !== doc.id))).toBe(true);
    expect(overview.picture.figures[0]?.evidenceLinks.length).toBeGreaterThan(0);
    expect(overview.accounts.every((account) => account.evidenceLinks.length > 0)).toBe(true);
    expect(activity.items.every((activity) => activity.evidenceLinks.length > 0)).toBe(true);
  });

  it("anchors June checking activity to the fictional June statement period", () => {
    const juneDocument = documentById(documents.documents, "demo-doc-silverline-checking-2026-06");
    expect(juneDocument).toMatchObject({
      name: "silverline-checking-2026-06.pdf",
      detail: "Synthetic corpus · 2026-06-01 to 2026-06-30",
      pages: "1 page",
      provenance: "Synthetic PDF · checking statement · June 2026 · page 1",
    });

    for (const activityId of ["paycheck-jun-28", "home-utilities-jun-24"]) {
      const activityItem = activity.items.find((item) => item.id === activityId);
      expect(activityItem?.provenance).toBe(juneDocument?.provenance);
      expect(activityItem?.evidenceLinks).toEqual([
        expect.objectContaining({ targetDocumentId: juneDocument?.id, page: "page 1" }),
      ]);
      expect(activityItem?.evidenceLinks[0].targetDocumentId).not.toBe("demo-doc-silverline-checking-2026-07");
    }
  });

  it("keeps Overview recent movements canonical and relationship rows Activity-only", () => {
    for (const recent of overview.recent) {
      const matches = activity.items.filter((item) => item.id === recent.id);
      expect(matches).toHaveLength(1);
      expect(matches[0]).toBe(recent);
    }
    expect(overview.recent.map((item) => item.id)).toEqual(["paycheck-jun-28", "home-utilities-jun-24", "statement-gap-may-14"]);
    expect(activity.items.slice(3).map((item) => item.id)).toEqual(["sample-transfer-out-jul-02", "sample-transfer-in-jul-02"]);
    expect(activity.items.slice(3).map((item) => item.sample?.relationships?.[0].targetActivityId)).toEqual(["sample-transfer-in-jul-02", "sample-transfer-out-jul-02"]);
    expect(activity.sample?.filters?.directions.map((facet) => facet.id)).toEqual(["direction-incoming", "direction-outgoing", "direction-unavailable"]);
  });

  it("projects the four-year synthetic corpus without inventing backend facts", () => {
    expect(syntheticCorpus.documentCount).toBe(176);
    expect(syntheticCorpus.range).toEqual({ from: "2022-08-01", to: "2026-07-31" });
    expect(syntheticCorpus.accountFamilies).toHaveLength(5);
    expect(syntheticCorpus.documents.at(-1)?.pages).toBe("2 pages");
    expect(corpusCoverageLabel(syntheticCorpus)).toContain("176 synthetic documents");
  });

  it("routes duplicate document names by target id after reorder", () => {
    const base = documents.documents[0];
    const reordered: SurfaceDocument[] = [
      { ...base, id: "document-b", name: "duplicate.pdf", evidenceLinks: [] },
      { ...base, id: "document-a", name: "duplicate.pdf", evidenceLinks: [] },
    ];
    const link = { targetDocumentId: "document-a", label: "Exact target", relation: "same_period" as const, page: "page 1" };

    expect(documentById(reordered, link.targetDocumentId)?.id).toBe("document-a");
    expect(documentById(reordered.reverse(), link.targetDocumentId)?.id).toBe("document-a");
  });

  it("keeps the complete surface graph referentially intact", () => {
    const documentIds = new Set(documents.documents.map((doc) => doc.id));
    const ids = [
      ...overview.accounts.map((account) => account.id),
      ...activity.items.map((item) => item.id),
      ...review.queue.map((item) => item.id),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    expect(documentIds.size).toBe(documents.documents.length);
    const allEvidenceLinks = [
      ...overview.picture.figures.flatMap((figure) => figure.evidenceLinks),
      ...overview.accounts.flatMap((account) => account.evidenceLinks),
      ...activity.items.flatMap((activity) => activity.evidenceLinks),
      ...documents.documents.flatMap((doc) => doc.evidenceLinks),
      ...review.queue.flatMap((question) => question.sample?.evidenceLinks ?? []),
    ];
    expect(allEvidenceLinks.every((link) => documentIds.has(link.targetDocumentId))).toBe(true);
  });
});
