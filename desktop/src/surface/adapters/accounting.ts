import { gradePresentation } from "../evidence";
import type { AccountingView, AccountingLine, AccountingNode } from "../types";
import { isRecord, record, textValue } from "./primitives";

function rows(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter(isRecord) : []; }
function totals(value: unknown): { currency: string; values: Record<string, string> }[] {
  return Object.entries(record(value)).map(([currency, supplied]) => ({ currency, values: Object.fromEntries(Object.entries(record(supplied)).map(([key, display]) => [key, textValue(display)])) }));
}
function line(raw: Record<string, unknown>): AccountingLine {
  const amount = record(raw.amount_evidence);
  const meaning = record(raw.classification_evidence);
  const sources = [...rows(amount.sources), ...rows(amount.related_sources)];
  const documentIds = [...new Set((Array.isArray(raw.document_ids) ? raw.document_ids.map(textValue) : [
    textValue(record(amount.provenance).doc_id), textValue(raw.proves),
    ...sources.map((source) => textValue(record(source.provenance).doc_id)),
  ]).filter(Boolean))];
  const actorLabels: Record<string, string> = { human: "Your explanation", human_rule: "Your earlier explanation", document: "Supporting document", model: "Viva's interpretation", inference: "Viva's interpretation", default: "Ordinary accounting default", merchant_prior: "Merchant knowledge" };
  const explanation = textValue(meaning.explanation) || rows(meaning.sources).map((source) => textValue(source.explanation)).filter(Boolean).join(" ");
  const actor = textValue(meaning.by);
  const reasonLabels: Record<string, string> = { default: "Ordinary income or expense interpretation", ruling: "Recorded accounting treatment", linked: "Matched movement between accounts", merchant_prior: "Interpretation based on merchant knowledge", recorded_posting: "Accounting treatment recorded by the supporting document", recorded_balance: "Balance recorded by the account statement", loan: "Payment associated with a loan", mixed: "Payment allocation remains unresolved", model: "Viva's accounting interpretation", human: "Accounting treatment explained by you", human_rule: "Accounting treatment learned from your earlier explanation", conflicting_user_treatment: "The supporting document disagrees with your recorded accounting treatment", unsupported_deposit_link: "The supporting document has no uniquely matched deposit" };
  const reason = textValue(meaning.reason) || textValue(raw.reason);
  const describedReason = reasonLabels[reason] || (reason.includes("_") ? "Recorded accounting interpretation" : reason);
  return { existingExplanation: textValue(record(meaning.existing_treatment).said), supportingComponents: rows(raw.supporting_components).map((component) => ({ label: textValue(component.account), display: textValue(component.display) })), documentIds, id: textValue(raw.movement_key) || textValue(raw.account), label: [raw.merchant, raw.category, raw.subcategory].map(textValue).filter(Boolean).join(" · ") || textValue(raw.account), account: textValue(raw.account), date: textValue(raw.date) || textValue(raw.as_of), currency: textValue(raw.currency), display: textValue(raw.display), provisional: raw.provisional === true, amountEvidence: (typeof amount.provenance === "string" ? amount.provenance : "") || gradePresentation(textValue(amount.grade) || textValue(raw.grade) || textValue(sources[0]?.grade)).description, classificationEvidence: explanation || describedReason, classifiedBy: actorLabels[actor] || (actor ? "Recorded interpretation" : ""), origin: textValue(raw.origin) };
}
function node(raw: Record<string, unknown>): AccountingNode {
  return { label: textValue(raw.label), display: textValue(raw.display), children: rows(raw.children).map(node) };
}
export function adaptAccounting(raw: unknown): AccountingView | undefined {
  if (!isRecord(raw) || !isRecord(raw.balance_sheet) || !isRecord(raw.profit_loss)) return undefined;
  const balance = raw.balance_sheet;
  const profit = raw.profit_loss;
  return { asOf: textValue(balance.as_of), start: textValue(profit.start), end: textValue(profit.end), balanceComplete: balance.complete === true, profitComplete: profit.complete === true, balanceTotals: totals(balance.display_by_currency), profitTotals: totals(profit.display_by_currency), balances: rows(balance.lines).map(line), lines: rows(profit.lines).map(line), unresolved: rows(profit.unresolved_components).map(line), missing: rows(balance.missing).map((item) => ({ label: textValue(item.account) || textValue(item.name), reason: textValue(item.why) || textValue(item.reason) })), heldCount: rows(balance.held).length, hierarchy: rows(profit.hierarchy_tree).map((item) => ({ currency: textValue(item.currency), roots: rows(item.roots).map(node) })) };
}
