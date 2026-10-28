import type { NumericalAxis, NumericalBoundary, NumericalFigure, NumericalObservedInput, NumericalPremise, NumericalReceipt, NumericalSourcePage, InvestmentDerivation, TurnFigure } from "../types";
import { isRecord } from "./primitives";
const kinds = ["financial", "computed", "activity", "hypothetical"];
const grades = ["", "verified", "corroborated", "unverified", "conflicted"];
const investmentQuantities = ["security_units", "holding_cost_basis", "investment_contribution", "investment_dividend", "sale_proceeds", "disposed_cost_basis", "realized_gain"];
const quantities = [...investmentQuantities, "deposit_contract_principal", "loan_original_principal", "instrument_rate", "allocation_percentage_points", "spending", "income", "balance", "owed", "net_worth", "gross_flow", "net_movement", "movement", "repayment", "count", "ratio", "time", "ratio_of_spending", "ratio_of_income", "ratio_of_balance", "ratio_of_owed", "ratio_of_net_worth", "ratio_of_gross_flow", "ratio_of_net_movement", "ratio_of_movement", "ratio_of_repayment", "ratio_of_count"];
const axes = ["account_set", "security", "account", "merchant", "category", "period", "since", "until", "subcategory", "tag", "currency", "kind"];
const localFieldLabels = ["Goal title", "Currency", "Target amount", "Target date", "Monthly contribution", "Contribution day", "Recorded date", "Account", "Amount"];
const contextLabels = ["Retirement funding source scope", "Selected retirement plans", "Retirement funding view", "Documented rollover relationship", "Canonical rollover source", "Canonical rollover destination", "Investment view", "Disposed-basis derivation", "Investment evidence limit", "Instrument view", "Selected account", "Valuation currency", "Authenticated read revision", "Allocation comparison operation", "Accepted exposure market-value numerator", "Numerator source figure", "Accepted cash-inclusive market-value denominator", "Denominator source figure", "Display-only rounded allocation weight", "Current target receipt", "Exposure", "Snapshot date", "Arithmetic convention", "Tax absence rule", "Read day", "Projection horizon end", "Scenario horizon end", "Period from", "Period to", "Result limit", "Modeled periods", "Premise source", "Original monthly anchor", "Horizon in months", "Scenario currency", "Trajectory", "Source receipt limit", "Local receipt limit"];
const localEventTypes = ["GoalCreated", "GoalFundsReserved", "GoalFundsReleased"];
const decimal = new RegExp("^-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$");
// A signed percentage-point difference has its own dimension. A leading plus
// never changes the accepted syntax for ordinary monetary or ratio values.
function numericValue(value: string, quantity: unknown): boolean {
  return decimal.test(value) || quantity === "allocation_percentage_points" && value.startsWith("+") && decimal.test(value.slice(1)) && !value.startsWith("+-");
}
const setId = new RegExp("^retirement-set:[a-f0-9]{64}$");
const relationshipId = new RegExp("^retirement-rollover:[a-f0-9]{64}$");
function canonicalId(value: unknown): value is string { return typeof value === "string" && value.length > 0 && value.length <= 128 && new RegExp("^[\\x20-\\x7e]+$").test(value); }
function retirementSubject(raw: unknown): boolean {
  if (!isRecord(raw)) return false;
  const related = Object.hasOwn(raw, "relationship_id");
  if (!keys(raw, ["account_set_id", "set_type", "member_ids"], related ? ["relationship_id", "source_account_id", "destination_account_id"] : []) || typeof raw.account_set_id !== "string" || !setId.test(raw.account_set_id) || raw.set_type !== "retirement_plans" || !Array.isArray(raw.member_ids) || raw.member_ids.length < 1 || raw.member_ids.length > 3 || !raw.member_ids.every(canonicalId)) return false;
  const members = raw.member_ids as string[];
  if (new Set(members).size !== members.length || members.some((id, index) => index > 0 && members[index - 1] >= id)) return false;
  return !related || typeof raw.relationship_id === "string" && relationshipId.test(raw.relationship_id) && canonicalId(raw.source_account_id) && canonicalId(raw.destination_account_id) && raw.source_account_id !== raw.destination_account_id && members.includes(raw.source_account_id) && members.includes(raw.destination_account_id);
}
function retirementShape(raw: Record<string, unknown>): boolean {
  if (!retirementSubject(raw.subject) || !isRecord(raw.subject) || !isRecord(raw.boundary)) return false;
  const selected = raw.boundary.selected as NumericalAxis[] | undefined, cut = raw.boundary.cut as NumericalAxis[] | undefined;
  if (!selected || !cut || selected.length !== 1 || cut.length !== 2 || selected[0].kind !== "account_set" || selected[0].value !== JSON.stringify(raw.subject.member_ids) || cut.filter((a) => a.kind === "account_set" && a.value === selected[0].value).length !== 1) return false;
  const periods = cut.filter((a) => a.kind === "period");
  if (periods.length !== 1 || !periods[0].to) return false;
  const from = periods[0].value, to = periods[0].to;
  const iso = new RegExp("^[0-9]{4}-[0-9]{2}-[0-9]{2}$");
  if (!iso.test(from) || !iso.test(to) || !Number.isFinite(Date.parse(from)) || !Number.isFinite(Date.parse(to)) || new Date(from).toISOString().slice(0, 10) !== from || new Date(to).toISOString().slice(0, 10) !== to || to < from) return false;
  if (raw.kind !== "financial" || raw.grade === "" || !grades.includes(String(raw.grade)) || typeof raw.currency !== "string" || !new RegExp("^[A-Z]{3}$").test(raw.currency) || typeof raw.value !== "string") return false;
  if (Object.hasOwn(raw.subject, "relationship_id")) return ["investment_contribution", "gross_flow", "income"].includes(String(raw.quantity)) && (raw.quantity === "income" || !raw.value.startsWith("-")) && (Date.parse(to) - Date.parse(from)) / 86400000 < 3660;
  return raw.quantity === "investment_contribution" && !raw.value.startsWith("-") && from.endsWith("-01-01") && to === `${from.slice(0, 4)}-12-31`;
}
function investmentShape(raw: Record<string, unknown>): boolean {
  if (isRecord(raw.subject) && Object.hasOwn(raw.subject, "account_set_id")) return retirementShape(raw);
  if (isRecord(raw.boundary) && [raw.boundary.selected, raw.boundary.cut].some((axes) => Array.isArray(axes) && axes.some((axis) => isRecord(axis) && axis.kind === "account_set"))) return false;
  const investment = investmentQuantities.includes(String(raw.quantity));
  const paired = isRecord(raw.subject) && Object.hasOwn(raw.subject, "security_id");
  if (!investment && !paired) return true;
  if (!isRecord(raw.subject) || !keys(raw.subject, ["account_id"], paired ? ["security_id"] : []) || !string(raw.subject.account_id) || !raw.subject.account_id) return false;
  if (!isRecord(raw.boundary) || !Array.isArray(raw.boundary.selected) || !Array.isArray(raw.boundary.cut)) return false;
  const selected = raw.boundary.selected as NumericalAxis[], cut = raw.boundary.cut as NumericalAxis[];
  const account = raw.subject.account_id;
  if (selected.filter((a) => a.kind === "account").length !== 1 || cut.filter((a) => a.kind === "account").length !== 1 ||
      [...selected, ...cut].some((a) => a.kind === "account" && a.value !== account)) return false;
  if (paired) {
    const security = raw.subject.security_id;
    if (!string(security) || !security || cut.filter((a) => a.kind === "security").length !== 1 ||
        [...selected, ...cut].some((a) => a.kind === "security" && a.value !== security) ||
        typeof raw.dated !== "string" || !new RegExp("^[0-9]{4}-[0-9]{2}-[0-9]{2}$").test(raw.dated)) return false;
  }
  if (!investment) return true;
  if (!paired && [...selected, ...cut].some((a) => a.kind === "security")) return false;
  if (raw.kind !== "financial" || !grades.includes(String(raw.grade)) || raw.grade === "" || typeof raw.value !== "string") return false;
  if (raw.quantity !== "realized_gain" && raw.value.startsWith("-")) return false;
  if (raw.quantity === "security_units") {
    const canonical = raw.value.includes(".") ? raw.value.replace(new RegExp("0+$"), "").replace(new RegExp("\\.$"), "") : raw.value;
    return paired && raw.currency === "" && typeof raw.written === "string" && raw.written.length > 0 && raw.written.length <= 40 && raw.value.length <= 64 && new RegExp("^(?:0|[1-9][0-9]{0,17})(?:\\.[0-9]{1,12})?$").test(canonical);
  }
  if (typeof raw.currency !== "string" || !new RegExp("^[A-Z]{3}$").test(raw.currency)) return false;
  if (raw.quantity === "holding_cost_basis") return paired;
  return !paired && cut.filter((a) => a.kind === "period").length === 1;
}
function dedicatedShape(raw: Record<string, unknown>): boolean {
  if (!investmentShape(raw)) return false;
  if (raw.quantity === "allocation_percentage_points") return raw.kind === "hypothetical" && raw.grade === "" && raw.currency === "";
  if (!["deposit_contract_principal", "loan_original_principal", "instrument_rate"].includes(String(raw.quantity))) return true;
  return raw.kind === "financial" && raw.grade !== "" && grades.includes(String(raw.grade)) &&
    (raw.quantity === "instrument_rate" ? raw.currency === "" : typeof raw.currency === "string" && raw.currency.trim().length > 0);
}
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
  if (isRecord(raw) && keys(raw, ["kind", "value"]) && string(raw.kind) && axes.includes(raw.kind) && raw.kind !== "account_set" && string(raw.value) && !!raw.value) return true;
  if (!isRecord(raw)) return false;
  if (Object.hasOwn(raw, "account_set_id")) return retirementSubject(raw);
  if (keys(raw, ["grouping"])) return ["category", "merchant", "account"].includes(String(raw.grouping));
  if (keys(raw, ["account_id", "security_id"])) return string(raw.account_id) && !!raw.account_id && string(raw.security_id) && !!raw.security_id;
  return ["account_id", "merchant", "goal_id"].some((name) => keys(raw, [name]) && string(raw[name]) && !!raw[name]);
}
export function numericalFigure(raw: Record<string, unknown>): NumericalFigure | undefined {
  if (!["value", "quantity", "kind", "currency", "dated", "grade", "boundary"].every((name) => Object.hasOwn(raw, name))) return undefined;
  if (!string(raw.value) || !numericValue(raw.value, raw.quantity) || !string(raw.quantity) || !quantities.includes(raw.quantity) || !string(raw.kind) || !kinds.includes(raw.kind) || !string(raw.currency) || !string(raw.dated) || !string(raw.grade) || !grades.includes(raw.grade) || !boundary(raw.boundary)) return undefined;
  if (["activity", "hypothetical"].includes(raw.kind) && raw.grade !== "") return undefined;
  if (!dedicatedShape(raw) || !subject(raw.subject)) return undefined;
  return { value: raw.value, quantity: raw.quantity, kind: raw.kind as NumericalFigure["kind"], currency: raw.currency, dated: raw.dated, grade: raw.grade, boundary: raw.boundary, subject: (raw.subject ?? null) as NumericalFigure["subject"] };
}
function premise(raw: unknown, question: string): raw is NumericalPremise {
  if (!isRecord(raw) || !keys(raw, ["parameter", "role", "raw", "modeled", "unit", "currency", "source", "quote", "derivation"]) || raw.source !== "current_question") return false;
  if (!Object.values(raw).every((value) => value === null || string(value))) return false;
  return raw.quote === null || typeof raw.quote === "string" && question.includes(raw.quote);
}
function observed(raw: unknown): raw is NumericalObservedInput {
  if (!isRecord(raw) || investmentQuantities.includes(String(raw.quantity)) || !keys(raw, ["account_id", "value", "modeled_value", "quantity", "kind", "currency", "dated", "grade", "measurement_view", "record_ids", "carry_forward_hypothetical"])) return false;
  return ["account_id", "value", "modeled_value", "quantity", "kind", "currency", "dated", "grade", "measurement_view"].every((name) => string(raw[name])) && numericValue(String(raw.value), raw.quantity) && numericValue(String(raw.modeled_value), raw.quantity) && grades.includes(String(raw.grade)) && quantities.includes(String(raw.quantity)) && kinds.includes(String(raw.kind)) && strings(raw.record_ids) && typeof raw.carry_forward_hypothetical === "boolean" && dedicatedShape(raw);
}
function fields(raw: unknown): raw is { label: string; value: string }[] { return list(raw) && raw.every((row) => isRecord(row) && keys(row, ["label", "value"]) && string(row.label) && !!row.label && string(row.value)); }
function investmentMetadata(row: Record<string, unknown>, figures: readonly TurnFigure[], sourceRecords: NumericalReceipt["sourceRecords"]): Pick<NumericalReceipt, "figureProvenance" | "investmentDerivations"> | null {
  const ids = row.figure_ids as string[];
  const owned = figures.filter((figure) => ids.includes(figure.id));
  const required = owned.some((figure) => figure.numerical && (investmentQuantities.includes(figure.numerical.quantity) || figure.numerical.subject && ("security_id" in figure.numerical.subject || "account_set_id" in figure.numerical.subject)));
  if (!required && row.figure_provenance === undefined && row.investment_derivations === undefined) return {};
  const rawDerivations = row.investment_derivations === undefined ? [] : row.investment_derivations;
  if (!list(rawDerivations)) return null;
  if (!required && row.figure_provenance === undefined && !rawDerivations.length) return { investmentDerivations: [] };
  if (!isRecord(row.figure_provenance) || !keys(row.figure_provenance, ids)) return null;
  if (owned.length !== ids.length) return null;
  const anchors = new Set<string>();
  function pages(raw: unknown): NumericalSourcePage[] | null {
    if (!list(raw)) return null;
    const result: NumericalSourcePage[] = [];
    for (const page of raw) {
      if (!isRecord(page) || !keys(page, ["document_id", "page"]) || typeof page.document_id !== "string" || !new RegExp("^[a-f0-9]{64}$").test(page.document_id) || !integer(page.page) || page.page < 1 || page.page > 200) return null;
      anchors.add(`${page.document_id}:${page.page}`);
      if (anchors.size > 512) return null;
      result.push({ documentId: page.document_id, page: page.page });
    }
    return result;
  }
  const provenance: Record<string, readonly NumericalSourcePage[]> = Object.create(null);
  for (const id of ids) {
    const figure = owned.find((figure) => figure.id === id);
    const value = pages(row.figure_provenance[id]);
    if (!figure?.numerical || !value || !value.length) return null;
    if (value.some((page) => !sourceRecords.some((source) => source.documentId === page.documentId && figure.recordIds.includes(source.recordId)) || !figure.evidenceLinks.some((link) => link.targetDocumentId === page.documentId && link.page === String(page.page)))) return null;
    if (figure.evidenceLinks.some((link) => !value.some((page) => page.documentId === link.targetDocumentId && String(page.page) === link.page))) return null;
    provenance[id] = value;
  }
  const context = row.context as { label: string; value: string }[];
  const retired = owned.filter((figure) => figure.numerical?.subject && "account_set_id" in figure.numerical.subject);
  if (retired.length) {
    if (retired.length !== owned.length) return null;
    const first = retired[0].numerical!.subject as { account_set_id: string; member_ids: readonly string[]; relationship_id?: string; source_account_id?: string; destination_account_id?: string };
    const members = context.filter((field) => field.label === "Selected retirement plans"), view = context.filter((field) => field.label === "Retirement funding view"), scope = context.filter((field) => field.label === "Retirement funding source scope");
    if (members.length !== 1 || members[0].value !== first.member_ids.join(", ") || view.length !== 1 || view[0].value !== (first.relationship_id ? "direct_rollovers" : "annual_employee_contributions") || scope.length !== 1 || scope[0].value !== (first.relationship_id ? "complete accepted posting set for each documented direct rollover" : "accepted recorded payroll population")) return null;
    const relationships = new Map<string, string>();
    if (retired.some((figure) => {
      const subject = figure.numerical!.subject as typeof first;
      if (subject.account_set_id !== first.account_set_id || JSON.stringify(subject.member_ids) !== JSON.stringify(first.member_ids) || !!subject.relationship_id !== !!first.relationship_id || figure.numerical!.currency !== retired[0].numerical!.currency) return true;
      if (subject.relationship_id) { const endpoints = JSON.stringify([subject.source_account_id, subject.destination_account_id]); if (relationships.has(subject.relationship_id) && relationships.get(subject.relationship_id) !== endpoints) return true; relationships.set(subject.relationship_id, endpoints); }
      return false;
    })) return null;
    const ids = context.filter((field) => field.label === "Documented rollover relationship").map((field) => field.value);
    if (relationships.size > 2 || ids.length !== relationships.size || new Set(ids).size !== ids.length || ids.some((id) => !relationships.has(id))) return null;
  } else if (required) {
    const account = context.filter((field) => field.label === "Selected account");
    const currency = context.filter((field) => field.label === "Valuation currency");
    if (account.length !== 1 || currency.length !== 1 || owned.some((figure) => !figure.numerical?.subject || !("account_id" in figure.numerical.subject) || figure.numerical.subject.account_id !== account[0].value || figure.numerical.currency !== "" && figure.numerical.currency !== currency[0].value)) return null;
  }
  const derivations: InvestmentDerivation[] = [];
  for (const item of rawDerivations) {
    if (!isRecord(item) || !keys(item, ["figure_id", "operation", "rows"]) || typeof item.figure_id !== "string" || !ids.includes(item.figure_id) || item.operation !== "proceeds_minus_reported_realized_gain" || !list(item.rows, 1000) || derivations.some((d) => d.figureId === item.figure_id)) return null;
    const target = owned.find((figure) => figure.id === item.figure_id);
    if (target?.numerical?.quantity !== "disposed_cost_basis" || !item.rows.length && !new RegExp("^0(?:\\.0+)?$").test(target.numerical.value)) return null;
    const rows: InvestmentDerivation["rows"][number][] = [];
    for (const raw of item.rows) {
      if (!isRecord(raw) || !keys(raw, ["row_id", "proceeds", "reported_realized_gain", "source_pages"]) || !string(raw.row_id) || !raw.row_id || rows.some((r) => r.rowId === raw.row_id) || !string(raw.proceeds) || !decimal.test(raw.proceeds) || raw.proceeds.startsWith("-") || !string(raw.reported_realized_gain) || !decimal.test(raw.reported_realized_gain)) return null;
      const sourcePages = pages(raw.source_pages);
      if (!sourcePages?.length || sourcePages.some((p) => !provenance[item.figure_id as string].some((known) => known.documentId === p.documentId && known.page === p.page))) return null;
      rows.push({ rowId: raw.row_id, proceeds: raw.proceeds, reportedRealizedGain: raw.reported_realized_gain, sourcePages });
    }
    derivations.push({ figureId: item.figure_id, operation: item.operation, rows });
  }
  if (owned.some((figure) => figure.numerical?.quantity === "disposed_cost_basis" && !derivations.some((d) => d.figureId === figure.id))) return null;
  return { figureProvenance: provenance, investmentDerivations: derivations };
}
export function numericalReceipts(raw: unknown, question: string, figures: readonly TurnFigure[]): NumericalReceipt[] | null {
  if (!list(raw, 128)) return null;
  const receipts: NumericalReceipt[] = [];
  for (const row of raw) {
    if (!isRecord(row) || !keys(row, ["schema_version", "id", "figure_ids", "source_records", "premises", "observed_inputs", "local_inputs", "context", "caveats"], ["figure_provenance", "investment_derivations"]) || row.schema_version !== 1 || !string(row.id) || !row.id || !strings(row.figure_ids) || !row.figure_ids.length || new Set(row.figure_ids).size !== row.figure_ids.length || row.figure_ids.some((id) => !figures.some((figure) => figure.id === id)) || receipts.some((receipt) => receipt.id === row.id)) return null;
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
    const investment = investmentMetadata(row, figures, sourceRecords);
    if (!investment) return null;
    receipts.push({ ...investment, id: row.id, figureIds: row.figure_ids, sourceRecords, premises: row.premises as NumericalPremise[], observedInputs: row.observed_inputs as NumericalObservedInput[], localInputs, context: row.context, caveats: row.caveats });
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
    return { ...figure, numericalQuestion: question, receiptState: valid ? "ready" : "unavailable", numericalReceipts: valid ? (matched as NumericalReceipt[]).map((receipt) => ({ ...receipt, ...(receipt.figureProvenance ? { figureProvenance: { [figure.id]: receipt.figureProvenance[figure.id] }, investmentDerivations: receipt.investmentDerivations?.filter((item) => item.figureId === figure.id) } : {}), context: figure.numerical?.subject && "account_set_id" in figure.numerical.subject ? receipt.context.filter((field) => !["Documented rollover relationship", "Canonical rollover source", "Canonical rollover destination"].includes(field.label)) : receipt.context, sourceRecords: receipt.sourceRecords.filter((source) => figure.recordIds.includes(source.recordId)), localInputs: receipt.localInputs.filter((input) => figure.recordIds.includes(input.eventId)) })) : [] };
  });
}
