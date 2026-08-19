import type { ActivityView, SampleActivityDetails } from "../../surface/types";

export type SampleActivityFilters = { date: string; account: string; merchant: string; category: string; tag: string; nature: string; direction: string };

export const emptySampleActivityFilters: SampleActivityFilters = { date: "", account: "", merchant: "", category: "", tag: "", nature: "", direction: "" };

export type ActivitySelection =
  | { state: "empty"; reason: "items_empty" | "no_selection" | "no_selectable_identity" }
  | { state: "ready"; item: ActivityView }
  | { state: "missing"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

export type RelatedActivityResolution =
  | { state: "ready"; item: ActivityView }
  | { state: "missing_identity" }
  | { state: "missing_activity"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

function matchesById(items: readonly ActivityView[], id: string): ActivityView[] {
  return items.filter((item) => item.id === id);
}

export function firstUniqueActivityId(items: readonly ActivityView[]): string {
  return items.find((item) => item.id.trim() && matchesById(items, item.id).length === 1)?.id ?? "";
}

export function resolveActivitySelection(items: readonly ActivityView[], requestedId: string): ActivitySelection {
  if (!items.length) return { state: "empty", reason: "items_empty" };
  if (!requestedId.trim()) return firstUniqueActivityId(items) ? { state: "empty", reason: "no_selection" } : { state: "empty", reason: "no_selectable_identity" };
  const matches = matchesById(items, requestedId);
  if (!matches.length) return { state: "missing", requestedId };
  if (matches.length > 1) return { state: "conflicted_identity", requestedId };
  return { state: "ready", item: matches[0] };
}

export function resolveRelatedActivity(items: readonly ActivityView[], targetActivityId: string): RelatedActivityResolution {
  if (!targetActivityId.trim()) return { state: "missing_identity" };
  const matches = matchesById(items, targetActivityId);
  if (!matches.length) return { state: "missing_activity", requestedId: targetActivityId };
  if (matches.length > 1) return { state: "conflicted_identity", requestedId: targetActivityId };
  return { state: "ready", item: matches[0] };
}

export function sampleActivityFiltersAreEmpty(filters: SampleActivityFilters): boolean {
  return !filters.date && !filters.account && !filters.merchant && !filters.category && !filters.tag && !filters.nature && !filters.direction;
}

function facetMatches(selected: string, supplied: string | undefined): boolean {
  return !selected || supplied === selected;
}

function searchableText(item: ActivityView, sample: SampleActivityDetails | undefined): string[] {
  return [item.id, item.label, item.detail, item.provenance, sample?.date?.id ?? "", sample?.date?.label ?? "", sample?.account?.id ?? "", sample?.account?.label ?? "", sample?.merchant?.id ?? "", sample?.merchant?.label ?? "", sample?.category?.id ?? "", sample?.category?.label ?? "", sample?.nature?.id ?? "", sample?.nature?.label ?? "", sample?.direction?.id ?? "", sample?.direction?.label ?? ""];
}

export function filterSampleActivity(items: readonly ActivityView[], query: string, filters: SampleActivityFilters): ActivityView[] {
  const literal = query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    const sample = item.sample;
    const searchMatches = !literal || searchableText(item, sample).some((value) => value.toLocaleLowerCase().includes(literal)) || (sample?.tags ?? []).some((tag) => tag.id.toLocaleLowerCase().includes(literal) || tag.label.toLocaleLowerCase().includes(literal));
    return searchMatches
      && facetMatches(filters.date, sample?.date?.id)
      && facetMatches(filters.account, sample?.account?.id)
      && facetMatches(filters.merchant, sample?.merchant?.id)
      && facetMatches(filters.category, sample?.category?.id)
      && facetMatches(filters.tag, sample?.tags?.find((tag) => tag.id === filters.tag)?.id)
      && facetMatches(filters.nature, sample?.nature?.id)
      && facetMatches(filters.direction, sample?.direction?.id);
  });
}

export function retainVisibleActivitySelection(allItems: readonly ActivityView[], visibleItems: readonly ActivityView[], selectedId: string): string {
  return selectedId.trim() && matchesById(allItems, selectedId).length === 1 && matchesById(visibleItems, selectedId).length === 1 ? selectedId : "";
}
