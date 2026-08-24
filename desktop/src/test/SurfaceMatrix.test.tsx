import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Accounts } from "../features/accounts/Accounts";
import { Overview } from "../features/overview/Overview";
import type { ActivityData, FeatureResult, OverviewData, ReviewData, ReviewView } from "../surface/types";
import { LONG_TRUTH, absent, failed, makeAccount, makeOverview, makePicture, makeSurfaceScenario, needsInput, partial, ready, unavailable } from "./surfaceScenarios";

const actions = { showVerificationDetails: false, onSelectAccount: vi.fn(), onOpenEvidence: vi.fn(), onOpenFigure: vi.fn(), onExploreSample: vi.fn() };
const overviewActions = { ...actions, onOpenReviewQuestion: vi.fn(), onNavigate: vi.fn() };
const absentReview = absent<ReviewData>();

const absentActivity = absent<ActivityData>();

function accountView(result: FeatureResult<OverviewData>) {
  return render(<Accounts {...actions} result={result} selectedAccount="" />);
}

function overviewView(result: FeatureResult<OverviewData>, reviewResult: FeatureResult<ReviewData> = absentReview) {
  return render(<Overview {...overviewActions} result={result} reviewResult={reviewResult} activityResult={absentActivity} selectedAccount="" />);
}

const reviewRow = (id: string, label: string): ReviewView => ({ id, label, detail: "", status: "", action: "", type: "", evidence: "", state: "needs_input", outcome: null, disposition: null });

describe("surface scenario support", () => {
  it("creates shallow scenarios without implicit feature data", () => {
    const scenario = makeSurfaceScenario();
    expect(scenario.disclosure.title).toBe("Private vault");
    expect(scenario.overview.state).toBe("absent");
    expect(scenario.trust.state).toBe("absent");
    expect(LONG_TRUTH).toHaveLength(128);
  });
});

describe("Overview and Accounts state matrix", () => {
  it("renders all Accounts states with callouts before retained data", () => {
    const data = makeOverview({ accounts: [makeAccount()] });
    const view = accountView(absent());
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<Accounts {...actions} result={unavailable()} selectedAccount="" />);
    expect(view.getByText("Accounts unavailable")).toBeInTheDocument();
    view.rerender(<Accounts {...actions} result={failed()} selectedAccount="" />);
    expect(view.getByText("The accounts section could not be read. The private vault is still open.")).toBeInTheDocument();
    view.rerender(<Accounts {...actions} result={partial(data)} selectedAccount="" />);
    const partialCallout = view.getByText("Some account details are unavailable. Available accounts are shown below.");
    const partialHeading = view.getByRole("heading", { name: "Accounts in this read" });
    expect(partialCallout.compareDocumentPosition(partialHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<Accounts {...actions} result={needsInput(data)} selectedAccount="" />);
    const needsCallout = view.getByText("Some accounts need more information. Available account details are shown below.");
    expect(needsCallout.compareDocumentPosition(view.getByRole("heading", { name: "Accounts in this read" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<Accounts {...actions} result={ready(makeOverview())} selectedAccount="" />);
    expect(view.getByText("No accounts yet")).toBeInTheDocument();
  });

  it("renders all Overview states without turning initial states into alerts", () => {
    const data = makeOverview({ accounts: [makeAccount()] });
    const view = overviewView(absent());
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<Overview {...overviewActions} result={unavailable()} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.getByText("Financial picture unavailable")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={failed()} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.getByText("The financial picture could not be read. The private vault is still open.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={partial(data)} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.getByText("Some financial-picture details are unavailable. Available details are shown below.")).toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={needsInput(data)} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.getByText("Some parts of the financial picture need more information. Available details are shown below.")).toBeInTheDocument();
    expect(view.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Overview supplied truth and identity boundaries", () => {
  // The horizon the projection was cut at is empty on every live read, and a
  // heading over an empty horizon tells a person a freshness fact was withheld
  // when none was ever asked for. The horizon does not reach this side; the
  // picture states the day it was read on inside its own sentence.
  it("makes no freshness claim out of the projection horizon", () => {
    const view = overviewView(ready(makeOverview()));
    for (const retired of ["Current-through value", "Shown as supplied. The interface does not infer freshness.", "Current-through value was not supplied by this overview read."]) {
      expect(view.queryByText(retired), retired).not.toBeInTheDocument();
    }
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview())} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.queryByText("Sample current-through value was not authored.")).not.toBeInTheDocument();
  });

  // The picture's own sentence reaches a live screen whole, because the backend
  // wrote it. The corpus fields are a demo-only concept and still do not.
  it("shows the picture sentence the read supplied and no corpus field beside it", () => {
    const supplied = makeOverview({ picture: makePicture({ coverage: "SUPPLIED PICTURE SENTENCE" }) });
    const view = overviewView(ready(supplied));
    expect(view.getByText("SUPPLIED PICTURE SENTENCE")).toBeInTheDocument();
    expect(view.queryByText("DEMO-ONLY CORPUS")).not.toBeInTheDocument();
    view.rerender(<Overview {...overviewActions} result={ready(makeOverview())} reviewResult={absentReview} activityResult={absentActivity} selectedAccount="" />);
    expect(view.queryByText("Nothing is silently inferred.")).not.toBeInTheDocument();
  });

  it("shows mixed currency display strings independently without a total", () => {
    const view = accountView(ready(makeOverview({ accounts: [makeAccount({ id: "usd", display: "$10.00", currency: "USD" }), makeAccount({ id: "eur", name: "Euro account", display: "€20.00", currency: "EUR" })] })));
    expect(view.getAllByText("$10.00").length).toBeGreaterThan(0);
    expect(view.getAllByText("€20.00").length).toBeGreaterThan(0);
    expect(view.queryByText(/combined total/i)).not.toBeInTheDocument();
  });

  it("groups invalid account and review identities and exposes only unique actions", () => {
    const accounts = [makeAccount({ id: "", name: "Blank account" }), makeAccount({ id: "dup-account", name: "Duplicate account one" }), makeAccount({ id: "dup-account", name: "Duplicate account two" }), makeAccount({ id: "unique-account", name: "Unique account" })];
    const queue = [reviewRow("", "Blank review"), reviewRow("dup-review", "Duplicate review one"), reviewRow("dup-review", "Duplicate review two"), reviewRow("unique-review", "Unique review")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const view = overviewView(ready(makeOverview({ accounts })), reviewResult);
    expect(view.getByText("Account identity unavailable")).toBeInTheDocument();
    expect(view.getByText("Account identity conflicted")).toBeInTheDocument();
    expect(view.getByText("Question identity unavailable")).toBeInTheDocument();
    expect(view.getByText("Question identity conflicted")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "View question" })).toBeInTheDocument();
    for (const hidden of ["Blank account", "Duplicate account one", "Duplicate account two", "Blank review", "Duplicate review one", "Duplicate review two"]) expect(view.queryByText(hidden)).not.toBeInTheDocument();
  });


  it("keeps long conflicted identities bounded without actions, Figures, proof controls, or truncation", () => {
    const queue = [reviewRow(LONG_TRUTH, "Conflicted review one"), reviewRow(LONG_TRUTH, "Conflicted review two")];
    const reviewResult = ready<ReviewData>({ queue, count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } });
    const accounts = [makeAccount({ id: LONG_TRUTH, name: "Conflicted account one" }), makeAccount({ id: LONG_TRUTH, name: "Conflicted account two" })];
    const view = overviewView(ready(makeOverview({ accounts })), reviewResult);
    expect(view.container).toHaveTextContent(LONG_TRUTH);
    expect(view.queryByRole("button", { name: /Conflicted account|View question/i })).not.toBeInTheDocument();
    expect(view.queryByRole("button", { description: /View evidence for Conflicted/i })).not.toBeInTheDocument();
    expect(view.container.querySelector("[title]")).toBeNull();
  });

});
