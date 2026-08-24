import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ActivityActionResult, ActivityCorrectionState, ActivityData, FeatureResult, MovementView } from "../../surface/types";
import { Activity } from "./Activity";
import type { ActivityCorrectionControls } from "./Activity";
import moments from "../../../../product/viva/persona/pack-v31/moments.json";

const vocabularies: ActivityData["vocabularies"] = { categories: { items: [{ id: "food", label: "Food" }, { id: "housing", label: "Housing" }], complete: true, limit: 20 }, tags: { items: [{ id: "trip", label: "Trip" }, { id: "tax", label: "Tax" }], complete: true, limit: 20, maxSelected: 8, maxLabelLength: 40 } };
const movement = (over: Partial<MovementView> = {}): MovementView => ({ id: "m1", date: "2026-07-01", description: "a shop", account: "acct:one", direction: "out", exactValue: "10.00", currency: "USD", display: "USD 10.00", nature: "spending", sentence: "", decidedBy: "default", provisional: false, linked: false, category: { id: "food", label: "Food", valid: true }, tags: [{ id: "trip", label: "Trip" }], tagsValid: true, transfer: { state: "none" }, actions: [], ...over });
const counterpart = { id: "counterpart-one", date: "2026-07-02", description: "other account movement", account: "acct:two", direction: "in" as const, exactValue: "10.00", currency: "USD", display: "USD 10.00" };
const read = (movements: MovementView[]): ActivityData => ({ sentence: movements.length ? moments.activity_scope : moments.activity_empty, movements, beyond: { count: 0 }, vocabularies });
const ready = (value: ActivityData): FeatureResult<ActivityData> => ({ state: "ready", data: value });
const noAction = () => {};
const completed: ActivityActionResult = { state: "settled", outcome: { kind: "completed", message: "The correction was recorded.", reason: "" } };
function controls(state: ActivityCorrectionState, onAssignCategory = vi.fn(), onReplaceTags = vi.fn(), onConfirmTransfer = vi.fn(), onRejectTransfer = vi.fn(), onUnlinkTransfer = vi.fn()): ActivityCorrectionControls { return { state, onAssignCategory, onReplaceTags, onConfirmTransfer, onRejectTransfer, onUnlinkTransfer }; }

describe("Activity surface", () => {
  it("renders every FeatureResult state, and an empty read in the read's own words", () => {
    const props = { onOpenEvidence: noAction };
    const { getByText, queryByText, rerender } = render(<Activity {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Activity unavailable")).not.toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "unavailable", reason: "not_connected" }} />);
    expect(getByText("Activity is not connected to this vault read.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("Activity could not be read. The vault is still open.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "partial", data: read([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some activity details are unavailable. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "needs_input", data: read([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some activity details need more information. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={ready(read([]))} />);
    // The read composes its own sentence about knowing of nothing that moved,
    // and it is not the same as nothing having moved.
    expect(getByText(moments.activity_empty, { selector: "span" })).toBeInTheDocument();
  });

  it("has one way to draw a movement, and no second path for a sample vault", () => {
    // This screen used to carry a search box, seven facet filters and a
    // relationship graph over rows composed in the shell for the sample
    // vault. The sample is a vault now and arrives through this read, so
    // there is one implementation and this is what says so.
    const { getByText, queryByRole } = render(<Activity result={ready(read([movement()]))} onOpenEvidence={noAction} />);
    expect(getByText("What moved")).toBeInTheDocument();
    expect(getByText("a shop")).toBeInTheDocument();
    expect(queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says which way the money went in the read's own word, and shows no sign", () => {
    const { getByText, queryByText } = render(<Activity result={ready(read([movement({ direction: "out", display: "USD 120.00" })]))} onOpenEvidence={noAction} />);
    expect(getByText("out")).toBeInTheDocument();
    expect(getByText("USD 120.00")).toBeInTheDocument();
    expect(queryByText("-USD 120.00")).not.toBeInTheDocument();
  });

  it("shows the read's own line for a row that is not plain spending", () => {
    const { getByText } = render(<Activity result={ready(read([movement({ sentence: moments.activity_transfer })]))} onOpenEvidence={noAction} />);
    expect(getByText(moments.activity_transfer)).toBeInTheDocument();
  });

  it("says how many movements are in the vault and not in this list", () => {
    const { getByText } = render(<Activity result={ready({ sentence: moments.activity_scope, movements: [movement()], beyond: { count: 6 }, vocabularies })} onOpenEvidence={noAction} />);
    expect(getByText("6 more are in this vault and not in this list.")).toBeInTheDocument();
  });

  it("names a movement the vault recorded nothing for, rather than leaving the row blank", () => {
    const { getByText } = render(<Activity result={ready(read([movement({ description: "" })]))} onOpenEvidence={noAction} />);
    expect(getByText("No description was recorded for this movement.")).toBeInTheDocument();
  });

  it("shows current backend category and complete tags, with controls only from each row's declared availability", async () => {
    const user = userEvent.setup();
    render(<Activity result={ready(read([
      movement({ id: "one", description: "Corner shop", actions: ["assign_category"] }),
      movement({ id: "two", description: "Train fare", category: { id: "housing", label: "Housing", valid: true }, tags: [], actions: ["replace_tags"] }),
      movement({ id: "three", description: "Inherited", actions: [] }),
    ]))} correction={controls({ state: "idle" })} onOpenEvidence={noAction} />);

    expect(screen.getAllByText("Food").length).toBeGreaterThan(0);
    expect(screen.getByText("No tags recorded")).toBeInTheDocument();
    const categorySummary = screen.getByText("Correct category");
    const tagSummary = screen.getByText("Correct tags");
    expect(categorySummary).toHaveAccessibleName("Correct category for 2026-07-01, Corner shop, acct:one, USD 10.00, one");
    expect(tagSummary).toHaveAccessibleName("Correct tags for 2026-07-01, Train fare, acct:one, USD 10.00, two");
    await user.click(categorySummary);
    expect(within(categorySummary.parentElement!).getByRole("combobox", { name: "Category for 2026-07-01, Corner shop, acct:one, USD 10.00, one" })).toBeInTheDocument();
    expect(within(categorySummary.parentElement!).getByRole("button", { name: "Save category for 2026-07-01, Corner shop, acct:one, USD 10.00, one" })).toBeInTheDocument();
    expect(within(categorySummary.parentElement!).queryByRole("group", { name: /Tags for/ })).not.toBeInTheDocument();
    await user.click(tagSummary);
    expect(within(tagSummary.parentElement!).getByRole("group", { name: "Tags for 2026-07-01, Train fare, acct:one, USD 10.00, two" })).toBeInTheDocument();
    expect(within(tagSummary.parentElement!).getByRole("checkbox", { name: "Trip tag for 2026-07-01, Train fare, acct:one, USD 10.00, two" })).toBeInTheDocument();
    expect(within(tagSummary.parentElement!).getByRole("button", { name: "Save complete tag set for 2026-07-01, Train fare, acct:one, USD 10.00, two" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/nature|merchant-wide|new label/i)).not.toBeInTheDocument();
  });

  it("submits one existing category and a complete desired tag set, including empty", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    const replace = vi.fn();
    render(<Activity result={ready(read([movement({ actions: ["assign_category", "replace_tags"] })]))} correction={controls({ state: "idle" }, assign, replace)} onOpenEvidence={noAction} />);
    await user.click(screen.getByText(/Correct category or tags/));
    await user.selectOptions(screen.getByRole("combobox", { name: /Category for/ }), "housing");
    await user.click(screen.getByRole("button", { name: /Save category for/ }));
    expect(assign).toHaveBeenCalledWith("m1", "housing");
    await user.click(screen.getByRole("checkbox", { name: /Trip tag for/ }));
    await user.click(screen.getByRole("checkbox", { name: /Tax tag for/ }));
    await user.click(screen.getByRole("button", { name: /Save complete tag set for/ }));
    expect(replace).toHaveBeenCalledWith("m1", ["tax"]);
    await user.click(screen.getByRole("checkbox", { name: /Tax tag for/ }));
    await user.click(screen.getByRole("button", { name: /Save complete tag set for/ }));
    expect(replace).toHaveBeenLastCalledWith("m1", []);
  });

  it("keeps busy controls focusable with aria-disabled and guards pointer and keyboard submissions", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    const replace = vi.fn();
    render(<Activity result={ready(read([movement({ actions: ["assign_category", "replace_tags"] })]))} correction={controls({ state: "working", movementId: "m1", verb: "category" }, assign, replace)} onOpenEvidence={noAction} />);
    await user.click(screen.getByText(/Correct category or tags/));
    const category = screen.getByRole("combobox", { name: /Category for/ });
    const save = screen.getByRole("button", { name: /Save category for/ });
    expect(category).toHaveAttribute("aria-disabled", "true");
    expect(save).toHaveAttribute("aria-disabled", "true");
    expect(category).not.toBeDisabled();
    expect(save).not.toBeDisabled();
    save.focus();
    expect(save).toHaveFocus();
    await user.click(save);
    await user.keyboard("{Enter}{Space}");
    await user.click(screen.getByRole("button", { name: /Save complete tag set for/ }));
    expect(assign).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByText(/Pressing again does nothing/)).toBeInTheDocument();
  });

  it("renders a complete reviewed transfer suggestion verbatim and submits distinct confirm and reject verbs", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn();
    const reject = vi.fn();
    const exactExplanation = "The reviewed suggestion remains available for this movement.";
    const exactRelationship = "The reviewed candidate is the other side named by the vault.";
    render(<Activity result={ready(read([movement({
      transfer: { state: "suggested", explanation: exactExplanation, candidates: [{ ...counterpart, relationship: exactRelationship }], complete: true, limit: 20 },
      actions: ["confirm_transfer", "reject_transfer"],
    })]))} correction={controls({ state: "idle" }, vi.fn(), vi.fn(), confirm, reject)} onOpenEvidence={noAction} />);
    await user.click(screen.getByText("Review transfer suggestion"));
    expect(screen.getByText(exactExplanation)).toBeInTheDocument();
    expect(screen.getByText(exactRelationship)).toBeInTheDocument();
    expect(screen.getByText("other account movement")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Confirm transfer for .*m1; counterpart .*counterpart-one$/ }));
    await user.click(screen.getByRole("button", { name: /Reject transfer suggestion for .*m1$/ }));
    expect(confirm).toHaveBeenCalledWith("m1", "counterpart-one");
    expect(reject).toHaveBeenCalledWith("m1");
  });

  it("shows incomplete reviewed suggestion context read-only and never infers controls from equal display values", async () => {
    const user = userEvent.setup();
    render(<Activity result={ready(read([
      movement({ id: "source", transfer: { state: "suggested", explanation: "More candidates may exist.", candidates: [{ ...counterpart, relationship: "A reviewed possibility." }], complete: false, limit: 20 }, actions: [] }),
      movement({ id: "equal-value", description: "same displayed value", display: counterpart.display, transfer: { state: "none" }, actions: [] }),
    ]))} correction={controls({ state: "idle" })} onOpenEvidence={noAction} />);
    await user.click(screen.getByText("Review transfer suggestion"));
    expect(screen.getByText("More candidates may exist.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm transfer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reject transfer suggestion/ })).not.toBeInTheDocument();
    expect(screen.getByText("same displayed value").closest("li")?.querySelector(".activity-correction")).toBeNull();
  });

  it("renders a reviewed linked relationship and unlinks only its exact counterpart identity", async () => {
    const user = userEvent.setup();
    const unlink = vi.fn();
    render(<Activity result={ready(read([movement({
      linked: false,
      transfer: { state: "linked", explanation: "The vault reviewed this existing link.", counterpart, relationship: "This is the exact reviewed relationship." },
      actions: ["unlink_transfer"],
    })]))} correction={controls({ state: "idle" }, vi.fn(), vi.fn(), vi.fn(), vi.fn(), unlink)} onOpenEvidence={noAction} />);
    await user.click(screen.getByText("Review transfer link"));
    expect(screen.getByText("The vault reviewed this existing link.")).toBeInTheDocument();
    expect(screen.getByText("This is the exact reviewed relationship.")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /Unlink transfer for .*m1; counterpart .*counterpart-one$/ });
    await user.click(button);
    expect(unlink).toHaveBeenCalledWith("m1", "counterpart-one");
  });

  it("keeps transfer verbs focusable but inert while any correction and reread are busy", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn();
    const reject = vi.fn();
    render(<Activity result={ready(read([movement({ transfer: { state: "suggested", explanation: "Reviewed.", candidates: [{ ...counterpart, relationship: "Reviewed relationship." }], complete: true, limit: 20 }, actions: ["confirm_transfer", "reject_transfer"] })]))} correction={controls({ state: "refreshing", movementId: "m1", verb: "category", result: completed }, vi.fn(), vi.fn(), confirm, reject)} onOpenEvidence={noAction} />);
    await user.click(screen.getByText("Review transfer suggestion"));
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toBeDisabled();
      button.focus();
      expect(button).toHaveFocus();
      await user.click(button);
      await user.keyboard("{Enter}{Space}");
    }
    expect(confirm).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
    expect(screen.getByText(/Pressing again does nothing/)).toBeInTheDocument();
  });

  it.each([
    ["refused", { state: "settled", movementId: "m1", verb: "category", result: { state: "settled", outcome: { kind: "refused", message: "That category was refused.", reason: "unknown" } }, refresh: "refreshed" } as ActivityCorrectionState, "Correction refused"],
    ["stale", { state: "settled", movementId: "m1", verb: "tags", result: { state: "settled", outcome: { kind: "stale", message: "That movement moved away.", reason: "missing" } }, refresh: "refreshed" } as ActivityCorrectionState, "Correction out of date"],
    ["reread failed", { state: "settled", movementId: "m1", verb: "category", result: completed, refresh: "failed" } as ActivityCorrectionState, "Correction recorded"],
  ])("shows and focuses the distinct %s outcome", (_name, state, title) => {
    render(<Activity result={ready(read([movement()]))} correction={controls(state)} onOpenEvidence={noAction} />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveFocus();
    if (state.state === "settled" && state.refresh === "failed") expect(screen.getByText(/old picture is still on screen and is stale/i)).toBeInTheDocument();
  });

  it.each([
    ["confirm_transfer", "completed", "Transfer confirmed"],
    ["confirm_transfer", "refused", "Transfer confirmation refused"],
    ["reject_transfer", "completed", "Transfer suggestion rejected"],
    ["reject_transfer", "stale", "Transfer suggestion changed"],
    ["unlink_transfer", "completed", "Transfer unlinked"],
    ["unlink_transfer", "stale", "Transfer link changed"],
  ] as const)("keeps the %s %s outcome distinct", (verb, kind, title) => {
    const reason = kind === "completed" ? "" : "changed";
    render(<Activity result={ready(read([movement()]))} correction={controls({ state: "settled", movementId: "m1", verb, result: { state: "settled", outcome: { kind, message: "Backend-reviewed outcome.", reason } }, refresh: "refreshed" })} onOpenEvidence={noAction} />);
    expect(screen.getByText(title)).toBeInTheDocument();
  });

  it("focuses the refreshed financial row after a completed correction", () => {
    render(<Activity result={ready(read([movement()]))} correction={controls({ state: "settled", movementId: "m1", verb: "category", result: completed, refresh: "refreshed" })} onOpenEvidence={noAction} />);
    expect(screen.getByText("a shop").closest("li")).toHaveFocus();
  });

  it("uniquely names every repeated correction control when backend descriptions and figures match", async () => {
    const user = userEvent.setup();
    render(<Activity result={ready(read([
      movement({ id: "movement-one", description: "Same shop", actions: ["assign_category", "replace_tags"] }),
      movement({ id: "movement-two", description: "Same shop", actions: ["assign_category", "replace_tags"] }),
    ]))} correction={controls({ state: "idle" })} onOpenEvidence={noAction} />);
    const summaries = screen.getAllByText("Correct category or tags");
    expect(summaries).toHaveLength(2);
    expect(summaries[0]).toHaveAccessibleName("Correct category or tags for 2026-07-01, Same shop, acct:one, USD 10.00, movement-one");
    expect(summaries[1]).toHaveAccessibleName("Correct category or tags for 2026-07-01, Same shop, acct:one, USD 10.00, movement-two");
    await user.click(summaries[0]);
    await user.click(summaries[1]);
    for (const role of ["combobox", "group", "checkbox", "button"] as const) {
      const names = screen.getAllByRole(role).filter((control) => control.closest(".activity-correction") && control.hasAttribute("aria-label")).map((control) => control.getAttribute("aria-label"));
      expect(new Set(names).size).toBe(names.length);
      expect(names.every((name) => name?.includes("movement-one") || name?.includes("movement-two"))).toBe(true);
    }
  });

  it("uniquely names repeated transfer sources and candidates with backend identities last", async () => {
    const user = userEvent.setup();
    const transfer = (candidateId: string) => ({ state: "suggested" as const, explanation: "Reviewed suggestion.", candidates: [{ ...counterpart, id: candidateId, relationship: "Reviewed relationship." }], complete: true, limit: 20 });
    render(<Activity result={ready(read([
      movement({ id: "movement-one", description: "Same shop", transfer: transfer("candidate-one"), actions: ["confirm_transfer", "reject_transfer"] }),
      movement({ id: "movement-two", description: "Same shop", transfer: transfer("candidate-two"), actions: ["confirm_transfer", "reject_transfer"] }),
    ]))} correction={controls({ state: "idle" })} onOpenEvidence={noAction} />);
    const summaries = screen.getAllByText("Review transfer suggestion");
    expect(summaries[0]).toHaveAccessibleName(/movement-one$/);
    expect(summaries[1]).toHaveAccessibleName(/movement-two$/);
    await user.click(summaries[0]);
    await user.click(summaries[1]);
    const names = screen.getAllByRole("button").map((button) => button.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(names.length);
    expect(names.some((name) => name?.endsWith("candidate-one"))).toBe(true);
    expect(names.some((name) => name?.endsWith("candidate-two"))).toBe(true);
    expect(names.some((name) => name?.endsWith("movement-one"))).toBe(true);
    expect(names.some((name) => name?.endsWith("movement-two"))).toBe(true);
  });

  it("does not turn malformed current classification into an absence claim or a control", () => {
    render(<Activity result={ready(read([movement({ category: { id: null, label: "", valid: false }, tags: [], tagsValid: false, actions: [] })]))} correction={controls({ state: "idle" })} onOpenEvidence={noAction} />);
    expect(screen.getByText("Category unavailable from this read")).toBeInTheDocument();
    expect(screen.getByText("Tags unavailable from this read")).toBeInTheDocument();
    expect(screen.queryByText(/Correct category or tags/)).not.toBeInTheDocument();
  });
});
