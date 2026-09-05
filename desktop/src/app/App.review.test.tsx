import { within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, userEvent, waitFor, installResponsiveMatchMedia, openSample, sampleReads } from "./App.testSupport";

beforeEach(() => { installResponsiveMatchMedia(1440); });
afterEach(() => { window.orionVivaBridge = undefined; });

describe("Review and Ask Viva separation", () => {
  it("keeps the Overview compact and Ask Viva free of backend questions", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    expect(view.queryByText("Questions in your conversation")).not.toBeInTheDocument();
    expect(view.getByRole("button", { name: /open review/i })).toBeInTheDocument();

    await user.click(view.getByRole("button", { name: "Ask Viva" }));
    expect(view.getByRole("dialog", { name: "Ask Viva" })).toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Ask about your money" })).toBeInTheDocument();
    expect(view.queryByRole("heading", { name: "Questions for you" })).not.toBeInTheDocument();
  });

  it("opens Review without calling the model and follows an exact transaction target", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    await user.click(view.getByRole("button", { name: /Review, 15 actionable items/i }));
    expect(view.getByRole("heading", { name: "Review", level: 1 })).toBeInTheDocument();
    expect(view.getByLabelText("15 actionable review items")).toBeInTheDocument();
    expect(view.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(view.getAllByRole("button", { name: /review transaction/i })[0]);
    await waitFor(() => expect(view.getByRole("dialog", { name: "possible transfer to savings" })).toBeInTheDocument());
    const drawer = view.getByRole("dialog", { name: "possible transfer to savings" });
    expect(drawer.closest(".app-shell")).toBeNull();
    expect(view.container.querySelector(".app-shell")).toHaveAttribute("inert");
    expect(view.container.querySelector(".app-shell")).toHaveAttribute("aria-hidden", "true");
    expect(view.container.querySelector(".sidebar")).toHaveAttribute("inert");
    expect(view.container.querySelector(".main-content")).toHaveAttribute("inert");
    expect(drawer.closest("[inert], [aria-hidden=\"true\"]")).toBeNull();
    expect(view.getByText("Everyday Checking", { selector: ".account-transaction-summary dd" })).toBeInTheDocument();
    await user.click(view.getByRole("button", { name: "Close transaction details" }));
    await user.click(view.getByRole("button", { name: "Back to Review" }));
    expect(view.getByRole("heading", { name: "Review", level: 1 })).toBeInTheDocument();
    await waitFor(() => expect(document.getElementById("review-item-question:merchant:possible transfer to savings")).toHaveFocus());
  });

  it("leaves no background control outside an inert ancestor while the transaction drawer owns a 320-wide app", async () => {
    const viewport = installResponsiveMatchMedia(1440);
    const user = userEvent.setup();
    const view = await openSample();
    viewport.resize(320);
    await user.click(view.getByRole("button", { name: "Open navigation" }));
    await user.click(view.getByRole("button", { name: /Review, 15 actionable items/i }));
    await user.click(view.getAllByRole("button", { name: /review transaction/i })[0]);
    const drawer = await view.findByRole("dialog", { name: "possible transfer to savings" });
    const backgroundControls = [...document.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')].filter((control) => !drawer.contains(control));
    expect(backgroundControls.length).toBeGreaterThan(0);
    backgroundControls.forEach((control) => expect(control.closest("[inert]")).not.toBeNull());
    within(drawer).getAllByRole("button").forEach((control) => expect(control.closest("[inert], [aria-hidden=\"true\"]")).toBeNull());
  });

  it("hands Review transaction focus through the question drawer and back to the canonical ledger row", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    await user.click(view.getByRole("button", { name: /Review, 15 actionable items/i }));
    await user.click(view.getAllByRole("button", { name: /review transaction/i })[0]);
    const transaction = await view.findByRole("dialog", { name: "possible transfer to savings" });
    const marker = view.getByLabelText("Viva needs an answer");
    const ledgerRow = marker.closest<HTMLElement>(".account-ledger-row")!;
    await user.click(within(transaction).getByRole("button", { name: "Answer this question" }));
    expect(await view.findByRole("dialog", { name: "Review question" })).toBeInTheDocument();
    expect(view.getByLabelText("Viva needs an answer")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(view.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(ledgerRow).toHaveFocus());
    expect(view.getByLabelText("Viva needs an answer")).toBeInTheDocument();
  });

  it("returns a direct Review question to its exact item and falls back to the Review heading if that item was removed", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    await user.click(view.getByRole("button", { name: /Review, 15 actionable items/i }));
    const answer = view.getAllByRole("button", { name: "Answer question" })[0];
    const item = answer.closest<HTMLElement>(".review-center-row")!;
    await user.click(answer);
    await view.findByRole("dialog", { name: "Review question" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(item).toHaveFocus());

    await user.click(within(item).getByRole("button", { name: "Answer question" }));
    await view.findByRole("dialog", { name: "Review question" });
    item.remove();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(view.getByRole("heading", { name: "Review", level: 1 })).toHaveFocus());
  });

  it("shows authored transfer comparison and routes exact available controls to Transactions", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    const accountCard = view.getAllByText("Everyday Checking").find((node) => node.closest("button")?.classList.contains("account-card-button"))?.closest("button");
    expect(accountCard).toBeDefined();
    await user.click(accountCard!);
    await view.findByRole("heading", { name: "Everyday Checking" });
    await user.click(view.getByRole("button", { name: /Possible transfer to savings/i }));
    const drawer = await view.findByRole("dialog", { name: /possible transfer to savings/i });
    const transfer = within(drawer).getByRole("region", { name: "Possible transfer" });
    expect(transfer).toHaveTextContent("Rainy Day Savings");
    expect(transfer).toHaveTextContent("1 possible counterpart movement(s) remain from the vault's transfer evidence.");
    expect(transfer).toHaveTextContent("This would treat 2026-06-22's possible transfer to savings on Everyday Checking (USD 275.00) and 2026-06-23's possible transfer from checking on Rainy Day Savings (USD 275.00) as one transfer between your own accounts");
    await user.click(within(transfer).getByRole("button", { name: "Review transfer controls in Transactions" }));
    expect(view.getByRole("heading", { name: "Transactions", level: 1 })).toBeInTheDocument();
    const activityRow = view.getAllByText(/possible transfer to savings/i).map((node) => node.closest("li")).find(Boolean);
    expect(activityRow).toHaveFocus();
  });

  it("keeps every authored target actionable beyond the old ten-question conversation window", async () => {
    const user = userEvent.setup();
    const view = await openSample();
    await user.click(view.getByRole("button", { name: /Review, 15 actionable items/i }));
    const rows = [...view.container.querySelectorAll<HTMLElement>(".review-center-row")];
    expect(rows).toHaveLength(15);
    const target = rows[10];
    const action = within(target).getByRole("button");
    await user.click(action);
    await waitFor(() => expect(view.getByRole("dialog")).toBeInTheDocument());
    expect(view.getByRole("dialog")).toHaveTextContent(target.querySelector("strong")?.textContent ?? "");
  });

  it("fails a same-ID semantic disagreement closed before an action can open", async () => {
    const review = structuredClone(sampleReads.review.result.data) as { groups: Array<{ items: Array<{ label: string; binding: { label: string } }> }> };
    review.groups[0].items[0].label = "Changed label under the same question ID";
    review.groups[0].items[0].binding.label = "Changed label under the same question ID";

    const view = await openSample({ review });

    expect(view.getByRole("button", { name: "Review, count unavailable" })).toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Review could not be read" })).toBeInTheDocument();
    expect(view.queryByRole("button", { name: /Changed label/ })).not.toBeInTheDocument();
  });
});
