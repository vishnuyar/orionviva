import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentsData, FeatureResult, SurfaceDocument } from "../../surface/types";
import { Documents } from "./Documents";
import { lifecyclePresentation, resolveDocumentSelection, sampleLifecycle } from "./documentPresentation";

const document = (id: string, name = "sample.pdf"): SurfaceDocument => ({ id, name, state: "Sample", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [] });
const data = (documents: SurfaceDocument[]): DocumentsData => ({ documents, captureQueue: [], processingJobs: [], outboundRecords: [] });
const ready = (documents: SurfaceDocument[]): FeatureResult<DocumentsData> => ({ state: "ready", data: data(documents) });
const noAction = () => {};

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
    const { container, getByRole, getByText, getAllByText, queryByText, queryByRole } = render(<Documents result={ready(documents)} mode="demo" selectedDocument="document-captured" onSelectDocument={noAction} onOpenEvidence={openEvidence} onExploreSample={noAction} />);

    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByText("These are static fictional examples stored with the app. No file is selected, no vault event is written, no model call is made, nothing is sent, and no durable state changes.")).toBeInTheDocument();
    expect(getByRole("button", { name: "Choose a local file" })).toBeDisabled();
    expect(getByRole("button", { name: "Choose a local file" })).toHaveAccessibleDescription("File selection and drag-and-drop are not available in the fictional sample.");
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
    const injected = { ...document("live-document-identity", "MALICIOUS-FILENAME.pdf"), docType: "statement", resolved: true, rawAvailable: false, phase: "verified" as const, phaseLabel: "MALICIOUS-PHASE", detail: "MALICIOUS-DETAIL", source: "MALICIOUS-SOURCE", pages: "MALICIOUS-PAGES", provenance: "MALICIOUS-PROVENANCE", sample: { region: "MALICIOUS-REGION", contribution: "MALICIOUS-CONTRIBUTION", waitReason: "MALICIOUS-WAIT" }, evidenceLinks: [{ targetDocumentId: "hidden-target", label: "MALICIOUS-LINK", relation: "same_period" as const, page: "MALICIOUS-PAGE" }] };
    const { getByRole, getAllByText, getByText, queryByText } = render(<Documents result={ready([injected])} mode="live" selectedDocument="live-document-identity" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);

    expect(getByRole("heading", { name: "Document capture unavailable" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "What this read can show" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Documents in this vault read" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "statement" })).toBeInTheDocument();
    expect(getAllByText(/live-document-identity/).length).toBeGreaterThan(0);
    expect(getByText("Resolved", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    for (const leaked of ["MALICIOUS-FILENAME.pdf", "MALICIOUS-PHASE", "MALICIOUS-DETAIL", "MALICIOUS-SOURCE", "MALICIOUS-PAGES", "MALICIOUS-PROVENANCE", "MALICIOUS-REGION", "MALICIOUS-CONTRIBUTION", "MALICIOUS-WAIT", "MALICIOUS-LINK", "MALICIOUS-PAGE"]) expect(queryByText(leaked)).not.toBeInTheDocument();
  });

  it("keeps true, false, and missing live statuses explicit", () => {
    const documents = [
      { ...document("resolved"), docType: "statement", resolved: true, rawAvailable: true },
      { ...document("unresolved"), docType: "notice", resolved: false, rawAvailable: false },
      { ...document("missing") },
    ];
    const { getByText, rerender } = render(<Documents result={ready(documents)} mode="live" selectedDocument="resolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Available", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents result={ready(documents)} mode="live" selectedDocument="unresolved" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Unresolved", { selector: ".document-detail strong" })).toBeInTheDocument();
    expect(getByText("Unavailable", { selector: ".document-detail strong" })).toBeInTheDocument();
    rerender(<Documents result={ready(documents)} mode="live" selectedDocument="missing" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("Document type was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Resolution status was not supplied by this read.")).toBeInTheDocument();
    expect(getByText("Original availability was not supplied by this read.")).toBeInTheDocument();
  });

  it("renders missing and runtime-unknown sample lifecycle values without inference", () => {
    const missing = document("missing-phase", "missing-phase.pdf");
    const runtimeUnknown = { ...document("unknown-phase", "unknown-phase.pdf"), phase: "future-runtime-phase" as SurfaceDocument["phase"] };
    const { getAllByText, rerender } = render(<Documents result={ready([missing])} mode="demo" selectedDocument="missing-phase" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getAllByText("Lifecycle unavailable").length).toBeGreaterThan(0);
    expect(getAllByText("Lifecycle was not supplied by this fictional sample.").length).toBeGreaterThan(0);
    rerender(<Documents result={ready([runtimeUnknown])} mode="demo" selectedDocument="unknown-phase" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getAllByText("Lifecycle not recognized").length).toBeGreaterThan(0);
    expect(getAllByText("This fictional sample supplies a lifecycle value this preview does not recognize. No later step is implied.").length).toBeGreaterThan(0);
  });

  it("keeps every FeatureResult state bounded", () => {
    const props = { mode: "live" as const, selectedDocument: "", onSelectDocument: noAction, onOpenEvidence: noAction, onExploreSample: noAction };
    const { getByText, queryByText, rerender } = render(<Documents {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Document capture unavailable")).not.toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "unavailable", reason: "internal" }} />);
    expect(getByText("Document details are not available in this build.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("The documents section could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some document details are unavailable. Available documents are shown below.")).toBeInTheDocument();
    expect(getByText("Document capture unavailable")).toBeInTheDocument();
    rerender(<Documents {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some documents need review. Available document details are shown below.")).toBeInTheDocument();
    rerender(<Documents {...props} result={ready([])} />);
    expect(queryByText("Some documents need review. Available document details are shown below.")).not.toBeInTheDocument();
  });

  it("shows capture and honest empty states without a sample lifecycle", () => {
    const { getByRole, getByText, queryByRole, rerender } = render(<Documents result={ready([])} mode="demo" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByRole("heading", { name: "A sample document journey" })).toBeInTheDocument();
    expect(getByText("No sample documents")).toBeInTheDocument();
    expect(queryByRole("heading", { name: "Sample lifecycle" })).not.toBeInTheDocument();
    rerender(<Documents result={ready([])} mode="live" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("No documents yet")).toBeInTheDocument();
    expect(getByRole("button", { name: "Explore fictional sample data" })).toBeInTheDocument();
  });

  it("keeps blank, conflicted, and disappeared selections bounded", () => {
    const duplicate = [document("duplicate", "first.pdf"), document("duplicate", "second.pdf")];
    const { getByText, rerender } = render(<Documents result={ready(duplicate)} mode="demo" selectedDocument="duplicate" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("More than one document in this read uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
    rerender(<Documents result={ready([document("")])} mode="demo" selectedDocument="" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("This row has no stable document ID, so it cannot be selected.")).toBeInTheDocument();
    rerender(<Documents result={ready([document("present")])} mode="demo" selectedDocument="removed" onSelectDocument={noAction} onOpenEvidence={noAction} onExploreSample={noAction} />);
    expect(getByText("The selected document is no longer present in the current vault read.")).toBeInTheDocument();
  });
});
