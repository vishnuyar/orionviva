import type { NumericalAxis, NumericalBoundary, NumericalFigure, NumericalObservedInput, NumericalPremise, NumericalReceipt, TurnFigure } from "../types";
import { isRecord } from "./primitives";
const kinds = ["financial", "computed", "activity", "hypothetical"];
const grades = ["", "verified", "corroborated", "unverified", "conflicted"];
const quantities = ["spending", "income", "balance", "owed", "net_worth", "gross_flow", "net_movement", "movement", "repayment", "count", "ratio", "time", "ratio_of_spending", "ratio_of_income", "ratio_of_balance", "ratio_of_owed", "ratio_of_net_worth", "ratio_of_gross_flow", "ratio_of_net_movement", "ratio_of_movement", "ratio_of_repayment", "ratio_of_count"];
const axes = ["account", "merchant", "category", "period", "since", "until", "subcategory", "tag", "currency", "kind"];
const localFieldLabels = ["Goal title", "Currency", "Target amount", "Target date", "Monthly contribution", "Contribution day", "Recorded date", "Account", "Amount"];
const contextLabels = ["Read day", "Projection horizon end", "Scenario horizon end", "Period from", "Period to", "Result limit", "Modeled periods", "Premise source", "Original monthly anchor", "Horizon in months", "Scenario currency", "Trajectory", "Source receipt limit", "Local receipt limit"];
const localEventTypes = ["GoalCreated", "GoalFundsReserved", "GoalFundsReleased"];
const decimal = new RegExp("^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$");
function string(value: unknown): value is string { return typeof value === "string" && value.length <= 16_384; }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 2048 && value.every((item) => string(item) && item.length > 0); }
function list(value: unknown, max = 512): value is unknown[] { return Array.isArray(value) && value.length <= max; }
function keys(value: Record<string, unknown>, required: string[], optional: string[] = []): boolean { return required.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => required.includes(key) || optional.includes(key)); }
function integer(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function axis(raw: unknown): raw is NumericalAxis { return isRecord(raw) && keys(raw, ["kind", "value"], ["to"]) && string(raw.kind) && axes.includes(raw.kind) && string(raw.value) && !!raw.value && (raw.kind === "period" ? string(raw.to) && !!raw.to : raw.to === undefined); }
function boundary(raw: unknown): raw is NumericalBoundary {
  if (!isRecord(raw) || !keys(raw, [], ["whole", "accounts", "selected", "cut", "unmeasured", "unposted"])) return false;
  if (raw.whole !== undefined && typeof raw.whole !== "boolean") return false;
  if (raw.accounts !== undefined && (!isRecord(raw.accounts) || !keys(raw.accounts, ["counted", "held"]) || !integer(raw.accounts.counted) || !integer(raw.accounts.held) || raw.accounts.counted > raw.accounts.held)) return false;
  for (const name of ["selected", "cut"]) if (raw[name] !== undefined && (!list(raw[name]) || !raw[name].every(axis))) return false;
  if (raw.unmeasured !== undefined && (!list(raw.unmeasured) || !raw.unmeasured.every((row) => isRecord(row) && keys(row, ["account", "reason", "settled_by"]) && string(row.account) && ["refused", "unobserved"].includes(String(row.reason)) && string(row.settled_by)))) return false;
  return raw.unposted === undefined || integer(raw.unposted);
}
function subject(raw: unknown): boolean {
  if (raw === undefined || raw === null) return true;
  if (isRecord(raw) && keys(raw, ["kind", "value"]) && string(raw.kind) && axes.includes(raw.kind) && string(raw.value) && !!raw.value) return true;
  if (!isRecord(raw)) return false;
  if (keys(raw, ["grouping"])) return ["category", "merchant", "account"].includes(String(raw.grouping));
  return ["account_id", "merchant", "goal_id"].some((name) => keys(raw, [name]) && string(raw[name]) && !!raw[name]);
}
export function numericalFigure(raw: Record<string, unknown>): NumericalFigure | undefined {
  if (!["value", "quantity", "kind", "currency", "dated", "grade", "boundary"].every((name) => Object.hasOwn(raw, name))) return undefined;
  if (!string(raw.value) || !decimal.test(raw.value) || !string(raw.quantity) || !quantities.includes(raw.quantity) || !string(raw.kind) || !kinds.includes(raw.kind) || !string(raw.currency) || !string(raw.dated) || !string(raw.grade) || !grades.includes(raw.grade) || !boundary(raw.boundary)) return undefined;
  if (["activity", "hypothetical"].includes(raw.kind) && raw.grade !== "") return undefined;
  if (!subject(raw.subject)) return undefined;
  return { value: raw.value, quantity: raw.quantity, kind: raw.kind as NumericalFigure["kind"], currency: raw.currency, dated: raw.dated, grade: raw.grade, boundary: raw.boundary, subject: (raw.subject ?? null) as NumericalFigure["subject"] };
}
function premise(raw: unknown, question: string): raw is NumericalPremise {
  if (!isRecord(raw) || !keys(raw, ["parameter", "role", "raw", "modeled", "unit", "currency", "source", "quote", "derivation"]) || raw.source !== "current_question") return false;
  if (!Object.values(raw).every((value) => value === null || string(value))) return false;
  return raw.quote === null || typeof raw.quote === "string" && question.includes(raw.quote);
}
function observed(raw: unknown): raw is NumericalObservedInput {
  if (!isRecord(raw) || !keys(raw, ["account_id", "value", "modeled_value", "quantity", "kind", "currency", "dated", "grade", "measurement_view", "record_ids", "carry_forward_hypothetical"])) return false;
  return ["account_id", "value", "modeled_value", "quantity", "kind", "currency", "dated", "grade", "measurement_view"].every((name) => string(raw[name])) && decimal.test(String(raw.value)) && decimal.test(String(raw.modeled_value)) && grades.includes(String(raw.grade)) && quantities.includes(String(raw.quantity)) && kinds.includes(String(raw.kind)) && strings(raw.record_ids) && typeof raw.carry_forward_hypothetical === "boolean";
}
function fields(raw: unknown): raw is { label: string; value: string }[] { return list(raw) && raw.every((row) => isRecord(row) && keys(row, ["label", "value"]) && string(row.label) && !!row.label && string(row.value)); }
export function numericalReceipts(raw: unknown, question: string, figures: readonly TurnFigure[]): NumericalReceipt[] | null {
  if (!list(raw, 128)) return null;
  const receipts: NumericalReceipt[] = [];
  for (const row of raw) {
    if (!isRecord(row) || !keys(row, ["schema_version", "id", "figure_ids", "source_records", "premises", "observed_inputs", "local_inputs", "context", "caveats"]) || row.schema_version !== 1 || !string(row.id) || !row.id || !strings(row.figure_ids) || !row.figure_ids.length || new Set(row.figure_ids).size !== row.figure_ids.length || row.figure_ids.some((id) => !figures.some((figure) => figure.id === id)) || receipts.some((receipt) => receipt.id === row.id)) return null;
    if (!list(row.source_records) || !list(row.premises) || !row.premises.every((item) => premise(item, question)) || !list(row.observed_inputs) || !row.observed_inputs.every(observed) || !list(row.local_inputs) || !fields(row.context) || !row.context.every((field) => contextLabels.includes(field.label)) || !strings(row.caveats)) return null;
    const sourceRecords: NumericalReceipt["sourceRecords"][number][] = [];
    for (const source of row.source_records) {
      if (!isRecord(source) || !keys(source, ["record_id", "kind", "document_id"]) || !string(source.record_id) || !source.record_id || !["document", "movement", "local_activity", "unavailable"].includes(String(source.kind)) || !(source.document_id === null || typeof source.document_id === "string" && new RegExp("^[a-f0-9]{64}$").test(source.document_id)) || ["local_activity", "unavailable"].includes(String(source.kind)) && source.document_id !== null || source.kind === "document" && source.document_id === null) return null;
      if (sourceRecords.some((record) => record.recordId === source.record_id)) return null;
      sourceRecords.push({ recordId: source.record_id, kind: source.kind as NumericalReceipt["sourceRecords"][number]["kind"], documentId: source.document_id as string | null });
    }
    const localInputs: NumericalReceipt["localInputs"][number][] = [];
    for (const local of row.local_inputs) {
      if (!isRecord(local) || !keys(local, ["event_id", "event_type", "fields"]) || !string(local.event_id) || !string(local.event_type) || !localEventTypes.includes(local.event_type) || !fields(local.fields) || !local.fields.every((field) => localFieldLabels.includes(field.label))) return null;
      if (localInputs.some((input) => input.eventId === local.event_id)) return null;
      localInputs.push({ eventId: local.event_id, eventType: local.event_type, fields: local.fields });
    }
    receipts.push({ id: row.id, figureIds: row.figure_ids, sourceRecords, premises: row.premises as NumericalPremise[], observedInputs: row.observed_inputs as NumericalObservedInput[], localInputs, context: row.context, caveats: row.caveats });
  }
  return receipts;
}
export function attachNumericalReceipts(figures: TurnFigure[], raw: unknown, question: string): TurnFigure[] {
  const receipts = numericalReceipts(raw, question, figures);
  return figures.map((figure) => {
    if (!figure.numerical && figure.receiptIds === undefined) return { ...figure, receiptState: "legacy" };
    const suffix = `:${figure.id}`;
    const prefix = figure.evidenceId.startsWith("conversation:") && figure.evidenceId.endsWith(suffix) ? figure.evidenceId.slice(0, -figure.id.length) : "";
    const matched = figure.receiptIds?.map((id) => prefix && id.startsWith(`${prefix}numerical:`) ? receipts?.find((receipt) => receipt.id === id && receipt.figureIds.includes(figure.id)) : undefined);
    const valid = !!figure.numerical && !!matched?.length && new Set(figure.receiptIds).size === figure.receiptIds?.length && matched.every((receipt) => receipt !== undefined);
    return { ...figure, numericalQuestion: question, receiptState: valid ? "ready" : "unavailable", numericalReceipts: valid ? (matched as NumericalReceipt[]).map((receipt) => ({ ...receipt, sourceRecords: receipt.sourceRecords.filter((source) => figure.recordIds.includes(source.recordId)), localInputs: receipt.localInputs.filter((input) => figure.recordIds.includes(input.eventId)) })) : [] };
  });
}
