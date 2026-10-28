import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BulkDocumentSelection } from "./BulkDocumentSelection";
import type { BulkDocumentSession } from "../../surface/types";

describe("bulk selection presentation", () => {
  it("paginates 794 session rows without replacing completed results with job registry history", () => {
    const session: BulkDocumentSession = { state: "finished", jobIds: ["recent-1"], rows: Array.from({ length: 794 }, (_, i) => ({ path: `/selected/document-${i}.pdf`, status: i === 0 ? "awaiting" : "posted" })) };
    render(<BulkDocumentSelection controls={{ session, working: false, onChoose: vi.fn(), onStop: vi.fn() }} unavailable={false} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(25); expect(screen.getByText("Held: awaiting counterpart")).toBeVisible();
    for (let i = 0; i < 31; i++) fireEvent.click(screen.getByRole("button", { name: "Next selection page" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(19); expect(screen.getByText("document-793.pdf")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next selection page" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText(/Closing it loses unstarted selections/)).toBeVisible();
  });
  it("keeps choosing focusable while busy and announces stopping until active reads finish", () => {
    const choose = vi.fn(), stop = vi.fn();
    render(<BulkDocumentSelection controls={{ session: { state: "stopping", rows: [{ path: "/active.pdf", status: "working" }], jobIds: [] }, working: true, onChoose: choose, onStop: stop }} unavailable={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose multiple documents" })); fireEvent.click(screen.getByRole("button", { name: "Stop remaining documents" }));
    expect(choose).not.toHaveBeenCalled(); expect(stop).not.toHaveBeenCalled();
    expect(screen.getByRole("status", { name: "Document selection progress" })).toHaveTextContent("Stopping; finishing active reads");
    expect(screen.getByRole("button", { name: "Choose multiple documents" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Choose multiple documents" })).not.toHaveAttribute("disabled");
  });
  it("shows uncertainty without claiming an uncaptured file was saved", () => {
    render(<BulkDocumentSelection controls={{ session: { state: "uncertain", rows: [{ path: "/maybe.pdf", status: "uncertain" }, { path: "/later.pdf", status: "not_started" }], jobIds: [] }, working: false, onChoose: vi.fn(), onStop: vi.fn() }} unavailable={false} />);
    expect(screen.getByRole("status", { name: "Document selection progress" })).toHaveTextContent("outcome is unknown");
    expect(screen.getByText("Outcome unknown")).toBeVisible(); expect(screen.queryByText(/Saved original:/)).toBeNull();
    expect(screen.getByText("Not started; reselect to submit")).toBeVisible();
  });
  it.each(["finished", "uncertain"] as const)("returns focused Stop to progress when work becomes %s", (state) => {
    const controls = { session: { state: "running" as const, rows: [{ path: "/active.pdf", status: "working" as const }], jobIds: [] }, working: true, onChoose: vi.fn(), onStop: vi.fn() };
    const view = render(<BulkDocumentSelection controls={controls} unavailable={false} />);
    screen.getByRole("button", { name: "Stop remaining documents" }).focus();
    view.rerender(<BulkDocumentSelection controls={{ ...controls, session: { ...controls.session, state }, working: false }} unavailable={false} />);
    expect(screen.getByRole("status", { name: "Document selection progress" })).toHaveFocus();
  });
  it("keeps a person's other focus when Stop disappears", () => {
    const controls = { session: { state: "running" as const, rows: [], jobIds: [] }, working: true, onChoose: vi.fn(), onStop: vi.fn() };
    const view = render(<BulkDocumentSelection controls={controls} unavailable={false} />);
    const choose = screen.getByRole("button", { name: "Choose multiple documents" }); choose.focus();
    view.rerender(<BulkDocumentSelection controls={{ ...controls, session: { ...controls.session, state: "finished" }, working: false }} unavailable={false} />);
    expect(choose).toHaveFocus();
  });
  it("announces selected page range while retaining the navigation focus", () => {
    render(<BulkDocumentSelection controls={{ session: { state: "finished", rows: Array.from({ length: 30 }, (_, i) => ({ path: `/file-${i}.pdf`, status: "posted" })), jobIds: [] }, working: false, onChoose: vi.fn(), onStop: vi.fn() }} unavailable={false} />);
    const next = screen.getByRole("button", { name: "Next selection page" }); next.focus(); fireEvent.click(next);
    expect(next).toHaveFocus(); const range = screen.getByRole("status", { name: "Selected document page" }); expect(range).toHaveTextContent("Selection rows 26–30 of 30"); expect(range).toHaveAttribute("aria-live", "polite");
  });
  it("explains a refused selection without displaying arbitrary transport messages", () => {
    render(<BulkDocumentSelection controls={{ session: { state: "finished", rows: [{ path: "/file.pdf", status: "refused" }], jobIds: [] }, working: false, onChoose: vi.fn(), onStop: vi.fn() }} unavailable={false} />);
    expect(screen.getByText(/could not accept this selection request/)).toBeVisible(); expect(screen.getByText(/Nothing was retried automatically/)).toBeVisible();
    expect(screen.getByRole("status", { name: "Document selection progress" })).toHaveTextContent("1 terminal result of 1 selected document");
  });

});

it("uses retained-reading progress and identity without claiming another upload", () => {
 const controls = { session: { mode: "retained" as const, state: "running" as const, rows: [{ path: "retained.pdf", documentId: "a".repeat(64), status: "working" as const }], jobIds: [] }, working: true, onChoose: vi.fn(), onStop: vi.fn() };
 const view = render(<BulkDocumentSelection controls={controls} unavailable={false} />);
 expect(screen.getByRole("heading", { name: "Read saved originals again" })).toBeVisible(); expect(screen.getByText("a".repeat(64))).toBeVisible();
 const stop = screen.getByRole("button", { name: "Stop remaining readings" }); stop.focus();
 view.rerender(<BulkDocumentSelection controls={{ ...controls, session: { ...controls.session, state: "uncertain" }, working: false }} unavailable={false} />);
 expect(screen.getByRole("status", { name: "Document selection progress" })).toHaveFocus(); expect(screen.getByText(/outcome is unknown/)).toBeVisible();
});
