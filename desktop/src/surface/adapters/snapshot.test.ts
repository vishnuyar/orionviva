import { describe, expect, it } from "vitest";
import { buildLiveSnapshot } from "./snapshot";

describe("snapshot adapter", () => {
  it("builds a live snapshot with unsupported features unavailable", () => {
    const snapshot = buildLiveSnapshot({ state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, corpusCoverage: "", accounts: [], recent: [] } }, { state: "ready", data: { documents: [], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, { state: "ready", data: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } });
    expect(snapshot.mode).toBe("live");
    expect(snapshot.activity.state).toBe("unavailable");
    expect(snapshot.conversation.state).toBe("unavailable");
    expect(snapshot.trust.state).toBe("unavailable");
    expect(JSON.stringify(snapshot)).not.toContain("Synthetic PDF");
  });
});
