import { gradePresentation } from "../evidence";
import type { AccountView, OverviewData } from "../types";
import { isRecord, record, textValue, uniqueRecordsById } from "./primitives";

export function adaptOverview(raw: unknown): OverviewData | null {
  if (!isRecord(raw) || !Array.isArray(raw.accounts)) return null;
  if (raw.accounts.some((item) => !isRecord(item) || !textValue(item.account) || (item.balance !== undefined && !isRecord(item.balance)))) return null;
  const rows = uniqueRecordsById(raw.accounts, "account");
  const accounts: AccountView[] = rows.map((account) => {
    const balance = record(account.balance);
    const evidence = gradePresentation(textValue(balance.grade) || undefined);
    const backendGradeLabel = textValue(balance.grade_label);
    const canonicalDisplay = textValue(balance.display);
    const measure = balance.measure === "balance" || balance.measure === "owed" ? balance.measure : null;
    const currency = textValue(balance.currency) || textValue(account.currency);
    const asOf = textValue(balance.dated) || textValue(balance.as_of);
    const coverage = textValue(balance.coverage);
    const provenance = textValue(balance.provenance);
    const reviewed = ["verified", "corroborated", "unverified", "conflicted"].includes(textValue(balance.grade));
    return { id: textValue(account.account), name: textValue(account.name) || textValue(account.account), kind: textValue(account.kind), measure, exactValue: textValue(balance.amount), currency, display: canonicalDisplay && measure && currency && asOf && coverage && provenance && reviewed ? canonicalDisplay : "", grade: evidence.grade, gradeLabel: backendGradeLabel.trim() ? backendGradeLabel : evidence.label, gradeDescription: evidence.description, note: textValue(balance.explanation) || null, asOf, coverage: coverage || null, provenance: provenance || null, evidenceLinks: [], state: "ready" };
  });
  return { currentThrough: textValue(raw.as_of), coverage: "", corpusCoverage: "", corpusSource: "Opened local vault", netWorth: null, accounts, recent: [] };
}
