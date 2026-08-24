import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SurfaceSnapshot } from "../surface/types";
import { EvidenceBadge } from "./EvidenceBadge";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { FeatureBoundary } from "./FeatureBoundary";
import { Figure } from "./Figure";
import { accountEvidenceFigure } from "../surface/evidence";
import { UNSPOKEN_REPLY, channelPresentation } from "./actionChannel";

const noAction = () => {};
const noticeIcons = { acknowledged: <span>acknowledged-mark</span>, refused: <span>refused-mark</span> };
import { PanelStateView, type PanelStateCopy } from "./PanelStateView";
import { ProofQualifications } from "./ProofCaveats";
import { ProofLinks } from "./ProofLinks";
import { SourceDisclosure } from "./SourceDisclosure";
import { StatusNotice } from "./StatusNotice";

const copy: PanelStateCopy = { partial: "Partial copy", needsInput: "Needs input copy", unavailable: { title: "Unavailable", detail: "Unavailable detail" }, failed: { title: "Failed", detail: "Failed detail" } };

describe("required proof qualifications", () => {
  it("renders backend lines byte-for-byte and removes only exact already-visible duplicates", () => {
    const exact = "  Backend spacing remains intact.  ";
    const view = render(<ProofQualifications proof={{ emphasis: "required", reasons: ["inexact"], qualifications: ["Already visible.", exact] }} alreadyRendered={["Already visible."]} />);
    expect(view.queryByText("Already visible.")).not.toBeInTheDocument();
    expect(view.getByRole("list", { name: "Required qualifications" }).querySelector("li")?.textContent).toBe(exact);
  });

  it("adds no qualification list to valid routine proof", () => {
    const view = render(<ProofQualifications proof={{ emphasis: "routine", reasons: [], qualifications: [] }} />);
    expect(view.queryByRole("list", { name: "Required qualifications" })).not.toBeInTheDocument();
  });
});
const sampleDisclosure: SurfaceSnapshot["disclosure"] = { title: "Sample vault", subtitle: "Nothing here is real", detail: "Every account in this vault was invented." };
function Broken(): never { throw new Error("feature only"); }

describe("shared surface components", () => {
  it("hides absent results", () => {
    const { queryByText } = render(<PanelStateView result={{ state: "absent", reason: "none" }} copy={copy}>{() => <span>Child</span>}</PanelStateView>);
    expect(queryByText("Child")).not.toBeInTheDocument();
  });

  it("renders ready data", () => {
    const { getByText } = render(<PanelStateView result={{ state: "ready", data: "Ready child" }} copy={copy}>{(data) => <span>{data}</span>}</PanelStateView>);
    expect(getByText("Ready child")).toBeInTheDocument();
  });

  it("renders partial copy before its data", () => {
    const { getByText } = render(<PanelStateView result={{ state: "partial", data: "Partial child", issues: [{ code: "partial", message: "One field was unavailable" }] }} copy={copy}>{(data) => <span>{data}</span>}</PanelStateView>);
    expect(getByText("Partial copy")).toBeInTheDocument();
    expect(getByText("Partial child")).toBeInTheDocument();
  });

  it("renders needs-input copy before its data", () => {
    const { getByText } = render(<PanelStateView result={{ state: "needs_input", data: "Input child", issues: [{ code: "input", message: "Input is required" }] }} copy={copy}>{(data) => <span>{data}</span>}</PanelStateView>);
    expect(getByText("Needs input copy")).toBeInTheDocument();
    expect(getByText("Input child")).toBeInTheDocument();
  });

  it("renders a bounded unavailable state without its reason", () => {
    const { getByText, queryByText } = render(<PanelStateView result={{ state: "unavailable", reason: "internal detail" }} copy={copy}>{() => <span>Child</span>}</PanelStateView>);
    expect(getByText("Unavailable detail")).toBeInTheDocument();
    expect(queryByText("internal detail")).not.toBeInTheDocument();
  });

  it("renders a bounded failed state", () => {
    const { getByText } = render(<PanelStateView result={{ state: "failed", reason: "invalid_payload" }} copy={copy}>{() => <span>Child</span>}</PanelStateView>);
    expect(getByText("Failed detail")).toBeInTheDocument();
  });

  it("isolates a thrown feature and resets at the next feature", () => {
    const { getByText, rerender } = render(<FeatureBoundary resetKey="broken"><Broken /></FeatureBoundary>);
    expect(getByText("The rest of the vault is still available. Your vault was not changed.")).toBeInTheDocument();
    rerender(<FeatureBoundary resetKey="healthy"><span>Healthy feature</span></FeatureBoundary>);
    expect(getByText("Healthy feature")).toBeInTheDocument();
  });

  it("recovers the same destination when a new request identity arrives", () => {
    const { getByText, rerender } = render(<FeatureBoundary resetKey="1-overview"><Broken /></FeatureBoundary>);
    expect(getByText("This surface could not be shown")).toBeInTheDocument();
    rerender(<FeatureBoundary resetKey="2-overview"><span>Recovered overview</span></FeatureBoundary>);
    expect(getByText("Recovered overview")).toBeInTheDocument();
  });

  it.each(["overview", "accounts", "activity", "documents", "review", "trust"])("bounds and recovers the %s destination by request-shaped reset key", (destination) => {
    const view = render(<><span>Healthy shell sibling</span><FeatureBoundary resetKey={`1-${destination}`}><Broken /></FeatureBoundary></>);
    expect(view.getByText("Healthy shell sibling")).toBeInTheDocument();
    expect(view.getByText("This surface could not be shown")).toBeInTheDocument();
    view.rerender(<><span>Healthy shell sibling</span><FeatureBoundary resetKey={`2-${destination}`}><span>Recovered {destination}</span></FeatureBoundary></>);
    expect(view.getByText("Healthy shell sibling")).toBeInTheDocument();
    expect(view.getByText(`Recovered ${destination}`)).toBeInTheDocument();
    expect(view.queryByText("This surface could not be shown")).not.toBeInTheDocument();
  });

  it("isolates Conversation from the destination and recovers it on a new request", () => {
    const { getByText, rerender } = render(<><FeatureBoundary resetKey="1-overview"><span>Healthy destination</span></FeatureBoundary><FeatureBoundary resetKey="1-conversation"><Broken /></FeatureBoundary></>);
    expect(getByText("Healthy destination")).toBeInTheDocument();
    expect(getByText("This surface could not be shown")).toBeInTheDocument();
    rerender(<><FeatureBoundary resetKey="1-overview"><span>Healthy destination</span></FeatureBoundary><FeatureBoundary resetKey="2-conversation"><span>Recovered conversation</span></FeatureBoundary></>);
    expect(getByText("Healthy destination")).toBeInTheDocument();
    expect(getByText("Recovered conversation")).toBeInTheDocument();
  });

  it("renders stable proof controls", () => {
    const onOpen = vi.fn();
    const link = { targetDocumentId: "doc", label: "Statement", relation: "same_period" as const, page: "page 1" };
    const { getByRole } = render(<ProofLinks label="View source" links={[link]} onOpen={onOpen} />);
    fireEvent.click(getByRole("button", { name: "Statement · page 1" }));
    expect(onOpen).toHaveBeenCalledWith(link);
  });

  it("renders a canonical figure as a dialog trigger", () => {
    const onOpen = vi.fn();
    const projected = accountEvidenceFigure({ id: "account", name: "Card", kind: "card", measure: "owed", exactValue: "101", currency: "USD", display: "$101", grade: "verified", gradeLabel: "Verified", gradeDescription: "Verified", proofPresentation: { emphasis: "routine", reasons: [], qualifications: [] }, note: null, asOf: "today", coverage: null, provenance: null, evidenceLinks: [], state: "ready" });
    const { getByRole } = render(<Figure figure={projected} onOpenEvidence={onOpen} />);
    // The control is named by the amount it shows, so a person who cannot see
    // the screen hears the number; the invitation to leave it for the evidence
    // rides beside it as the control's description.
    // The name begins with the amount, so a person who cannot see the screen
    // hears the number, and continues with what the figure is of, so two
    // figures showing the same amount are not the same announcement.
    const trigger = getByRole("button", { name: "$101 Card amount owed" });
    expect(trigger).toHaveTextContent("$101");
    expect(trigger).toHaveAccessibleDescription("View evidence for Card amount owed");
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-controls", "figure-evidence-drawer");
    fireEvent.click(trigger);
    expect(onOpen).toHaveBeenCalledWith("account:account");
  });

  it("renders the complete evidence drawer in reviewed section order", () => {
    const account = { id: "account", name: "Card", kind: "card", measure: "owed" as const, exactValue: "101", currency: "USD", display: "$101", grade: "verified" as const, gradeLabel: "Verified", gradeDescription: "Verified", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, note: null, asOf: "today", coverage: "monthly", provenance: "Statement page 1", evidenceLinks: [{ targetDocumentId: "doc", label: "Card statement", relation: "same_account" as const, page: "page 1" }], state: "ready" as const, exactness: "rounded", recordIds: ["record-card-1"] };
    const snapshot: SurfaceSnapshot = { disclosure: sampleDisclosure, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [account] } }, documents: { state: "ready", data: { documents: [{ id: "doc", name: "card.pdf", state: "Verified", phaseLabel: "Verified", detail: "", source: "", pages: "1", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const open = vi.fn();
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByRole, getByText, getAllByRole } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={open} renderEvidenceBadge={badge} />);
    expect(getByRole("dialog", { name: "Evidence for Card amount owed" })).toHaveAttribute("aria-describedby", "figure-evidence-summary");
    expect(getByText("Sample vault · Nothing here is real")).toBeInTheDocument();
    expect(getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Evidence status", "Figure details", "Records behind this figure", "Source trail", "Limits and omissions"]);
    expect(getByText("Rounded")).toBeInTheDocument();
    expect(getByText("record-card-1")).toBeInTheDocument();
    expect(getByText("These are record identities, not document links.")).toBeInTheDocument();
    expect(getByText("No limits were stated for this figure.")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Open card.pdf" }));
    expect(open).toHaveBeenCalledWith(account.evidenceLinks[0]);
  });

  it("keeps the Evidence shell dismissible when its body throws and resets for another figure", () => {
    const first = { id: "first", name: "First account", kind: "deposit", measure: "balance" as const, exactValue: "", currency: "USD", display: "$1", grade: "verified" as const, gradeLabel: "Verified", gradeDescription: "Verified", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" as const };
    const second = { ...first, id: "second", name: "Second account", display: "$2" };
    const snapshot: SurfaceSnapshot = { disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [first, second] } }, documents: { state: "unavailable", reason: "none" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const dismiss = vi.fn();
    const view = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:first" }} onDismiss={dismiss} onOpenDocument={vi.fn()} renderEvidenceBadge={() => <Broken />} />);
    expect(view.getByRole("dialog", { name: "Evidence for First account balance" })).toBeInTheDocument();
    expect(view.getByText("Private vault · Opened on this device")).toBeInTheDocument();
    expect(view.getByText("This surface could not be shown")).toBeInTheDocument();
    fireEvent.click(view.getByRole("button", { name: "Close evidence" }));
    expect(dismiss).toHaveBeenCalledOnce();
    view.rerender(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:second" }} onDismiss={dismiss} onOpenDocument={vi.fn()} renderEvidenceBadge={(grade) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />} />);
    expect(view.getByRole("dialog", { name: "Evidence for Second account balance" })).toBeInTheDocument();
    expect(view.getByRole("heading", { name: "Evidence status" })).toBeInTheDocument();
    expect(view.queryByText("This surface could not be shown")).not.toBeInTheDocument();
  });

  it("renders backend-supplied unavailable-grade copy without changing unavailable semantics", () => {
    const customLabel = "Backend attested — custom";
    const customDescription = "Verified by the private-vault attestation service.";
    const account = { id: "live-custom", name: "Attested account", kind: "deposit", measure: "balance" as const, exactValue: "101", currency: "USD", display: "Canonical account display", grade: "unavailable" as const, gradeLabel: customLabel, gradeDescription: customDescription, proofPresentation: { emphasis: "required" as const, reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "2026-08-18", coverage: "Statement period", provenance: "Private statement page 1", evidenceLinks: [], state: "ready" as const };
    const snapshot: SurfaceSnapshot = { disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [account] } }, documents: { state: "ready", data: { documents: [], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;

    const { getByLabelText, getByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:live-custom" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);

    expect(getByText(customLabel)).toBeInTheDocument();
    expect(getByText(customDescription)).toBeInTheDocument();
    expect(getByLabelText(`${customLabel}. ${customDescription}`)).toHaveClass("unavailable");
  });

  it("keeps missing and conflicted figure identities bounded", () => {
    const base = { id: "account", name: "Card", kind: "card", measure: "balance" as const, exactValue: "1", currency: "", display: "$1", grade: "unavailable" as const, gradeLabel: "", gradeDescription: "", proofPresentation: { emphasis: "required" as const, reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" as const };
    const makeSnapshot = (accounts: typeof base[]): SurfaceSnapshot => ({ disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts } }, documents: { state: "unavailable", reason: "none" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } });
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, rerender } = render(<EvidenceDrawer snapshot={makeSnapshot([])} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("This figure is no longer present in the current vault read.")).toBeInTheDocument();
    rerender(<EvidenceDrawer snapshot={makeSnapshot([base, { ...base, display: "$2" }])} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("More than one figure in this read uses this identity, so the interface will not choose between them.")).toBeInTheDocument();
  });

  it("keeps unavailable live figure metadata and document targets explicit", () => {
    const account = { id: "live", name: "Live account", kind: "", measure: null, exactValue: "raw-secret-937.25", currency: "", display: "", grade: "unavailable" as const, gradeLabel: "", gradeDescription: "", proofPresentation: { emphasis: "required" as const, reasons: ["test"], qualifications: ["A reviewed qualification."] }, note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [{ targetDocumentId: "doc", label: "Live statement", relation: "same_account" as const, page: "" }], state: "ready" as const };
    const snapshot: SurfaceSnapshot = { disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [] }, accounts: [account] } }, documents: { state: "unavailable", reason: "not connected" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, queryByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:live" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("Evidence status unavailable")).toBeInTheDocument();
    expect(getByText("This read did not provide a recognized evidence grade.")).toBeInTheDocument();
    expect(getByText("Amount unavailable from this preview read.")).toBeInTheDocument();
    expect(getByText("Exactness unavailable")).toBeInTheDocument();
    expect(getByText("Record identities were not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Measurement type was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Documents are not available in the current vault read.")).toBeInTheDocument();
    // A row that was given no page says nothing where the page would be: the
    // document it points at is named by the control beside it, and repeating
    // the word unavailable once per row discloses nothing.
    expect(queryByText("Page or region was not supplied by this read.")).not.toBeInTheDocument();
    expect(queryByText("Source label unavailable")).not.toBeInTheDocument();
    expect(getByText("Same account")).toBeInTheDocument();
    expect(queryByText("raw-secret-937.25")).not.toBeInTheDocument();
  });

  // A picture figure's drawer names what the read said the figure measures.
  // The drawer's default sentence about an unsupplied measurement type is for
  // a figure the read named none for, and this is not one.
  it("names what a picture figure measures instead of printing a machinery sentence", () => {
    const figure = { id: "AAA", display: "AAA 1.00", exactValue: "", currency: "AAA", measure: "net_worth" as const, grade: "corroborated" as const, gradeLabel: "corroborated", gradeDescription: "One reviewed sentence.", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, asOf: "2026-08-21", coverage: ["A boundary the read declared."], caveats: [], evidenceLinks: [] };
    const snapshot: SurfaceSnapshot = { disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [figure], withheld: [], unplaced: [] }, accounts: [] } }, documents: { state: "unavailable", reason: "not connected" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, queryByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "net-worth:AAA" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("Net worth")).toBeInTheDocument();
    expect(queryByText("Measurement type was not supplied by this read.")).not.toBeInTheDocument();
    // The complete receipt retains the boundary even when compact proof on the
    // picture is quiet.
    expect(queryByText("A boundary the read declared.")).toBeInTheDocument();
    expect(queryByText("Coverage")).toBeInTheDocument();
  });

  // The panel's sentence counts the accounts a read could not value and never
  // names them, because a list of account names is the one thing on that
  // screen a person cannot un-share. The naming half belongs here — and until
  // it existed the drawer told a person no limits were stated about a figure
  // whose own boundary declared one.
  it("names the accounts the read could not value instead of saying none were stated", () => {
    const figure = { id: "AAA", display: "AAA 1.00", exactValue: "", currency: "AAA", measure: "net_worth" as const, grade: "corroborated" as const, gradeLabel: "corroborated", gradeDescription: "One reviewed sentence.", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, asOf: "2026-08-21", coverage: ["A boundary the read declared."], caveats: [], evidenceLinks: [], unmeasured: [{ account: "acct:named-row", name: "Rainy Day Savings", sentence: "Nothing has measured Rainy Day Savings, so it is not in this total." }, { account: "acct:second-row", name: "Sample Home Loan", sentence: "A figure could not be put on Sample Home Loan, so it is not in this total." }] };
    const row = { id: "acct:named-row", name: "A different name for the same account", kind: "Depository", measure: "balance" as const, exactValue: "", currency: "AAA", display: "AAA 2.00", grade: "verified" as const, gradeLabel: "verified", gradeDescription: "One reviewed sentence.", proofPresentation: { emphasis: "routine" as const, reasons: [], qualifications: [] }, note: null, asOf: "2026-08-21", coverage: null, provenance: null, evidenceLinks: [], state: "ready" as const };
    const snapshot: SurfaceSnapshot = { disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [figure], withheld: [], unplaced: [] }, accounts: [row] } }, documents: { state: "unavailable", reason: "not connected" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, queryByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "net-worth:AAA" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    // The name is the read's, not one worked out here from a ledger path. The
    // row beside it in this snapshot deliberately carries a different name, so
    // a drawer resolving the account itself would show that one instead.
    // The sentence names the account itself, so the drawer does not print the
    // name a second time above it: the same fact said once by each side is
    // what took the date off an account card.
    expect(queryByText("Rainy Day Savings")).not.toBeInTheDocument();
    expect(queryByText("A different name for the same account")).not.toBeInTheDocument();
    expect(queryByText("acct:named-row")).not.toBeInTheDocument();
    // And beside each name, the read's own sentence for why it is not in the
    // total. Nothing here chose those words or read them.
    expect(getByText("Nothing has measured Rainy Day Savings, so it is not in this total.")).toBeInTheDocument();
    expect(getByText("A figure could not be put on Sample Home Loan, so it is not in this total.")).toBeInTheDocument();
    expect(queryByText("No limits were stated for this figure.")).not.toBeInTheDocument();
  });

  it("renders evidence with non-color meaning", () => {
    const { getByLabelText } = render(<EvidenceBadge grade="verified" label="Verified" description="Confirmed by review." />);
    expect(getByLabelText("Verified. Confirmed by review.")).toBeInTheDocument();
  });

  it("renders exact source disclosure", () => {
    const { getByRole, getByText } = render(<SourceDisclosure disclosure={sampleDisclosure} />);
    expect(getByRole("complementary", { name: "Vault source" })).toHaveClass("source-disclosure", "corpus-note");
    expect(getByText("Sample vault · Nothing here is real")).toBeInTheDocument();
    expect(getByText("Every account in this vault was invented.")).toBeInTheDocument();
  });

  it("says what the source said about itself, and never a second sentence of its own", () => {
    // Both lines used to be a dialect switch. There is one vault kind now, so
    // the disclosure repeats the read's own words rather than choosing between
    // two it was carrying.
    const disclosure: SurfaceSnapshot["disclosure"] = { title: "Private vault", subtitle: "Opened on this device", detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so." };
    const { getByText, queryByText } = render(<SourceDisclosure disclosure={disclosure} />);
    expect(getByText("Private vault · Opened on this device")).toBeInTheDocument();
    expect(getByText("The surfaces below are read from this vault. Features that are not connected stay hidden or say so.")).toBeInTheDocument();
    expect(queryByText("unused long disclosure")).not.toBeInTheDocument();
  });

  it("renders and dismisses status notice controls", () => {
    const dismiss = vi.fn();
    const { getByRole } = render(<StatusNotice notice={{ kind: "acknowledged", text: "Status copy" }} onDismiss={dismiss} icons={noticeIcons} dismissIcon={<span>x</span>} />);
    expect(getByRole("status")).toHaveTextContent("Status copy");
    fireEvent.click(getByRole("button", { name: "Dismiss notice" }));
    expect(dismiss).toHaveBeenCalledOnce();
  });

  // The mark a notice wears follows the word it declares. A sentence saying
  // something did not happen cannot reach the mark that means it did, whatever
  // the sentence says.
  // A refusal carries no mark: the universal glyph for something went wrong is
  // a third signal where the screen that already ships a refusal uses one.
  it("gives a refusal no mark of its own", () => {
    const marks = { acknowledged: <span>acknowledged-mark</span>, refused: null };
    const { getByRole } = render(<StatusNotice notice={{ kind: "refused", text: "Nothing was added." }} onDismiss={noAction} icons={marks} dismissIcon={<span>x</span>} />);
    const notice = getByRole("status");
    expect(notice).toHaveTextContent("Nothing was added.");
    // The sentence and the dismiss control, and nothing standing before them.
    expect([...notice.children].map((child) => child.textContent)).toEqual(["Nothing was added.", "x"]);
  });

  it("dresses a notice by the kind it declares and never by what it says", () => {
    const said = "Nothing was added.";
    const acknowledged = render(<StatusNotice notice={{ kind: "acknowledged", text: said }} onDismiss={noAction} icons={noticeIcons} dismissIcon={<span>x</span>} />);
    expect(acknowledged.getByRole("status")).toHaveAttribute("data-kind", "acknowledged");
    expect(acknowledged.getByRole("status").className).toBe("notice");
    expect(acknowledged.getByText("acknowledged-mark")).toBeInTheDocument();
    acknowledged.unmount();

    const refused = render(<StatusNotice notice={{ kind: "refused", text: said }} onDismiss={noAction} icons={noticeIcons} dismissIcon={<span>x</span>} />);
    expect(refused.getByRole("status")).toHaveAttribute("data-kind", "refused");
    expect(refused.getByRole("status").className).toBe("notice notice-refused");
    expect(refused.queryByText("acknowledged-mark")).not.toBeInTheDocument();
  });
});

describe("the words every screen uses for a request that never reached an answer", () => {
  it("names each channel by what did not happen to the request, and names no verb", () => {
    expect(channelPresentation({ state: "unserved" })).toEqual({ title: "Your vault would not take this request", detail: "Your vault refused the request as this screen sent it. Whether anything was recorded is not something this screen can tell you." });
    expect(channelPresentation({ state: "unanswered" })).toEqual({ title: "Your vault did not answer", detail: "Nothing came back, so this screen will not say whether anything was recorded." });
    expect(channelPresentation({ state: "unreadable" })).toEqual({ title: "The reply could not be read", detail: "Your vault answered in a way this screen does not recognise, so it will not say whether anything was recorded." });
    expect(UNSPOKEN_REPLY).toBe("Your vault recorded no sentence for this reply.");
  });

  it("leaves no channel without words", () => {
    for (const state of ["unserved", "unanswered", "unreadable"] as const) {
      const said = channelPresentation({ state });
      expect(said.title.trim()).not.toBe("");
      expect(said.detail.trim()).not.toBe("");
    }
  });
});
