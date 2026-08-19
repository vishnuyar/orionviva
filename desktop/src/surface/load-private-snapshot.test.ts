import { describe, expect, it } from "vitest";
import type { BridgeClient, SurfaceName } from "../bridge/contracts";
import { loadPrivateSnapshot } from "./load-private-snapshot";
import { demoSource, privateSource } from "./sources";

function client(data: Partial<Record<SurfaceName, unknown>> = {}): BridgeClient {
  const defaults: Record<SurfaceName, unknown> = { overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } };
  const read = async (surface: SurfaceName) => ({ surface, job_id: `test-${surface}`, data: surface in data ? data[surface] : defaults[surface] });
  return { openVault: async () => undefined, readOverview: () => read("overview"), readDocuments: () => read("documents"), readReview: () => read("review") };
}

describe("surface loading boundary", () => {
  it("keeps the fixture-backed preview path explicit", async () => {
    const snapshot = await demoSource.load();
    expect(snapshot.overview.state).toBe("ready");
    if (snapshot.overview.state === "ready") expect(snapshot.overview.data.currentThrough).toBe("July 31, 2026");
    expect(demoSource.boundary).toBe("fixture");
  });

  it("provides one typed demo source boundary for the shell", async () => {
    const snapshot = await demoSource.load();
    expect(demoSource.id).toBe("synthetic-demo");
    expect(demoSource.label).toBe("Sample vault");
    expect(demoSource.mode).toBe("demo");
    expect(snapshot).toBe(await demoSource.load());
    expect([snapshot.overview.state, snapshot.documents.state, snapshot.activity.state]).toEqual(["ready", "ready", "ready"]);
  });

  it("exposes a typed private source seam", async () => {
    const source = privateSource(client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } }));
    const snapshot = await source.load();
    expect(source.boundary).toBe("bridge-ready");
    expect(snapshot.mode).toBe("live");
    expect(snapshot.review.state).toBe("ready");
  });

  it("settles surface reads independently", async () => {
    const base = client({ overview: { accounts: [] }, review: { questions: [], total: 0 } });
    const snapshot = await loadPrivateSnapshot({ ...base, readDocuments: async () => { throw new Error("bounded read failure"); } });
    expect([snapshot.overview.state, snapshot.documents.state, snapshot.review.state]).toEqual(["ready", "failed", "ready"]);
    expect(snapshot.documents).toEqual({ state: "failed", reason: "read_failed" });
  });

  it("maps fulfilled malformed unknown payloads to invalid payload failures", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: null, documents: "bad", review: [] }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("rejects a fulfilled overview payload without its owned accounts collection", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: {} }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.documents.state).toBe("ready");
    expect(snapshot.review.state).toBe("ready");
  });

  it("rejects a fulfilled documents payload without its owned documents collection", async () => {
    const snapshot = await loadPrivateSnapshot(client({ documents: { wrong: [] } }));
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(snapshot.overview.state).toBe("ready");
    expect(snapshot.review.state).toBe("ready");
  });

  it("rejects a fulfilled review payload without its owned questions and numeric total", async () => {
    const missingTotal = await loadPrivateSnapshot(client({ review: { questions: [] } }));
    const wrongTotal = await loadPrivateSnapshot(client({ review: { questions: [], total: "0" } }));
    expect(missingTotal.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect(wrongTotal.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("isolates malformed optional review summaries as an invalid review payload", async () => {
    const malformedTail = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: "0" }, pending: { count: 1 } } }));
    expect(malformedTail.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([malformedTail.overview.state, malformedTail.documents.state]).toEqual(["ready", "ready"]);

    const malformedPending = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: 2, amount: "2.00" }, pending: { count: -1 } } }));
    expect(malformedPending.review).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([malformedPending.overview.state, malformedPending.documents.state]).toEqual(["ready", "ready"]);
  });

  it("keeps explicit zero review summaries ready", async () => {
    const snapshot = await loadPrivateSnapshot(client({ review: { questions: [], total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 } } }));
    expect(snapshot.review).toEqual({ state: "ready", data: { queue: [], count: 0, meta: { total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 }, invite: "", answeredByDocument: "" } } });
    expect([snapshot.overview.state, snapshot.documents.state]).toEqual(["ready", "ready"]);
  });

  it("rejects a malformed overview row without discarding valid sibling surfaces", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: { accounts: [{ name: "missing stable id" }] } }));
    expect(snapshot.overview).toEqual({ state: "failed", reason: "invalid_payload" });
    expect([snapshot.documents.state, snapshot.review.state]).toEqual(["ready", "ready"]);
  });

  it("rejects a primitive document collection member", async () => {
    const snapshot = await loadPrivateSnapshot(client({ documents: { documents: ["not a document"] } }));
    expect(snapshot.documents).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("rejects a malformed review row even with an explicit numeric total", async () => {
    const snapshot = await loadPrivateSnapshot(client({ review: { questions: [{ text: "missing stable id" }], total: 1 } }));
    expect(snapshot.review).toEqual({ state: "failed", reason: "invalid_payload" });
  });

  it("adversarially exercises all eight fulfilled and rejected combinations", async () => {
    for (let mask = 0; mask < 8; mask += 1) {
      const base = client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } });
      const reject = async (): Promise<never> => { throw new Error("bounded read failure"); };
      const snapshot = await loadPrivateSnapshot({ ...base, readOverview: mask & 1 ? base.readOverview : reject, readDocuments: mask & 2 ? base.readDocuments : reject, readReview: mask & 4 ? base.readReview : reject });
      expect([snapshot.overview.state, snapshot.documents.state, snapshot.review.state]).toEqual([mask & 1 ? "ready" : "failed", mask & 2 ? "ready" : "failed", mask & 4 ? "ready" : "failed"]);
    }
  });

  it("never imports demo facts into a private snapshot", async () => {
    const snapshot = await loadPrivateSnapshot(client({ overview: { accounts: [] }, documents: { documents: [] }, review: { questions: [], total: 0 } }));
    const serialized = JSON.stringify(snapshot);
    for (const marker of ["Everyday checking", "$48,240.18", "silverline-checking", "Synthetic PDF"]) expect(serialized).not.toContain(marker);
  });
});
