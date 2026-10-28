import { attachNumericalReceipts, numericalFigure } from "./numerical-receipts";
import type { ActionOutcome, ConversationData, ConversationGoalDraft, ConversationProposal, ConversationTurn, EvidenceLink, EvidenceRelation, PlanVerb, SpokenTurn, TurnFigure, TurnView, SourceAssertionReceipt, RetirementSourceAssertionReceipt, UserTargetPremise, FigureGrade } from "../types";
import { booleanValue, isRecord, textValue } from "./primitives";
import { adaptPlanDraftView } from "./plans";
import { adaptQuestions } from "./questions";

const OUTCOMES: readonly ActionOutcome[] = ["completed", "refused", "proposal", "waiting", "stale", "set_aside"];
const KINDS: readonly ConversationTurn["kind"][] = ["ask", "answer", "decline", "confirm"];
const RELATIONS: readonly EvidenceRelation[] = ["attests", "corroborates", "same_period", "same_account", "settles_question"];
const SOURCE_CLAIMS: readonly string[] = ["deposit_opened", "deposit_maturity", "loan_originated", "loan_maturity", "settlement_date", "payment_date", "tax_payment_date", "redemption_date", "deposit_compounding", "deposit_withdrawal_restriction", "escrow_withdrawal_restriction", "property_identity", "payment_reference", "tax_payment_reference", "settlement_reference", "redemption_reference", "refinance_old_account_reference", "refinance_new_account_reference", "deposit_rate_basis", "loan_note_rate_basis", "deposit_day_count", "availability_restriction", "loan_fixed_rate", "disclosure_apr_status", "disclosure_apr_context"];
const SOURCE_GRADES: readonly FigureGrade[] = ["verified", "corroborated", "unverified", "conflicted", "unavailable", "not_applicable"];
function boundedText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.length > 0 && new TextEncoder().encode(value).length <= max;
}
function opaqueId(value: unknown): value is string { return boundedText(value, 128) && /^[\x20-\x7e]+$/.test(value); }
const RETIREMENT_CLAIMS = ["rollover_date", "rollover_reference", "rollover_source_account", "rollover_destination_account"];
function retirementAssertion(item: Record<string, unknown>, figures: readonly TurnFigure[]): RetirementSourceAssertionReceipt | null {
  const fields = ["claim", "value", "value_type", "account", "anchors", "observation_ids", "record_association", "grade", "disposition", "source_lineage_digest", "association_label", "source_account_id", "destination_account_id", "id", "written"];
  if (Object.keys(item).length !== fields.length || !fields.every((field) => Object.hasOwn(item, field)) || !RETIREMENT_CLAIMS.includes(textValue(item.claim)) || !opaqueId(item.id) || !boundedText(item.value, 256) || !boundedText(item.written, 2048) || !boundedText(item.association_label, 512) || !boundedText(item.account, 128) || !opaqueId(item.source_account_id) || !opaqueId(item.destination_account_id) || item.source_account_id === item.destination_account_id || typeof item.record_association !== "string" || !new RegExp("^retirement-rollover:[a-f0-9]{64}$").test(item.record_association) || typeof item.source_lineage_digest !== "string" || !new RegExp("^[a-f0-9]{64}$").test(item.source_lineage_digest) || item.disposition !== "accepted" || !["verified", "corroborated", "unverified", "conflicted"].includes(textValue(item.grade))) return null;
  if (item.claim === "rollover_date" ? item.value_type !== "date" || !new RegExp("^[0-9]{4}-[0-9]{2}-[0-9]{2}$").test(item.value) || !Number.isFinite(Date.parse(item.value)) || new Date(item.value).toISOString().slice(0, 10) !== item.value : item.value_type !== "literal_text") return null;
  const related = figures.filter((figure) => figure.numerical?.subject && "relationship_id" in figure.numerical.subject && figure.numerical.subject.relationship_id === item.record_association);
  if (!related.length || related.some((figure) => { const subject = figure.numerical!.subject; return !subject || !("relationship_id" in subject) || subject.account_set_id !== item.account || subject.source_account_id !== item.source_account_id || subject.destination_account_id !== item.destination_account_id; })) return null;
  if (!Array.isArray(item.observation_ids) || item.observation_ids.length !== 1 || item.observation_ids[0] !== item.record_association || !Array.isArray(item.anchors) || !item.anchors.length || item.anchors.length > 512) return null;
  const anchors: RetirementSourceAssertionReceipt["anchors"][number][] = [];
  for (const anchor of item.anchors) {
    if (!isRecord(anchor) || Object.keys(anchor).length !== 2 || typeof anchor.document_id !== "string" || !new RegExp("^[a-f0-9]{64}$").test(anchor.document_id) || !Number.isSafeInteger(anchor.page) || (anchor.page as number) < 1 || (anchor.page as number) > 200 || related.some((figure) => !figure.evidenceLinks.some((link) => link.targetDocumentId === anchor.document_id && link.page === String(anchor.page)))) return null;
    anchors.push({ documentId: anchor.document_id, page: anchor.page as number });
  }
  return { sourceKind: "retirement_relationship", id: item.id, claim: item.claim as string, valueType: item.value_type as "date" | "literal_text", value: item.value, written: item.written, account: item.account, grade: item.grade as FigureGrade, recordAssociation: item.record_association, associationLabel: item.association_label, sourceAccountId: item.source_account_id, destinationAccountId: item.destination_account_id, disposition: "accepted", sourceLineageDigest: item.source_lineage_digest, anchors, observationIds: item.observation_ids as string[] };
}
function sourceAssertions(raw: unknown, figures: readonly TurnFigure[]): SourceAssertionReceipt[] {
  if (!Array.isArray(raw) || raw.length > 80) return [];
  const values: SourceAssertionReceipt[] = [];
  for (const item of raw) {
    if (isRecord(item) && RETIREMENT_CLAIMS.includes(textValue(item.claim))) {
      const receipt = retirementAssertion(item, figures); if (!receipt) return [];
      const group = values.filter((value) => value.recordAssociation === receipt.recordAssociation);
      if (group.some((value) => !("sourceKind" in value) || value.sourceLineageDigest !== receipt.sourceLineageDigest || value.sourceAccountId !== receipt.sourceAccountId || value.destinationAccountId !== receipt.destinationAccountId || value.associationLabel !== receipt.associationLabel || value.claim === receipt.claim)) return [];
      values.push(receipt); continue;
    }
    if (!isRecord(item) || !opaqueId(item.id) || !opaqueId(item.receipt_id) || !SOURCE_CLAIMS.includes(textValue(item.claim)) || !["date", "literal_text", "boolean", "enum"].includes(textValue(item.value_type)) || !boundedText(item.written, 2048) || !boundedText(item.account, 128) || !boundedText(item.effective_date, 10) || !SOURCE_GRADES.includes(item.grade as FigureGrade)) return [];
    if (typeof item.value !== "string" && typeof item.value !== "boolean") return [];
    if (typeof item.value === "string" && !boundedText(item.value, item.claim === "disclosure_apr_context" ? 2048 : 256)) return [];
    if (!Array.isArray(item.anchors) || !item.anchors.length || item.anchors.length > 512 || !Array.isArray(item.observation_ids) || !item.observation_ids.length || item.observation_ids.length > 512 || !item.observation_ids.every((id) => boundedText(id, 256))) return [];
    if (item.record_association !== null && item.record_association !== undefined && !opaqueId(item.record_association)) return [];
    const anchors: { documentId: string; page: number; anchorId: string }[] = [];
    for (const anchor of item.anchors) {
      if (!isRecord(anchor) || !boundedText(anchor.document_id, 256) || !opaqueId(anchor.anchor_id) || !Number.isSafeInteger(anchor.page) || (anchor.page as number) < 1) return [];
      anchors.push({ documentId: anchor.document_id, page: anchor.page as number, anchorId: anchor.anchor_id });
    }
    values.push({ ...(typeof item.record_association === "string" ? { recordAssociation: item.record_association } : {}), id: item.id, receiptId: item.receipt_id, claim: textValue(item.claim), valueType: item.value_type as SourceAssertionReceipt["valueType"], value: item.value, written: item.written, account: item.account, effectiveDate: item.effective_date, grade: item.grade as FigureGrade, anchors, observationIds: item.observation_ids as string[] });
  }
  return new Set(values.map((item) => item.id)).size === values.length ? values : [];
}
function targetPremises(raw: unknown): UserTargetPremise[] {
  if (!Array.isArray(raw) || raw.length !== 1) return [];
  const item = raw[0];
  if (!isRecord(item) || item.kind !== "user_stated" || item.claim !== "allocation_target" || Object.hasOwn(item, "grade") || !opaqueId(item.receipt_id) || !opaqueId(item.question_id) || !boundedText(item.target_role_text, 64) || !boundedText(item.written, 256) || !boundedText(item.account, 128) || !boundedText(item.as_of, 10) || !["bond", "equity", "cash", "other"].includes(textValue(item.exposure))) return [];
  return [{ receiptId: item.receipt_id, questionId: item.question_id, kind: "user_stated", claim: "allocation_target", targetRoleText: item.target_role_text, exposure: textValue(item.exposure), written: item.written, account: item.account, asOf: item.as_of }];
}

const PLAN_VERBS: readonly PlanVerb[] = ["create", "change_terms", "reserve", "release", "pause", "resume", "set_aside"];

function goalDraft(raw: unknown): ConversationGoalDraft | null {
  if (!isRecord(raw) || !["ready", "needs_input", "refused"].includes(textValue(raw.kind))) return null;
  const verb = PLAN_VERBS.find((candidate) => candidate === raw.verb);
  if (!verb) return null;
  return { kind: raw.kind as ConversationGoalDraft["kind"], message: textValue(raw.message), reason: textValue(raw.reason), verb, draft: adaptPlanDraftView(raw.draft), reviewInPlans: booleanValue(raw.review_in_plans) === true };
}

function evidenceLink(raw: unknown): EvidenceLink | null {
  if (!isRecord(raw)) return null;
  const targetDocumentId = textValue(raw.document_id);
  const relation = RELATIONS.find((candidate) => candidate === raw.relation);
  if (!targetDocumentId || !relation) return null;
  return { targetDocumentId, label: textValue(raw.label), relation, page: textValue(raw.page) };
}

// One figure the sentence stated. A figure with no identity is dropped: it
// could not be tied back to anything, and a row that cannot be followed is a
// claim with no route out of it.
function figure(raw: unknown): TurnFigure | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  if (!id) return null;
  return {
    id,
    numerical: numericalFigure(raw),
    ...(Array.isArray(raw.receipt_ids) && raw.receipt_ids.every((id) => typeof id === "string") ? { receiptIds: raw.receipt_ids as string[] } : ["receipt_ids", "value", "quantity", "kind", "boundary", "subject"].some((field) => Object.hasOwn(raw, field)) ? { receiptIds: [] } : {}),
    evidenceId: textValue(raw.evidence_id),
    written: textValue(raw.written),
    dated: textValue(raw.dated),
    grade: textValue(raw.grade),
    what: textValue(raw.what),
    recordIds: Array.isArray(raw.record_ids) ? raw.record_ids.map(textValue).filter((record) => record) : [],
    evidenceLinks: (Array.isArray(raw.evidence_links) ? raw.evidence_links : []).map(evidenceLink).filter((link): link is EvidenceLink => link !== null),
  };
}

// What a voice may say. `maySpeak` is the read's own answer and is never
// inferred here from whether there is text: a turn whose text mirror is not in
// front of the person carries text and may not be spoken, and those two facts
// are exactly the pair this field exists to keep apart.
function spoken(raw: unknown): SpokenTurn {
  if (!isRecord(raw)) return { maySpeak: false, withheld: "", parts: [], text: "", gradeSentence: "", citationSentence: "", localOnly: "" };
  return {
    maySpeak: booleanValue(raw.may_speak) === true,
    withheld: textValue(raw.withheld),
    parts: Array.isArray(raw.parts) ? raw.parts.map(textValue).filter((part) => part) : [],
    text: textValue(raw.text),
    gradeSentence: textValue(raw.grade_sentence),
    citationSentence: textValue(raw.citation_sentence),
    localOnly: textValue(raw.local_only),
  };
}

// One turn, read into the shape a screen holds. A turn with neither an answer
// nor a refusal is read as no turn at all: there would be nothing to show and
// nothing to say about why.
export function adaptTurn(raw: unknown): TurnView | null {
  if (!isRecord(raw)) return null;
  const text = textValue(raw.text);
  const refusal = textValue(raw.refusal);
  if (!text.trim() && !refusal.trim()) return null;
  const statuses = ["answered", "partial", "needs_clarification", "needs_assumption", "missing_data", "capability_gap", "outside_domain", "failed"] as const;
  const status = statuses.find((candidate) => candidate === raw.status)
    ?? (booleanValue(raw.answered) === true ? "answered" : "failed");
  const options = (Array.isArray(raw.options) ? raw.options : []).flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = textValue(item.id), label = textValue(item.label);
    return id && label ? [{ id, label }] : [];
  });
  const missing = (Array.isArray(raw.missing) ? raw.missing : []).flatMap((item) => {
    if (!isRecord(item)) return [];
    const tag = textValue(item.tag) || textValue(item.reason) || textValue(item.type);
    const label = textValue(item.label) || textValue(item.source);
    const question = textValue(item.question);
    const requestedFamily = textValue(item.requested_family);
    const requestedLabel = textValue(item.requested_label);
    const supportedFamilies = Array.isArray(item.supported_families)
      ? item.supported_families.flatMap((family) => {
        if (!isRecord(family)) return [];
        const id = textValue(family.id), supportedLabel = textValue(family.label), example = textValue(family.example);
        return id && supportedLabel && example ? [{ id, label: supportedLabel, example }] : [];
      })
      : [];
    return tag || label || question || requestedFamily || requestedLabel || supportedFamilies.length
      ? [{ tag, label, question, requestedFamily, requestedLabel, supportedFamilies }]
      : [];
  });
  const correction = isRecord(raw.accounting_correction) ? raw.accounting_correction : null;
  const figures = attachNumericalReceipts((Array.isArray(raw.figures) ? raw.figures : []).map(figure).filter((item): item is TurnFigure => item !== null), raw.numerical_receipts, textValue(raw.question));
  return {
    ...(correction && textValue(correction.id) ? { accountingCorrection: { id: textValue(correction.id), movementIds: Array.isArray(correction.movement_ids) ? correction.movement_ids.map(textValue).filter(Boolean) : [], ruleId: textValue(correction.rule_id) } } : {}),
    ...(opaqueId(raw.answer_id) ? { answerId: raw.answer_id, continuationEligible: raw.continuation_eligible === true && raw.answered === true } : {}),
    ...(Array.isArray(raw.allocation_selection_ids) && raw.allocation_selection_ids.length <= 4 && raw.allocation_selection_ids.every(opaqueId) ? { allocationSelectionIds: raw.allocation_selection_ids as string[] } : {}),
    sourceAssertions: sourceAssertions(raw.source_assertions, figures),
    targetPremises: targetPremises(raw.target_premises),
    question: textValue(raw.question),
    text,
    answered: booleanValue(raw.answered) === true,
    status,
    outcomeTag: textValue(raw.outcome_tag),
    refusal,
    grade: textValue(raw.grade),
    gradeSentence: textValue(raw.grade_sentence),
    figures,
    options,
    missing,
    spoken: spoken(raw.spoken),
    goalDraft: goalDraft(raw.goal_draft),
  };
}

function proposal(raw: unknown): ConversationProposal | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  if (!id) return null;
  return { id, summary: textValue(raw.summary), status: textValue(raw.status), outcome: textValue(raw.outcome), message: textValue(raw.message), reason: textValue(raw.reason) };
}

function timelineTurn(raw: unknown): ConversationTurn | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const kind = KINDS.find((candidate) => candidate === raw.kind);
  const outcome = OUTCOMES.find((candidate) => candidate === raw.outcome);
  if (!id || !kind || !outcome) return null;
  return {
    id,
    kind,
    contextMode: raw.context_mode === "new_question" || raw.context_mode === "follow_up" || raw.context_mode === "legacy" ? raw.context_mode : "legacy",
    occurredAt: textValue(raw.occurred_at),
    prompt: textValue(raw.prompt),
    said: textValue(raw.said),
    questionId: textValue(raw.question_id),
    outcome,
    message: textValue(raw.message),
    reason: textValue(raw.reason),
    answer: adaptTurn(raw.answer),
    proposal: proposal(raw.proposal),
  };
}

export function adaptConversation(raw: unknown): ConversationData | null {
  if (!isRecord(raw) || !Array.isArray(raw.turns)) return null;
  const questions = adaptQuestions(raw);
  if (!questions) return null;
  const turns = raw.turns.map(timelineTurn);
  if (turns.some((turn) => turn === null)) return null;
  return { turns: turns as ConversationTurn[], questions };
}
