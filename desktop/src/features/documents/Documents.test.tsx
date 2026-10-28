import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionResult, DocumentsData, FeatureResult, JobView, RescanActionState, RescanReport, SurfaceDocument } from "../../surface/types";
import { Documents } from "./Documents";
import type { CaptureControls, RescanControls } from "./Documents";
// The sentences a person is told, read from the pack that ships them. A test
// that types one out passes against words nobody shipped.
import moments from "../../../../product/viva/persona/pack-v31/moments.json";

const SAVED_NO_READER = moments.documents_saved_no_reader;
const ALREADY_HELD = moments.documents_already_held;
const TOO_LARGE = moments.documents_too_large.replace("{limit}", "a limit the reader owns");
import { documentRowLabel, resolveDocumentSelection } from "./documentPresentation";

const document = (id: string, name = "sample.pdf"): SurfaceDocument => ({ id, name, state: "Sample", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] });
const data = (documents: SurfaceDocument[], readingSentence = ""): DocumentsData => ({ documents, readingSentence, captureQueue: [], processingJobs: [], outboundRecords: [] });
const ready = (documents: SurfaceDocument[], readingSentence = ""): FeatureResult<DocumentsData> => ({ state: "ready", data: data(documents, readingSentence) });
const noAction = () => {};
// No job and no stop unless a test says so: a screen given nothing about a job
// must render nothing about one, which is the state every case below but the
// progress cases is in.
const quiet = { job: null, cancel: { state: "idle" } as const, onStop: null };
const idle = (onChoose: () => void = noAction): CaptureControls => ({ ...quiet, state: { state: "idle" }, onChoose });
const droppedOnly = (result: ActionResult): CaptureControls => ({ ...quiet, state: { state: "settled", result }, onChoose: null });
const working = (onChoose: () => void = noAction): CaptureControls => ({ ...quiet, state: { state: "working", result: null }, onChoose });
const settled = (message: string): CaptureControls => ({ ...quiet, state: { state: "settled", result: { state: "settled", outcome: { kind: "completed", message, reason: "" } } }, onChoose: noAction });
const reply = (result: ActionResult): CaptureControls => ({ ...quiet, state: { state: "settled", result }, onChoose: noAction });
const runningJob = (over: Partial<JobView> = {}): JobView => ({ jobId: "viva.documents.upload-1", operation: "viva.documents.upload", state: "running", completed: 1, total: 3, message: "", step: "checked", attempt: 1, steps: ["checked", "opened", "settled"], cancellable: true, ...over });

describe("document presentation", () => {

  it("names a row by the file the vault recorded, and by the kind where it recorded none", () => {
    expect(documentRowLabel(document("d", "everyday-checking.pdf"))).toBe("everyday-checking.pdf");
    expect(documentRowLabel({ ...document("d", ""), docType: "Bank statement" })).toBe("Bank statement");
    expect(documentRowLabel(document("d", ""))).toBe("Document type unavailable");
  });

  it("selects strictly by stable identity across reorder and duplicate names", () => {
    const documents = [document("document-a", "duplicate.pdf"), document("document-b", "duplicate.pdf")];
    expect(resolveDocumentSelection(documents, "document-b")).toMatchObject({ state: "ready", document: { id: "document-b" } });
    expect(resolveDocumentSelection([...documents].reverse(), "document-b")).toMatchObject({ state: "ready", document: { id: "document-b" } });
  });

  it("refuses blank, duplicate, and disappeared identities", () => {
    expect(resolveDocumentSelection([document(""), document("unique")], "")).toMatchObject({ state: "ready", document: { id: "unique" } });
    expect(resolveDocumentSelection([document("duplicate"), document("duplicate")], "duplicate")).toEqual({ state: "conflicted_identity" });
    expect(resolveDocumentSelection([document("duplicate"), document("duplicate")], "")).toEqual({ state: "empty" });
    expect(resolveDocumentSelection([document("")], "")).toEqual({ state: "empty" });
    expect(resolveDocumentSelection([document("present")], "missing")).toEqual({ state: "missing" });
  });
});

describe("Documents surface", () => {
  it("offers settings before capture without starting a read or hiding failed document state", () => {
    const onChoose = vi.fn();
    const onOpenSettings = vi.fn();
    const view = render(<Documents rescan={null} capture={idle(onChoose)} onOpenSettings={onOpenSettings} result={{ state: "failed", reason: "read_failed" }} selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    fireEvent.click(view.getByRole("button", { name: "Check document-reading settings" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(onChoose).not.toHaveBeenCalled();
    expect(view.getByText("Documents could not be read")).toBeVisible();
    expect(view.getByRole("button", { name: "Choose statement file" })).toBeVisible();
  });


  it("renders only the four returned live fields even when demo-shaped fields are injected", () => {
    const injected = { ...document("live-document-identity", "quarter-close.pdf"), docType: "statement", resolved: true, rawAvailable: false, phase: "verified" as const, phaseLabel: "MALICIOUS-PHASE", detail: "MALICIOUS-DETAIL", source: "MALICIOUS-SOURCE", pages: "MALICIOUS-PAGES", provenance: "MALICIOUS-PROVENANCE", sample: { region: "MALICIOUS-REGION", contribution: "MALICIOUS-CONTRIBUTION", waitReason: "MALICIOUS-WAIT" }, evidenceLinks: [{ targetDocumentId: "hidden-target", label: "MALICIOUS-LINK", relation: "same_period" as const, page: "MALICIOUS-PAGE" }] };
    const { getByRole, getAllByText, getByText, queryByText } = render(<Documents rescan={null} capture={null} result={ready([injected])} selectedDocument="live-document-identity" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);

    expect(queryByText("Document capture unavailable")).not.toBeInTheDocument();
    expect(getByText("What this page can show")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Your statements" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "quarter-close.pdf" })).toBeInTheDocument();
    expect(getAllByText(/live-document-identity/).length).toBeGreaterThan(0);
    expect(getByText("Resolved", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    for (const leaked of ["MALICIOUS-PHASE", "MALICIOUS-DETAIL", "MALICIOUS-SOURCE", "MALICIOUS-PAGES", "MALICIOUS-PROVENANCE", "MALICIOUS-REGION", "MALICIOUS-CONTRIBUTION", "MALICIOUS-WAIT", "MALICIOUS-LINK", "MALICIOUS-PAGE"]) expect(queryByText(leaked)).not.toBeInTheDocument();
  });

  it("keeps true, false, and missing live statuses explicit", () => {
    const documents = [
      { ...document("resolved"), docType: "statement", resolved: true, rawAvailable: true },
      { ...document("unresolved"), docType: "notice", resolved: false, rawAvailable: false },
      { ...document("missing") },
    ];
    const { getByText, rerender } = render(<Documents rescan={null} capture={null} result={ready(documents)} selectedDocument="resolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Available", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents rescan={null} capture={null} result={ready(documents)} selectedDocument="unresolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Unresolved", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents rescan={null} capture={null} result={ready(documents)} selectedDocument="missing" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Document type unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Resolution status unavailable")).toBeInTheDocument();
    expect(getByText("Original availability unavailable")).toBeInTheDocument();
  });


  it("keeps every FeatureResult state bounded", () => {
    const props = { rescan: null, selectedDocument: "", capture: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
    const { getByText, queryByText, rerender } = render(<Documents {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("What this page can show")).not.toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByText("Document details are not available in this build.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some document details are unavailable. Available documents are shown below.")).toBeInTheDocument();
    expect(getByText("What this page can show")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some documents need review. Available document details are shown below.")).toBeInTheDocument();
    rerender(<Documents {...props} result={ready([])} />);
    expect(queryByText("Some documents need review. Available document details are shown below.")).not.toBeInTheDocument();
  });


  it("keeps blank, conflicted, and disappeared selections bounded", () => {
    const duplicate = [document("duplicate", "first.pdf"), document("duplicate", "second.pdf")];
    const { getByText, rerender } = render(<Documents rescan={null} capture={null} result={ready(duplicate)} selectedDocument="duplicate" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("More than one document in this read uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    rerender(<Documents rescan={null} capture={null} result={ready([document("")])} selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("This row has no stable document ID, so it cannot be selected.")).toBeInTheDocument();
    rerender(<Documents rescan={null} capture={null} result={ready([document("present")])} selectedDocument="removed" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("The selected document is no longer present in the current vault read.")).toBeInTheDocument();
  });
});

describe("adding a document", () => {
  const props = { rescan: null, selectedDocument: "", onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };

  it("offers the chosen file as the only invitation, and never invites the gesture nobody could watch land", () => {
    const { container, getByRole, getByText } = render(<Documents {...props} capture={idle()} result={ready([])} />);
    expect(getByRole("heading", { name: "Add a statement" })).toBeInTheDocument();
    expect(getByText("Choose one statement or financial document. It is encrypted and saved in this vault on this machine.")).toBeInTheDocument();
    expect(getByRole("button", { name: "Choose statement file" })).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/drop|drag/i);
  });

  it("renders no capture control at all when nothing is behind one", () => {
    const { queryByRole } = render(<Documents {...props} capture={null} result={ready([])} />);
    expect(queryByRole("heading", { name: "Add a statement" })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: "Choose statement file" })).not.toBeInTheDocument();
  });

  it("keeps a busy control reachable, says why in words, and refuses the second press", () => {
    const choose = vi.fn();
    const { container, getByRole, getByText, rerender } = render(<Documents {...props} capture={idle(choose)} result={ready([])} />);
    const control = getByRole("button", { name: "Choose statement file" });
    fireEvent.click(control);
    expect(choose).toHaveBeenCalledTimes(1);

    rerender(<Documents {...props} capture={working(choose)} result={ready([])} />);
    expect(control).not.toHaveAttribute("disabled");
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect([...container.querySelectorAll("button:not([disabled])")]).toContain(control);
    expect(getByText("Your previous request is still running. Wait for its result before starting another.")).toBeInTheDocument();
    expect(control).toHaveAccessibleDescription("Your previous request is still running. Wait for its result before starting another.");

    fireEvent.click(control);
    expect(choose).toHaveBeenCalledTimes(1);
  });

  it("says what the vault answered in the vault's own words and writes none of its own", () => {
    const { getAllByText } = render(<Documents {...props} capture={settled(SAVED_NO_READER)} result={ready([])} />);
    expect(getAllByText(SAVED_NO_READER).length).toBeGreaterThan(0);
  });

  // Four channels, four sentences. A capture that was taken, one the vault
  // refused, one it never answered, and one whose reply could not be read all
  // put words in front of a person; none of them is a silence.
  it("puts a sentence on screen for every channel a reply can arrive through", () => {
    const channels: Array<[CaptureControls, string]> = [
      [settled(SAVED_NO_READER), SAVED_NO_READER],
      [reply({ state: "settled", outcome: { kind: "refused", message: TOO_LARGE, reason: "over_ceiling" } }), TOO_LARGE],
      [reply({ state: "settled", outcome: { kind: "completed", message: "", reason: "" } }), "Your vault recorded no sentence for this reply."],
      [reply({ state: "unserved" }), "Your vault refused the request as this screen sent it. Whether anything was recorded is not something this screen can tell you."],
      [reply({ state: "unanswered" }), "Nothing came back, so this screen will not say whether anything was recorded."],
      [reply({ state: "unreadable" }), "Your vault answered in a way this screen does not recognise, so it will not say whether anything was recorded."],
    ];
    for (const [capture, sentence] of channels) {
      const { getAllByText, getByRole, unmount } = render(<Documents {...props} capture={capture} result={ready([])} />);
      expect(getAllByText(sentence, { selector: "p" })).toHaveLength(1);
      expect(getByRole("status")).toHaveTextContent(sentence);
      unmount();
    }
  });


  it("says what a capture answered even when the read that followed it failed", () => {
    const { getAllByText, getByText } = render(<Documents {...props} capture={settled(SAVED_NO_READER)} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1);
    expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    expect(getByText("Choose statement file")).toBeInTheDocument();
  });

  it("keeps the one control this screen has when the read could not be made at all", () => {
    const { getByRole } = render(<Documents {...props} capture={idle()} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByRole("button", { name: "Choose statement file" })).toBeInTheDocument();
  });

  it("says one sentence at a time, the vault's answer standing in the slot the read's sentence would have had", () => {
    const panel = SAVED_NO_READER;
    const answer = ALREADY_HELD;
    const { container, getAllByText, queryByText } = render(<Documents {...props} capture={settled(answer)} result={ready([document("one", "one.pdf")], panel)} />);
    expect(getAllByText(answer, { selector: "p" })).toHaveLength(1);
    expect(queryByText(panel)).not.toBeInTheDocument();
    expect(container.querySelectorAll(".document-capture-answer p")).toHaveLength(1);
  });

  it("says what a dropped file became even where the host offers no picker", () => {
    const capture = droppedOnly({ state: "settled", outcome: { kind: "completed", message: SAVED_NO_READER, reason: "" } });
    const { getAllByText, queryByRole } = render(<Documents {...props} capture={capture} result={ready([])} />);
    expect(queryByRole("button", { name: "Choose statement file" })).not.toBeInTheDocument();
    expect(queryByRole("heading", { name: "Add a statement" })).not.toBeInTheDocument();
    expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1);
  });

  it("nests the capture answer where the stylesheet this cycle authored reaches it", () => {
    const { container } = render(<Documents {...props} capture={settled(SAVED_NO_READER)} result={ready([])} />);
    expect(container.querySelector(".documents-surface .document-capture-answer p")).not.toBeNull();
  });
});

describe("what this read says about reading", () => {
  const props = { rescan: null, selectedDocument: "", capture: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
  const sentence = SAVED_NO_READER;

  it("shows the panel sentence once, however many rows are never read", () => {
    const rows = ["one", "two", "three"].map((id) => ({ ...document(id, `${id}.pdf`), reading: "never_read" as const, docType: "statement" }));
    const { getAllByText } = render(<Documents {...props} result={ready(rows, sentence)} />);
    expect(getAllByText(sentence, { selector: "p" })).toHaveLength(1);
  });

  it("shows no panel sentence when the read wrote none", () => {
    const { queryByText } = render(<Documents {...props} result={ready([document("one", "one.pdf")], "")} />);
    expect(queryByText(sentence)).not.toBeInTheDocument();
  });

  it("labels a row by the name of the file, and by the kind of document when no name was recorded", () => {
    const named = { ...document("named", "quarter-close.pdf"), docType: "statement" };
    const unnamed = { ...document("unnamed", ""), docType: "statement" };
    const { container, getAllByText, getByText } = render(<Documents {...props} result={ready([named, unnamed])} />);
    // The name a row is labelled by is somewhere in the panel that row opens.
    // The panel's own heading is the kind of document, not the name.
    expect(container.querySelector(".document-library")).toHaveTextContent("quarter-close.pdf");
    expect(container.querySelector(".document-detail")).toHaveTextContent("quarter-close.pdf");
    expect(getAllByText("statement").length).toBeGreaterThan(0);
    expect(getByText("named")).toBeInTheDocument();
  });
});

describe("what the sidecar says it is doing", () => {
  const props = { rescan: null, selectedDocument: "", onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };

  it("says nothing about a job when the sidecar has said nothing", () => {
    const { queryByRole } = render(<Documents {...props} capture={idle()} result={ready([])} />);
    expect(queryByRole("heading", { name: "viva.documents.upload" })).not.toBeInTheDocument();
  });

  it("names the step the sidecar named and counts the steps the job declared", () => {
    const capture = { ...idle(), job: runningJob() };
    const { getByRole, getByText, queryByText } = render(<Documents {...props} capture={capture} result={ready([])} />);
    expect(getByRole("heading", { name: "Adding your statement" })).toBeInTheDocument();
    expect(queryByText("viva.documents.upload")).not.toBeInTheDocument();
    expect(getByText("Step 1 of 3 — checked")).toBeInTheDocument();
  });

  it("hides stale progress and blocks only duplicate job triggers until recheck", () => {
    const asked: string[] = [];
    const capture = { ...idle(), job: runningJob(), onChoose: () => asked.push("upload") };
    const rescan = { state: { state: "idle" as const }, onRescan: () => asked.push("rescan") };
    const { getByRole, queryByText } = render(<Documents {...props} capture={capture} rescan={rescan} jobStatus="unavailable" onRecheckJobs={() => asked.push("recheck")} result={ready([document("kept")])} />);
    const choose = getByRole("button", { name: "Choose statement file" });
    const look = getByRole("button", { name: "Check records", hidden: true });
    expect(choose).toHaveAttribute("aria-disabled", "true");
    expect(look).toHaveAttribute("aria-disabled", "true");
    expect(choose).toHaveAccessibleDescription(expect.stringContaining("Job status unavailable"));
    fireEvent.click(choose);
    fireEvent.click(look);
    fireEvent.click(getByRole("button", { name: "Recheck job status" }));
    expect(asked).toEqual(["recheck"]);
    expect(queryByText("Step 1 of 3 — checked")).not.toBeInTheDocument();
    expect(getByRole("button", { name: /sample\.pdf/i })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("keeps a repeated recheck focusable but inert while job status is checking", () => {
    const asked: string[] = [];
    const { getByRole } = render(<Documents {...props} capture={idle()} result={ready([])} jobStatus="unavailable" jobCheck="checking" onRecheckJobs={() => asked.push("recheck")} />);
    const recheck = getByRole("button", { name: "Recheck job status" });
    expect(recheck).toHaveAttribute("aria-disabled", "true");
    expect(recheck).toHaveAccessibleDescription("Checking job status…");
    fireEvent.click(recheck);
    expect(asked).toEqual([]);
  });

  it("offers a stop only while the sidecar says the job can still be stopped", () => {
    const stoppable = { ...idle(), job: runningJob(), onStop: noAction };
    const running = render(<Documents {...props} capture={stoppable} result={ready([])} />);
    expect(running.queryByRole("button", { name: "Stop" })).toBeInTheDocument();
    running.unmount();

    const over = { ...idle(), job: runningJob({ state: "completed" as const, completed: 3, cancellable: false }), onStop: noAction };
    const finished = render(<Documents {...props} capture={over} result={ready([])} />);
    expect(finished.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(finished.getByText("Finished at step 3 of 3")).toBeInTheDocument();
  });

  it("offers no stop where the source carries none, rather than one that would refuse", () => {
    const capture = { ...idle(), job: runningJob(), onStop: null };
    const { queryByRole } = render(<Documents {...props} capture={capture} result={ready([])} />);
    expect(queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
  });

  it("hands the stop the identity the sidecar minted, and nothing else", () => {
    const stopped: string[] = [];
    const capture = { ...idle(), job: runningJob(), onStop: (jobId: string) => stopped.push(jobId) };
    const { getByRole } = render(<Documents {...props} capture={capture} result={ready([])} />);
    fireEvent.click(getByRole("button", { name: "Stop" }));
    expect(stopped).toEqual(["viva.documents.upload-1"]);
  });

  it("says which attempt this is rather than restarting a bar with no word for why", () => {
    const capture = { ...idle(), job: runningJob({ attempt: 2, completed: 0, step: "" }) };
    const { getByText } = render(<Documents {...props} capture={capture} result={ready([])} />);
    expect(getByText("This is attempt 2. The earlier one did not finish.")).toBeInTheDocument();
  });

  it("keeps the stop in the tab order while the vault is answering it", () => {
    const capture = { ...idle(), job: runningJob(), onStop: noAction, cancel: { state: "working" as const, jobId: "viva.documents.upload-1" } };
    const { getByRole, getByText } = render(<Documents {...props} capture={capture} result={ready([])} />);
    expect(getByRole("button", { name: "Stop" })).toHaveAttribute("aria-disabled", "true");
    expect(getByText("Asking your vault to stop. What has already finished is kept.")).toBeInTheDocument();
  });
});

describe("going back over what is already here", () => {
  const props = { selectedDocument: "", capture: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
  const controls = (state: RescanActionState, onRescan = noAction): RescanControls => ({ state, onRescan });
  const report = (over: Partial<RescanReport> = {}): RescanReport => ({ sentence: moments.rescan_nothing, changes: [], standing: [], linkCount: 0, ...over });

  it("offers no control where the source cannot do it", () => {
    const { queryByRole } = render(<Documents {...props} rescan={null} result={ready([])} />);
    expect(queryByRole("button", { name: "Check records", hidden: true })).not.toBeInTheDocument();
  });

  it("asks the vault once when the control is pressed", () => {
    const asked: number[] = [];
    const { getByRole } = render(<Documents {...props} rescan={controls({ state: "idle" }, () => asked.push(1))} result={ready([])} />);
    fireEvent.click(getByRole("button", { name: "Check records", hidden: true }));
    expect(asked).toEqual([1]);
  });

  it("keeps the control in the tab order while the vault is answering", () => {
    const { getByRole } = render(<Documents {...props} rescan={controls({ state: "working" })} result={ready([])} />);
    expect(getByRole("button", { name: "Check records", hidden: true })).toHaveAttribute("aria-disabled", "true");
  });

  it("says the backend's own sentence for a pass that changed nothing", () => {
    const settled: RescanActionState = { state: "settled", result: { state: "settled", outcome: { kind: "completed", message: moments.rescan_nothing, reason: "" } }, report: report() };
    const { getAllByText } = render(<Documents {...props} rescan={controls(settled)} result={ready([])} />);
    expect(getAllByText(moments.rescan_nothing).length).toBeGreaterThan(0);
  });

  it("renders one line per change and composes none of them", () => {
    const changed = report({ sentence: moments.rescan_unread, changes: [{ id: "gaps", count: 2, sentence: "Two gaps were closed." }, { id: "auto", count: 1, sentence: "One pair was one transfer." }] });
    const settled: RescanActionState = { state: "settled", result: { state: "settled", outcome: { kind: "completed", message: moments.rescan_unread, reason: "" } }, report: changed };
    const { getByText } = render(<Documents {...props} rescan={controls(settled)} result={ready([])} />);
    expect(getByText("Two gaps were closed.")).toBeInTheDocument();
    expect(getByText("One pair was one transfer.")).toBeInTheDocument();
  });

  it("will not say what a pass did when the reply carried no report", () => {
    const settled: RescanActionState = { state: "settled", result: { state: "unanswered" }, report: null };
    const { getByText } = render(<Documents {...props} rescan={controls(settled)} result={ready([])} />);
    expect(getByText(/Nothing came back, so this screen will not say whether anything was recorded/)).toBeInTheDocument();
  });
});


describe("saved-original recovery", () => {
  it("requires an explicit gesture after cost and egress disclosure even without document rows", () => {
    const onRecoverDocument = vi.fn();
    const jobs = [runningJob({ state: "failed", recovery: { state: "available", message: "Saved original can be checked." } })];
    const view = render(<Documents result={{ state: "absent", reason: "not_read" }} selectedDocument="" capture={idle()} rescan={null} onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} recoveryJobs={jobs} onRecoverDocument={onRecoverDocument} />);
    expect(onRecoverDocument).not.toHaveBeenCalled();
    const button = view.getByRole("button", { name: /^Read saved original again/ });
    expect(button).toHaveAccessibleDescription(/may send it to that service, and may incur charges again/);
    fireEvent.click(button);
    expect(onRecoverDocument).toHaveBeenCalledWith(jobs[0].jobId);
  });

  it("retains refusal guidance and blocks recovery while job status is unavailable", () => {
    const onRecoverDocument = vi.fn();
    const jobs = [runningJob({ recovery: { state: "blocked", message: "Inspect the partial result." } })];
    const props = { result: ready([]), selectedDocument: "", capture: idle(), rescan: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction, recoveryJobs: jobs, onRecoverDocument };
    const view = render(<Documents {...props} />);
    expect(view.getByText("Inspect the partial result.")).toBeVisible();
    expect(view.queryByRole("button", { name: /^Read saved original again/ })).not.toBeInTheDocument();
    view.rerender(<Documents {...props} recoveryJobs={[runningJob({ recovery: { state: "available", message: "Check saved original." } })]} jobStatus="unavailable" />);
    fireEvent.click(view.getByRole("button", { name: /^Read saved original again/ }));
    expect(onRecoverDocument).not.toHaveBeenCalled();
  });
});


it("distinguishes interrupted imports visibly and accessibly and explains blocked controls", () => {
  const onRecoverDocument = vi.fn();
  const jobs = ["viva.documents.upload-1", "viva.documents.upload-2"].map((jobId) => runningJob({ jobId, state: "failed", recovery: { state: "available", message: "Saved original can be checked." } }));
  const props = { result: ready([]), selectedDocument: "", capture: { ...idle(), job: jobs[0] }, rescan: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction, recoveryJobs: jobs, onRecoverDocument };
  const view = render(<Documents {...props} />);
  expect(view.getAllByText(jobs[0].jobId)).toHaveLength(2);
  expect(view.getByText(jobs[1].jobId)).toBeVisible();
  const secondName = `Read saved original again — import ${jobs[1].jobId}`;
  fireEvent.click(view.getByRole("button", { name: secondName }));
  expect(onRecoverDocument).toHaveBeenCalledExactlyOnceWith(jobs[1].jobId);
  view.rerender(<Documents {...props} capture={{ ...working(), onChoose: null }} />);
  const waiting = view.getByRole("button", { name: secondName });
  expect(waiting).toHaveAttribute("aria-disabled", "true");
  expect(waiting).toHaveAccessibleDescription(/Your previous request is still running/);
  fireEvent.click(waiting);
  expect(onRecoverDocument).toHaveBeenCalledTimes(1);
  view.rerender(<Documents {...props} jobStatus="unavailable" />);
  const unavailable = view.getByRole("button", { name: secondName });
  expect(unavailable).toHaveAttribute("aria-disabled", "true");
  expect(unavailable).toHaveAccessibleDescription(/Job status unavailable/);
  expect(unavailable).toHaveAccessibleDescription(/may incur charges again/);
});

it.each(["blocked", "settled", "removed"] as const)("keeps a focused recovery outcome reachable when its action becomes %s", (outcome) => {
  const job = runningJob({ state: "failed", recovery: { state: "available", message: "Saved original can be checked." } });
  const props = { result: ready([]), selectedDocument: "", capture: idle(), rescan: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction, onRecoverDocument: noAction };
  const view = render(<Documents {...props} recoveryJobs={[job]} />);
  view.getByRole("button", { name: /^Read saved original again/ }).focus();
  const recoveryJobs = outcome === "removed" ? [] : [{ ...job, recovery: { state: outcome, message: "The saved original has been checked." } }];
  view.rerender(<Documents {...props} recoveryJobs={recoveryJobs} />);
  expect(outcome === "removed" ? view.getByRole("region", { name: "Statements" }) : view.getByRole("heading", { name: "Interrupted statements" })).toHaveFocus();
});

it("does not steal focus when the user leaves a recovery action before its outcome arrives", () => {
  const job = runningJob({ state: "failed", recovery: { state: "available", message: "Saved original can be checked." } });
  const props = { result: ready([]), selectedDocument: "", capture: idle(), rescan: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction, onRecoverDocument: noAction };
  const view = render(<Documents {...props} recoveryJobs={[job]} />);
  view.getByRole("button", { name: /^Read saved original again/ }).focus();
  const elsewhere = view.getByRole("button", { name: "Choose statement file" });
  elsewhere.focus();
  view.rerender(<Documents {...props} recoveryJobs={[]} />);
  expect(elsewhere).toHaveFocus();
});


describe("import journey and result", () => {
  const props = { rescan: null, selectedDocument: "", onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };

  it("uses indeterminate progress when no total is supplied", () => {
    const view = render(<Documents {...props} capture={{ ...idle(), job: runningJob({ total: 0, completed: 0, step: "" }) }} result={ready([])} />);
    expect(view.getByRole("progressbar")).not.toHaveAttribute("value");
    expect(view.queryByText(/Step 0 of 0/)).not.toBeInTheDocument();
    expect(view.getByText("Waiting for progress from your vault…")).toBeVisible();
  });

  it("offers Review only for a reported held result without guessing a document link", () => {
    const onOpenReview = vi.fn();
    const onSelectDocument = vi.fn();
    const capture = reply({ state: "settled", outcome: { kind: "completed", message: "Saved for review.", reason: "", terminalState: "held", reading: "read" } });
    const view = render(<Documents {...props} capture={capture} result={ready([document("unrelated")])} onOpenReview={onOpenReview} onSelectDocument={onSelectDocument} />);
    expect(view.getByRole("region", { name: "Import result" })).toHaveTextContent("Held for resolution");
    fireEvent.click(view.getByRole("button", { name: "Open Review" }));
    expect(onOpenReview).toHaveBeenCalledOnce();
    expect(onSelectDocument).not.toHaveBeenCalled();
    view.rerender(<Documents {...props} capture={settled("Saved original.")} result={ready([])} onOpenReview={onOpenReview} />);
    expect(view.queryByRole("button", { name: "Open Review" })).not.toBeInTheDocument();
  });

  it("keeps contribution and posting caveats visible while optional file metadata is collapsed", () => {
    const view = render(<Documents {...props} capture={null} result={ready([{ ...document("statement"), contribution: "No entries posted.", snapshotSentence: "Snapshot held until identity is resolved." }])} />);
    expect(view.getByText("No entries posted.")).toBeVisible();
    expect(view.getByText("Snapshot held until identity is resolved.")).toBeVisible();
    const fileDetails = view.getByText("File and source details").closest("details");
    expect(fileDetails).not.toHaveAttribute("open");
    expect(view.getByText("Original availability unavailable")).not.toBeVisible();
  });

  it("places record matching after the library behind an expandable control", () => {
    const view = render(<Documents {...props} capture={null} rescan={{ state: { state: "idle" }, onRescan: noAction }} result={ready([document("statement")])} />);
    const matching = view.getByText("Check for matching records").closest("details");
    expect(matching).not.toHaveAttribute("open");
    expect(view.getByRole("heading", { name: "Your statements" }).compareDocumentPosition(matching!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    fireEvent.click(view.getByText("Check for matching records"));
    expect(view.getByRole("button", { name: "Check records" })).toBeVisible();
  });
});

it("opens saved originals outside the narrow library and metadata columns", async () => {
  const read = vi.fn(async () => ({ status: "ready" as const, sourceKind: "text" as const, page: 1, pageCount: 1, text: "saved source marker", image: null, width: null, height: null }));
  const view = render(<Documents previewReader={read} rescan={null} capture={null} result={ready([document("a".repeat(64), "source.pdf")])} selectedDocument={"a".repeat(64)} onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
  const trigger = view.getByRole("button", { name: "View saved original" });
  expect(trigger.closest(".document-library-layout")).toBeNull();
  expect(read).not.toHaveBeenCalled(); fireEvent.click(trigger);
  expect(await view.findByText("saved source marker")).toBeInTheDocument();
  expect(view.getByRole("heading", { name: "Saved original: source.pdf" })).toHaveFocus();
});

it("shows accepted and held sections separately and opens the explicitly selected source page", () => {
  const id = "d".repeat(64);
  const doc = { ...document(id, "mortgage.pdf"), resolved: false, componentStatuses: [
    { component: "mortgage_terms", kind: "mortgage_terms", label: "Mortgage contract terms", disposition: "accepted" as const, reasonCode: "accepted", reason: "Terms passed applicable checks.", sourcePages: [{ documentId: id, page: 1, label: "Terms source page 1" }] },
    { component: "payment:PAY-A", kind: "payment", label: "Payment PAY-A", disposition: "held" as const, reasonCode: "unmatched_counterpart", reason: "A unique compatible counterpart source has not been established.", sourcePages: [{ documentId: id, page: 2, label: "Payment source page 2" }] },
  ] };
  const preview = vi.fn(async () => ({ status: "unavailable" as const, reason: "original_unavailable" as const }));
  const review = vi.fn();
  const view = render(<Documents result={ready([doc])} selectedDocument={id} capture={null} rescan={null} onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} previewReader={preview} onOpenReview={review} />);
  expect(view.getByText("Accepted section")).toBeInTheDocument();
  expect(view.getByText("Needs review")).toBeInTheDocument();
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(view.getByRole("button", { name: "Payment source page 2" }));
  expect(preview).toHaveBeenCalledWith(id, 2);
  fireEvent.click(view.getByRole("button", { name: "Review unresolved source sections" }));
  expect(review).toHaveBeenCalledOnce();
});

it("requires independent detail for a versioned in-page summary", () => {
  const row = { ...document("a".repeat(64)), detailRequiresLookup: true };
  expect(resolveDocumentSelection([row], row.id)).toEqual({ state: "pending" });
  expect(resolveDocumentSelection([row], "")).toEqual({ state: "pending" });
  expect(resolveDocumentSelection([row], row.id, { state: "unavailable", id: row.id, document: null })).toEqual({ state: "unavailable" });
});

describe("saved original new-reading confirmation", () => {
 const doc = { ...document("a".repeat(64), "retained.pdf"), retry: { state: "available" as const, reason: "new_reading_available" as const, confirmationToken: "opaque-hidden" } };
 const props = { rescan: null, capture: null, selectedDocument: doc.id, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
 function supported() { return { state: "ready" as const, data: { ...data([doc]), retainedReadingVersion: "retained-reading-v1" as const, selectedDocument: { state: "ready" as const, reason: null, document: doc } } }; }
 function controls() { return { selection: [{ documentId: doc.id, name: doc.name, reason: "new_reading_available" as const, confirmationToken: "opaque-hidden" }], blocked: false, canSelect: () => true, onAdd: vi.fn(), onRemove: vi.fn(), onConfirm: vi.fn() }; }
 it("discloses exact identities and additional cost, keeps selection separate from explicit confirmation, and hides tokens", () => {
  const retained = controls(); const view = render(<Documents {...props} retained={{ ...retained, selection: [] }} result={supported()} />);
  expect(view.getByText(/may charge again/)).toBeVisible(); expect(view.queryByText(/opaque-hidden/)).toBeNull();
  expect(view.getAllByText(doc.id).length).toBeGreaterThan(0); expect(retained.onConfirm).not.toHaveBeenCalled();
  fireEvent.click(view.getByRole("button", { name: "Select saved original for a new reading" })); expect(retained.onAdd).toHaveBeenCalledWith(doc); expect(retained.onConfirm).not.toHaveBeenCalled();
  view.rerender(<Documents {...props} retained={retained} result={supported()} />);
  fireEvent.click(view.getByRole("button", { name: "Read these saved originals again" })); expect(retained.onConfirm).toHaveBeenCalledOnce();
  fireEvent.click(view.getByRole("button", { name: /Remove retained.pdf/ })); expect(retained.onRemove).toHaveBeenCalledWith(doc.id);
 });
 it("hides the new action on old hosts and refuses confirmation when unavailable", () => {
  const retained = controls(); const view = render(<Documents {...props} retained={retained} result={ready([doc])} />);
  expect(view.queryByRole("button", { name: "Read these saved originals again" })).toBeNull(); expect(view.queryByRole("button", { name: "Select saved original for a new reading" })).toBeNull();
  view.rerender(<Documents {...props} retained={{ ...retained, blocked: true }} result={supported()} />);
  const confirm = view.getByRole("button", { name: "Read these saved originals again" }); expect(confirm).toHaveAttribute("aria-disabled", "true"); fireEvent.click(confirm); expect(retained.onConfirm).not.toHaveBeenCalled();
 });
 it.each(["selected", "full", "blocked", "consumed"] as const)("explains the actual local %s selection restriction beside its inert control", (state) => {
  const retained = controls();
  const selection = state === "selected" ? retained.selection : state === "full" ? ["b", "c", "d"].map((letter) => ({ ...retained.selection[0], documentId: letter.repeat(64), name: `${letter}.pdf`, confirmationToken: `token-${letter}` })) : [];
  const view = render(<Documents {...props} retained={{ ...retained, selection, blocked: state === "blocked", canSelect: () => false }} result={supported()} />);
  const availability = within(view.getByRole("region", { name: "Saved original reading availability" }));
  const select = availability.getByRole("button", { name: "Select saved original for a new reading" });
  const reason = availability.getByRole("status");
  expect(select).toHaveAttribute("aria-describedby", reason.id); expect(select).toHaveAttribute("aria-disabled", "true");
  expect(reason).not.toHaveTextContent("Available for a new paid reading");
  expect(reason).toHaveTextContent(state === "selected" ? /already selected/ : state === "full" ? /Three saved originals are already selected/ : state === "blocked" ? /temporarily unavailable/ : /refresh this document.s details/);
  fireEvent.click(select); expect(retained.onAdd).not.toHaveBeenCalled(); expect(retained.onConfirm).not.toHaveBeenCalled();
 });
 it("offers the next keyboard control as a deliberate route to review selection and cost without starting a reading", () => {
  const retained = controls(); const view = render(<Documents {...props} retained={{ ...retained, selection: [] }} result={supported()} />);
  const select = view.getByRole("button", { name: "Select saved original for a new reading" }); select.focus(); fireEvent.click(select);
  expect(retained.onAdd).toHaveBeenCalledOnce(); expect(retained.onConfirm).not.toHaveBeenCalled();
  view.rerender(<Documents {...props} retained={{ ...retained, canSelect: () => false }} result={supported()} />);
  const region = within(view.getByRole("region", { name: "Saved original reading availability" }));
  const route = region.getByRole("button", { name: "Review selection and reading cost" });
  expect(region.getAllByRole("button")).toEqual([select, route]); expect(select).toHaveFocus();
  const heading = view.getByRole("heading", { name: "Select saved originals for a new reading" }); heading.scrollIntoView = vi.fn();
  route.focus(); fireEvent.click(route); expect(heading).toHaveFocus(); expect(heading.scrollIntoView).toHaveBeenCalledWith({ block: "start" });
  expect(retained.onConfirm).not.toHaveBeenCalled(); expect(retained.onAdd).toHaveBeenCalledOnce();
 });
 it("returns focus from a removed selection to the stable confirmation heading", () => {
  const retained = controls(); const view = render(<Documents {...props} retained={retained} result={supported()} />);
  const remove = view.getByRole("button", { name: /Remove retained.pdf/ }); remove.focus(); fireEvent.click(remove);
  view.rerender(<Documents {...props} retained={{ ...retained, selection: [] }} result={supported()} />);
  expect(view.getByRole("heading", { name: "Select saved originals for a new reading" })).toHaveFocus();
 });
});
