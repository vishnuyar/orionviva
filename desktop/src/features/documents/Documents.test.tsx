import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActionResult, DocumentsData, FeatureResult, SurfaceDocument } from "../../surface/types";
import { Documents } from "./Documents";
import type { CaptureControls } from "./Documents";
// The sentences a person is told, read from the pack that ships them. A test
// that types one out passes against words nobody shipped.
import moments from "../../../../product/viva/persona/pack-v19/moments.json";

const SAVED_NO_READER = moments.documents_saved_no_reader;
const ALREADY_HELD = moments.documents_already_held;
const TOO_LARGE = moments.documents_too_large.replace("{limit}", "a limit the reader owns");
import { lifecyclePresentation, resolveDocumentSelection, sampleLifecycle } from "./documentPresentation";

const document = (id: string, name = "sample.pdf"): SurfaceDocument => ({ id, name, state: "Sample", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] });
const data = (documents: SurfaceDocument[], readingSentence = ""): DocumentsData => ({ documents, readingSentence, captureQueue: [], processingJobs: [], outboundRecords: [] });
const ready = (documents: SurfaceDocument[], readingSentence = ""): FeatureResult<DocumentsData> => ({ state: "ready", data: data(documents, readingSentence) });
const noAction = () => {};
const idle = (onChoose: () => void = noAction): CaptureControls => ({ state: { state: "idle" }, onChoose });
const droppedOnly = (result: ActionResult): CaptureControls => ({ state: { state: "settled", result }, onChoose: null });
const working = (onChoose: () => void = noAction): CaptureControls => ({ state: { state: "working", result: null }, onChoose });
const settled = (message: string): CaptureControls => ({ state: { state: "settled", result: { state: "settled", outcome: { kind: "completed", message, reason: "" } } }, onChoose: noAction });
const reply = (result: ActionResult): CaptureControls => ({ state: { state: "settled", result }, onChoose: noAction });

describe("document presentation", () => {
  it("maps every reviewed sample lifecycle without implying progression", () => {
    expect(sampleLifecycle.map((item) => lifecyclePresentation(item.phase))).toEqual(sampleLifecycle.map((item) => ({ state: "ready", title: item.title, detail: item.detail })));
  });

  it("keeps missing and unknown lifecycle values explicit", () => {
    expect(lifecyclePresentation(undefined)).toEqual({ state: "missing", title: "Lifecycle unavailable", detail: "Lifecycle was not supplied by this fictional sample." });
    expect(lifecyclePresentation("future-runtime-phase")).toEqual({ state: "unrecognized", title: "Lifecycle not recognized", detail: "This fictional sample supplies a lifecycle value this preview does not recognize. No later step is implied." });
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
  it("renders the static sample lifecycle, capture boundary, library before detail, and no legacy jobs", () => {
    const documents = sampleLifecycle.map((item) => ({ ...document(`document-${item.phase}`, `${item.phase}.pdf`), phase: item.phase, phaseLabel: item.title, evidenceLinks: item.phase === "captured" ? [{ targetDocumentId: "document-verified", label: "Verified sample", relation: "corroborates" as const, page: "page 1" }] : [] }));
    const openEvidence = vi.fn();
    const { container, getByRole, getByText, getAllByText, queryByText, queryByRole } = render(<Documents capture={null} result={ready(documents)} mode="demo" selectedDocument="document-captured" onSelectDocument={noAction} onOpenEvidence={openEvidence} onExploreSample={noAction} />);

    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByText("These are static fictional examples stored with the app. No file is selected, no vault event is written, no model call is made, nothing is sent, and no durable state changes.")).toBeInTheDocument();
    expect(queryByRole("button", { name: /choose a/i })).not.toBeInTheDocument();
    expect(getByText("Nothing is added to a vault from the fictional sample.")).toBeInTheDocument();
    for (const item of sampleLifecycle) expect(getAllByText(item.title).length).toBeGreaterThan(0);
    expect(getByText("These labels describe distinct states. They do not imply that one starts the next. Ledger posting and outbound transmission are separate unavailable actions.")).toBeInTheDocument();
    expect(queryByText("Capture queue")).not.toBeInTheDocument();
    expect(queryByText("Processing and recovery")).not.toBeInTheDocument();
    expect(queryByText("Outbound records")).not.toBeInTheDocument();
    expect(queryByRole("textbox")).not.toBeInTheDocument();
    const library = container.querySelector(".document-library");
    const detail = container.querySelector(".document-detail");
    expect(library).not.toBeNull();
    expect(detail).not.toBeNull();
    expect((library as Element).compareDocumentPosition(detail as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(getByRole("button", { name: /Verified sample.*page 1/i }));
    expect(openEvidence).toHaveBeenCalledWith(documents[0].evidenceLinks[0]);
  });

  it("renders only the four returned live fields even when demo-shaped fields are injected", () => {
    const injected = { ...document("live-document-identity", "quarter-close.pdf"), docType: "statement", resolved: true, rawAvailable: false, phase: "verified" as const, phaseLabel: "MALICIOUS-PHASE", detail: "MALICIOUS-DETAIL", source: "MALICIOUS-SOURCE", pages: "MALICIOUS-PAGES", provenance: "MALICIOUS-PROVENANCE", sample: { region: "MALICIOUS-REGION", contribution: "MALICIOUS-CONTRIBUTION", waitReason: "MALICIOUS-WAIT" }, evidenceLinks: [{ targetDocumentId: "hidden-target", label: "MALICIOUS-LINK", relation: "same_period" as const, page: "MALICIOUS-PAGE" }] };
    const { getByRole, getAllByText, getByText, queryByText } = render(<Documents capture={null} result={ready([injected])} mode="live" selectedDocument="live-document-identity" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);

    expect(queryByText("Document capture unavailable")).not.toBeInTheDocument();
    expect(getByRole("heading", { name: "What this read can show" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "statement" })).toBeInTheDocument();
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
    const { getByText, rerender } = render(<Documents capture={null} result={ready(documents)} mode="live" selectedDocument="resolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Available", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents capture={null} result={ready(documents)} mode="live" selectedDocument="unresolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Unresolved", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents capture={null} result={ready(documents)} mode="live" selectedDocument="missing" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Document type was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Resolution status was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Original availability was not supplied by this read.")).toBeInTheDocument();
  });

  it("renders missing and runtime-unknown sample lifecycle values without inference", () => {
    const missing = document("missing-phase", "missing-phase.pdf");
    const runtimeUnknown = { ...document("unknown-phase", "unknown-phase.pdf"), phase: "future-runtime-phase" as SurfaceDocument["phase"] };
    const { getAllByText, rerender } = render(<Documents capture={null} result={ready([missing])} mode="demo" selectedDocument="missing-phase" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getAllByText("Lifecycle unavailable").length).toBeGreaterThan(0);
    expect(getAllByText("Lifecycle was not supplied by this fictional sample.").length).toBeGreaterThan(0);
    rerender(<Documents capture={null} result={ready([runtimeUnknown])} mode="demo" selectedDocument="unknown-phase" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getAllByText("Lifecycle not recognized").length).toBeGreaterThan(0);
    expect(getAllByText("This fictional sample supplies a lifecycle value this preview does not recognize. No later step is implied.").length).toBeGreaterThan(0);
  });

  it("keeps every FeatureResult state bounded", () => {
    const props = { mode: "live" as const, selectedDocument: "", capture: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
    const { getByText, queryByText, rerender } = render(<Documents {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("What this read can show")).not.toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByText("Document details are not available in this build.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some document details are unavailable. Available documents are shown below.")).toBeInTheDocument();
    expect(getByText("What this read can show")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some documents need review. Available document details are shown below.")).toBeInTheDocument();
    rerender(<Documents {...props} result={ready([])} />);
    expect(queryByText("Some documents need review. Available document details are shown below.")).not.toBeInTheDocument();
  });

  it("shows capture and honest empty states without a sample lifecycle", () => {
    const { getByRole, getByText, queryByRole, rerender } = render(<Documents capture={null} result={ready([])} mode="demo" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByText("No sample documents")).toBeInTheDocument();
    expect(queryByRole("heading", { name: "Sample lifecycle" })).not.toBeInTheDocument();
    rerender(<Documents capture={null} result={ready([])} mode="live" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("No documents yet")).toBeInTheDocument();
    expect(getByText("Nothing has been added to this vault yet. Choose a file to add one.")).toBeInTheDocument();
    expect(getByRole("button", { name: "Explore fictional sample data" })).toBeInTheDocument();
  });

  it("keeps blank, conflicted, and disappeared selections bounded", () => {
    const duplicate = [document("duplicate", "first.pdf"), document("duplicate", "second.pdf")];
    const { getByText, rerender } = render(<Documents capture={null} result={ready(duplicate)} mode="demo" selectedDocument="duplicate" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("More than one document in this read uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    rerender(<Documents capture={null} result={ready([document("")])} mode="demo" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("This row has no stable document ID, so it cannot be selected.")).toBeInTheDocument();
    rerender(<Documents capture={null} result={ready([document("present")])} mode="demo" selectedDocument="removed" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("The selected document is no longer present in the current vault read.")).toBeInTheDocument();
  });
});

describe("adding a document", () => {
  const props = { mode: "live" as const, selectedDocument: "", onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };

  it("offers the chosen file as the only invitation, and never invites the gesture nobody could watch land", () => {
    const { container, getByRole, getByText } = render(<Documents {...props} capture={idle()} result={ready([])} />);
    expect(getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    expect(getByText("Choose a file and it is saved into this vault, encrypted, on this machine. It is not sent anywhere.")).toBeInTheDocument();
    expect(getByRole("button", { name: "Choose a file" })).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/drop|drag/i);
  });

  it("renders no capture control at all when nothing is behind one", () => {
    const { queryByRole } = render(<Documents {...props} capture={null} result={ready([])} />);
    expect(queryByRole("heading", { name: "Add a document" })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: "Choose a file" })).not.toBeInTheDocument();
  });

  it("keeps a busy control reachable, says why in words, and refuses the second press", () => {
    const choose = vi.fn();
    const { container, getByRole, getByText, rerender } = render(<Documents {...props} capture={idle(choose)} result={ready([])} />);
    const control = getByRole("button", { name: "Choose a file" });
    fireEvent.click(control);
    expect(choose).toHaveBeenCalledTimes(1);

    rerender(<Documents {...props} capture={working(choose)} result={ready([])} />);
    expect(control).not.toHaveAttribute("disabled");
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect([...container.querySelectorAll("button:not([disabled])")]).toContain(control);
    expect(getByText("Your vault is answering the last request. Pressing again does nothing until it has.")).toBeInTheDocument();
    expect(control).toHaveAccessibleDescription("Your vault is answering the last request. Pressing again does nothing until it has.");

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
    expect(getByText("Choose a file")).toBeInTheDocument();
  });

  it("keeps the one control this screen has when the read could not be made at all", () => {
    const { getByRole } = render(<Documents {...props} capture={idle()} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByRole("button", { name: "Choose a file" })).toBeInTheDocument();
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
    expect(queryByRole("button", { name: "Choose a file" })).not.toBeInTheDocument();
    expect(queryByRole("heading", { name: "Add a document" })).not.toBeInTheDocument();
    expect(getAllByText(SAVED_NO_READER, { selector: "p" })).toHaveLength(1);
  });

  it("nests the capture answer where the stylesheet this cycle authored reaches it", () => {
    const { container } = render(<Documents {...props} capture={settled(SAVED_NO_READER)} result={ready([])} />);
    expect(container.querySelector(".documents-surface .document-capture-answer p")).not.toBeNull();
  });
});

describe("what this read says about reading", () => {
  const props = { mode: "live" as const, selectedDocument: "", capture: null, onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
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
    expect(getByText("Document ID · named")).toBeInTheDocument();
  });
});
