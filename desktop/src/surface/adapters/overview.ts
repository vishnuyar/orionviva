import { gradePresentation } from "../evidence";
import type { AccountView, EvidenceLink, EvidenceRelation, FeatureIssue, FigureMeasure, FigureView, OverviewData, PanelState, PictureView, UnmeasuredAccount, UnplacedAccount, WithheldCurrency } from "../types";
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

function measure(value: unknown): FigureMeasure | null {
  const named = textValue(value);
  return MEASURES.find((known) => known === named) ?? null;
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
  return { picture: picture(raw.picture), accounts };
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
