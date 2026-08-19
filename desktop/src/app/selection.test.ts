import { describe, expect, it } from "vitest";
import { identifiedRows, resolveStableSelection, retainSelection } from "./selection";

describe("stable selection presentation", () => {
  const longId = "A deliberately long supplied truth value stays visible and wraps without truncation across supported narrow viewport boundaries.";
  const rows = [{ id: "", label: "Blank" }, { id: " ", label: "Also blank" }, { id: "same", label: "First" }, { id: "same", label: "Second" }, { id: "one", label: "Duplicate label" }, { id: "two", label: "Duplicate label" }];

  it("groups blank and duplicate identities while preserving unique exact IDs and disjoint keys", () => {
    const presented = identifiedRows(rows, "account");
    expect(presented.map((row) => row.state)).toEqual(["missing_identity", "conflicted_identity", "ready", "ready"]);
    expect(presented.map((row) => row.key)).toEqual(["account:missing-identity", "account:conflicted-identity:same", "account:ready:one", "account:ready:two"]);
    expect(new Set(presented.map((row) => row.key)).size).toBe(presented.length);
  });

  it("uses exact IDs, treats whitespace requests as empty, and never falls back for explicit invalid IDs", () => {
    expect(resolveStableSelection(rows, " ")).toMatchObject({ state: "ready", item: { id: "one" } });
    expect(resolveStableSelection(rows, "same")).toEqual({ state: "conflicted_identity", requestedId: "same" });
    expect(resolveStableSelection(rows, "missing")).toEqual({ state: "missing", requestedId: "missing" });
    expect(resolveStableSelection([{ id: " exact ", label: "Spaced" }], " exact ")).toMatchObject({ state: "ready", item: { id: " exact " } });
    expect(resolveStableSelection([{ id: " exact ", label: "Spaced" }], "exact")).toEqual({ state: "missing", requestedId: "exact" });
    expect(resolveStableSelection([], "")).toEqual({ state: "empty", reason: "no_rows" });
    expect(resolveStableSelection(rows.slice(0, 4), "")).toEqual({ state: "empty", reason: "no_selectable_identity" });
  });

  it("preserves the existing session retention behavior", () => {
    expect(retainSelection("two", ["one", "two"])).toBe("two");
    expect(retainSelection("missing", ["one", "two"])).toBe("one");
    expect(retainSelection("", [])).toBe("");
  });

  it("preserves exact 128-character identities and disjoint state keys through reorder", () => {
    expect(longId).toHaveLength(128);
    const values = [{ id: longId, label: "Long" }, { id: "", label: "Blank" }, { id: "duplicate", label: "One" }, { id: "duplicate", label: "Two" }, { id: "other", label: "Other" }];
    const first = identifiedRows(values, "long-row");
    const reordered = identifiedRows([...values].reverse(), "long-row");
    expect(first.find((row) => row.state === "ready" && row.item.id === longId)?.key).toBe(`long-row:ready:${longId}`);
    expect(resolveStableSelection(values, longId)).toMatchObject({ state: "ready", item: { id: longId } });
    expect(resolveStableSelection([...values].reverse(), longId)).toMatchObject({ state: "ready", item: { id: longId } });
    expect(new Set(first.map((row) => row.key))).toEqual(new Set(reordered.map((row) => row.key)));
    expect(new Set(reordered.map((row) => row.key)).size).toBe(reordered.length);
    expect(reordered.map((row) => row.key)).not.toEqual(first.map((row) => row.key));
  });
});
