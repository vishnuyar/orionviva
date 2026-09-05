import type { SpendingBar, SpendingBreakdownData, SpendingGranularity, SpendingPeriodId } from "../types";

type Row = Record<string, unknown>;
const PERIODS: readonly SpendingPeriodId[] = ["latest_complete_month", "current_month", "last_3_months", "year_to_date", "custom"];
const GRANULARITIES: readonly SpendingGranularity[] = ["category", "subcategory"];
const COLORS: readonly SpendingBar["colorToken"][] = ["category-1", "category-2", "category-3", "category-4", "category-5", "category-6"];
const EXCLUSIONS = ["outside_attested_coverage", "unattested_posting", "conflicted_posting", "provisional_treatment", "transfer", "debt_or_settlement", "mixed_treatment", "income_or_non_expense", "unknown_treatment", "undecided_treatment", "duplicate_conflict", "account_scope_conflict", "invalid_date"] as const;
const UNSUPPORTED = ["missing_account_id", "missing_account_name", "unsupported_account_kind", "missing_account_currency"] as const;
const TOP_KEYS = ["contract", "state", "title", "as_of", "timezone_policy", "period", "granularity", "scope_summary", "controls", "sections", "coverage", "exclusions", "notes"];

function row(value: unknown): Row | null { return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Row : null; }
function exact(value: Row, keys: readonly string[]): boolean { const actual = Object.keys(value).sort(); const wanted = [...keys].sort(); return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]); }
function text(value: unknown): string | null { return typeof value === "string" && value.trim() ? value : null; }
function optionalText(value: unknown): string | null { return typeof value === "string" ? value : null; }
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number | null { return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum ? value : null; }
function iso(value: unknown): string | null {
  const held = text(value);
  if (!held || !new RegExp("^\\d{4}-\\d{2}-\\d{2}$").test(held)) return null;
  try { return new Date(`${held}T00:00:00Z`).toISOString() === `${held}T00:00:00.000Z` ? held : null; }
  catch { return null; }
}
function list<T>(value: unknown, adapt: (item: unknown) => T | null): T[] | null { if (!Array.isArray(value)) return null; const out = value.map(adapt); return out.every((item): item is T => item !== null) ? out : null; }
function unique(values: readonly string[]): boolean { return new Set(values).size === values.length; }
function sequential(values: readonly { order: number }[]): boolean { return values.every((item, index) => item.order === index); }

function orderedOption(value: unknown): { id: string; label: string; order: number } | null {
  const item = row(value); if (!item || !exact(item, ["id", "label", "order"])) return null;
  const id = text(item.id), label = text(item.label), order = integer(item.order);
  return id && label && order !== null ? { id, label, order } : null;
}
function accountOption(value: unknown): { id: string; label: string; currency: string; order: number } | null {
  const item = row(value); if (!item || !exact(item, ["id", "label", "currency", "order"])) return null;
  const id = text(item.id), label = text(item.label), currency = text(item.currency), order = integer(item.order);
  return id && label && currency && order !== null ? { id, label, currency, order } : null;
}
function periodOption(value: unknown): { id: SpendingPeriodId; label: string; requiresCustom: boolean } | null {
  const item = row(value); if (!item || !exact(item, ["id", "label", "requires_custom"])) return null;
  const id = PERIODS.find((known) => known === item.id), label = text(item.label);
  return id && label && typeof item.requires_custom === "boolean" ? { id, label, requiresCustom: item.requires_custom } : null;
}
function granularityOption(value: unknown): { id: SpendingGranularity; label: string } | null {
  const item = row(value); if (!item || !exact(item, ["id", "label"])) return null;
  const id = GRANULARITIES.find((known) => known === item.id), label = text(item.label);
  return id && label ? { id, label } : null;
}
function bar(value: unknown): SpendingBar | null {
  const item = row(value);
  if (!item || !exact(item, ["id", "order", "label", "amount_display", "share_basis_points", "bar_basis_points", "count", "color_token"])) return null;
  const id = text(item.id), order = integer(item.order), label = text(item.label), amountDisplay = text(item.amount_display);
  const shareBasisPoints = integer(item.share_basis_points, 0, 10000), barBasisPoints = integer(item.bar_basis_points, 0, 10000), count = integer(item.count, 1);
  const colorToken = COLORS.find((known) => known === item.color_token);
  return id && order !== null && label && amountDisplay && shareBasisPoints !== null && barBasisPoints !== null && count !== null && colorToken
    ? { id, order, label, amountDisplay, shareBasisPoints, barBasisPoints, count, colorToken } : null;
}

export function adaptSpendingBreakdown(value: unknown): SpendingBreakdownData | null {
  const source = row(value);
  if (!source || !exact(source, TOP_KEYS) || source.contract !== "SpendingBreakdown.v1" || (source.state !== "ready" && source.state !== "empty")) return null;
  const title = text(source.title), asOf = iso(source.as_of), timezonePolicy = text(source.timezone_policy), scopeSummary = text(source.scope_summary);
  const period = row(source.period), controls = row(source.controls), coverage = row(source.coverage);
  const granularity = GRANULARITIES.find((known) => known === source.granularity);
  if (!title || !asOf || !timezonePolicy || !scopeSummary || !period || !controls || !coverage || !granularity) return null;
  if (!exact(period, ["id", "label", "start_date", "end_date"]) || !exact(controls, ["periods", "granularities", "accounts", "currencies", "selected_period", "selected_granularity", "selected_account_id", "selected_currency"]) || !exact(coverage, ["state", "label", "covered_from", "covered_to", "gaps", "unsupported_accounts", "included_count", "excluded_count"])) return null;

  const periodId = PERIODS.find((known) => known === period.id), periodLabel = text(period.label), startDate = iso(period.start_date), endDate = iso(period.end_date);
  const selectedPeriod = PERIODS.find((known) => known === controls.selected_period), selectedGranularity = GRANULARITIES.find((known) => known === controls.selected_granularity);
  const selectedAccountId = optionalText(controls.selected_account_id), selectedCurrency = optionalText(controls.selected_currency);
  const periodOptions = list(controls.periods, periodOption), granularityOptions = list(controls.granularities, granularityOption), accountOptions = list(controls.accounts, accountOption), currencyOptions = list(controls.currencies, orderedOption);
  if (!periodId || !periodLabel || !startDate || !endDate || endDate > asOf || startDate > endDate || periodId !== selectedPeriod || granularity !== selectedGranularity || selectedAccountId === null || selectedCurrency === null || !periodOptions || !granularityOptions || !accountOptions || !currencyOptions) return null;
  if (periodOptions.map((item) => item.id).join("|") !== PERIODS.join("|") || periodOptions.some((item) => item.requiresCustom !== (item.id === "custom")) || granularityOptions.map((item) => item.id).join("|") !== GRANULARITIES.join("|") || !sequential(accountOptions) || !sequential(currencyOptions)) return null;
  if (!unique(accountOptions.map((item) => item.id)) || !unique(currencyOptions.map((item) => item.id)) || accountOptions.some((item) => !currencyOptions.some((option) => option.id === item.currency)) || (selectedAccountId && !accountOptions.some((item) => item.id === selectedAccountId)) || (selectedCurrency && !currencyOptions.some((item) => item.id === selectedCurrency))) return null;

  const sections = list(source.sections, (entry) => {
    const item = row(entry); if (!item || !exact(item, ["currency", "order", "included_count", "total_display", "bars", "empty_message"])) return null;
    const currency = text(item.currency), order = integer(item.order), includedCount = integer(item.included_count), totalDisplay = text(item.total_display), emptyMessage = optionalText(item.empty_message), bars = list(item.bars, bar);
    if (!currency || order === null || includedCount === null || !totalDisplay || emptyMessage === null || !bars || !unique(bars.map((part) => part.id)) || !sequential(bars)) return null;
    let shareTotal = 0, sectionIncludedCount = 0;
    for (const part of bars) { shareTotal += part.shareBasisPoints; sectionIncludedCount += part.count; }
    if (includedCount !== sectionIncludedCount || (bars.length && (bars[0].barBasisPoints !== 10000 || shareTotal !== 10000 || emptyMessage)) || (!bars.length && (!emptyMessage || includedCount !== 0))) return null;
    for (let index = 1; index < bars.length; index += 1) if (bars[index - 1].barBasisPoints < bars[index].barBasisPoints) return null;
    return { currency, order, includedCount, totalDisplay, bars, emptyMessage };
  });
  if (!sections || !sequential(sections) || !unique(sections.map((section) => section.currency)) || sections.some((section) => !currencyOptions.some((option) => option.id === section.currency)) || (selectedCurrency && (sections.length !== 1 || sections[0]?.currency !== selectedCurrency)) || (!selectedCurrency && sections.map((section) => section.currency).join("|") !== currencyOptions.map((option) => option.id).join("|"))) return null;
  if (selectedAccountId) {
    const account = accountOptions.find((option) => option.id === selectedAccountId);
    if (!account || currencyOptions.length !== 1 || currencyOptions[0]?.id !== account.currency || sections.length !== 1 || sections[0]?.currency !== account.currency || (selectedCurrency && selectedCurrency !== account.currency)) return null;
  }

  const gaps = list(coverage.gaps, (entry) => {
    const item = row(entry); if (!item || !exact(item, ["order", "account_id", "account_label", "from", "to", "reason", "sentence"]) || item.reason !== "missing_statement_coverage") return null;
    const order = integer(item.order), accountId = text(item.account_id), accountLabel = text(item.account_label), from = iso(item.from), to = iso(item.to), sentence = text(item.sentence);
    return order !== null && accountId && accountLabel && from && to && sentence && startDate <= from && from <= to && to <= endDate && accountOptions.some((option) => option.id === accountId && option.label === accountLabel) ? { order, accountId, accountLabel, from, to, reason: item.reason as "missing_statement_coverage", sentence } : null;
  });
  const unsupportedAccounts = list(coverage.unsupported_accounts, (entry) => {
    const item = row(entry); if (!item || !exact(item, ["order", "account_id", "label", "currency", "reason", "sentence"])) return null;
    const order = integer(item.order), accountId = optionalText(item.account_id), label = text(item.label), currency = optionalText(item.currency), reason = UNSUPPORTED.find((known) => known === item.reason), sentence = text(item.sentence);
    if (order === null || accountId === null || !label || currency === null || !reason || !sentence) return null;
    // Backend precedence is identity, name, kind, then currency. Earlier
    // reasons may retain an empty later field, but the named missing field
    // itself must be empty.
    if ((reason === "missing_account_id") !== (accountId === "") || (reason === "missing_account_currency" && currency !== "")) return null;
    return { order, accountId, label, currency, reason, sentence };
  });
  const coverageState = ["complete", "partial", "unavailable"].find((known) => known === coverage.state) as SpendingBreakdownData["coverage"]["state"] | undefined;
  const coverageLabel = text(coverage.label), coveredFrom = optionalText(coverage.covered_from), coveredTo = optionalText(coverage.covered_to), includedCount = integer(coverage.included_count), excludedCount = integer(coverage.excluded_count);
  const exclusions = list(source.exclusions, (entry) => { const item = row(entry); if (!item || !exact(item, ["kind", "count", "sentence"])) return null; const kind = EXCLUSIONS.find((known) => known === item.kind), count = integer(item.count, 1), sentence = text(item.sentence); return kind && count !== null && sentence ? { kind, count, sentence } : null; });
  const notes = Array.isArray(source.notes) && source.notes.every((item) => typeof item === "string" && item.trim()) && unique(source.notes as string[]) ? source.notes as string[] : null;
  const unsupportedIds = unsupportedAccounts?.map((item) => item.accountId).filter(Boolean) ?? [];
  if (!gaps || !unsupportedAccounts || !sequential(gaps) || !sequential(unsupportedAccounts) || !unique(unsupportedIds) || unsupportedAccounts.some((item) => (item.accountId !== "" && accountOptions.some((account) => account.id === item.accountId)) || (selectedCurrency && item.currency && item.currency !== selectedCurrency)) || (selectedAccountId && unsupportedAccounts.length > 0) || !coverageState || !coverageLabel || coveredFrom === null || coveredTo === null || includedCount === null || excludedCount === null || !exclusions || !notes || !unique(exclusions.map((item) => item.kind))) return null;
  const gapEnds = new Map<string, string>();
  for (const gap of gaps) {
    const priorEnd = gapEnds.get(gap.accountId);
    if (priorEnd && gap.from <= priorEnd) return null;
    gapEnds.set(gap.accountId, gap.to);
  }
  let authoredIncludedCount = 0, authoredExcludedCount = 0;
  for (const section of sections) authoredIncludedCount += section.includedCount;
  for (const item of exclusions) authoredExcludedCount += item.count;
  if (includedCount !== authoredIncludedCount || excludedCount !== authoredExcludedCount || (source.state === "ready") !== sections.some((section) => section.bars.length > 0)) return null;
  if ((coveredFrom || coveredTo) && (!iso(coveredFrom) || !iso(coveredTo) || coveredFrom > coveredTo || coveredFrom < startDate || coveredTo > endDate)) return null;
  if (coverageState === "complete" && (gaps.length > 0 || unsupportedAccounts.length > 0 || coveredFrom !== startDate || coveredTo !== endDate)) return null;
  if (coverageState === "partial" && (!coveredFrom || !coveredTo || (!gaps.length && !unsupportedAccounts.length))) return null;
  if (coverageState === "unavailable" && (coveredFrom || coveredTo || includedCount !== 0)) return null;

  return { contract: "SpendingBreakdown.v1", state: source.state, title, asOf, timezonePolicy, period: { id: periodId, label: periodLabel, startDate, endDate }, granularity, scopeSummary, controls: { periods: periodOptions, granularities: granularityOptions, accounts: accountOptions, currencies: currencyOptions, selectedPeriod, selectedGranularity, selectedAccountId, selectedCurrency }, sections, coverage: { state: coverageState, label: coverageLabel, coveredFrom, coveredTo, includedCount, excludedCount, gaps, unsupportedAccounts }, exclusions, notes };
}
