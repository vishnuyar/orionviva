import { cleanup, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import contract from "../../../../product/viva/surface/fixtures/surface-v1.json";
import moments from "../../../../product/viva/persona/pack-v40/moments.json";
import { adaptPlanActionOutcome, adaptPlanDraftReply, adaptPlans } from "../../surface/adapters/plans";
import type { ActionResult, GoalPlanView, PlanDraftResult, PlansData } from "../../surface/types";
import { Plans } from "./Plans";

const goal: GoalPlanView = {
  id: "goal-one", title: "Journey", group: "active", state: "active", status: "on_track", statusLabel: "On track",
  headline: "The recorded target and reserved amount remain separate.", explanation: "The account evidence stands beneath availability.",
  currency: "USD", targetAmount: "600", targetDisplay: "USD 600.00", targetDate: "2027-02-28",
  reserved: "100", reservedDisplay: "USD 100.00", remaining: "500", remainingDisplay: "USD 500.00",
  monthlyContribution: "100", monthlyDisplay: "USD 100.00", contributionDay: 1, requiredMonthly: "100",
  requiredMonthlyDisplay: "USD 100.00", projectedCompletionDate: "2027-02-28", deviation: "0", deviationDisplay: "USD 0.00",
  nextContributionDate: "2026-09-01", noMoneyMoved: "This is a local reservation; the bank balance is unchanged.",
  accounts: [{ id: "checking", name: "Checking", currency: "USD", eligible: true, balance: "1000", balanceDisplay: "USD 1,000.00", reserved: "100", reservedDisplay: "USD 100.00", available: "900", availableDisplay: "USD 900.00", grade: "verified", gradeDescription: "The issuer statement verifies this balance.", dated: "2026-08-29", asOf: "", balanceExplanation: "Statement closing balance.", sourceDocumentId: "statement", sourcePage: "1", sourceRegion: "closing", sourceNote: "", caveats: [], sentence: "USD 900.00 is available after local reservations.", reason: "", evidenceLinks: [{ targetDocumentId: "statement", label: "statement.pdf", relation: "attests", page: "1" }] }],
  history: [{ kind: "reserved", accountId: "checking", amount: "100", amountDisplay: "USD 100.00", reason: "", occurredAt: "2026-08-29", sentence: "USD 100.00 was reserved locally.", valid: true }], historyNote: "",
  assumptions: [], caveats: [], actions: ["change_terms", "pause", "reserve", "release"],
};
const base: PlansData = { state: "ready", title: "Your plans", invitation: { title: "Make room for a goal", body: "Start with a calculation." }, noMoneyMoved: "", goals: [goal], groups: { active: [goal.id] }, proposals: [], actions: ["draft", "propose", "confirm", "decline"] };
const settled = (message: string): ActionResult => ({ state: "settled", outcome: { kind: "completed", message, reason: "" } });
const controls = {
  draft: vi.fn<() => Promise<PlanDraftResult>>(),
  propose: vi.fn<() => Promise<ActionResult>>(),
  confirm: vi.fn<() => Promise<ActionResult>>(),
  decline: vi.fn<() => Promise<ActionResult>>(),
};

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("the plans surface", () => {
  it("renders every generated contract state through the production adapter", () => {
    const fixtures = (contract.fixtures as Array<{ capability_id: string; state: string; payload: { surface: object; action: object | null } }>).filter((row) => row.capability_id === "plans.goals");
    expect(fixtures.map((row) => row.state)).toEqual(["absent", "ready", "needs_input", "partial", "refused", "open", "completed", "stale"]);
    for (const fixture of fixtures) {
      const data = adaptPlans(fixture.payload.surface)!;
      const result = data.state === "partial" ? { state: "partial" as const, data, issues: [{ code: "plans_partial", message: "Bounded detail." }] } : { state: "ready" as const, data };
      const draft = fixture.state === "needs_input" ? adaptPlanDraftReply(fixture.payload.action) : null;
      const outcome = fixture.payload.action ? adaptPlanActionOutcome(fixture.payload.action) : null;
      const receipt = outcome && fixture.state !== "needs_input" ? { state: "settled" as const, outcome } : null;
      const view = render(<Plans result={result} controls={controls} initialDraft={draft} receipt={receipt} onOpenEvidence={vi.fn()} />);
      expect(view.container.querySelector(".plans-surface"), fixture.state).not.toBeNull();
      if (fixture.state === "open") expect(view.getByText(data.proposals[0].summary)).toBeInTheDocument();
      if (fixture.state === "partial") {
        expect(view.getByText(moments.plans_history_withheld)).toBeInTheDocument();
        expect(view.queryByText(/release_exceeds_reserved|fixture_invalid_history/)).not.toBeInTheDocument();
      }
      if (fixture.payload.action) expect(view.getAllByText((fixture.payload.action as { message: string }).message).length).toBeGreaterThan(0);
      view.unmount();
    }
  });

  it("renders the reviewed absent, ready and partial read states", () => {
    for (const state of ["absent", "ready", "partial"] as const) {
      const data = { ...base, state, goals: state === "absent" ? [] : base.goals };
      const result = state === "partial" ? { state: "partial" as const, data, issues: [{ code: "bounded", message: "One history row was unavailable." }] } : { state: "ready" as const, data };
      const view = render(<Plans result={result} controls={null} onOpenEvidence={vi.fn()} />);
      expect(view.container.querySelector(".plans-surface"), state).not.toBeNull();
      view.unmount();
    }
  });

  it("calculates a pure draft, then holds exactly the returned payload", async () => {
    const user = userEvent.setup();
    controls.draft.mockResolvedValue({ state: "settled", kind: "ready", message: "Draft ready. Nothing was recorded.", reason: "", draft: { verb: "create", payload: { title: "Journey", currency: "USD", target_amount: "600" }, calculated: { reserved: "0", remaining: "600", required_monthly: "100", projected_completion_date: "2027-02-28", status: "on_track" } } });
    controls.propose.mockResolvedValue(settled("Held for confirmation."));
    const view = render(<Plans result={{ state: "ready", data: base }} controls={controls} onOpenEvidence={vi.fn()} />);
    expect(view.getByRole("form", { name: "Calculate a draft" })).toBeInTheDocument();
    await user.type(view.getAllByLabelText("Plan name")[0], "Journey");
    await user.type(view.getAllByLabelText("Target amount")[0], "600");
    await user.click(view.getByRole("button", { name: "Calculate draft" }));
    expect(await view.findByText("Draft ready. Nothing was recorded.")).toBeInTheDocument();
    expect(controls.propose).not.toHaveBeenCalled();
    await user.click(view.getByRole("button", { name: "Hold exact proposal" }));
    expect(controls.propose).toHaveBeenCalledWith({ verb: "create", title: "Journey", currency: "USD", target_amount: "600" });
  });

  it("explains why a plan action is waiting", async () => {
    const user = userEvent.setup();
    controls.propose.mockReturnValue(new Promise<ActionResult>(() => undefined));
    const view = render(<Plans result={{ state: "ready", data: base }} controls={controls} onOpenEvidence={vi.fn()} />);
    await user.click(view.getByText("Plan actions"));
    const reserve = view.getByRole("form", { name: /Reserve locally for/ });
    await user.type(reserve.querySelector("input")!, "25");
    const button = view.getByRole("button", { name: "Review reservation" });
    await user.click(button);
    expect(view.getByText("Waiting for the vault…")).toHaveAttribute("role", "status");
    expect(button).toHaveAttribute("aria-describedby", `plan-actions-waiting-${goal.id}`);
  });

  it("confirms only the exact open proposal identity", async () => {
    const user = userEvent.setup();
    controls.confirm.mockResolvedValue({ state: "settled", outcome: { kind: "stale", message: "The account basis changed.", reason: "proposal_basis_changed" } });
    const data: PlansData = { ...base, proposals: [{ id: "proposal-one", verb: "reserve", goalId: goal.id, summary: "Reserve USD 50.00 locally.", consequence: "Confirmation records this proposal.", noMoneyMoved: "The bank balance is unchanged.", exact: { goal_id: goal.id, account_id: "checking", amount: "50" }, display: { plan_name: "Journey", account_name: "Checking", amount: "USD 50.00" }, assumptions: [], actions: ["confirm", "decline"] }] };
    const view = render(<Plans result={{ state: "ready", data }} controls={controls} receipt={{ state: "settled", outcome: { kind: "stale", message: "The account basis changed.", reason: "proposal_basis_changed" } }} onOpenEvidence={vi.fn()} />);
    expect(view.getAllByText("Checking").length).toBeGreaterThan(0);
    expect(view.getByText("USD 50.00")).toBeInTheDocument();
    await user.click(view.getByRole("button", { name: "Confirm exact proposal" }));
    expect(controls.confirm).toHaveBeenCalledWith("proposal-one");
    expect(view.getByRole("status")).toHaveTextContent("The account basis changed.");
  });

  it("edits and calculates changed terms before it can hold a proposal", async () => {
    const user = userEvent.setup();
    controls.draft.mockResolvedValue({ state: "settled", kind: "ready", message: "Changed draft ready.", reason: "", draft: { verb: "change_terms", payload: { goal_id: goal.id, title: "Longer journey", currency: "USD", target_amount: "750" }, calculated: { required_monthly: "125", projected_completion_date: "2027-02-28" } } });
    controls.propose.mockResolvedValue(settled("Held."));
    const view = render(<Plans result={{ state: "ready", data: base }} controls={controls} onOpenEvidence={vi.fn()} />);
    await user.click(view.getByText("Plan actions"));
    const names = view.getAllByLabelText("Plan name");
    await user.clear(names[1]);
    await user.type(names[1], "Longer journey");
    const targets = view.getAllByLabelText("Target amount");
    await user.clear(targets[1]);
    await user.type(targets[1], "750");
    await user.click(view.getByRole("button", { name: "Calculate changed terms" }));
    expect(await view.findByText("Changed draft ready.")).toBeInTheDocument();
    expect(controls.propose).not.toHaveBeenCalled();
    await user.click(view.getByRole("button", { name: "Hold changed terms" }));
    expect(controls.propose).toHaveBeenCalledWith({ verb: "change_terms", goal_id: goal.id, title: "Longer journey", currency: "USD", target_amount: "750" });
  });

  it("shows account availability and opens the supplied citation", async () => {
    const user = userEvent.setup();
    const openEvidence = vi.fn();
    const view = render(<Plans result={{ state: "ready", data: base }} controls={null} onOpenEvidence={openEvidence} />);
    await user.click(view.getByText("Availability and evidence"));
    await user.click(view.getByRole("button", { name: "Open statement.pdf" }));
    expect(openEvidence).toHaveBeenCalledWith(goal.accounts[0].evidenceLinks[0]);
  });

  it("opens and replaces the same conversational draft without recalculating or proposing", () => {
    const initialDraft: PlanDraftResult = {
      state: "settled", kind: "ready",
      message: "Draft ready. Nothing was recorded.", reason: "",
      draft: {
        verb: "create",
        payload: { title: "Trip", currency: "USD", target_amount: "600" },
        calculated: { reserved: "0", remaining: "600", required_monthly: "100", projected_completion_date: "2027-02-28", status: "on_track" },
      },
    };

    const view = render(<Plans result={{ state: "ready", data: base }} controls={controls} initialDraft={initialDraft} onOpenEvidence={vi.fn()} />);

    expect(view.getAllByLabelText("Plan name")[0]).toHaveValue("Trip");
    expect(view.getAllByLabelText("Target amount")[0]).toHaveValue("600");
    expect(view.getByText("Draft review")).toBeInTheDocument();
    expect(controls.draft).not.toHaveBeenCalled();
    expect(controls.propose).not.toHaveBeenCalled();

    const nextDraft: PlanDraftResult = { ...initialDraft, draft: { ...initialDraft.draft!, payload: { ...initialDraft.draft!.payload, title: "Rainy day", target_amount: "900" } } };
    view.rerender(<Plans result={{ state: "ready", data: base }} controls={controls} initialDraft={nextDraft} onOpenEvidence={vi.fn()} />);
    expect(view.getAllByLabelText("Plan name")[0]).toHaveValue("Rainy day");
    expect(view.getAllByLabelText("Target amount")[0]).toHaveValue("900");
  });
});
