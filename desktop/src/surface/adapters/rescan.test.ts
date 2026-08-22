import { describe, expect, it } from "vitest";
import { adaptRescan } from "./rescan";

const reply = {
  state: "ready",
  sentence: "Nothing changed.",
  changes: [{ id: "gaps", count: 2, sentence: "Two gaps were closed." }],
  standing: [{ id: "suggested", count: 1, sentence: "One is waiting." }],
  link_count: 4,
};

describe("what a pass back over a vault said it did", () => {
  it("carries the backend's sentences unchanged and counts nothing itself", () => {
    expect(adaptRescan(reply)).toEqual({
      sentence: "Nothing changed.",
      changes: [{ id: "gaps", count: 2, sentence: "Two gaps were closed." }],
      standing: [{ id: "suggested", count: 1, sentence: "One is waiting." }],
      linkCount: 4,
    });
  });

  it("drops a row with no sentence rather than showing a bare number", () => {
    // This side has no words for what a gap is. A count on its own is a number
    // a person has to guess the meaning of.
    const { changes } = adaptRescan({ ...reply, changes: [{ id: "gaps", count: 2 }] })!;
    expect(changes).toEqual([]);
  });

  it("is read as no report at all when the panel's own sentence is missing", () => {
    expect(adaptRescan({ ...reply, sentence: "" })).toBeNull();
    expect(adaptRescan(null)).toBeNull();
  });

  it("keeps what is still open apart from what the pass did", () => {
    const read = adaptRescan(reply)!;
    expect(read.changes.map((row) => row.id)).toEqual(["gaps"]);
    expect(read.standing.map((row) => row.id)).toEqual(["suggested"]);
  });
});
