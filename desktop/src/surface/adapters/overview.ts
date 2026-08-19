import { gradePresentation } from "../evidence";
import type { AccountView, EvidenceLink, EvidenceRelation, FeatureIssue, OverviewData, PanelState } from "../types";
import { isRecord, record, textValue, uniqueRecordsById } from "./primitives";

// The words a citation may stand in to its figure. The set is the backend's,
// restated here to render it and held to the backend's by the parity fixture.
// A word outside it is dropped rather than shown.
const RELATIONS: readonly EvidenceRelation[] = ["attests", "corroborates", "same_period", "same_account", "settles_question"];

// The panel states that withhold something and carry the reasons why. Any
// other state is a read that returned its rows.
const WITHHOLDING: readonly PanelState[] = ["partial", "needs_input"];

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
  return { currentThrough: textValue(raw.as_of), coverage: "", corpusCoverage: "", corpusSource: "Opened local vault", netWorth: null, accounts, recent: [] };
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
