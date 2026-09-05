import type { ReviewContext, ReviewData, ReviewItem, ReviewQuestionBinding, ReviewQuestionReferences, ReviewTarget } from "../types";
import { isRecord, optionalNonNegativeInteger } from "./primitives";

const ACTIONS = ["open_question", "open_transaction"] as const;

function exact(raw: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(raw).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function string(raw: unknown, allowEmpty = false): string | null {
  return typeof raw === "string" && (allowEmpty || raw.trim().length > 0) ? raw : null;
}

function context(raw: unknown): ReviewContext | null {
  if (!isRecord(raw) || !exact(raw, ["date", "amount", "account", "merchant"])) return null;
  const date = string(raw.date, true), amount = string(raw.amount, true);
  const account = string(raw.account, true), merchant = string(raw.merchant, true);
  return date === null || amount === null || account === null || merchant === null
    ? null : { date, amount, account, merchant };
}

export function adaptReviewTarget(raw: unknown): ReviewTarget | null {
  if (!isRecord(raw)) return null;
  const questionId = string(raw.question_id);
  if (!questionId) return null;
  if (raw.kind === "conversation") {
    if (!exact(raw, ["kind", "question_id", "disclosure"])) return null;
    const disclosure = string(raw.disclosure);
    return disclosure ? { kind: "conversation", questionId, disclosure } : null;
  }
  if (raw.kind !== "transaction" || !exact(raw, ["kind", "question_id", "account_id", "movement_id", "canonical_movement_id", "member_movement_ids"])) return null;
  const accountId = string(raw.account_id), movementId = string(raw.movement_id);
  const canonicalMovementId = string(raw.canonical_movement_id);
  if (!Array.isArray(raw.member_movement_ids)) return null;
  const memberMovementIds = raw.member_movement_ids.map((identity) => string(identity));
  if (!accountId || !movementId || !canonicalMovementId || memberMovementIds.some((identity) => identity === null)) return null;
  const safeMembers = memberMovementIds as string[];
  if (!safeMembers.length || new Set(safeMembers).size !== safeMembers.length
      || safeMembers[0] !== canonicalMovementId
      || JSON.stringify(safeMembers) !== JSON.stringify([...safeMembers].sort())
      || !safeMembers.includes(movementId)) return null;
  return { kind: "transaction", questionId, accountId, requestedMovementId: movementId, canonicalMovementId, memberMovementIds: safeMembers };
}

function bindingRefs(raw: unknown): ReviewQuestionReferences | null {
  if (!isRecord(raw) || !exact(raw, ["movement", "movements", "candidates", "document", "doc_id", "account"])) return null;
  const movement = string(raw.movement, true), document = string(raw.document, true);
  const documentId = string(raw.doc_id, true), account = string(raw.account, true);
  if (movement === null || document === null || documentId === null || account === null
      || !Array.isArray(raw.movements) || !Array.isArray(raw.candidates)) return null;
  const movements = raw.movements.map((identity) => string(identity));
  const candidates = raw.candidates.map((identity) => string(identity));
  if (movements.some((identity) => identity === null) || candidates.some((identity) => identity === null)) return null;
  const safeMovements = movements as string[], safeCandidates = candidates as string[];
  if (new Set(safeMovements).size !== safeMovements.length || new Set(safeCandidates).size !== safeCandidates.length) return null;
  return { movement, movements: safeMovements, candidates: safeCandidates, document, documentId, account };
}

export function adaptReviewBinding(raw: unknown): ReviewQuestionBinding | null {
  if (!isRecord(raw) || !exact(raw, ["item_id", "question_id", "question_kind", "label", "reason", "refs", "target", "status", "primary_action", "allowed_actions"])) return null;
  const itemId = string(raw.item_id), questionId = string(raw.question_id);
  const questionKind = string(raw.question_kind), label = string(raw.label), reason = string(raw.reason);
  const refs = bindingRefs(raw.refs), parsedTarget = adaptReviewTarget(raw.target);
  const primaryAction = ACTIONS.find((action) => action === raw.primary_action);
  if (!Array.isArray(raw.allowed_actions)) return null;
  const allowedActions = raw.allowed_actions.map((action) => ACTIONS.find((candidate) => candidate === action));
  if (!itemId || !questionId || !questionKind || !label || !reason || !refs || !parsedTarget
      || raw.status !== "open" || !primaryAction || allowedActions.some((action) => !action)
      || allowedActions.length !== 1 || allowedActions[0] !== primaryAction
      || itemId !== `question:${questionId}` || parsedTarget.questionId !== questionId
      || (primaryAction === "open_transaction") !== (parsedTarget.kind === "transaction")) return null;
  return { itemId, questionId, questionKind, label, reason, refs, target: parsedTarget, status: "open", primaryAction, allowedActions: allowedActions as ReviewQuestionBinding["allowedActions"] };
}

function sameTarget(left: ReviewTarget, right: ReviewTarget): boolean {
  if (left.kind !== right.kind || left.questionId !== right.questionId) return false;
  if (left.kind === "conversation" || right.kind === "conversation") return left.kind === "conversation" && right.kind === "conversation" && left.disclosure === right.disclosure;
  return left.accountId === right.accountId
    && left.requestedMovementId === right.requestedMovementId
    && left.canonicalMovementId === right.canonicalMovementId
    && left.memberMovementIds.length === right.memberMovementIds.length
    && left.memberMovementIds.every((identity, index) => identity === right.memberMovementIds[index]);
}

function item(raw: unknown): ReviewItem | null {
  if (!isRecord(raw) || !exact(raw, ["id", "type", "type_label", "marker", "marker_label", "label", "reason", "status", "context", "target", "primary_action", "action_label", "allowed_actions", "binding"])) return null;
  const id = string(raw.id), label = string(raw.label), reason = string(raw.reason);
  const typeLabel = string(raw.type_label), markerLabel = string(raw.marker_label), actionLabel = string(raw.action_label);
  const parsedContext = context(raw.context), parsedTarget = adaptReviewTarget(raw.target);
  const binding = adaptReviewBinding(raw.binding);
  const primaryAction = ACTIONS.find((action) => action === raw.primary_action);
  if (!Array.isArray(raw.allowed_actions)) return null;
  const allowedActions = raw.allowed_actions.map((action) => ACTIONS.find((candidate) => candidate === action));
  if (!id || !label || !reason || !typeLabel || !markerLabel || !actionLabel || raw.type !== "question" || raw.marker !== "?" || raw.status !== "open"
      || !parsedContext || !parsedTarget || !binding || !primaryAction || allowedActions.some((action) => !action)
      || allowedActions.length !== 1 || allowedActions[0] !== primaryAction
      || (primaryAction === "open_transaction") !== (parsedTarget.kind === "transaction")
      || id !== `question:${parsedTarget.questionId}` || binding.itemId !== id
      || binding.label !== label || binding.reason !== reason || binding.status !== raw.status
      || binding.primaryAction !== primaryAction
      || binding.allowedActions.length !== allowedActions.length
      || !binding.allowedActions.every((action, index) => action === allowedActions[index])
      || !sameTarget(binding.target, parsedTarget)) return null;
  return { id, type: "question", typeLabel, marker: "?", markerLabel, label, reason, status: "open", context: parsedContext, target: parsedTarget, primaryAction, actionLabel, allowedActions: allowedActions as ReviewItem["allowedActions"], binding };
}

export function adaptReview(raw: unknown): ReviewData | null {
  if (!isRecord(raw) || !exact(raw, ["state", "contract", "title", "summary", "actionable_count", "shown_count", "remaining_count", "types", "groups"])
      || raw.state !== "ready" || raw.contract !== "ReviewSummary.v1" || !Array.isArray(raw.types) || !Array.isArray(raw.groups)) return null;
  const actionableCount = optionalNonNegativeInteger(raw.actionable_count);
  const shownCount = optionalNonNegativeInteger(raw.shown_count);
  const remainingCount = optionalNonNegativeInteger(raw.remaining_count);
  if (actionableCount === undefined || shownCount === undefined || remainingCount === undefined || actionableCount !== shownCount + remainingCount) return null;
  const types = raw.types.map((entry) => {
    if (!isRecord(entry) || !exact(entry, ["id", "label", "count"]) || entry.id !== "questions") return null;
    const count = optionalNonNegativeInteger(entry.count), label = string(entry.label);
    return count === undefined || !label ? null : { id: "questions" as const, label, count };
  });
  if (types.some((entry) => entry === null) || new Set(types.map((entry) => entry?.id)).size !== types.length) return null;
  const groups = raw.groups.map((entry) => {
    if (!isRecord(entry) || !exact(entry, ["id", "label", "count", "items"]) || entry.id !== "questions" || !Array.isArray(entry.items)) return null;
    const count = optionalNonNegativeInteger(entry.count), label = string(entry.label);
    const items = entry.items.map(item);
    if (count === undefined || !label || items.some((row) => row === null) || count !== items.length) return null;
    return { id: "questions" as const, label, count, items: items as ReviewItem[] };
  });
  if (groups.some((entry) => entry === null) || new Set(groups.map((entry) => entry?.id)).size !== groups.length) return null;
  const items = groups.flatMap((group) => group?.items ?? []);
  if (items.length !== shownCount || new Set(items.map((row) => row.id)).size !== items.length
      || new Set(items.map((row) => row.target.questionId)).size !== items.length) return null;
  if ((shownCount === 0) !== (groups.length === 0) || (shownCount === 0) !== (types.length === 0)) return null;
  if (shownCount > 0 && (groups.length !== 1 || types.length !== 1
      || types[0]?.count !== shownCount || groups[0]?.count !== shownCount
      || types[0]?.label !== groups[0]?.label)) return null;
  const title = string(raw.title), summary = string(raw.summary);
  if (!title || !summary) return null;
  return { contract: "ReviewSummary.v1", title, summary, actionableCount, shownCount, remainingCount, types: types as ReviewData["types"], groups: groups as ReviewData["groups"] };
}
