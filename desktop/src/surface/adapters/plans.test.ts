import { describe, expect, it } from "vitest";
import parity from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
import { adaptPlanDraftReply, adaptPlans } from "./plans";

describe("the plans contract adapter", () => {
  it("carries the sample vault goal, evidence and actions from real provider bytes", () => {
    const raw = parity.reads.plans.result.data as Record<string, unknown>;
    const adapted = adaptPlans(raw)!;
    const goal = adapted.goals[0];
    expect(goal.title).toBe((raw.goals as Array<{ title: string }>)[0].title);
    expect(goal.accounts).toHaveLength(8);
    expect(goal.accounts.some((account) => account.evidenceLinks.length > 0)).toBe(true);
    expect(goal.actions).toEqual(["change_terms", "pause", "reserve", "release"]);
  });

  it("bounds an incomplete draft as needs-input and keeps its reviewed message", () => {
    const raw = { kind: "waiting", message: "One more contribution detail is required.", reason: "contribution_day_required", state: { draft: {}, draft_state: "needs_input" } };
    expect(adaptPlanDraftReply(raw)).toEqual({
      state: "settled",
      kind: "needs_input",
      message: raw.message,
      reason: "contribution_day_required",
      draft: null,
    });
  });

  it("fails closed on a malformed plans reply", () => {
    expect(adaptPlans({ state: "ready", invitation: null })).toBeNull();
    expect(adaptPlanDraftReply({ kind: "completed" })).toEqual({ state: "unreadable" });
  });
});
