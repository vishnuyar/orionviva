import { describe, expect, it } from "vitest";
import { adaptReview } from "./review";

const conversationTarget = { kind: "conversation", question_id: "q-1", disclosure: "No exact transaction was supplied." };
const binding = (target: Record<string, unknown> = conversationTarget, action = "open_question") => ({ item_id: "question:q-1", question_id: "q-1", question_kind: "identity", label: "What was this?", reason: "The records do not say.", refs: { movement: "", movements: [], candidates: [], document: "", doc_id: "", account: "" }, target, status: "open", primary_action: action, allowed_actions: [action] });
const baseItem = { id: "question:q-1", type: "question", type_label: "Question", marker: "?", marker_label: "Viva needs an answer", label: "What was this?", reason: "The records do not say.", status: "open", context: { date: "", amount: "", account: "", merchant: "" }, target: conversationTarget, primary_action: "open_question", action_label: "Answer question", allowed_actions: ["open_question"], binding: binding() };
const payload = (items: unknown[] = [baseItem], total = items.length) => ({ state: "ready", contract: "ReviewSummary.v1", title: "Review", summary: `${total} waiting.`, actionable_count: total, shown_count: items.length, remaining_count: total - items.length, types: items.length ? [{ id: "questions", label: "Questions", count: items.length }] : [], groups: items.length ? [{ id: "questions", label: "Questions", count: items.length, items }] : [] });

describe("ReviewSummary.v1 adapter", () => {
  it("accepts one authored question group without deriving a count", () => {
    expect(adaptReview(payload())?.actionableCount).toBe(1);
  });

  it("accepts a strict canonical transaction target", () => {
    const target = { kind: "transaction", question_id: "q-1", account_id: "acct-1", movement_id: "member-2", canonical_movement_id: "member-1", member_movement_ids: ["member-1", "member-2"] };
    const adapted = adaptReview(payload([{ ...baseItem, target, primary_action: "open_transaction", action_label: "Review transaction", allowed_actions: ["open_transaction"], binding: binding(target, "open_transaction") }]));
    expect(adapted?.groups[0].items[0].target).toEqual({ kind: "transaction", questionId: "q-1", accountId: "acct-1", requestedMovementId: "member-2", canonicalMovementId: "member-1", memberMovementIds: ["member-1", "member-2"] });
  });

  it.each([
    ["inconsistent total", { ...payload(), actionable_count: 2 }],
    ["duplicate item identity", payload([baseItem, baseItem], 2)],
    ["movement outside members", payload([{ ...baseItem, target: { kind: "transaction", question_id: "q-1", account_id: "acct-1", movement_id: "other", canonical_movement_id: "member-1", member_movement_ids: ["member-1"] }, primary_action: "open_transaction", allowed_actions: ["open_transaction"] }])],
    ["mismatched action", payload([{ ...baseItem, target: conversationTarget, primary_action: "open_transaction", allowed_actions: ["open_transaction"] }])],
    ["invented type", { ...payload(), types: [{ id: "classification", label: "Classification", count: 1 }] }],
  ])("refuses %s atomically", (_name, raw) => expect(adaptReview(raw)).toBeNull());

  it.each([
    ["top-level unknown key", () => ({ ...payload(), surprise: true })],
    ["non-ready state", () => ({ ...payload(), state: "partial" })],
    ["type unknown key", () => { const raw = payload(); return { ...raw, types: [{ ...raw.types[0], surprise: true }] }; }],
    ["group unknown key", () => { const raw = payload(); return { ...raw, groups: [{ ...raw.groups[0], surprise: true }] }; }],
    ["item unknown key", () => payload([{ ...baseItem, surprise: true }])],
    ["context unknown key", () => payload([{ ...baseItem, context: { ...baseItem.context, surprise: true } }])],
    ["target unknown key", () => payload([{ ...baseItem, target: { ...conversationTarget, surprise: true } }])],
    ["binding unknown key", () => payload([{ ...baseItem, binding: { ...binding(), surprise: true } }])],
    ["binding label disagreement", () => payload([{ ...baseItem, binding: { ...binding(), label: "Something else" } }])],
    ["binding target disagreement", () => payload([{ ...baseItem, binding: { ...binding(), target: { ...conversationTarget, disclosure: "Different fallback." } } }])],
    ["coerced count", () => ({ ...payload(), actionable_count: "1" })],
    ["item/question identity disagreement", () => payload([{ ...baseItem, id: "question:somewhere-else" }])],
    ["reordered canonical members", () => payload([{ ...baseItem, target: { kind: "transaction", question_id: "q-1", account_id: "acct-1", movement_id: "member-2", canonical_movement_id: "member-1", member_movement_ids: ["member-2", "member-1"] }, primary_action: "open_transaction", action_label: "Review transaction", allowed_actions: ["open_transaction"] }])],
  ])("rejects a closed-shape violation: %s", (_name, make) => expect(adaptReview(make())).toBeNull());

  it("accepts zero and large backend-authored counts", () => {
    expect(adaptReview(payload([], 0))?.actionableCount).toBe(0);
    expect(adaptReview(payload([baseItem], 1250))?.remainingCount).toBe(1249);
  });
});
