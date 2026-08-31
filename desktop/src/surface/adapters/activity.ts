import type { ActivityActionOutcome, ActivityCategoryVocabulary, ActivityData, ActivityRowAction, ActivityTagVocabulary, ActivityTransferReference, ActivityTransferState, ActivityTreatment, ActivityVocabularyItem, MovementView } from "../types";
import { booleanValue, isRecord, optionalNonNegativeInteger, textValue } from "./primitives";

// The two words a direction can be, closed on both sides. A word outside the
// set is a movement this interface has not been taught to render, and the row
// is dropped rather than shown under the nearest one — a purchase reported as
// money arriving is exactly the defect that kept this read off a screen.
const DIRECTIONS = ["in", "out"] as const;
const TREATMENTS = ["spending", "loan", "loan_repayment", "settlement", "mixed", "not_spending"] as const;
const ROW_ACTIONS = ["assign_category", "assign_meaning", "replace_tags", "confirm_transfer", "reject_transfer", "unlink_transfer"] as const;
const TRANSFER_ACTIONS = ["confirm_transfer", "reject_transfer", "unlink_transfer"] as const;

// Activity writes have three terminal answers. A proposal, a wait, or a review
// disposition belongs to another capability; accepting one here would let an
// unrelated receipt claim what happened to financial classification.
export function adaptActivityActionOutcome(raw: unknown): ActivityActionOutcome | null {
  if (!isRecord(raw) || Object.keys(raw).sort().join(",") !== "kind,message,reason,state") return null;
  if (raw.state !== null || typeof raw.message !== "string" || !raw.message.trim()) return null;
  if (raw.kind === "completed") return raw.reason === null ? { kind: "completed", message: raw.message, reason: "" } : null;
  if ((raw.kind === "refused" || raw.kind === "stale") && typeof raw.reason === "string" && raw.reason.trim()) {
    return { kind: raw.kind, message: raw.message, reason: raw.reason };
  }
  return null;
}

function vocabularyItems(raw: unknown): { items: readonly ActivityVocabularyItem[]; valid: boolean } {
  if (!Array.isArray(raw)) return { items: [], valid: false };
  const seen = new Set<string>();
  const items: ActivityVocabularyItem[] = [];
  let valid = true;
  raw.forEach((value) => {
    if (!isRecord(value) || typeof value.id !== "string" || !value.id.trim() || typeof value.label !== "string" || !value.label.trim() || seen.has(value.id)) {
      valid = false;
      return;
    }
    seen.add(value.id);
    items.push({ id: value.id, label: value.label });
  });
  return { items, valid };
}

function categoryVocabulary(raw: unknown): ActivityCategoryVocabulary {
  if (!isRecord(raw)) return { items: [], complete: false, limit: 0 };
  const parsed = vocabularyItems(raw.items);
  const limit = optionalNonNegativeInteger(raw.limit);
  return {
    items: parsed.items,
    complete: booleanValue(raw.complete) === true && parsed.valid && limit !== undefined && parsed.items.length <= limit,
    limit: limit ?? 0,
  };
}

function tagVocabulary(raw: unknown): ActivityTagVocabulary {
  const base = categoryVocabulary(raw);
  const maxSelected = isRecord(raw) ? optionalNonNegativeInteger(raw.max_selected) : undefined;
  const maxLabelLength = isRecord(raw) ? optionalNonNegativeInteger(raw.max_label_length) : undefined;
  return {
    ...base,
    complete: base.complete && maxSelected !== undefined && maxSelected > 0 && maxLabelLength !== undefined && maxLabelLength > 0 && base.items.every((item) => item.id.length <= maxLabelLength),
    maxSelected: maxSelected ?? 0,
    maxLabelLength: maxLabelLength ?? 0,
  };
}

function exactKeys(raw: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(raw).sort().join(",") === [...expected].sort().join(",");
}

function transferReference(raw: unknown, relationship: boolean): (ActivityTransferReference & { relationship?: string }) | null {
  if (!isRecord(raw)) return null;
  const expected = ["id", "date", "description", "account", "direction", "exact_value", "currency", "display", ...(relationship ? ["relationship"] : [])];
  if (!exactKeys(raw, expected)) return null;
  const direction = DIRECTIONS.find((candidate) => candidate === raw.direction);
  const fields = [raw.id, raw.date, raw.description, raw.account, raw.exact_value, raw.currency, raw.display, ...(relationship ? [raw.relationship] : [])];
  if (!direction || fields.some((field) => typeof field !== "string" || !field.trim())) return null;
  return {
    id: raw.id as string,
    date: raw.date as string,
    description: raw.description as string,
    account: raw.account as string,
    direction,
    exactValue: raw.exact_value as string,
    currency: raw.currency as string,
    display: raw.display as string,
    ...(relationship ? { relationship: raw.relationship as string } : {}),
  };
}

function transferState(raw: unknown, sourceId: string): ActivityTransferState | null {
  if (!isRecord(raw) || typeof raw.state !== "string") return null;
  if (raw.state === "none") return exactKeys(raw, ["state"]) ? { state: "none" } : null;
  if (raw.state === "suggested") {
    if (!exactKeys(raw, ["state", "explanation", "candidates", "complete", "limit"]) || typeof raw.explanation !== "string" || !raw.explanation.trim() || typeof raw.complete !== "boolean") return null;
    const limit = optionalNonNegativeInteger(raw.limit);
    if (limit === undefined || limit < 1 || !Array.isArray(raw.candidates) || raw.candidates.length > limit) return null;
    const candidates = raw.candidates.map((candidate) => transferReference(candidate, true));
    if (candidates.some((candidate) => candidate === null)) return null;
    const safe = candidates as (ActivityTransferReference & { relationship: string })[];
    const ids = safe.map((candidate) => candidate.id);
    if (ids.includes(sourceId) || new Set(ids).size !== ids.length || (raw.complete && !safe.length)) return null;
    return { state: "suggested", explanation: raw.explanation, candidates: safe, complete: raw.complete, limit };
  }
  if (raw.state === "linked") {
    if (!exactKeys(raw, ["state", "explanation", "counterpart", "relationship"]) || typeof raw.explanation !== "string" || !raw.explanation.trim() || typeof raw.relationship !== "string" || !raw.relationship.trim()) return null;
    const counterpart = transferReference(raw.counterpart, false);
    if (!counterpart || counterpart.id === sourceId) return null;
    return { state: "linked", explanation: raw.explanation, counterpart, relationship: raw.relationship };
  }
  return null;
}

function treatment(raw: unknown): ActivityTreatment | null {
  if (!isRecord(raw) || !exactKeys(raw, ["kind", "name"])) return null;
  const kind = TREATMENTS.find((candidate) => candidate === raw.kind);
  if (!kind || typeof raw.name !== "string") return null;
  if ((kind === "loan" || kind === "loan_repayment") !== Boolean(raw.name.trim())) return null;
  return { kind, name: raw.name };
}

function rowActions(raw: unknown, currentClassificationValid: boolean, categoriesComplete: boolean, tagsComplete: boolean, transfer: ActivityTransferState | null): readonly ActivityRowAction[] {
  if (!Array.isArray(raw) || !currentClassificationValid) return [];
  const ordinary = ROW_ACTIONS.filter((candidate) => raw.includes(candidate)).filter((action) => action === "assign_category" ? categoriesComplete : action === "assign_meaning" ? true : action === "replace_tags" ? tagsComplete : false);
  const declaredTransfer = raw.filter((action): action is typeof TRANSFER_ACTIONS[number] => typeof action === "string" && TRANSFER_ACTIONS.includes(action as typeof TRANSFER_ACTIONS[number]));
  const expectedTransfer: readonly typeof TRANSFER_ACTIONS[number][] = transfer?.state === "suggested" && transfer.complete
    ? ["confirm_transfer", "reject_transfer"]
    : transfer?.state === "linked" ? ["unlink_transfer"] : [];
  const coherent = declaredTransfer.length === new Set(declaredTransfer).size
    && declaredTransfer.length === expectedTransfer.length
    && expectedTransfer.every((action) => declaredTransfer.includes(action));
  return coherent ? [...ordinary, ...expectedTransfer] : ordinary;
}

function movement(raw: unknown, categories: ActivityCategoryVocabulary, tagVocabulary: ActivityTagVocabulary): MovementView | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const direction = DIRECTIONS.find((candidate) => candidate === raw.direction);
  if (!id || !direction) return null;
  const category = isRecord(raw.category) ? raw.category : {};
  const categoryValid = (category.id === null || (typeof category.id === "string" && Boolean(category.id.trim()))) && typeof category.label === "string" && Boolean(category.label.trim());
  const tags = vocabularyItems(raw.tags);
  const tagsWithinBounds = tags.items.length <= tagVocabulary.maxSelected && tags.items.every((tag) => tag.id.length <= tagVocabulary.maxLabelLength && tagVocabulary.items.some((choice) => choice.id === tag.id));
  const transfer = transferState(raw.transfer, id);
  const parsedTreatment = treatment(raw.treatment);
  if (!parsedTreatment) return null;
  const loanRepaymentChoices = Array.isArray(raw.loan_repayment_choices)
    && raw.loan_repayment_choices.every((choice) => typeof choice === "string" && Boolean(choice.trim()))
    ? [...new Set(raw.loan_repayment_choices as string[])] : [];
  return {
    id,
    date: textValue(raw.date),
    description: textValue(raw.description),
    account: textValue(raw.account),
    direction,
    exactValue: textValue(raw.exact_value),
    currency: textValue(raw.currency),
    display: textValue(raw.display),
    nature: textValue(raw.nature),
    treatment: parsedTreatment,
    loanRepaymentChoices,
    sentence: textValue(raw.sentence),
    decidedBy: textValue(raw.decided_by),
    provisional: booleanValue(raw.provisional) === true,
    linked: booleanValue(raw.linked) === true,
    category: { id: typeof category.id === "string" && category.id.trim() ? category.id : null, label: textValue(category.label), valid: categoryValid },
    tags: tags.items,
    tagsValid: tags.valid,
    transfer,
    actions: rowActions(raw.actions, categoryValid && tags.valid, categoryValid && tags.valid && categories.complete && categories.items.length > 0, categoryValid && tags.valid && tagVocabulary.complete && tagsWithinBounds, transfer),
  };
}

// What moved, read into the shape a screen holds. The panel's own sentence is
// required: a read with none is one this side would have to narrate, and
// narrating what a person's money did is the claim this interface must not
// make.
export function adaptActivity(raw: unknown): ActivityData | null {
  if (!isRecord(raw)) return null;
  const sentence = textValue(raw.sentence);
  if (!sentence.trim()) return null;
  const rows = Array.isArray(raw.items) ? raw.items : [];
  const vocabularies = isRecord(raw.vocabularies) ? raw.vocabularies : {};
  const categories = categoryVocabulary(vocabularies.categories);
  const tags = tagVocabulary(vocabularies.tags);
  return {
    sentence,
    movements: rows.map((row) => movement(row, categories, tags)).filter((row): row is MovementView => row !== null),
    beyond: { count: (isRecord(raw.beyond) ? optionalNonNegativeInteger(raw.beyond.count) : undefined) ?? 0 },
    vocabularies: { categories, tags },
  };
}
