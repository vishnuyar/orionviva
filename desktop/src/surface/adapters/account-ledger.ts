import type { AccountLedgerBalance, AccountLedgerCoverageRun, AccountLedgerData, AccountLedgerDeduplication, AccountLedgerGap, AccountLedgerMovement, AccountLedgerSource } from "../types";
import { adaptReadOnlyMovement } from "./activity";
import { isRecord, nextCalendarDay, optionalNonNegativeInteger, previousCalendarDay } from "./primitives";

const ACCOUNT_TYPES = ["depository", "liability", "investment"] as const;
const BALANCE_KINDS = ["current_balance", "amount_owed"] as const;
const GRADES = ["verified", "corroborated", "unverified", "conflicted"] as const;
const COVERAGE_STATES = ["unavailable", "continuous", "gapped", "discontinuous"] as const;
const BALANCE_STATES = ["reconciled", "conflicted", "not_established"] as const;
const RELATIONS = ["statement", "movement_evidence", "statement_and_movement_evidence"] as const;
const MAX_LIMIT = 100;

function exact(raw: Record<string, unknown>, fields: readonly string[]): boolean {
  return Object.keys(raw).sort().join(",") === [...fields].sort().join(",");
}

function nonblank(raw: unknown): string | null {
  return typeof raw === "string" && raw.trim() ? raw : null;
}

function day(raw: unknown): string | null {
  const value = nonblank(raw);
  if (!value || !/^[1-9]\d{3}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf())
    && parsed.toISOString().slice(0, 10) === value ? value : null;
}

function decimal(raw: unknown): string | null {
  const value = nonblank(raw);
  return value && new RegExp("^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?$").test(value)
    ? value : null;
}

function negativeNonZeroDecimal(value: string): boolean {
  if (!value.startsWith("-")) return false;
  const mantissa = value.slice(1).split(/[eE]/, 1)[0];
  return /[1-9]/.test(mantissa);
}

function period(raw: unknown): { from: string; to: string } | null | undefined {
  if (raw === null) return null;
  if (!isRecord(raw) || !exact(raw, ["from", "to"])) return undefined;
  const from = day(raw.from); const to = day(raw.to);
  return from && to && from <= to ? { from, to } : undefined;
}

function coverageRun(raw: unknown): AccountLedgerCoverageRun | null {
  if (!isRecord(raw) || !exact(raw, ["from", "to", "statement_ids"])) return null;
  const from = day(raw.from); const to = day(raw.to);
  if (!from || !to || from > to || !Array.isArray(raw.statement_ids) || raw.statement_ids.length === 0
      || raw.statement_ids.some((id) => !nonblank(id))) return null;
  const ids = raw.statement_ids as string[];
  if (new Set(ids).size !== ids.length) return null;
  return { from, to, statementIds: ids };
}

function gap(raw: unknown): AccountLedgerGap | null {
  if (!isRecord(raw) || !exact(raw, ["from", "to", "reason"])) return null;
  const from = day(raw.from); const to = day(raw.to);
  return from && to && from <= to && raw.reason === "missing_statement_coverage"
    ? { from, to, reason: raw.reason } : null;
}

function source(raw: unknown): AccountLedgerSource | null {
  if (!isRecord(raw) || !exact(raw, ["document_id", "account_id", "filename", "relation", "period"])) return null;
  const documentId = nonblank(raw.document_id);
  const accountId = nonblank(raw.account_id);
  const relation = RELATIONS.find((item) => item === raw.relation);
  const parsedPeriod = period(raw.period);
  if (!documentId || !accountId || !relation || typeof raw.filename !== "string" || parsedPeriod === undefined
      || (relation === "movement_evidence") !== (parsedPeriod === null)) return null;
  return { documentId, accountId, filename: raw.filename, relation, period: parsedPeriod };
}

function balance(raw: unknown, accountType: typeof ACCOUNT_TYPES[number]): AccountLedgerBalance | null {
  if (!isRecord(raw) || typeof raw.state !== "string") return null;
  if (raw.state === "absent") {
    return exact(raw, ["state", "reason"])
      && raw.reason === "no_authoritative_balance_observation"
      ? { state: "absent", reason: raw.reason } : null;
  }
  if (raw.state !== "available" || !exact(raw, ["state", "kind", "exact_value", "display", "as_of", "grade"])) return null;
  const kind = BALANCE_KINDS.find((item) => item === raw.kind);
  const grade = GRADES.find((item) => item === raw.grade);
  const exactValue = decimal(raw.exact_value); const display = nonblank(raw.display); const asOf = day(raw.as_of);
  const expectedKind = accountType !== "liability" || negativeNonZeroDecimal(exactValue ?? "")
    ? "current_balance" : "amount_owed";
  if (!kind || kind !== expectedKind
      || !grade || !exactValue || !display || !asOf) return null;
  return { state: "available", kind, exactValue, display, asOf, grade };
}

function ledgerMovement(raw: unknown): AccountLedgerMovement | null {
  if (!isRecord(raw) || !Object.prototype.hasOwnProperty.call(raw, "direction_display")) return null;
  const directionDisplay = (["Debit", "Credit", "Direction unavailable"] as const).find((label) => label === raw.direction_display);
  const activityRaw = { ...raw };
  delete activityRaw.direction_display;
  const parsed = adaptReadOnlyMovement(activityRaw);
  return parsed && directionDisplay ? { ...parsed, directionDisplay } : null;
}

export function adaptAccountLedger(raw: unknown): AccountLedgerData | null {
  if (!isRecord(raw) || !exact(raw, ["state", "scope", "revision", "account", "coverage", "reconciliation", "sources", "groups", "page"]) || raw.state !== "ready") return null;
  if (!isRecord(raw.scope) || !exact(raw.scope, ["kind", "account_id"]) || raw.scope.kind !== "account") return null;
  const accountId = nonblank(raw.scope.account_id); const revision = nonblank(raw.revision);
  const account = raw.account;
  if (!accountId || !revision || !isRecord(account) || !exact(account, ["id", "name", "number_masked", "type", "currency", "balance"])) return null;
  const accountType = ACCOUNT_TYPES.find((item) => item === account.type);
  const name = nonblank(account.name); const maskedNumber = nonblank(account.number_masked); const currency = nonblank(account.currency);
  if (account.id !== accountId || !accountType || !name || !maskedNumber || !/^\u2022{4}\d{4}$/.test(maskedNumber) || !currency) return null;
  const parsedBalance = balance(account.balance, accountType);
  if (!parsedBalance) return null;

  const coverage = raw.coverage;
  if (!isRecord(coverage) || !exact(coverage, ["state", "runs", "gaps"])) return null;
  const coverageState = COVERAGE_STATES.find((item) => item === coverage.state);
  if (!coverageState || !Array.isArray(coverage.runs) || !Array.isArray(coverage.gaps)) return null;
  const runs = coverage.runs.map(coverageRun); const gaps = coverage.gaps.map(gap);
  if (runs.some((item) => item === null) || gaps.some((item) => item === null)) return null;
  const safeRuns = runs as AccountLedgerCoverageRun[];
  const safeGaps = gaps as AccountLedgerGap[];
  const statementIds = safeRuns.flatMap((run) => run.statementIds);
  if (new Set(statementIds).size !== statementIds.length
      || safeRuns.some((run, index) => index > 0 && run.from <= safeRuns[index - 1].to)) return null;
  const exactGaps: AccountLedgerGap[] = [];
  safeRuns.slice(1).forEach((run, index) => {
    const from = nextCalendarDay(safeRuns[index].to);
    const to = previousCalendarDay(run.from);
    if (from && to && from <= to) exactGaps.push({
      from, to, reason: "missing_statement_coverage",
    });
  });
  if (JSON.stringify(safeGaps) !== JSON.stringify(exactGaps)) return null;
  if ((coverageState === "unavailable" && (runs.length !== 0 || gaps.length !== 0))
      || (coverageState === "continuous" && (runs.length !== 1 || gaps.length !== 0))
      || (coverageState === "gapped" && (runs.length < 2 || gaps.length === 0))
      || (coverageState === "discontinuous" && (runs.length < 2 || gaps.length !== 0))) return null;

  const reconciliation = raw.reconciliation;
  if (!isRecord(reconciliation) || !exact(reconciliation, ["balance", "overlap", "running_balance"])) return null;
  const balanceState = BALANCE_STATES.find((item) => item === reconciliation.balance);
  const overlap = reconciliation.overlap; const running = reconciliation.running_balance;
  if (!balanceState || !isRecord(overlap) || !exact(overlap, ["state", "deduplication", "groups"])
      || !["none_observed", "overlap_present"].includes(String(overlap.state)) || !Array.isArray(overlap.groups)
      || !isRecord(running) || !exact(running, ["state", "reason"]) || running.state !== "absent" || running.reason !== "not_authoritatively_available") return null;
  const overlapGroups = overlap.groups.map((item) => {
    if (!isRecord(item) || !exact(item, ["from", "to", "document_ids"]) || !Array.isArray(item.document_ids)) return null;
    const from = day(item.from); const to = day(item.to); const documentIds = item.document_ids as unknown[];
    if (!from || !to || from > to || documentIds.length !== 2 || documentIds.some((id) => !nonblank(id))
        || new Set(documentIds).size !== documentIds.length
        || JSON.stringify(documentIds) !== JSON.stringify([...documentIds].sort())) return null;
    return { from, to, documentIds: documentIds as [string, string] };
  });
  if (overlapGroups.some((item) => item === null)) return null;
  if ((overlap.state === "none_observed") !== (overlapGroups.length === 0)) return null;

  const rawDeduplication = overlap.deduplication;
  if (!isRecord(rawDeduplication)
      || !exact(rawDeduplication, ["state", "policy", "collapsed", "unresolved"])
      || !["none", "exact_duplicates_collapsed", "unresolved_candidates_present", "exact_duplicates_collapsed_with_unresolved_candidates"].includes(String(rawDeduplication.state))
      || rawDeduplication.policy !== "exact_economic_posting_in_overlapping_statements_only"
      || !Array.isArray(rawDeduplication.collapsed) || !Array.isArray(rawDeduplication.unresolved)) return null;
  const collapsed = rawDeduplication.collapsed.map((item) => {
    if (!isRecord(item) || !exact(item, ["canonical_movement_id", "member_movement_ids", "document_ids"])
        || !Array.isArray(item.member_movement_ids) || !Array.isArray(item.document_ids)) return null;
    const canonicalMovementId = nonblank(item.canonical_movement_id);
    const memberMovementIds = item.member_movement_ids as unknown[];
    const documentIds = item.document_ids as unknown[];
    if (!canonicalMovementId || memberMovementIds.length < 2 || documentIds.length < 2
        || memberMovementIds.some((id) => !nonblank(id)) || documentIds.some((id) => !nonblank(id))
        || new Set(memberMovementIds).size !== memberMovementIds.length || new Set(documentIds).size !== documentIds.length
        || memberMovementIds[0] !== canonicalMovementId
        || JSON.stringify(memberMovementIds) !== JSON.stringify([...memberMovementIds].sort())
        || JSON.stringify(documentIds) !== JSON.stringify([...documentIds].sort())) return null;
    return { canonicalMovementId, memberMovementIds: memberMovementIds as string[], documentIds: documentIds as string[] };
  });
  const unresolved = rawDeduplication.unresolved.map((item) => {
    if (!isRecord(item) || !exact(item, ["kind", "movement_ids", "document_ids"])
        || !["probable", "conflicting"].includes(String(item.kind))
        || !Array.isArray(item.movement_ids) || !Array.isArray(item.document_ids)
        || item.movement_ids.length !== 2 || item.document_ids.length !== 2
        || item.movement_ids.some((id) => !nonblank(id)) || item.document_ids.some((id) => !nonblank(id))
        || new Set(item.movement_ids).size !== 2 || new Set(item.document_ids).size !== 2
        || JSON.stringify(item.movement_ids) !== JSON.stringify([...item.movement_ids].sort())
        || JSON.stringify(item.document_ids) !== JSON.stringify([...item.document_ids].sort())) return null;
    return { kind: item.kind as "probable" | "conflicting", movementIds: item.movement_ids as [string, string], documentIds: item.document_ids as [string, string] };
  });
  if (collapsed.some((item) => item === null) || unresolved.some((item) => item === null)
      || new Set((collapsed as NonNullable<typeof collapsed[number]>[]).map((item) => item.canonicalMovementId)).size !== collapsed.length) return null;
  const hasCollapsed = collapsed.length > 0; const hasUnresolved = unresolved.length > 0;
  const expectedDeduplicationState = hasCollapsed && hasUnresolved
    ? "exact_duplicates_collapsed_with_unresolved_candidates"
    : hasCollapsed ? "exact_duplicates_collapsed"
      : hasUnresolved ? "unresolved_candidates_present" : "none";
  if (rawDeduplication.state !== expectedDeduplicationState) return null;

  if (!Array.isArray(raw.sources)) return null;
  const sources = raw.sources.map(source);
  if (sources.some((item) => item === null)) return null;
  const safeSources = sources as AccountLedgerSource[];
  const sourceIds = safeSources.map((item) => item.documentId);
  if (new Set(sourceIds).size !== sourceIds.length
      || safeSources.some((item) => item.accountId !== accountId)) return null;
  const statementSources = safeSources
    .filter((item) => item.relation !== "movement_evidence")
    .sort((left, right) => left.documentId.localeCompare(right.documentId));
  const exactOverlapGroups: { from: string; to: string; documentIds: [string, string] }[] = [];
  statementSources.forEach((left, index) => statementSources.slice(index + 1).forEach((right) => {
    if (!left.period || !right.period) return;
    const from = left.period.from > right.period.from ? left.period.from : right.period.from;
    const to = left.period.to < right.period.to ? left.period.to : right.period.to;
    if (from <= to) exactOverlapGroups.push({ from, to, documentIds: [left.documentId, right.documentId] });
  }));
  exactOverlapGroups.sort((left, right) => left.from.localeCompare(right.from)
    || left.to.localeCompare(right.to) || left.documentIds.join("\u0000").localeCompare(right.documentIds.join("\u0000")));
  if (JSON.stringify(overlapGroups) !== JSON.stringify(exactOverlapGroups)) return null;
  const overlapPairs = new Set(exactOverlapGroups.map((group) => group.documentIds.join("\u0000")));

  if (!Array.isArray(raw.groups)) return null;
  const seen = new Set<string>(); const seenMonths = new Set<string>(); let prior: [string, string] | null = null;
  const groups = raw.groups.map((group) => {
    if (!isRecord(group) || !exact(group, ["month", "label", "movements"]) || !Array.isArray(group.movements)) return null;
    const month = nonblank(group.month); const label = nonblank(group.label);
    if (!month || !/^\d{4}-(?:0[1-9]|1[0-2])$/.test(month) || !label
        || group.movements.length === 0 || seenMonths.has(month)) return null;
    const movements = group.movements.map(ledgerMovement);
    if (movements.some((item) => item === null)) return null;
    for (const movement of movements) {
      if (!movement || movement.accountId !== accountId || movement.currency !== currency
          || movement.date.slice(0, 7) !== month || seen.has(movement.id)) return null;
      const key: [string, string] = [movement.date, movement.id];
      if (prior && (key[0] > prior[0] || (key[0] === prior[0] && key[1] > prior[1]))) return null;
      prior = key; seen.add(movement.id);
    }
    seenMonths.add(month);
    return { month, label, movements: movements as NonNullable<typeof movements[number]>[] };
  });
  if (groups.some((item) => item === null)) return null;

  const evidenceIds = new Set((groups as NonNullable<typeof groups[number]>[])
    .flatMap((group) => group.movements)
    .flatMap((movement) => movement.evidenceLinks)
    .map((link) => link.targetDocumentId));
  const allStatementIds = new Set(statementIds);
  const expectedSourceIds = new Set([...allStatementIds, ...evidenceIds]);
  if (expectedSourceIds.size !== sourceIds.length
      || sourceIds.some((id) => !expectedSourceIds.has(id))) return null;
  for (const item of safeSources) {
    const expectedRelation = allStatementIds.has(item.documentId)
      ? evidenceIds.has(item.documentId) ? "statement_and_movement_evidence" : "statement"
      : "movement_evidence";
    if (item.relation !== expectedRelation) return null;
    if (allStatementIds.has(item.documentId)) {
      if (!item.period) return null;
      const namedRuns = safeRuns.filter((run) => run.statementIds.includes(item.documentId));
      if (namedRuns.length !== 1 || namedRuns.some((run) =>
        item.period!.from < run.from || item.period!.to > run.to)) return null;
      const namedOverlaps = (overlapGroups as NonNullable<typeof overlapGroups[number]>[])
        .filter((group) => group.documentIds.includes(item.documentId));
      if (namedOverlaps.some((group) =>
        item.period!.from > group.from || item.period!.to < group.to)) return null;
    }
  }
  const safeCollapsed = collapsed as NonNullable<typeof collapsed[number]>[];
  const safeUnresolved = unresolved as NonNullable<typeof unresolved[number]>[];
  if ([...safeCollapsed, ...safeUnresolved].some((item) =>
    item.documentIds.some((id) => !allStatementIds.has(id)))) return null;
  const collapsedMembers = safeCollapsed.flatMap((item) => item.memberMovementIds);
  if (new Set(collapsedMembers).size !== collapsedMembers.length
      || safeCollapsed.some((item) => item.documentIds.some((documentId) =>
        !item.documentIds.some((otherId) => otherId !== documentId
          && overlapPairs.has([documentId, otherId].sort().join("\u0000")))))
      || safeUnresolved.some((item) => !overlapPairs.has([...item.documentIds].sort().join("\u0000")))) return null;
  const visibleMovements = new Map((groups as NonNullable<typeof groups[number]>[])
    .flatMap((group) => group.movements).map((movement) => [movement.id, movement]));
  for (const movement of visibleMovements.values()) {
    const declaration = safeCollapsed.find((item) => item.canonicalMovementId === movement.id);
    if (movement.deduplication.state === "exact_duplicate") {
      const evidenceDocuments = [...new Set(movement.evidenceLinks.map((link) => link.targetDocumentId))].sort();
      if (!declaration || JSON.stringify(declaration.memberMovementIds) !== JSON.stringify(movement.deduplication.memberMovementIds)
          || JSON.stringify(declaration.documentIds) !== JSON.stringify(evidenceDocuments)) return null;
    } else if (declaration || collapsedMembers.includes(movement.id)) return null;
  }

  if (!isRecord(raw.page) || !exact(raw.page, ["limit", "returned", "remaining", "next_cursor"])) return null;
  const limit = optionalNonNegativeInteger(raw.page.limit); const returned = optionalNonNegativeInteger(raw.page.returned); const remaining = optionalNonNegativeInteger(raw.page.remaining);
  const nextCursor = raw.page.next_cursor === null
    ? null : nonblank(raw.page.next_cursor) ?? undefined;
  if (limit === undefined || limit < 1 || limit > MAX_LIMIT || returned === undefined || remaining === undefined || nextCursor === undefined
      || returned !== seen.size || returned > limit || (remaining > 0) !== Boolean(nextCursor)
      || (remaining > 0 && returned !== limit)
      || (returned === 0 && (remaining !== 0 || nextCursor !== null))) return null;
  if (parsedBalance.state === "absent" && balanceState !== "not_established") return null;

  return {
    scope: { kind: "account", accountId }, revision,
    account: { id: accountId, name, maskedNumber, type: accountType, currency,
      balance: parsedBalance },
    coverage: { state: coverageState, runs: safeRuns, gaps: safeGaps },
    reconciliation: { balance: balanceState,
      overlap: { state: overlap.state as "none_observed" | "overlap_present",
        deduplication: { state: rawDeduplication.state, policy: rawDeduplication.policy,
          collapsed: safeCollapsed, unresolved: safeUnresolved } as AccountLedgerDeduplication,
        groups: overlapGroups as NonNullable<typeof overlapGroups[number]>[] },
      runningBalance: { state: "absent", reason: "not_authoritatively_available" } },
    sources: safeSources, groups: groups as NonNullable<typeof groups[number]>[],
    page: { limit, returned, remaining, nextCursor },
  };
}
