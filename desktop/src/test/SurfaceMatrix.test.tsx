import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Accounts } from "../features/accounts/Accounts";
import { Overview } from "../features/overview/Overview";
import type { ActivityView, FeatureResult, OverviewData, ReviewData, ReviewView } from "../surface/types";
import { LONG_TRUTH, absent, failed, makeAccount, makeOverview, makeSurfaceScenario, needsInput, partial, ready, unavailable } from "./surfaceScenarios";

const actions = { onSelectAccount: vi.fn(), onOpenEvidence: vi.fn(), onOpenFigure: vi.fn(), onExploreSample: vi.fn() };
const overviewActions = { ...actions, onOpenReviewQuestion: vi.fn(), onNavigate: vi.fn() };
const absentReview = absent<ReviewData>();

function accountView(result: FeatureResult<OverviewData>, mode: "demo" | "live" = "live") {
  return render(<Accounts {...actions} result={result} mode={mode} selectedAccount="" />);
}

function overviewView(result: FeatureResult<OverviewData>, mode: "demo" | "live" = "live", reviewResult: FeatureResult<ReviewData> = absentReview) {
  return render(<Overview {...overviewActions} result={result} reviewResult={reviewResult} mode={mode} selectedAccount="" />);
}

const reviewRow = (id: string, label: string): ReviewView => ({ id, label, detail: "", status: "", action: "", type: "", evidence: "", state: "needs_input", outcome: null, disposition: null });
const activityRow = (id: string, label: string): ActivityView => ({ id, label, exactValue: "", display: "$1.00", measure: "spending", detail: "Supplied detail", tone: "neutral", state: "ready", provenance: "", evidenceLinks: [], grade: "not_applicable" });

describe("surface scenario support", () => {
  it("creates mode-consistent shallow scenarios without implicit feature data", () => {
    const demo = makeSurfaceScenario("demo");
    const live = makeSurfaceScenario("live");
    expect(demo.disclosure.title).toBe("Sample vault");
    expect(live.disclosure.title).toBe("Private vault");
    expect(demo.overview.state).toBe("absent");
    expect(live.trust.state).toBe("absent");
    expect(LONG_TRUTH).toHaveLength(128);
  });
});

describe("Overview and Accounts state matrix", () => {
  it("renders all Accounts states with callouts before retained data", () => {
    const data = makeOverview({ accounts: [makeAccount()] });
    const view = accountView(absent());
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<Accounts {...actions} result={unavailable()} mode="live" selectedAccount="" />);
    expect(view.getByText("Accounts unavailable")).toBeInTheDocument();
    view.rerender(<Accounts {...actions} result={failed()} mode="live" selectedAccount="" />);
    expect(view.getByText("The accounts section could not be read. The private vault is still open.")).toBeInTheDocument();
    view.rerender(<Accounts {...actions} result={partial(data)} mode="live" selectedAccount="" />);
    const partialCallout = view.getByText("Some account details are unavailable. Available accounts are shown below.");
    const partialHeading = view.getByRole("heading", { name: "Accounts in this read" });
    expect(partialCallout.compareDocumentPosition(partialHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<Accounts {...actions} result={needsInput(data)} mode="live" selectedAccount="" />);
    const needsCallout = view.getByText("Some accounts need more information. Available account details are shown below.");
    expect(needsCallout.compareDocumentPosition(view.getByRole("heading", { name: "Accounts in this read" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<Accounts {...actions} result={ready(makeOverview())} mode="live" selectedAccount="" />);
    expect(view.getByText("No accounts yet")).toBeInTheDocument();
  });

  it("renders all Overview states without turning initial states into alerts", () => {
    const data = makeOverview({ accounts: [makeAccount()] });
    const view = overviewView(absent());
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<Overview {...overviewActions} result={unavailable()} reviewResult={absentReview} mode="live" selectedAccount="" />);
    expect(view.getByText("Financial picture unavailable")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={failed()} reviewResult={absentReview} mode="live" selectedAccount="" />);
    expect(view.getByText("The financial picture could not be read. The private vault is still open.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={partial(data)} reviewResult={absentReview} mode="live" selectedAccount="" />);
    expect(view.getByText("Some financial-picture details are unavailable. Available details are shown below.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={needsInput(data)} reviewResult={absentReview} mode="live" selectedAccount="" />);
    expect(view.getByText("Some parts of the financial picture need more information. Available details are shown below.")).toBeInTheDocument();
    expect(view.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Overview supplied truth and identity boundaries", () => {
  it("shows current-through as an opaque value and never infers freshness", () => {
    const view = overviewView(ready(makeOverview({ currentThrough: "Opaque stale-label bytes" })));
    expect(view.getByText("Current-through value")).toBeInTheDocument();
    expect(view.getByText("Opaque stale-label bytes")).toBeInTheDocument();
    expect(view.getByText("Shown as supplied. The interface does not infer freshness.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview())} reviewResult={absentReview} mode="live" selectedAccount="" />);
    expect(view.getByText("Current-through value was not supplied by this overview read.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview())} reviewResult={absentReview} mode="demo" selectedAccount="" />);
    expect(view.getByText("Sample current-through value was not authored.")).toBeInTheDocument();
  });

  it("hides live derived coverage and corpus fields while retaining exact demo fallbacks", () => {
    const malicious = makeOverview({ coverage: "MALICIOUS COVERAGE", corpusCoverage: "MALICIOUS CORPUS", corpusSource: "MALICIOUS SOURCE" });
    const view = overviewView(ready(malicious));
    expect(view.getByText("Coverage totals were not supplied by this overview read. Available accounts are shown individually.")).toBeInTheDocument();
    for (const hidden of ["MALICIOUS COVERAGE", "MALICIOUS CORPUS", "MALICIOUS SOURCE"]) expect(view.queryByText(hidden)).not.toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview())} reviewResult={absentReview} mode="demo" selectedAccount="" />);
    expect(view.getByText("Sample coverage was not authored.")).toBeInTheDocument();
    expect(view.getByText("Sample corpus coverage was not authored. The sample does not claim completeness.")).toBeInTheDocument();
    expect(view.getByText("Sample boundaries stay visible.")).toBeInTheDocument();
    expect(view.queryByText("Nothing is silently inferred.")).not.toBeInTheDocument();
  });

  it("shows mixed currency display strings independently without a total", () => {
    const view = accountView(ready(makeOverview({ accounts: [makeAccount({ id: "usd", display: "$10.00", currency: "USD" }), makeAccount({ id: "eur", name: "Euro account", display: "€20.00", currency: "EUR" })] })));
    expect(view.getAllByText("$10.00").length).toBeGreaterThan(0);
    expect(view.getAllByText("€20.00").length).toBeGreaterThan(0);
    expect(view.queryByText(/combined total/i)).not.toBeInTheDocument();
  });

  it("groups invalid account, review, and activity identities and exposes only unique actions", () => {
    const accounts = [makeAccount({ id: "", name: "Blank account" }), makeAccount({ id: "dup-account", name: "Duplicate account one" }), makeAccount({ id: "dup-account", name: "Duplicate account two" }), makeAccount({ id: "unique-account", name: "Unique account" })];
    const recent = [activityRow("", "Blank activity"), activityRow("dup-activity", "Duplicate activity one"), activityRow("dup-activity", "Duplicate activity two"), activityRow("unique-activity", "Unique activity")];
    const queue = [reviewRow("", "Blank review"), reviewRow("dup-review", "Duplicate review one"), reviewRow("dup-review", "Duplicate review two"), reviewRow("unique-review", "Unique review")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const view = overviewView(ready(makeOverview({ accounts, recent })), "live", reviewResult);
    expect(view.getByText("Account identity unavailable")).toBeInTheDocument();
    expect(view.getByText("Account identity conflicted")).toBeInTheDocument();
    expect(view.getByText("Question identity unavailable")).toBeInTheDocument();
    expect(view.getByText("Question identity conflicted")).toBeInTheDocument();
    expect(view.getByText("Activity identity unavailable")).toBeInTheDocument();
    expect(view.getByText("Activity identity conflicted")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View question" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View evidence for Unique activity spending" })).toBeInTheDocument();
    for (const hidden of ["Blank account", "Duplicate account one", "Duplicate account two", "Blank review", "Duplicate review one", "Duplicate review two", "Blank activity", "Duplicate activity one", "Duplicate activity two"]) expect(view.queryByText(hidden)).not.toBeInTheDocument();
  });

  it("routes distinct 128-character account, review, and activity identities exactly without truncation attributes", () => {
    const accountId = LONG_TRUTH;
    const reviewId = LONG_TRUTH.slice(0, -1) + "!";
    const activityId = LONG_TRUTH.slice(0, -1) + "?";
    const onSelectAccount = vi.fn();
    const onOpenReviewQuestion = vi.fn();
    const onOpenFigure = vi.fn();
    const queue = [reviewRow(reviewId, "Long review row")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const view = render(<Overview {...overviewActions} onSelectAccount={onSelectAccount} onOpenReviewQuestion={onOpenReviewQuestion} onOpenFigure={onOpenFigure} result={ready(makeOverview({ accounts: [makeAccount({ id: accountId, name: "Long account row" })], recent: [activityRow(activityId, "Long activity row")] }))} reviewResult={reviewResult} mode="live" selectedAccount="" />);
    const accountButton = view.getAllByRole("button", { name: /Long account row/i }).find((button) => button.classList.contains("account-card-button")) as HTMLElement;
    const reviewButton = view.getByRole("button", { name: "View question" });
    const activityFigure = view.getByRole("button", { name: "View evidence for Long activity row spending" });
    expect(accountId).toHaveLength(128);
    expect(reviewId).toHaveLength(128);
    expect(activityId).toHaveLength(128);
    accountButton.click();
    reviewButton.click();
    activityFigure.click();
    expect(onSelectAccount).toHaveBeenCalledWith(accountId);
    expect(onOpenReviewQuestion).toHaveBeenCalledWith(reviewId);
    expect(onOpenFigure).toHaveBeenCalledWith(`activity:${activityId}`);
    for (const control of [accountButton, reviewButton, activityFigure]) expect(control).not.toHaveAttribute("title");
  });

  it("keeps long conflicted identities bounded without actions, Figures, proof controls, or truncation", () => {
    const queue = [reviewRow(LONG_TRUTH, "Conflicted review one"), reviewRow(LONG_TRUTH, "Conflicted review two")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const accounts = [makeAccount({ id: LONG_TRUTH, name: "Conflicted account one" }), makeAccount({ id: LONG_TRUTH, name: "Conflicted account two" })];
    const recent = [activityRow(LONG_TRUTH, "Conflicted activity one"), activityRow(LONG_TRUTH, "Conflicted activity two")];
    const view = overviewView(ready(makeOverview({ accounts, recent })), "live", reviewResult);
    expect(view.container).toHaveTextContent(LONG_TRUTH);
    expect(view.queryByRole("button", { name: /Conflicted account|Conflicted activity|View question/i })).not.toBeInTheDocument();
    expect(view.queryByRole("button", { name: /View evidence for Conflicted/i })).not.toBeInTheDocument();
    expect(view.container.querySelector("[title]")).toBeNull();
  });

  it("keeps uniquely identified blank review and activity labels actionable with exact mode copy", () => {
    const queue = [reviewRow("blank-label-review", "")];
    const recent = [activityRow("blank-label-activity", "")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const view = overviewView(ready(makeOverview({ recent })), "demo", reviewResult);
    expect(view.getByText("Sample question text was not authored.")).toBeInTheDocument();
    expect(view.getByText("Sample activity label was not authored.")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View question" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View evidence for Activity label unavailable spending" })).toBeInTheDocument();
    for (const button of view.getAllByRole("button")) expect((button.getAttribute("aria-label") || button.textContent || "").trim()).not.toBe("");
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview({ recent }))} reviewResult={reviewResult} mode="live" selectedAccount="" />);
    expect(view.getByText("Question text was not supplied by this review read.")).toBeInTheDocument();
    expect(view.getByText("Activity label was not supplied by this overview read.")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View question" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View evidence for Activity label unavailable spending" })).toBeInTheDocument();
  });
});
