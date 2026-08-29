import { within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, waitFor, userEvent, moments, openSample, installResponsiveMatchMedia } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("live Plans handoffs", () => {
  it("keeps an action receipt after the post-action snapshot replaces the card", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    try {
      await user.click(await view.findByRole("button", { name: "Make a plan" }));
      await user.click(view.getByText("Plan actions"));
      const reserve = view.getByRole("form", { name: /Reserve locally for/ });
      await user.type(within(reserve).getByLabelText("Amount"), "25");
      await user.click(within(reserve).getByRole("button", { name: "Review reservation" }));

      await waitFor(() => expect(view.getByText("Done.")).toBeInTheDocument());
      await waitFor(() => expect(document.getElementById("plan-action-outcome")).toHaveFocus());
    } finally {
      view.restore();
    }
  });

  it("clears a reviewed conversational draft before another vault is shown", async () => {
    const user = userEvent.setup();
    const drafted = {
      state: "ready", turns: [{
        id: "goal-turn", kind: "ask", occurred_at: "2026-08-29",
        prompt: "Make a trip plan", said: "", question_id: "",
        outcome: "completed", message: "", reason: "", proposal: null,
        answer: {
          state: "ready", question: "Make a trip plan",
          text: moments.plans_draft_ready,
          answered: true, refusal: "", grade: "", grade_sentence: "",
          figures: [], spoken: { may_speak: true, withheld: "", parts: [], text: "", grade_sentence: "", citation_sentence: "", local_only: "" },
          goal_draft: { kind: "ready", message: moments.plans_draft_ready, reason: "", verb: "create", review_in_plans: true, draft: { verb: "create", payload: { title: "Trip", currency: "USD", target_amount: "600" }, calculated: { reserved: "0", remaining: "600", required_monthly: "100", projected_completion_date: "2027-02-28", status: "on_track" } } },
        },
      }], questions: [], total: 0, tail: { count: 0, amount: "" }, pending: { count: 0 }, invite: "", answered_by_document: "",
    };
    const view = await openSample({ conversation: drafted });
    try {
      await user.click(view.getByRole("button", { name: "Ask Viva" }));
      await user.click(view.getByRole("button", { name: "Review in Plans" }));
      expect(view.getByText("Draft review")).toBeInTheDocument();
      expect(view.getAllByLabelText("Plan name")[0]).toHaveValue("Trip");

      await user.click(view.getAllByRole("button", { name: moments.sample_frame_leave })[0]);
      await user.click(view.getAllByRole("button", { name: "Open the sample vault" })[0]);
      await waitFor(() => expect(view.getByText(moments.sample_frame)).toBeInTheDocument());
      await user.click(await view.findByRole("button", { name: "Make a plan" }));

      expect(view.queryByText("Draft review")).not.toBeInTheDocument();
      expect(view.getAllByLabelText("Plan name")[0]).toHaveValue("");
    } finally {
      view.restore();
    }
  });
});
