import type { ConversationPrompt, ConversationTurn } from "../../surface/types";

export type PromptSelection =
  | { state: "empty"; reason: "no_prompts" | "no_selectable_identity" }
  | { state: "ready"; prompt: ConversationPrompt }
  | { state: "missing"; requestedId: string }
  | { state: "conflicted_identity"; requestedId: string };

export type ConversationIdentityRow<T> =
  | { state: "ready"; item: T; key: string }
  | { state: "missing_identity"; key: string }
  | { state: "conflicted_identity"; id: string; key: string };

function matchesById<T extends { readonly id: string }>(items: readonly T[], id: string): T[] {
  return items.filter((item) => item.id === id);
}

export function resolveConversationPrompt(prompts: readonly ConversationPrompt[], requestedId: string): PromptSelection {
  if (requestedId.trim()) {
    const matches = matchesById(prompts, requestedId);
    if (!matches.length) return { state: "missing", requestedId };
    if (matches.length > 1) return { state: "conflicted_identity", requestedId };
    return { state: "ready", prompt: matches[0] };
  }
  if (!prompts.length) return { state: "empty", reason: "no_prompts" };
  for (const prompt of prompts) if (prompt.id.trim() && matchesById(prompts, prompt.id).length === 1) return { state: "ready", prompt };
  return { state: "empty", reason: "no_selectable_identity" };
}

export function presentConversationRows<T extends ConversationPrompt | ConversationTurn>(items: readonly T[], namespace: "prompt" | "turn"): ConversationIdentityRow<T>[] {
  const rows: ConversationIdentityRow<T>[] = [];
  const seen = new Set<string>();
  let missingShown = false;
  for (const item of items) {
    if (!item.id.trim()) {
      if (!missingShown) rows.push({ state: "missing_identity", key: `${namespace}:missing` });
      missingShown = true;
      continue;
    }
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    const matches = matchesById(items, item.id);
    if (matches.length === 1) rows.push({ state: "ready", item, key: `${namespace}:ready:${item.id}` });
    else rows.push({ state: "conflicted_identity", id: item.id, key: `${namespace}:conflict:${item.id}` });
  }
  return rows;
}
