import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NumericalFigureDetails, NumericalReceipt } from "./NumericalReceipt";
import type { NumericalReceipt as Receipt } from "../surface/types";
const receipt: Receipt = { id: "receipt-local", figureIds: ["f1"], sourceRecords: [{ recordId: "local-example", kind: "local_activity", documentId: null }], premises: [{ parameter: "starting_amount", role: "opening", raw: "10.005", modeled: "10.00", unit: "money", currency: "USD", source: "current_question", quote: "<b>10.005</b>", derivation: "decimal_numeric" }], observedInputs: [{ account_id: "Assets:Example", value: "100", modeled_value: "100.00", quantity: "balance", kind: "financial", currency: "USD", dated: "2026-01-31", grade: "unverified", measurement_view: "recorded_cash", record_ids: ["captured-example"], carry_forward_hypothetical: true }], localInputs: [{ eventId: "local-example", eventType: "GoalCreated", fields: [{ label: "Target amount", value: "500" }] }], context: [{ label: "Rounding", value: "Half-even cents" }], caveats: ["A local reservation is not a bank transfer."] };
describe("visible numerical receipt", () => {
  it("shows exact values, source kinds, literal current-user clauses, measured start, local terms and limits", () => {
    const view = render(<NumericalReceipt receipt={receipt} />);
    expect(view.container.querySelector('[data-receipt-section="source"] [data-field="kind"]')).toHaveTextContent("Local activity");
    expect(view.container.querySelector('[data-receipt-section="source"] [data-field="document_id"]')).toHaveTextContent("Not supplied");
    expect(view.container.querySelector('[data-field="quote"]')).toHaveTextContent("<b>10.005</b>"); expect(view.container.querySelector("b")).toBeNull();
    expect(view.container.querySelector('[data-field="modeled"]')).toHaveTextContent("10.00");
    expect(view.container.querySelector('[data-receipt-section="observed-input"] [data-field="dated"]')).toHaveTextContent("2026-01-31");
    expect(view.getByText("Target amount")).toBeVisible(); expect(view.getByText("500")).toBeVisible();
    expect(view.getByText("Half-even cents")).toBeVisible(); expect(view.getByText("A local reservation is not a bank transfer.")).toBeVisible();
    expect(view.queryByRole("link")).toBeNull(); expect(view.queryByRole("button")).toBeNull();
  });
  it("keeps hypothetical kind and empty bank grade distinct from a recorded measurement, and shows the typed subject/boundary", () => {
    const view = render(<NumericalFigureDetails figure={{ value: "400.00", quantity: "balance", kind: "hypothetical", currency: "USD", dated: "2026-03-31", grade: "", subject: { goal_id: "goal-example" }, boundary: { whole: false, selected: [{ kind: "account", value: "Assets:Example" }], cut: [{ kind: "period", value: "2026-01-01", to: "2026-03-31" }] } }} />);
    expect(view.getByText("No bank evidence grade")).toBeVisible(); expect(view.getByText("Hypothetical")).toBeVisible();
    expect(view.container.querySelector('[data-field="whole"]')).toHaveTextContent("No");
    expect(view.container.querySelector('[data-field="goal_id"]')).toHaveTextContent("goal-example");
    expect(view.container.querySelector('[data-receipt-section="cut"] [data-field="to"]')).toHaveTextContent("2026-03-31");
  });
});
