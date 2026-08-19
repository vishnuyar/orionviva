export function retainSelection(current: string, ids: string[]): string {
  return current && ids.includes(current) ? current : ids[0] ?? "";
}

export type IdentifiedRow<T> =
  | { state: "ready"; item: T; key: string }
  | { state: "missing_identity"; key: string }
  | { state: "conflicted_identity"; id: string; key: string };

export type StableSelection<T> =
  | { state: "empty"; reason: "no_rows" | "no_selectable_identity" }
  | { state: "ready"; item: T }
  | { state: "missing"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

export function identifiedRows<T extends { id: string }>(items: readonly T[], namespace: string): IdentifiedRow<T>[] {
  const rows: IdentifiedRow<T>[] = [];
  const represented = new Set<string>();
  let representedMissing = false;
  for (const item of items) {
    if (!item.id.trim()) {
      if (!representedMissing) rows.push({ state: "missing_identity", key: `${namespace}:missing-identity` });
      representedMissing = true;
      continue;
    }
    if (represented.has(item.id)) continue;
    represented.add(item.id);
    const matches = items.filter((candidate) => candidate.id === item.id);
    if (matches.length > 1) rows.push({ state: "conflicted_identity", id: item.id, key: `${namespace}:conflicted-identity:${item.id}` });
    else rows.push({ state: "ready", item, key: `${namespace}:ready:${item.id}` });
  }
  return rows;
}

export function resolveStableSelection<T extends { id: string }>(items: readonly T[], requestedId: string): StableSelection<T> {
  if (!items.length) return { state: "empty", reason: "no_rows" };
  if (!requestedId.trim()) {
    const first = identifiedRows(items, "selection").find((row) => row.state === "ready");
    return first?.state === "ready" ? { state: "ready", item: first.item } : { state: "empty", reason: "no_selectable_identity" };
  }
  const matches = items.filter((item) => item.id === requestedId);
  if (!matches.length) return { state: "missing", requestedId };
  if (matches.length > 1) return { state: "conflicted_identity", requestedId };
  return { state: "ready", item: matches[0] };
}
