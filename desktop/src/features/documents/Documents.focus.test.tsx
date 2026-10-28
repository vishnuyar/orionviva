import { fireEvent, render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Documents } from "./Documents";
import type { DocumentsData, DocumentDetailResolution, SurfaceDocument } from "../../surface/types";
const rows: SurfaceDocument[] = Array.from({ length: 50 }, (_, n) => ({ id: String(n), name: `statement-${n}.pdf`, state: "", phaseLabel: "", detail: "", source: "", pages: "", provenance: "", evidenceLinks: [], detailRequiresLookup: true }));
const data = (selectedDocument: DocumentDetailResolution): DocumentsData => ({ documents: rows, selectedDocument, readingSentence: "", captureQueue: [], processingJobs: [], outboundRecords: [] });
const base = { capture: null, rescan: null, onOpenEvidence: vi.fn(), onExploreSample: vi.fn(), onSelectDocument: vi.fn() };
it("waits for exact selected detail, focuses it, then returns to row50", () => {
 const view = render(<Documents {...base} selectedDocument="0" result={{ state: "ready", data: data({ state: "ready", id: "0", document: rows[0] }) }} />);
 const row = view.getByRole("button", { name: /statement-49.pdf/ }); row.focus(); fireEvent.click(row);
 view.rerender(<Documents {...base} selectedDocument="49" result={{ state: "ready", data: data({ state: "pending", id: "49", document: null }) }} />);
 expect(row).toHaveFocus();
 view.rerender(<Documents {...base} selectedDocument="49" result={{ state: "ready", data: data({ state: "ready", id: "49", document: rows[49] }) }} />);
 expect(view.getByRole("heading", { name: "statement-49.pdf" })).toHaveFocus();
 expect(view.getByRole("status")).toHaveTextContent("Selected statement: statement-49.pdf. Details are ready.");
 fireEvent.click(view.getByRole("button", { name: "Return to selected statement in list" })); expect(row).toHaveFocus();
});
it.each(["focus moved", "different document", "source preview"])("does not steal focus after %s", (boundary) => {
 const view = render(<><button>Another control</button><Documents {...base} selectedDocument="0" result={{ state: "ready", data: data({ state: "ready", id: "0", document: rows[0] }) }} /></>);
 const row = view.getByRole("button", { name: /statement-49.pdf/ }); row.focus(); fireEvent.click(row);
 if(boundary === "focus moved") view.getByRole("button", { name: "Another control" }).focus();
 const id = boundary === "different document" ? "1" : "49";
 view.rerender(<><button>Another control</button><Documents {...base} sourcePageRequest={boundary === "source preview" ? { documentId: "49", page: 2, nonce: 1 } : undefined} selectedDocument={id} result={{ state: "ready", data: data({ state: "ready", id, document: rows.find((row) => row.id === id)! }) }} /></>);
 expect(view.getByRole("heading", { name: `statement-${id}.pdf` })).not.toHaveFocus();
 expect(view.queryByRole("button", { name: "Return to selected statement in list" })).toBeNull();
});
it("focuses details after an explicit click on the already selected ready row", () => {
 const view = render(<Documents {...base} selectedDocument="49" result={{ state: "ready", data: data({ state: "ready", id: "49", document: rows[49] }) }} />);
 const row = view.getByRole("button", { name: /statement-49.pdf/ }); row.focus(); fireEvent.click(row);
 expect(view.getByRole("heading", { name: "statement-49.pdf" })).toHaveFocus();
 fireEvent.click(view.getByRole("button", { name: "Return to selected statement in list" })); expect(row).toHaveFocus();
});
