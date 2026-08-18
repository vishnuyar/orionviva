import { describe, expect, it } from "vitest";
import { demoState, destinations, nextDestination } from "./model";
import { corpusCoverageLabel, syntheticCorpus } from "./synthetic";
import { readSurface, syntheticSurfaceData } from "./data";

describe("minimal shell model", () => {
  it("covers every first-slice destination", () => {
    expect(destinations.map((item) => item.id)).toEqual(["overview", "accounts", "activity", "documents", "review", "trust"]);
    expect(destinations.map((item) => item.label)).toEqual(["Overview", "Accounts", "Activity", "Documents", "Review", "Trust"]);
    expect(destinations.map((item) => item.eyebrow)).toEqual(["Your picture", "Where money sits", "What moved", "What supports it", "What needs you", "How it works"]);
  });

  it("keeps the demo figure backend-shaped and exact", () => {
    expect(demoState.netWorth.exactValue).toBe("48240.18");
    expect(typeof demoState.netWorth.exactValue).toBe("string");
    expect(demoState.netWorth.coverage).toContain("statements");
    expect(demoState.netWorth.caveats).toHaveLength(1);
  });

  it("keeps the demo surface aligned with the current document and review slices", () => {
    expect(demoState.reviewCount).toBe(2);
    expect(demoState.documents.map((doc) => doc.state)).toEqual(["Verified", "Verified", "Verified", "Held", "Pending"]);
    expect(demoState.queue.map((item) => item.type)).toEqual(["Document review", "Merchant", "Transfer"]);
    expect(demoState.queue.map((item) => item.disposition)).toEqual(["proposal", "answer", "confirm"]);
    expect(demoState.recent.map((item) => item.tone)).toEqual(["inflow", "outflow", "neutral"]);
    expect(demoState.captureQueue.map((item) => item.state)).toEqual(["captured", "processing", "held", "ready"]);
    expect(demoState.processingJobs.map((job) => job.state)).toEqual(["running", "paused", "done"]);
    expect(demoState.outboundRecords.map((record) => record.state)).toEqual(["sent", "queued", "blocked"]);
    expect(demoState.conversationTurns.map((turn) => turn.state)).toEqual(["prompt", "citation", "prompt", "refusal"]);
    expect(demoState.conversationPrompts.map((prompt) => prompt.state)).toEqual(["ready", "refusal", "citation"]);
    expect(demoState.trustNotes).toHaveLength(3);
  });

  it("keeps capture, reading, and verification as separate document phases", () => {
    expect(demoState.documents.map((doc) => doc.phase)).toEqual(["verified", "verified", "verified", "held", "queued"]);
    expect(demoState.documents.map((doc) => doc.phaseLabel)).toEqual(["Verified read", "Verified read", "Verified read", "Held for review", "Queued for reading"]);
    expect(demoState.documents.every((doc) => doc.provenance.includes("Synthetic PDF"))).toBe(true);
  });

  it("uses backend-shaped read models for each financial surface", () => {
    expect(demoState.accounts.every((account) => account.exactValue === account.exactValue.trim())).toBe(true);
    expect(demoState.accounts.map((account) => account.measure)).toEqual(["balance", "balance", "owed", "owed", "balance"]);
    expect(demoState.accounts.every((account) => ["ready", "partial"].includes(account.state))).toBe(true);
    expect(demoState.recent.map((item) => item.measure)).toEqual(["income", "spending", "spending"]);
    expect(demoState.recent.every((item) => item.provenance.length > 0)).toBe(true);
    expect(demoState.queue.map((item) => item.outcome)).toEqual(["waiting", "proposal", "proposal"]);
  });

  it("keeps evidence links explicit and navigable by document identity", () => {
    const brokerage = demoState.documents.find((doc) => doc.name.startsWith("fidelity-brokerage"));
    expect(brokerage?.evidenceLinks).toHaveLength(1);
    expect(brokerage?.evidenceLinks[0]).toMatchObject({
      documentName: "north-river-savings-2026-05-to-2026-07.pdf",
      relation: "corroborates",
      page: "page 1",
    });
    expect(demoState.documents.every((doc) => doc.evidenceLinks.every((link) => link.documentName !== doc.name))).toBe(true);
  });

  it("projects the four-year synthetic corpus without inventing backend facts", () => {
    expect(syntheticCorpus.documentCount).toBe(176);
    expect(syntheticCorpus.range).toEqual({ from: "2022-08-01", to: "2026-07-31" });
    expect(syntheticCorpus.accountFamilies).toHaveLength(5);
    expect(syntheticCorpus.documents.at(-1)?.pages).toBe("2 pages");
    expect(corpusCoverageLabel(syntheticCorpus)).toContain("176 synthetic documents");
    expect(demoState.corpusSource).toContain("Synthetic local corpus");
  });

  it("does not reinterpret navigation state", () => {
    expect(nextDestination("overview", "review")).toBe("review");
    expect(nextDestination("review", "review")).toBe("review");
  });

  it("provides one typed snapshot boundary for the shell", async () => {
    const snapshot = await readSurface(syntheticSurfaceData);
    expect(syntheticSurfaceData.id).toBe("synthetic-demo");
    expect(syntheticSurfaceData.label).toBe("Synthetic local corpus");
    expect(snapshot).toBe(await readSurface(syntheticSurfaceData));
    expect(snapshot.documents.length).toBeGreaterThan(0);
    expect(snapshot.accounts.length).toBeGreaterThan(0);
    expect(snapshot.recent.every((item) => item.provenance.length > 0)).toBe(true);
  });

  it("keeps the complete surface graph referentially intact", () => {
    const documentNames = new Set(demoState.documents.map((doc) => doc.name));
    const ids = [
      ...demoState.accounts.map((account) => account.id),
      ...demoState.recent.map((item) => item.id),
      ...demoState.queue.map((item) => item.id),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    expect(demoState.documents.every((doc) => doc.evidenceLinks.every((link) => documentNames.has(link.documentName)))).toBe(true);
    expect(destinations.map((item) => item.id)).toHaveLength(new Set(destinations.map((item) => item.id)).size);
  });
});
