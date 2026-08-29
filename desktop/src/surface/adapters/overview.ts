import { gradePresentation } from "../evidence";
import type { AccountView, CurrentPeriodCompletenessView, CurrentPeriodExclusionView, CurrentPeriodSliceView, CurrentPeriodStepView, CurrentPeriodView, EvidenceLink, EvidenceRelation, FeatureIssue, FindingView, FigureMeasure, FigureView, ObligationView, OverviewData, PanelState, PictureView, ProofPresentation, UnmeasuredAccount, UnplacedAccount, UtilityView, WithheldCurrency } from "../types";
import { isRecord, record, textValue, uniqueRecordsById } from "./primitives";

// The words a citation may stand in to its figure. The set is the backend's,
// restated here to render it and held to the backend's by the parity fixture.
// A word outside it is dropped rather than shown.
const RELATIONS: readonly EvidenceRelation[] = ["attests", "corroborates", "same_period", "same_account", "settles_question"];

// The panel states that withhold something and carry the reasons why. Any
// other state is a read that returned its rows.
const WITHHOLDING: readonly PanelState[] = ["partial", "needs_input"];

// What a figure may say it measures. The set is the backend's, restated here
// so a word outside it is carried as no measure at all rather than shown as
// one this side invented.
const MEASURES: readonly FigureMeasure[] = ["balance", "owed", "spending", "income", "net_worth"];

function relation(value: unknown): EvidenceRelation | null {
  const named = textValue(value);
  return RELATIONS.find((known) => known === named) ?? null;
}

function evidenceLinks(balance: Record<string, unknown>): EvidenceLink[] {
  const citations = Array.isArray(balance.citations) ? balance.citations : [];
  const links: EvidenceLink[] = [];
  for (const citation of citations.map(record)) {
    const targetDocumentId = textValue(citation.document_id);
    const named = relation(citation.relation);
    if (!targetDocumentId || named === null) continue;
    links.push({ targetDocumentId, label: textValue(citation.label), relation: named, page: textValue(citation.page) });
  }
  return links;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(textValue).filter((item) => item.trim().length > 0) : [];
}

const OBLIGATION_ACTIONS = ["inspect", "ask_viva"] as const;
const FINDING_ACTIONS = ["inspect", "ask_viva", "set_aside"] as const;

function closedActions<T extends string>(value: unknown, allowed: readonly T[]): T[] {
  return stringList(value).filter((action): action is T => allowed.some((known) => known === action));
}

function obligation(value: unknown): ObligationView | null {
  const row = record(value);
  const id = textValue(row.id);
  const status = row.status === "due" || row.status === "expected" ? row.status : null;
  const basis = row.basis === "confirmed" || row.basis === "measured" || row.basis === "observed" ? row.basis : null;
  if (!id || status === null || basis === null || !textValue(row.headline) || !textValue(row.explanation) || !textValue(row.coverage)) return null;
  return { id, subject: textValue(row.subject), cadence: textValue(row.cadence), expectedDate: textValue(row.expected_date), status, basis, amountDisplay: textValue(row.amount_display), amountMin: textValue(row.amount_min), amountMax: textValue(row.amount_max), currency: textValue(row.currency), grade: textValue(row.grade), headline: textValue(row.headline), explanation: textValue(row.explanation), coverage: textValue(row.coverage), recordIds: stringList(row.record_ids), evidenceIds: stringList(row.evidence_ids), accountIds: stringList(row.account_ids), caveats: stringList(row.caveats), requiredVisibility: row.required_visibility === true, actions: closedActions(row.actions, OBLIGATION_ACTIONS) };
}

function finding(value: unknown): FindingView | null {
  const row = record(value);
  const id = textValue(row.id);
  const importance = typeof row.importance === "number" && Number.isInteger(row.importance) && row.importance > 0 ? row.importance : 0;
  if (!id || !importance || !textValue(row.kind) || !textValue(row.headline) || !textValue(row.explanation) || !textValue(row.coverage)) return null;
  return { id, kind: textValue(row.kind), subject: textValue(row.subject), importance, amountDisplay: textValue(row.amount_display), exactValue: textValue(row.exact_value), currency: textValue(row.currency), dated: textValue(row.dated), headline: textValue(row.headline), explanation: textValue(row.explanation), coverage: textValue(row.coverage), recordIds: stringList(row.record_ids), evidenceIds: stringList(row.evidence_ids), accountIds: stringList(row.account_ids), requiredVisibility: row.required_visibility === true, actions: closedActions(row.actions, FINDING_ACTIONS) };
}

function utility(value: unknown): UtilityView {
  const block = record(value);
  const obligations = (Array.isArray(block.obligations) ? block.obligations : []).map(obligation).filter((row): row is ObligationView => row !== null);
  const findings = (Array.isArray(block.findings) ? block.findings : []).map(finding).filter((row): row is FindingView => row !== null);
  const findingCount = typeof block.finding_count === "number" && Number.isInteger(block.finding_count) && block.finding_count >= findings.length ? block.finding_count : findings.length;
  return { state: block.state === "ready" ? "ready" : "absent", obligations, findings, findingCount };
}

function currentPeriodStep(value: unknown): CurrentPeriodStepView | null {
  const row = record(value);
  const kind = row.kind === "balance" || row.kind === "income" || row.kind === "obligation" ? row.kind : null;
  if (kind === null || !textValue(row.date) || !textValue(row.subject) || !textValue(row.amount_display) || !textValue(row.balance_display) || !textValue(row.tooltip)) return null;
  return { date: textValue(row.date), kind, subject: textValue(row.subject), amountDisplay: textValue(row.amount_display), amountMin: textValue(row.amount_min), amountMax: textValue(row.amount_max), balanceDisplay: textValue(row.balance_display), balanceMin: textValue(row.balance_min), balanceMax: textValue(row.balance_max), tooltip: textValue(row.tooltip), evidenceDates: stringList(row.evidence_dates), recordIds: stringList(row.record_ids), evidenceIds: stringList(row.evidence_ids), accountIds: stringList(row.account_ids) };
}

function currentPeriodCompleteness(value: unknown): CurrentPeriodCompletenessView | null {
  const row = record(value);
  const fields = [row.balances, row.income, row.obligations, row.planned_spending, row.goals];
  if (!fields.every((field) => typeof field === "boolean")) return null;
  return { balances: row.balances as boolean, income: row.income as boolean, obligations: row.obligations as boolean, plannedSpending: row.planned_spending as boolean, goals: row.goals as boolean };
}

function currentPeriodExclusion(value: unknown): CurrentPeriodExclusionView | null {
  const row = record(value);
  if (!textValue(row.kind) || !textValue(row.identity) || !textValue(row.reason) || !textValue(row.sentence)) return null;
  return { kind: textValue(row.kind), identity: textValue(row.identity), reason: textValue(row.reason), sentence: textValue(row.sentence), currency: textValue(row.currency), evidenceDates: stringList(row.evidence_dates), recordIds: stringList(row.record_ids), evidenceIds: stringList(row.evidence_ids), accountIds: stringList(row.account_ids) };
}

function currentPeriodSlice(value: unknown): CurrentPeriodSliceView | null {
  const row = record(value);
  const series = (Array.isArray(row.series) ? row.series : []).map(currentPeriodStep).filter((point): point is CurrentPeriodStepView => point !== null);
  const completeness = currentPeriodCompleteness(row.completeness);
  const exclusions = (Array.isArray(row.exclusions) ? row.exclusions : []).map(currentPeriodExclusion).filter((item): item is CurrentPeriodExclusionView => item !== null);
  if (!textValue(row.id) || !textValue(row.currency) || !textValue(row.horizon_start) || !textValue(row.horizon_end) || !textValue(row.headline) || !textValue(row.explanation) || !textValue(row.amount_display) || !textValue(row.coverage) || !textValue(row.grade_label) || !textValue(row.grade_description) || !textValue(row.evidence_label) || !textValue(row.evidence_heading) || completeness === null || !series.length || series[0]?.kind !== "balance") return null;
  const evidence = gradePresentation(textValue(row.grade) || undefined);
  return { id: textValue(row.id), currency: textValue(row.currency), horizonStart: textValue(row.horizon_start), horizonEnd: textValue(row.horizon_end), headline: textValue(row.headline), explanation: textValue(row.explanation), amountDisplay: textValue(row.amount_display), liquidBalance: textValue(row.liquid_balance), expectedIncomeMin: textValue(row.expected_income_min), expectedIncomeMax: textValue(row.expected_income_max), obligationsMin: textValue(row.obligations_min), obligationsMax: textValue(row.obligations_max), reservedForGoals: textValue(row.reserved_for_goals), goalContributions: textValue(row.goal_contributions), remainderMin: textValue(row.remainder_min), remainderMax: textValue(row.remainder_max), coverage: textValue(row.coverage), grade: evidence.grade, gradeLabel: textValue(row.grade_label), gradeDescription: textValue(row.grade_description), proofPresentation: proofPresentation(row.proof_presentation), evidenceLabel: textValue(row.evidence_label), evidenceHeading: textValue(row.evidence_heading), assumptions: stringList(row.assumptions), caveats: stringList(row.caveats), missingInputs: stringList(row.missing_inputs), completeness, exclusions, evidenceDates: stringList(row.evidence_dates), recordIds: stringList(row.record_ids), evidenceLinks: evidenceLinks(row), evidenceIds: stringList(row.evidence_ids), accountIds: stringList(row.account_ids), series, requiredVisibility: row.required_visibility === true };
}

function currentPeriod(value: unknown): CurrentPeriodView {
  const block = record(value);
  const slices = (Array.isArray(block.slices) ? block.slices : []).map(currentPeriodSlice).filter((row): row is CurrentPeriodSliceView => row !== null);
  const exclusions = (Array.isArray(block.exclusions) ? block.exclusions : []).map(currentPeriodExclusion).filter((item): item is CurrentPeriodExclusionView => item !== null);
  const state = (block.state === "ready" || block.state === "limited") && slices.length ? block.state : block.state === "refused" && textValue(block.refusal) ? "refused" : "absent";
  return { state, title: textValue(block.title), kicker: textValue(block.kicker), horizonStart: textValue(block.horizon_start), horizonEnd: textValue(block.horizon_end), slices, exclusions, refusal: textValue(block.refusal) };
}

function measure(value: unknown): FigureMeasure | null {
  const named = textValue(value);
  return MEASURES.find((known) => known === named) ?? null;
}

// Missing or unreadable policy fails visible. Reasons are carried for audit and
// tests but never become interface copy or another policy input.
function proofPresentation(value: unknown): ProofPresentation {
  const supplied = record(value);
  const reasonsValid = Array.isArray(supplied.reasons) && supplied.reasons.every((reason) => typeof reason === "string");
  const qualificationsValid = Array.isArray(supplied.qualifications) && supplied.qualifications.every((qualification) => typeof qualification === "string");
  const reasons = Array.isArray(supplied.reasons) ? supplied.reasons.filter((reason): reason is string => typeof reason === "string") : [];
  const qualifications = Array.isArray(supplied.qualifications) ? supplied.qualifications.filter((qualification): qualification is string => typeof qualification === "string") : [];
  const routine = supplied.emphasis === "routine" && reasonsValid && qualificationsValid && reasons.length === 0 && qualifications.length === 0;
  return {
    emphasis: routine ? "routine" : "required",
    reasons,
    qualifications,
  };
}

// One currency's part of the picture. Every field is the backend's; a figure
// that arrives without an identity or without a measure this side can label is
// left out rather than shown with a hole in it.
function pictureFigure(raw: Record<string, unknown>): FigureView | null {
  const id = textValue(raw.id);
  const named = measure(raw.measure);
  if (!id || named === null) return null;
  const evidence = gradePresentation(textValue(raw.grade) || undefined);
  const backendGradeLabel = textValue(raw.grade_label);
  const backendGradeDescription = textValue(raw.grade_description);
  return {
    id,
    display: textValue(raw.display),
    exactValue: textValue(raw.exact_value),
    currency: textValue(raw.currency),
    measure: named,
    grade: evidence.grade,
    gradeLabel: backendGradeLabel.trim() ? backendGradeLabel : evidence.label,
    // One whole reviewed sentence as the backend wrote it; never composed here
    // out of the ladder word.
    gradeDescription: backendGradeDescription.trim() ? backendGradeDescription : evidence.description,
    proofPresentation: proofPresentation(raw.proof_presentation),
    asOf: textValue(raw.as_of),
    // One line each, in the order the read put them in. Joining them here
    // would make a paragraph of sentences a person is meant to meet one at a
    // time, and splitting one back apart would be this side reading punctuation.
    coverage: stringList(raw.coverage),
    caveats: stringList(raw.caveats),
    evidenceLinks: evidenceLinks(raw),
    exactness: textValue(raw.exactness) || null,
    recordIds: stringList(raw.record_ids),
    // What a person who cannot see the screen is told about reaching this
    // figure's evidence. Both sentences are the read's, because one composed
    // here would announce identically for every currency.
    evidenceLabel: textValue(raw.evidence_label),
    evidenceHeading: textValue(raw.evidence_heading),
    // The accounts the read could not value, each with the reviewed sentence
    // saying why. The panel counts and never names; the figure's own evidence
    // names, which is where the rule that suppresses names sends them. The
    // boundary the read declared is not carried across at all, so nothing it
    // holds for a machine can reach a person by any route through here.
    unmeasured: unmeasured(raw.unmeasured),
  };
}

// One entry per currency the read kept back, each carrying its own sentence.
// An entry with no sentence is left out rather than rendered as a blank where
// a total would have been.
function withheld(value: unknown): WithheldCurrency[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.map(record)
    .map((row) => ({ currency: textValue(row.currency), sentence: textValue(row.sentence) }))
    .filter((row) => row.sentence.trim().length > 0);
}

// One entry per account the read left out, in the order it declared them, each
// carrying the name the read writes that account under. An entry missing any
// of the three is left out rather than shown as a name with no reason, a
// reason about nothing, or a ledger path a person never chose.
// The accounts no figure is beneath, each named and each carrying the reviewed
// sentence saying why. The read also records the token it decided under; that
// is what chose the sentence and it is not something to show a person, so it
// stops here.
function unplaced(value: unknown): UnplacedAccount[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.map(record)
    .map((row) => ({ account: textValue(row.account), name: textValue(row.name), sentence: textValue(row.sentence) }))
    .filter((row) => row.account.trim().length > 0 && row.name.trim().length > 0 && row.sentence.trim().length > 0);
}

function unmeasured(value: unknown): UnmeasuredAccount[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.map(record)
    .map((row) => ({ account: textValue(row.account), name: textValue(row.name), sentence: textValue(row.sentence) }))
    .filter((row) => row.account.trim().length > 0 && row.name.trim().length > 0 && row.sentence.trim().length > 0);
}

// The picture block as the read composed it. The sentence is carried whole and
// is never written here; the figures are carried one per currency and are
// never added together.
function picture(raw: unknown): PictureView {
  const block = record(raw);
  const supplied = Array.isArray(block.figures) ? block.figures : [];
  const figures: FigureView[] = [];
  for (const entry of supplied.map(record)) {
    const figure = pictureFigure(entry);
    if (figure !== null) figures.push(figure);
  }
  return {
    coverage: textValue(block.coverage),
    readOn: textValue(block.read_on),
    figures,
    withheld: withheld(block.withheld),
    unplaced: unplaced(block.unplaced),
  };
}

export function adaptOverview(raw: unknown): OverviewData | null {
  if (!isRecord(raw) || !Array.isArray(raw.accounts)) return null;
  if (raw.accounts.some((item) => !isRecord(item) || !textValue(item.account) || (item.balance !== undefined && item.balance !== null && !isRecord(item.balance)))) return null;
  const rows = uniqueRecordsById(raw.accounts, "account");
  const accounts: AccountView[] = rows.map((account) => {
    const balance = record(account.balance);
    const supplied = isRecord(account.balance);
    const evidence = gradePresentation(textValue(balance.grade) || undefined);
    const backendGradeLabel = textValue(balance.grade_label);
    const backendGradeDescription = textValue(balance.grade_description);
    const measure = balance.measure === "balance" || balance.measure === "owed" ? balance.measure : null;
    // Every field travels on its own: a field the read could not supply is
    // left out, and the fields beside it are carried regardless.
    return {
      id: textValue(account.account),
      name: textValue(account.name) || textValue(account.account),
      kind: textValue(account.kind),
      measure,
      exactValue: textValue(balance.exact_value),
      currency: textValue(balance.currency) || textValue(account.currency),
      display: textValue(balance.display),
      grade: evidence.grade,
      gradeLabel: backendGradeLabel.trim() ? backendGradeLabel : evidence.label,
      // One whole reviewed sentence as the backend wrote it; never composed
      // here out of the ladder word.
      gradeDescription: backendGradeDescription.trim() ? backendGradeDescription : evidence.description,
      proofPresentation: proofPresentation(balance.proof_presentation),
      note: backendGradeDescription.trim() ? backendGradeDescription : null,
      asOf: textValue(balance.as_of) || textValue(balance.dated),
      coverage: textValue(balance.coverage) || null,
      provenance: textValue(balance.provenance) || null,
      evidenceLinks: evidenceLinks(balance),
      state: supplied ? "ready" : "partial",
      caveats: stringList(balance.caveats),
      exactness: textValue(balance.exactness) || null,
      recordIds: stringList(balance.record_ids),
    };
  });
  return { picture: picture(raw.picture), accounts, utility: utility(raw.utility), currentPeriod: currentPeriod(raw.current_period) };
}

export type OverviewPanel = { state: PanelState; issues: FeatureIssue[] };

export function adaptOverviewPanel(raw: unknown): OverviewPanel {
  const payload = record(raw);
  const declared = WITHHOLDING.find((state) => state === textValue(payload.state));
  if (declared === undefined) return { state: "ready", issues: [] };
  const issues = (Array.isArray(payload.issues) ? payload.issues : []).map(record)
    .map((issue) => ({ code: textValue(issue.code), message: textValue(issue.message) }))
    .filter((issue) => issue.code.trim().length > 0);
  return { state: declared, issues };
}
