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
import { ProofLinks } from "./ProofLinks";
import { SourceDisclosure } from "./SourceDisclosure";
import { StatusNotice } from "./StatusNotice";

const copy: PanelStateCopy = { partial: "Partial copy", needsInput: "Needs input copy", unavailable: { title: "Unavailable", detail: "Unavailable detail" }, failed: { title: "Failed", detail: "Failed detail" } };
const sampleDisclosure: SurfaceSnapshot["disclosure"] = { title: "Sample vault", subtitle: "Fictional sample data", detail: "Every name, document, and figure in this vault is fictional and stored with the app." };
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
    const projected = accountEvidenceFigure({ id: "account", name: "Card", kind: "card", measure: "owed", exactValue: "101", currency: "USD", display: "$101", grade: "verified", gradeLabel: "Verified", gradeDescription: "Verified", note: null, asOf: "today", coverage: null, provenance: null, evidenceLinks: [], state: "ready" });
    const { getByRole } = render(<Figure figure={projected} onOpenEvidence={onOpen} />);
    const trigger = getByRole("button", { name: "View evidence for Card amount owed" });
    expect(trigger).toHaveTextContent("$101");
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-controls", "figure-evidence-drawer");
    fireEvent.click(trigger);
    expect(onOpen).toHaveBeenCalledWith("account:account");
  });

  it("renders the complete evidence drawer in reviewed section order", () => {
    const account = { id: "account", name: "Card", kind: "card", measure: "owed" as const, exactValue: "101", currency: "USD", display: "$101", grade: "verified" as const, gradeLabel: "Verified", gradeDescription: "Verified", note: null, asOf: "today", coverage: "monthly", provenance: "Statement page 1", evidenceLinks: [{ targetDocumentId: "doc", label: "Card statement", relation: "same_account" as const, page: "page 1" }], state: "ready" as const, exactness: "rounded", recordIds: ["record-card-1"] };
    const snapshot: SurfaceSnapshot = { mode: "demo", disclosure: sampleDisclosure, overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "", netWorth: null, accounts: [account], recent: [] } }, documents: { state: "ready", data: { documents: [{ id: "doc", name: "card.pdf", state: "Verified", phaseLabel: "Verified", detail: "", source: "", pages: "1", provenance: "", evidenceLinks: [] }], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const open = vi.fn();
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByRole, getByText, getAllByRole } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={open} renderEvidenceBadge={badge} />);
    expect(getByRole("dialog", { name: "Evidence for Card amount owed" })).toHaveAttribute("aria-describedby", "figure-evidence-summary");
    expect(getByText("Sample figure · Fictional data")).toBeInTheDocument();
    expect(getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Evidence status", "Figure details", "Records behind this figure", "Source trail", "Limits and omissions"]);
    expect(getByText("Rounded")).toBeInTheDocument();
    expect(getByText("record-card-1")).toBeInTheDocument();
    expect(getByText("These are record identities, not document links.")).toBeInTheDocument();
    expect(getByText("No limits were stated for this figure.")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Open card.pdf" }));
    expect(open).toHaveBeenCalledWith(account.evidenceLinks[0]);
  });

  it("keeps the Evidence shell dismissible when its body throws and resets for another figure", () => {
    const first = { id: "first", name: "First account", kind: "deposit", measure: "balance" as const, exactValue: "", currency: "USD", display: "$1", grade: "verified" as const, gradeLabel: "Verified", gradeDescription: "Verified", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" as const };
    const second = { ...first, id: "second", name: "Second account", display: "$2" };
    const snapshot: SurfaceSnapshot = { mode: "live", disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "", netWorth: null, accounts: [first, second], recent: [] } }, documents: { state: "unavailable", reason: "none" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const dismiss = vi.fn();
    const view = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:first" }} onDismiss={dismiss} onOpenDocument={vi.fn()} renderEvidenceBadge={() => <Broken />} />);
    expect(view.getByRole("dialog", { name: "Evidence for First account balance" })).toBeInTheDocument();
    expect(view.getByText("Private vault figure · Opened on this device")).toBeInTheDocument();
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
    const account = { id: "live-custom", name: "Attested account", kind: "deposit", measure: "balance" as const, exactValue: "101", currency: "USD", display: "Canonical account display", grade: "unavailable" as const, gradeLabel: customLabel, gradeDescription: customDescription, note: null, asOf: "2026-08-18", coverage: "Statement period", provenance: "Private statement page 1", evidenceLinks: [], state: "ready" as const };
    const snapshot: SurfaceSnapshot = { mode: "live", disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "", netWorth: null, accounts: [account], recent: [] } }, documents: { state: "ready", data: { documents: [], readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] } }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;

    const { getByLabelText, getByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:live-custom" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);

    expect(getByText(customLabel)).toBeInTheDocument();
    expect(getByText(customDescription)).toBeInTheDocument();
    expect(getByLabelText(`${customLabel}. ${customDescription}`)).toHaveClass("unavailable");
  });

  it("keeps missing and conflicted figure identities bounded", () => {
    const base = { id: "account", name: "Card", kind: "card", measure: "balance" as const, exactValue: "1", currency: "", display: "$1", grade: "unavailable" as const, gradeLabel: "", gradeDescription: "", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" as const };
    const makeSnapshot = (accounts: typeof base[]): SurfaceSnapshot => ({ mode: "live", disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "", netWorth: null, accounts, recent: [] } }, documents: { state: "unavailable", reason: "none" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } });
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, rerender } = render(<EvidenceDrawer snapshot={makeSnapshot([])} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("This figure is no longer present in the current vault read.")).toBeInTheDocument();
    rerender(<EvidenceDrawer snapshot={makeSnapshot([base, { ...base, display: "$2" }])} selection={{ figureId: "account:account" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("More than one figure in this read uses this identity, so the interface will not choose between them.")).toBeInTheDocument();
  });

  it("keeps unavailable live figure metadata and document targets explicit", () => {
    const account = { id: "live", name: "Live account", kind: "", measure: null, exactValue: "raw-secret-937.25", currency: "", display: "", grade: "unavailable" as const, gradeLabel: "", gradeDescription: "", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [{ targetDocumentId: "doc", label: "Live statement", relation: "same_account" as const, page: "" }], state: "ready" as const };
    const snapshot: SurfaceSnapshot = { mode: "live", disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: { state: "ready", data: { currentThrough: "", coverage: "", corpusCoverage: "", corpusSource: "", netWorth: null, accounts: [account], recent: [] } }, documents: { state: "unavailable", reason: "not connected" }, review: { state: "absent", reason: "" }, activity: { state: "absent", reason: "" }, conversation: { state: "absent", reason: "" }, trust: { state: "absent", reason: "" } };
    const badge = (grade: ReturnType<typeof accountEvidenceFigure>["grade"]) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />;
    const { getByText, queryByText } = render(<EvidenceDrawer snapshot={snapshot} selection={{ figureId: "account:live" }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={badge} />);
    expect(getByText("Evidence status unavailable")).toBeInTheDocument();
    expect(getByText("This read did not provide a recognized evidence grade.")).toBeInTheDocument();
    expect(getByText("Amount unavailable from this preview read.")).toBeInTheDocument();
    expect(getByText("Exactness unavailable")).toBeInTheDocument();
    expect(getByText("Record identities were not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Measurement type was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Documents are not available in the current vault read.")).toBeInTheDocument();
    expect(getByText("Page or region was not supplied by this read.")).toBeInTheDocument();
    expect(queryByText("raw-secret-937.25")).not.toBeInTheDocument();
  });

  it("renders evidence with non-color meaning", () => {
    const { getByLabelText } = render(<EvidenceBadge grade="verified" label="Verified" description="Confirmed by review." />);
    expect(getByLabelText("Verified. Confirmed by review.")).toBeInTheDocument();
  });

  it("renders exact source disclosure", () => {
    const { getByRole, getByText } = render(<SourceDisclosure mode="demo" disclosure={sampleDisclosure} />);
    expect(getByRole("complementary", { name: "Vault source" })).toHaveClass("source-disclosure", "corpus-note");
    expect(getByText("Sample vault · Fictional sample data")).toBeInTheDocument();
    expect(getByText("Every name, document, and figure here is fictional.")).toBeInTheDocument();
  });

  it("renders the bounded private-vault source disclosure", () => {
    const disclosure: SurfaceSnapshot["disclosure"] = { title: "Private vault", subtitle: "Opened on this device", detail: "unused long disclosure" };
    const { getByText, queryByText } = render(<SourceDisclosure mode="live" disclosure={disclosure} />);
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
