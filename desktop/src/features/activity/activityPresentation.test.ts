import { describe, expect, it } from "vitest";
import type { ActivityView } from "../../surface/types";
import { emptySampleActivityFilters, filterSampleActivity, firstUniqueActivityId, resolveActivitySelection, resolveRelatedActivity, retainVisibleActivitySelection, sampleActivityFiltersAreEmpty } from "./activityPresentation";

const item = (id: string, label = "Movement", overrides: Partial<ActivityView> = {}): ActivityView => ({ id, label, exactValue: "1", display: "$1", measure: "spending", detail: "Authored detail", tone: "neutral", state: "ready", provenance: "Authored provenance", evidenceLinks: [], grade: "not_applicable", ...overrides });
const authored = item("movement-a", "Coffee [literal]", { sample: { date: { id: "date-june", label: "June 24" }, account: { id: "account-checking", label: "Everyday checking" }, merchant: { id: "merchant-cafe", label: "Corner Cafe" }, category: { id: "category-food", label: "Food" }, tags: [{ id: "tag-local", label: "Local" }], nature: { id: "nature-purchase", label: "Purchase" }, direction: { id: "direction-outgoing", label: "Outgoing" } } });

describe("activity presentation", () => {
  it("resolves stable identities across reorder, duplicate labels, and every refusal state", () => {
    const items = [item("movement-a", "Duplicate"), item("movement-b", "Duplicate")];
    expect(firstUniqueActivityId(items)).toBe("movement-a");
    expect(resolveActivitySelection(items, "movement-b")).toMatchObject({ state: "ready", item: { id: "movement-b" } });
    expect(resolveActivitySelection([...items].reverse(), "movement-b")).toMatchObject({ state: "ready", item: { id: "movement-b" } });
    expect(resolveActivitySelection([], "")).toEqual({ state: "empty", reason: "items_empty" });
    expect(resolveActivitySelection(items, "")).toEqual({ state: "empty", reason: "no_selection" });
    expect(resolveActivitySelection([item(""), item(" ")], "")).toEqual({ state: "empty", reason: "no_selectable_identity" });
    expect(resolveActivitySelection(items, "missing")).toEqual({ state: "missing", requestedId: "missing" });
    expect(resolveActivitySelection([item("duplicate"), item("duplicate")], "duplicate")).toEqual({ state: "conflicted_identity", requestedId: "duplicate" });
  });

  it("treats special search characters as literal authored text", () => {
    expect(filterSampleActivity([authored], "[literal]", emptySampleActivityFilters)).toEqual([authored]);
    expect(filterSampleActivity([authored], ".*", emptySampleActivityFilters)).toEqual([]);
    for (const query of ["movement-a", "authored detail", "authored provenance", "june 24", "account-checking", "corner cafe", "category-food", "tag-local", "purchase", "direction-outgoing"]) {
      expect(filterSampleActivity([authored], query, emptySampleActivityFilters)).toEqual([authored]);
    }
  });

  it("combines exact authored facet IDs without guessing", () => {
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, date: "date-june" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, account: "account-checking" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, merchant: "merchant-cafe" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, category: "category-food" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, tag: "tag-local" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, nature: "nature-purchase" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "", { ...emptySampleActivityFilters, direction: "direction-outgoing" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "coffee", { ...emptySampleActivityFilters, date: "date-june", account: "account-checking", merchant: "merchant-cafe", category: "category-food", tag: "tag-local", nature: "nature-purchase", direction: "direction-outgoing" })).toEqual([authored]);
    expect(filterSampleActivity([authored], "coffee", { ...emptySampleActivityFilters, category: "Food" })).toEqual([]);
    expect(sampleActivityFiltersAreEmpty(emptySampleActivityFilters)).toBe(true);
    expect(sampleActivityFiltersAreEmpty({ ...emptySampleActivityFilters, tag: "tag-local" })).toBe(false);
  });

  it("retains only an exact uniquely visible selection", () => {
    expect(retainVisibleActivitySelection([item("kept")], [item("kept")], "kept")).toBe("kept");
    expect(retainVisibleActivitySelection([item("kept")], [item("other")], "kept")).toBe("");
    expect(retainVisibleActivitySelection([item("same"), item("same")], [item("same")], "same")).toBe("");
    expect(retainVisibleActivitySelection([item("missing")], [item("missing")], "other")).toBe("");
  });

  it("resolves related targets only by exact stable identity", () => {
    expect(resolveRelatedActivity([item("target")], "target")).toMatchObject({ state: "ready", item: { id: "target" } });
    expect(resolveRelatedActivity([item("target")], "")).toEqual({ state: "missing_identity" });
    expect(resolveRelatedActivity([item("target")], "missing")).toEqual({ state: "missing_activity", requestedId: "missing" });
    expect(resolveRelatedActivity([item("same"), item("same")], "same")).toEqual({ state: "conflicted_identity", requestedId: "same" });
  });
});
