import type { AccountLedgerMovement, ActivityActionOutcome, ActivityCategoryVocabulary, ActivityClassification, ActivityData, ActivityRowAction, ActivitySubcategoryVocabulary, ActivityTagVocabulary, ActivityTransferReference, ActivityTransferState, ActivityTreatment, ActivityVocabularyItem, EvidenceLink, MovementView } from "../types";
import { booleanValue, isRecord, optionalNonNegativeInteger, textValue } from "./primitives";

// The two words a direction can be, closed on both sides. A word outside the
// set is a movement this interface has not been taught to render, and the row
// is dropped rather than shown under the nearest one — a purchase reported as
// money arriving is exactly the defect that kept this read off a screen.
const DIRECTIONS = ["in", "out"] as const;
const TREATMENTS = ["spending", "loan", "loan_repayment", "settlement", "mixed", "not_spending"] as const;
const ROW_ACTIONS = ["assign_category", "assign_meaning", "replace_tags", "confirm_transfer", "reject_transfer", "unlink_transfer"] as const;
const TRANSFER_ACTIONS = ["confirm_transfer", "reject_transfer", "unlink_transfer"] as const;
const CLASSIFICATION_GRADES: readonly ActivityClassification["grade"][] = ["verified", "corroborated", "unverified", "conflicted"];

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

function subcategoryVocabulary(raw: unknown): ActivitySubcategoryVocabulary {
  if (!isRecord(raw) || !Array.isArray(raw.items)) return { items: [], complete: false, limit: 0 };
  const limit = optionalNonNegativeInteger(raw.limit);
  const seen = new Set<string>();
  const items: ActivitySubcategoryVocabulary["items"][number][] = [];
  let valid = limit !== undefined && limit > 0;
  raw.items.forEach((value) => {
    if (!isRecord(value) || !exactKeys(value, ["id", "label", "category_id"])
        || typeof value.id !== "string" || !value.id.trim()
        || typeof value.label !== "string" || !value.label.trim()
        || typeof value.category_id !== "string" || !value.category_id.trim()) { valid = false; return; }
    const key = `${value.category_id}\u0000${value.id}`;
    if (seen.has(key)) { valid = false; return; }
    seen.add(key);
    items.push({ id: value.id, label: value.label, categoryId: value.category_id });
  });
  return { items, complete: raw.complete === true && valid && items.length <= (limit ?? 0), limit: limit ?? 0 };
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
  const expected = ["id", "date", "description", "account", "account_id", "account_name", "direction", "exact_value", "currency", "display", ...(relationship ? ["relationship"] : [])];
  if (!exactKeys(raw, expected)) return null;
  const direction = DIRECTIONS.find((candidate) => candidate === raw.direction);
  const fields = [raw.id, raw.date, raw.description, raw.account, raw.account_id, raw.account_name, raw.exact_value, raw.currency, raw.display, ...(relationship ? [raw.relationship] : [])];
  if (!direction || fields.some((field) => typeof field !== "string" || !field.trim())) return null;
  return {
    id: raw.id as string,
    date: raw.date as string,
    description: raw.description as string,
    account: raw.account as string,
    accountId: raw.account_id as string,
    accountName: raw.account_name as string,
    direction,
    exactValue: raw.exact_value as string,
    currency: raw.currency as string,
    display: raw.display as string,
    ...(relationship ? { relationship: raw.relationship as string } : {}),
  };
}

function classificationValue(raw: unknown, emptyAllowed: boolean): { id: string | null; label: string; valid: boolean } {
  if (!isRecord(raw) || !exactKeys(raw, ["id", "label"])) return { id: null, label: "", valid: false };
  const id = raw.id === null ? null : typeof raw.id === "string" && raw.id.trim() ? raw.id : undefined;
  const label = typeof raw.label === "string" ? raw.label : undefined;
  const validEmpty = id === null && typeof label === "string"
    && (emptyAllowed ? label === "" : Boolean(label.trim()));
  const validValue = typeof id === "string" && typeof label === "string" && Boolean(label.trim());
  return { id: typeof id === "string" ? id : null, label: label ?? "", valid: validEmpty || validValue };
}

function classification(raw: unknown): { value: ActivityClassification | null; valid: boolean } {
  if (raw === null) return { value: null, valid: true };
  if (!isRecord(raw) || !exactKeys(raw, ["grade", "provenance"])) return { value: null, valid: false };
  const grade = CLASSIFICATION_GRADES.find((candidate) => candidate === raw.grade);
  if (!grade || typeof raw.provenance !== "string" || !raw.provenance.trim()) return { value: null, valid: false };
  return { value: { grade, provenance: raw.provenance }, valid: true };
}

function movementEvidenceLinks(raw: unknown): { links: readonly EvidenceLink[]; valid: boolean } {
  if (!Array.isArray(raw)) return { links: [], valid: false };
  const links: EvidenceLink[] = [];
  const seen = new Set<string>();
  for (const value of raw) {
    if (!isRecord(value) || !exactKeys(value, ["document_id", "label", "relation", "page", "region"])) return { links: [], valid: false };
    if (typeof value.document_id !== "string" || !value.document_id.trim() || value.relation !== "attests"
      || typeof value.label !== "string" || typeof value.page !== "string" || typeof value.region !== "string") return { links: [], valid: false };
    const identity = `${value.document_id}\u0000${value.relation}\u0000${value.page}\u0000${value.region}`;
    if (seen.has(identity)) return { links: [], valid: false };
    seen.add(identity);
    links.push({ targetDocumentId: value.document_id, label: value.label, relation: "attests", page: value.page, region: value.region });
  }
  return { links, valid: true };
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
  const account = typeof raw.account === "string" && raw.account.trim() ? raw.account : "";
  const accountId = typeof raw.account_id === "string" && raw.account_id.trim() ? raw.account_id : "";
  const accountName = typeof raw.account_name === "string" && raw.account_name.trim() ? raw.account_name : "";
  if (!id || !direction || !account || !accountId || accountId !== account || !accountName) return null;
  const category = classificationValue(raw.category, false);
  const subcategory = classificationValue(raw.subcategory, true);
  const parsedClassification = classification(raw.classification);
  // Category, subcategory, grade, and provenance are one authority record.
  // Reading the pieces independently would let a finer label appear to be
  // grounded when its parent or provenance was absent.
  const hasCategory = category.id !== null;
  const hasSubcategory = subcategory.id !== null;
  const hierarchyValid = !hasSubcategory || hasCategory;
  const classificationRequired = hasCategory || hasSubcategory;
  const classificationCoherent = parsedClassification.valid
    && hierarchyValid
    && (classificationRequired ? parsedClassification.value !== null : parsedClassification.value === null);
  const currentClassificationValid = category.valid && subcategory.valid && classificationCoherent;
  const tags = vocabularyItems(raw.tags);
  const tagsWithinBounds = tags.items.length <= tagVocabulary.maxSelected && tags.items.every((tag) => tag.id.length <= tagVocabulary.maxLabelLength && tagVocabulary.items.some((choice) => choice.id === tag.id));
  const transfer = transferState(raw.transfer, id);
  const parsedTreatment = treatment(raw.treatment);
  const evidence = movementEvidenceLinks(raw.evidence_links);
  if (!parsedTreatment) return null;
  const loanRepaymentChoices = Array.isArray(raw.loan_repayment_choices)
    && raw.loan_repayment_choices.every((choice) => typeof choice === "string" && Boolean(choice.trim()))
    ? [...new Set(raw.loan_repayment_choices as string[])] : [];
  return {
    id,
    date: textValue(raw.date),
    description: textValue(raw.description),
    account,
    accountId,
    accountName,
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
    category,
    subcategory: { ...subcategory, valid: subcategory.valid && hierarchyValid },
    classification: parsedClassification.value,
    classificationValid: currentClassificationValid,
    tags: tags.items,
    tagsValid: tags.valid,
    evidenceLinks: evidence.links,
    evidenceLinksValid: evidence.valid,
    transfer,
    actions: rowActions(raw.actions, currentClassificationValid && tags.valid, currentClassificationValid && tags.valid && categories.complete && categories.items.length > 0, currentClassificationValid && tags.valid && tagVocabulary.complete && tagsWithinBounds, transfer),
  };
}

// AccountLedger reuses the exact movement contract without inheriting the
// Activity write vocabulary. Its boundary is stricter than Activity's
// progressive parser: a malformed read-only row invalidates the ledger rather
// than becoming a row with silently downgraded evidence or closed state.
export function adaptReadOnlyMovement(raw: unknown): Omit<AccountLedgerMovement, "directionDisplay"> | null {
  const fields = ["id", "date", "description", "account", "account_id", "account_name", "direction", "exact_value", "currency", "display", "nature", "treatment", "loan_repayment_choices", "sentence", "decided_by", "provisional", "linked", "category", "subcategory", "classification", "tags", "evidence_links", "transfer", "actions", "deduplication"];
  if (!isRecord(raw) || !exactKeys(raw, fields)
      || !Array.isArray(raw.actions) || raw.actions.length !== 0
      || typeof raw.provisional !== "boolean" || typeof raw.linked !== "boolean"
      || !Array.isArray(raw.loan_repayment_choices)
      || raw.loan_repayment_choices.some((choice) => typeof choice !== "string" || !choice.trim())
      || new Set(raw.loan_repayment_choices).size !== raw.loan_repayment_choices.length
      || typeof raw.date !== "string" || !calendarDay(raw.date)
      || typeof raw.exact_value !== "string" || !finiteDecimal(raw.exact_value)
      || !strictTransferScalars(raw.transfer)) return null;
  const deduplication = raw.deduplication;
  if (!isRecord(deduplication)
      || !exactKeys(deduplication, ["state", "canonical_movement_id", "member_movement_ids"])
      || !["single", "exact_duplicate"].includes(String(deduplication.state))
      || deduplication.canonical_movement_id !== raw.id
      || !Array.isArray(deduplication.member_movement_ids)
      || deduplication.member_movement_ids.some((id) => typeof id !== "string" || !id.trim())
      || new Set(deduplication.member_movement_ids).size !== deduplication.member_movement_ids.length
      || JSON.stringify(deduplication.member_movement_ids) !== JSON.stringify([...deduplication.member_movement_ids].sort())
      || deduplication.member_movement_ids[0] !== raw.id
      || (deduplication.state === "single") !== (deduplication.member_movement_ids.length === 1)) return null;
  const adapted = movement(
    raw,
    { items: [], complete: false, limit: 0 },
    { items: [], complete: false, limit: 0, maxSelected: 0, maxLabelLength: 0 },
  );
  return adapted && adapted.actions.length === 0 && adapted.transfer !== null
    && adapted.classificationValid && adapted.tagsValid
    && adapted.evidenceLinksValid ? {
      ...adapted,
      deduplication: {
        state: deduplication.state as "single" | "exact_duplicate",
        canonicalMovementId: adapted.id,
        memberMovementIds: deduplication.member_movement_ids as string[],
      },
    } : null;
}

function calendarDay(raw: string): boolean {
  if (!/^[1-9]\d{3}-\d{2}-\d{2}$/.test(raw)) return false;
  const parsed = new Date(`${raw}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf())
    && parsed.toISOString().slice(0, 10) === raw;
}

function finiteDecimal(raw: string): boolean {
  // This grammar admits only finite decimal literals. Infinity and NaN have
  // no spelling in it, and no frontend arithmetic is needed to decide that.
  return new RegExp("^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?$").test(raw);
}

function strictTransferScalars(raw: unknown): boolean {
  if (!isRecord(raw) || typeof raw.state !== "string") return false;
  const references = raw.state === "suggested" && Array.isArray(raw.candidates)
    ? raw.candidates : raw.state === "linked" ? [raw.counterpart] : [];
  return references.every((reference) => isRecord(reference)
    && typeof reference.date === "string" && calendarDay(reference.date)
    && typeof reference.exact_value === "string"
    && finiteDecimal(reference.exact_value));
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
  const subcategories = subcategoryVocabulary(vocabularies.subcategories);
  const tags = tagVocabulary(vocabularies.tags);
  const movements = rows.map((row) => movement(row, categories, tags));
  // A malformed additive identity invalidates the read atomically. Returning
  // the other rows would look like a complete successful activity surface
  // while silently removing a real movement.
  if (movements.some((row) => row === null)) return null;
  return {
    sentence,
    movements: movements as MovementView[],
    beyond: { count: (isRecord(raw.beyond) ? optionalNonNegativeInteger(raw.beyond.count) : undefined) ?? 0 },
    vocabularies: { categories, subcategories, tags },
  };
}
