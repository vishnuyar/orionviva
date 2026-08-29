import type { EvidenceLink, FigureGrade, GoalAccountView, GoalHistoryView, GoalPlanView, GoalProposalView, PlanDraftResult, PlanDraftView, PlanPayload, PlanVerb, PlansData } from "../types";
import { isRecord, textValue } from "./primitives";
import { adaptActionOutcome } from "./questions";

const VERBS: readonly PlanVerb[] = ["create", "change_terms", "reserve", "release", "pause", "resume", "set_aside"];
const GRADES: readonly FigureGrade[] = ["verified", "corroborated", "unverified", "conflicted", "unavailable", "not_applicable"];
const STATUSES: readonly GoalPlanView["status"][] = ["complete", "paused", "ahead", "on_track", "at_risk", "unscheduled"];
const GROUPS: readonly GoalPlanView["group"][] = ["active", "paused", "complete", "set_aside"];
const STATES: readonly GoalPlanView["state"][] = ["active", "paused", "set_aside"];

function strings(raw: unknown): readonly string[] { return Array.isArray(raw) ? raw.map(textValue).filter(Boolean) : []; }
function payload(raw: unknown): PlanPayload {
  if (!isRecord(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => typeof value === "string" || typeof value === "number" || value === null)) as PlanPayload;
}
function links(raw: unknown): readonly EvidenceLink[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).map((row) => ({ targetDocumentId: textValue(row.document_id), label: textValue(row.label), relation: textValue(row.relation) as EvidenceLink["relation"], page: textValue(row.page) })).filter((row) => row.targetDocumentId);
}
function account(raw: unknown): GoalAccountView | null {
  if (!isRecord(raw) || !textValue(raw.id) || typeof raw.eligible !== "boolean") return null;
  const grade = GRADES.find((word) => word === raw.grade) ?? "";
  return { id: textValue(raw.id), name: textValue(raw.name), currency: textValue(raw.currency), eligible: raw.eligible, balance: textValue(raw.balance), balanceDisplay: textValue(raw.balance_display), reserved: textValue(raw.reserved), reservedDisplay: textValue(raw.reserved_display), available: textValue(raw.available), availableDisplay: textValue(raw.available_display), grade, gradeDescription: textValue(raw.grade_description), dated: textValue(raw.dated), asOf: textValue(raw.as_of), balanceExplanation: textValue(raw.balance_explanation), sourceDocumentId: textValue(raw.source_document_id), sourcePage: textValue(raw.source_page), sourceRegion: textValue(raw.source_region), sourceNote: textValue(raw.source_note), caveats: strings(raw.caveats), sentence: textValue(raw.sentence), reason: textValue(raw.reason), evidenceLinks: links(raw.citations) };
}
function history(raw: unknown): GoalHistoryView | null {
  if (!isRecord(raw) || (raw.kind !== "reserved" && raw.kind !== "released")) return null;
  return { kind: raw.kind, accountId: textValue(raw.account_id), amount: textValue(raw.amount), amountDisplay: textValue(raw.amount_display), reason: textValue(raw.reason), occurredAt: textValue(raw.occurred_at), sentence: textValue(raw.sentence), valid: raw.valid === true };
}
function goal(raw: unknown): GoalPlanView | null {
  if (!isRecord(raw)) return null;
  const group = GROUPS.find((word) => word === raw.group);
  const state = STATES.find((word) => word === raw.state);
  const status = STATUSES.find((word) => word === raw.status);
  if (!textValue(raw.id) || !textValue(raw.title) || !group || !state || !status) return null;
  const accounts = (Array.isArray(raw.accounts) ? raw.accounts : []).map(account).filter((row): row is GoalAccountView => row !== null);
  const rows = (Array.isArray(raw.history) ? raw.history : []).map(history).filter((row): row is GoalHistoryView => row !== null);
  const actions = (Array.isArray(raw.actions) ? raw.actions : []).map((word) => VERBS.find((candidate) => candidate === word)).filter((word): word is PlanVerb => Boolean(word));
  return { id: textValue(raw.id), title: textValue(raw.title), group, state, status, statusLabel: textValue(raw.status_label), headline: textValue(raw.headline), explanation: textValue(raw.explanation), currency: textValue(raw.currency), targetAmount: textValue(raw.target_amount), targetDisplay: textValue(raw.target_display), targetDate: textValue(raw.target_date), reserved: textValue(raw.reserved), reservedDisplay: textValue(raw.reserved_display), remaining: textValue(raw.remaining), remainingDisplay: textValue(raw.remaining_display), monthlyContribution: textValue(raw.monthly_contribution), monthlyDisplay: textValue(raw.monthly_display), contributionDay: typeof raw.contribution_day === "number" ? raw.contribution_day : null, requiredMonthly: textValue(raw.required_monthly), requiredMonthlyDisplay: textValue(raw.required_monthly_display), projectedCompletionDate: textValue(raw.projected_completion_date), deviation: textValue(raw.deviation), deviationDisplay: textValue(raw.deviation_display), nextContributionDate: textValue(raw.next_contribution_date), noMoneyMoved: textValue(raw.no_money_moved), accounts, history: rows, historyNote: textValue(raw.history_note), assumptions: strings(raw.assumptions), caveats: strings(raw.caveats), actions };
}
function proposal(raw: unknown): GoalProposalView | null {
  if (!isRecord(raw)) return null;
  const verb = VERBS.find((word) => word === raw.verb);
  if (!textValue(raw.id) || !verb) return null;
  const actions = Array.isArray(raw.actions) ? raw.actions.filter((word): word is "confirm" | "decline" => word === "confirm" || word === "decline") : [];
  const display = isRecord(raw.display) ? Object.fromEntries(Object.entries(raw.display).map(([key, value]) => [key, textValue(value)]).filter(([, value]) => value)) : {};
  return { id: textValue(raw.id), verb, goalId: textValue(raw.goal_id), summary: textValue(raw.summary), consequence: textValue(raw.consequence), noMoneyMoved: textValue(raw.no_money_moved), exact: payload(raw.exact), display, assumptions: strings(raw.assumptions), actions };
}

export function adaptPlans(raw: unknown): PlansData | null {
  if (!isRecord(raw) || !isRecord(raw.invitation) || !["absent", "ready", "partial"].includes(textValue(raw.state))) return null;
  const goals = (Array.isArray(raw.goals) ? raw.goals : []).map(goal).filter((row): row is GoalPlanView => row !== null);
  const proposals = (Array.isArray(raw.proposals) ? raw.proposals : []).map(proposal).filter((row): row is GoalProposalView => row !== null);
  const groups = isRecord(raw.groups) ? Object.fromEntries(Object.entries(raw.groups).map(([key, value]) => [key, strings(value)])) : {};
  return { state: raw.state as PlansData["state"], title: textValue(raw.title), invitation: { title: textValue(raw.invitation.title), body: textValue(raw.invitation.body) }, noMoneyMoved: textValue(raw.no_money_moved), goals, groups, proposals, actions: ["draft", "propose", "confirm", "decline"] };
}

export function adaptPlanDraftView(raw: unknown): PlanDraftView | null {
  if (!isRecord(raw)) return null;
  const verb = VERBS.find((word) => word === raw.verb);
  return verb && isRecord(raw.payload) && isRecord(raw.calculated) ? { verb, payload: payload(raw.payload), calculated: Object.fromEntries(Object.entries(raw.calculated).map(([key, value]) => [key, textValue(value)])) } : null;
}

export function adaptPlanDraftReply(raw: unknown): PlanDraftResult {
  if (!isRecord(raw) || !["completed", "waiting", "refused"].includes(textValue(raw.kind)) || !textValue(raw.message) || !isRecord(raw.state)) return { state: "unreadable" };
  const outcome = adaptActionOutcome(raw);
  if (!outcome) return { state: "unreadable" };
  const row = raw.state;
  const draftState = textValue(row.draft_state);
  if (!["ready", "needs_input", "refused"].includes(draftState)) return { state: "unreadable" };
  const draft = adaptPlanDraftView(row.draft);
  const kind = draftState === "ready" ? "ready" : draftState === "needs_input" ? "needs_input" : "refused";
  return { state: "settled", kind, message: outcome.message, reason: outcome.reason, draft };
}

export function adaptPlanActionOutcome(raw: unknown) {
  return adaptActionOutcome(raw);
}
