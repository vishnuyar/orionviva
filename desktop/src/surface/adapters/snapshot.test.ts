import { describe, expect, it } from "vitest";
import { buildLiveSnapshot } from "./snapshot";

describe("snapshot adapter", () => {
  it("builds a live snapshot with unsupported features unavailable", () => {
    const snapshot = buildLiveSnapshot({ state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [] } }, { state: "ready", data: { documents: [], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, { state: "ready", data: { turns: [], questions: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } } }, { state: "unavailable", reason: "not asked" }, { state: "unavailable", reason: "not asked" });
    expect(snapshot.activity.state).toBe("unavailable");
    expect(snapshot.conversation.state).toBe("ready");
    expect(snapshot.trust.state).toBe("unavailable");
    expect(JSON.stringify(snapshot)).not.toContain("Synthetic PDF");
  });

  it("carries the trust read the loader was handed rather than declaring it unavailable", () => {
    // Trust is a read now. A builder that decided its state would be a second
    // opinion about whether the vault answered.
    const trust = { state: "ready" as const, data: { notes: [], outbound: { sentence: "Nothing has left.", callCount: 0, phases: [], models: [], modelSentence: "", span: null, cost: null, absences: [] } } };
    const snapshot = buildLiveSnapshot({ state: "absent", reason: "x" }, { state: "absent", reason: "x" }, { state: "absent", reason: "x" }, trust, { state: "absent", reason: "x" });
    expect(snapshot.trust).toBe(trust);
  });
});
