import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ActivityData, ActivityView, FeatureResult, MovementView, SampleActivityFilterCatalog } from "../../surface/types";
import { Activity } from "./Activity";
import moments from "../../../../product/viva/persona/pack-v29/moments.json";

const item = (id: string, overrides: Partial<ActivityView> = {}): ActivityView => ({ id, label: "Returned movement", exactValue: "101.25", display: "Canonical display", measure: "income", detail: "Returned detail", tone: "inflow", state: "ready", provenance: "Returned provenance", evidenceLinks: [], grade: "not_applicable", recordIds: ["record-returned"], ...overrides });
const filters: SampleActivityFilterCatalog = {
  dates: [{ id: "date-one", label: "Date one" }], accounts: [{ id: "account-one", label: "Account one" }], merchants: [{ id: "merchant-one", label: "Merchant one" }], categories: [{ id: "category-one", label: "Category one" }], tags: [{ id: "tag-one", label: "Tag one" }], natures: [{ id: "nature-one", label: "Nature one" }], directions: [{ id: "direction-one", label: "Direction one" }],
};
const sample = (id: string, overrides: Partial<ActivityView> = {}): ActivityView => item(id, { label: `Sample ${id}`, sample: { date: filters.dates[0], account: filters.accounts[0], merchant: filters.merchants[0], category: filters.categories[0], tags: [filters.tags[0]], nature: filters.natures[0], direction: filters.directions[0] }, ...overrides });
const data = (items: ActivityView[], includeFilters = true): ActivityData => ({ items, sample: includeFilters ? { filters } : undefined });
const ready = (value: ActivityData): FeatureResult<ActivityData> => ({ state: "ready", data: value });
// A live read: its own rows, its own sentence, and no sample shape at all.
const movement = (over: Partial<MovementView> = {}): MovementView => ({ id: "m1", date: "2026-07-01", description: "a shop", account: "acct:one", direction: "out", exactValue: "10.00", currency: "USD", display: "USD 10.00", nature: "spending", sentence: "", decidedBy: "default", provisional: false, linked: false, ...over });
const live = (movements: MovementView[]): ActivityData => ({ items: [], sentence: movements.length ? moments.activity_scope : moments.activity_empty, movements, beyond: { count: 0 } });
const noAction = () => {};

function captureAnimationFrames() {
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
  const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
  const callbacks: FrameRequestCallback[] = [];
  globalThis.requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => { callbacks.push(callback); return callbacks.length; });
  globalThis.cancelAnimationFrame = vi.fn();
  return {
    callbacks,
    restore() {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
      globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    },
  };
}

function relatedSamplePair() {
  const incoming = sample("incoming", { label: "Incoming sample" });
  const outgoing = sample("outgoing", { label: "Outgoing sample", sample: { ...sample("base").sample, relationships: [{ targetActivityId: "incoming", label: "Incoming sample" }] } });
  return { incoming, outgoing };
}

describe("Activity surface", () => {
  it("renders all six FeatureResult states and honest empty modes", () => {
    const props = { mode: "live" as const, onOpenEvidence: noAction, onOpenFigure: noAction };
    const { getByText, queryByText, rerender } = render(<Activity {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Activity unavailable")).not.toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "unavailable", reason: "not_connected" }} />);
    expect(getByText("Activity is not connected to this private-vault read.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("Activity could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "partial", data: data([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some activity details are unavailable. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "needs_input", data: data([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some activity details need more information. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={ready(live([]))} />);
    // A live read composes its own sentence about knowing of nothing that
    // moved, and it is not the same as nothing having moved.
    expect(getByText(moments.activity_empty, { selector: "span" })).toBeInTheDocument();
    rerender(<Activity {...props} mode="demo" result={ready(data([]))} />);
    expect(getByText("No sample activity")).toBeInTheDocument();
  });

  it("renders a live read from its own rows and never from the sample shape", () => {
    // The two are different models. A live read composes movements; a fixture
    // composes items, and merging them would let a fixture field arrive on a
    // row about real money.
    const smuggled = item("live-id", { label: "SMUGGLED", sample: { date: { id: "secret-date", label: "Secret sample date" } } });
    const { getByText, queryByText, queryByRole } = render(<Activity result={ready({ items: [smuggled], sentence: moments.activity_scope, movements: [movement()], beyond: { count: 0 }, sample: { filters } })} mode="live" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("What moved")).toBeInTheDocument();
    expect(getByText("a shop")).toBeInTheDocument();
    for (const smuggledText of ["SMUGGLED", "Secret sample date"]) expect(queryByText(smuggledText)).not.toBeInTheDocument();
    expect(queryByRole("textbox", { name: "Search fictional activity" })).not.toBeInTheDocument();
  });

  it("says which way the money went in the read's own word, and shows no sign", () => {
    const { getByText, queryByText } = render(<Activity result={ready(live([movement({ direction: "out", display: "USD 120.00" })]))} mode="live" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("out")).toBeInTheDocument();
    expect(getByText("USD 120.00")).toBeInTheDocument();
    expect(queryByText("-USD 120.00")).not.toBeInTheDocument();
  });

  it("shows the read's own line for a row that is not plain spending", () => {
    const { getByText } = render(<Activity result={ready(live([movement({ sentence: moments.activity_transfer })]))} mode="live" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText(moments.activity_transfer)).toBeInTheDocument();
  });

  it("says how many movements are in the vault and not in this list", () => {
    const { getByText } = render(<Activity result={ready({ items: [], sentence: moments.activity_scope, movements: [movement()], beyond: { count: 6 } })} mode="live" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("6 more are in this vault and not in this list.")).toBeInTheDocument();
  });

  it("uses the shared activity Figure identity and exact document proof", () => {
    const openFigure = vi.fn();
    const openEvidence = vi.fn();
    const link = { targetDocumentId: "document-exact", label: "Exact statement", relation: "same_period" as const, page: "page 7" };
    const movement = sample("figure-id", { evidenceLinks: [link] });
    const { getAllByRole, getByRole } = render(<Activity result={ready(data([movement]))} mode="demo" onOpenEvidence={openEvidence} onOpenFigure={openFigure} />);
    fireEvent.click(getAllByRole("button", { description: /View evidence for Sample figure-id income/i })[0]);
    expect(openFigure).toHaveBeenCalledWith("activity:figure-id");
    fireEvent.click(getByRole("button", { name: "Exact statement · page 7" }));
    expect(openEvidence).toHaveBeenCalledWith(link);
  });

  it("filters literal sample text, combines authored facets, reports no match, and clears without auto-selection", () => {
    const first = sample("first", { label: "Coffee [literal]" });
    const second = sample("second", { label: "Second movement", sample: { ...sample("base").sample, category: { id: "category-other", label: "Other" } } });
    const catalog = { ...filters, categories: [...filters.categories, { id: "category-other", label: "Other" }] };
    const { getAllByRole, getByLabelText, getByRole, getByText } = render(<Activity result={ready({ items: [first, second], sample: { filters: catalog } })} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    fireEvent.change(getByLabelText("Search fictional activity"), { target: { value: "[literal]" } });
    expect(getByText("1 fictional sample movement shown.")).toBeInTheDocument();
    fireEvent.change(getByLabelText("Sample category"), { target: { value: "category-other" } });
    expect(getByText("No fictional sample movements match this view")).toBeInTheDocument();
    fireEvent.click(getAllByRole("button", { name: "Clear sample view" })[1]);
    expect(getByText("2 fictional sample movements shown.")).toBeInTheDocument();
    expect(getByRole("heading", { name: "No movement selected" })).not.toHaveFocus();
    expect(getByRole("heading", { name: "No movement selected" })).toHaveAttribute("id", "selected-activity-title");
  });

  it("retains a globally unique visible selection when Clear restores the full view", () => {
    const first = sample("first", { label: "First visible" });
    const second = sample("second", { label: "Second visible" });
    const { getByLabelText, getByRole } = render(<Activity result={ready(data([first, second]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    fireEvent.change(getByLabelText("Search fictional activity"), { target: { value: "First visible" } });
    expect(getByRole("button", { name: /First visible.*Fictional sample/i })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(getByRole("button", { name: "Clear sample view" }));
    expect(getByRole("button", { name: /First visible.*Fictional sample/i })).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("heading", { name: "First visible" })).not.toHaveFocus();
  });

  it("never legitimizes a duplicate identity when a filter hides its twin", () => {
    const categoryOther = { id: "category-other", label: "Other" };
    const catalog = { ...filters, categories: [...filters.categories, categoryOther] };
    const first = sample("duplicate", { label: "First duplicate" });
    const second = sample("duplicate", { label: "Second duplicate", sample: { ...sample("base").sample, category: categoryOther } });
    const { getAllByText, getByLabelText, getByRole, queryByRole, rerender } = render(<Activity result={ready({ items: [sample("duplicate")], sample: { filters: catalog } })} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    rerender(<Activity result={ready({ items: [first, second], sample: { filters: catalog } })} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByRole("heading", { name: "Movement selection unavailable" })).toBeInTheDocument();
    fireEvent.change(getByLabelText("Sample category"), { target: { value: "category-one" } });
    expect(getAllByText("More than one row uses this activity ID. No row with this identity can be selected.")).toHaveLength(1);
    expect(queryByRole("button", { name: /First duplicate.*Fictional sample/i })).not.toBeInTheDocument();
  });

  it("keeps duplicate labels with distinct stable IDs selectable", () => {
    const { getAllByRole, getByRole } = render(<Activity result={ready(data([sample("first", { label: "Same label" }), sample("second", { label: "Same label" })]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    const rows = getAllByRole("button", { name: /Same label.*Fictional sample/i });
    expect(rows).toHaveLength(2);
    fireEvent.click(rows[1]);
    expect(rows[1]).toHaveAttribute("aria-pressed", "true");
    expect(getByRole("heading", { name: "Same label" })).toBeInTheDocument();
  });

  it("keeps authored filters optional without hiding sample rows", () => {
    const { getAllByText, getByText, queryByRole } = render(<Activity result={ready(data([sample("shown")], false))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("Sample filters unavailable")).toBeInTheDocument();
    expect(getAllByText("Sample shown")).toHaveLength(2);
    expect(queryByRole("textbox", { name: "Search fictional activity" })).not.toBeInTheDocument();
  });

  it("keeps ordinary movement selection on the pressed button without focusing the detail", () => {
    const { getByRole } = render(<Activity result={ready(data([sample("first"), sample("second")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    const second = getByRole("button", { name: /Sample second.*Fictional sample/i });
    second.focus();
    fireEvent.click(second);
    expect(second).toHaveFocus();
    expect(getByRole("heading", { name: "Sample second" })).not.toHaveFocus();
  });

  it("states every missing fictional organization field without inference", () => {
    const movement = sample("missing-org", { sample: {} });
    const { getByText } = render(<Activity result={ready(data([movement]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    for (const copy of ["Sample date was not authored for this movement.", "Sample account was not authored for this movement.", "Sample merchant was not authored for this movement.", "Sample category was not authored for this movement.", "Sample tags were not authored for this movement.", "Sample nature was not authored for this movement.", "Sample direction was not authored for this movement."]) expect(getByText(copy)).toBeInTheDocument();
  });

  it("bounds blank, duplicate, disappeared, conflicted, and unselectable identities", () => {
    const { container, getAllByText, getByRole, getByText, rerender, unmount } = render(<Activity result={ready(data([sample("selected")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    rerender(<Activity result={ready(data([sample("other")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByRole("heading", { name: "Selected movement unavailable" })).toHaveAttribute("tabindex", "-1");
    expect(getByText("Requested activity ID: selected")).toBeInTheDocument();
    fireEvent.click(getByRole("button", { name: "Clear sample view" }));
    expect(getByRole("heading", { name: "No movement selected" })).not.toHaveFocus();
    rerender(<Activity result={ready(data([sample("selected")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    fireEvent.click(getByRole("button", { name: /Sample selected.*Fictional sample/i }));
    rerender(<Activity result={ready(data([sample("selected"), sample("selected")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByRole("heading", { name: "Movement selection unavailable" })).toBeInTheDocument();
    expect(getAllByText("More than one row uses this activity ID. No row with this identity can be selected.")).toHaveLength(2);
    expect(container.querySelectorAll("#selected-activity-title")).toHaveLength(1);
    fireEvent.click(getByRole("button", { name: "Clear sample view" }));
    expect(getByRole("heading", { name: "Movement selection unavailable" })).not.toHaveFocus();
    unmount();
    const blank = render(<Activity result={ready(data([sample(""), sample(" ")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(blank.getAllByText("This row has no stable activity ID, so it cannot be selected.")).toHaveLength(2);
    expect(blank.getByText("The current Activity view contains rows, but none has a unique nonblank activity ID.")).toBeInTheDocument();
  });

  it("shows authored organization and opens an exact related movement with cleared controls and guarded focus", async () => {
    const incoming = sample("incoming", { label: "Incoming sample" });
    const outgoing = sample("outgoing", { label: "Outgoing sample", sample: { ...sample("base").sample, relationships: [{ targetActivityId: "incoming", label: "Incoming sample" }] } });
    const { getByLabelText, getByRole, getByText } = render(<Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("Fictional organization details")).toBeInTheDocument();
    fireEvent.change(getByLabelText("Search fictional activity"), { target: { value: "Outgoing" } });
    fireEvent.click(getByRole("button", { name: "View related fictional movement: Incoming sample" }));
    await waitFor(() => expect(getByRole("heading", { name: "Incoming sample" })).toHaveFocus());
    expect(getByLabelText("Search fictional activity")).toHaveValue("");
    expect(getByText("2 fictional sample movements shown.")).toBeInTheDocument();
  });

  it("makes a captured related-focus callback inert after the mode changes", () => {
    const frames = captureAnimationFrames();
    try {
      const { incoming, outgoing } = relatedSamplePair();
      const result = ready(data([outgoing, incoming]));
      const { getByRole, rerender } = render(<><button type="button">Outside focus</button><Activity result={result} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      fireEvent.click(getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      rerender(<><button type="button">Outside focus</button><Activity result={result} mode="live" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      const outside = getByRole("button", { name: "Outside focus" });
      outside.focus();
      frames.callbacks.forEach((callback) => callback(performance.now()));
      expect(outside).toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("does not focus a refusal when the related target is removed or duplicated before the callback", () => {
    const frames = captureAnimationFrames();
    try {
      const { incoming, outgoing } = relatedSamplePair();
      const view = render(<><button type="button">Outside focus</button><Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      fireEvent.click(view.getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      view.rerender(<><button type="button">Outside focus</button><Activity result={ready(data([outgoing]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      const outside = view.getByRole("button", { name: "Outside focus" });
      outside.focus();
      frames.callbacks[0](performance.now());
      expect(outside).toHaveFocus();
      expect(view.getByRole("heading", { name: "Selected movement unavailable" })).not.toHaveFocus();

      view.rerender(<><button type="button">Outside focus</button><Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      fireEvent.click(view.getByRole("button", { name: /Outgoing sample.*Fictional sample/i }));
      fireEvent.click(view.getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      view.rerender(<><button type="button">Outside focus</button><Activity result={ready(data([outgoing, incoming, { ...incoming }]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      outside.focus();
      frames.callbacks[1](performance.now());
      expect(outside).toHaveFocus();
      expect(view.getByRole("heading", { name: "Movement selection unavailable" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("focuses the freshly rendered unique target when its authored content changes", () => {
    const frames = captureAnimationFrames();
    try {
      const { incoming, outgoing } = relatedSamplePair();
      const view = render(<Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
      fireEvent.click(view.getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      const updated = sample("incoming", { label: "Updated incoming sample", detail: "Updated incoming detail" });
      view.rerender(<Activity result={ready(data([outgoing, updated]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
      frames.callbacks[0](performance.now());
      const title = view.getByRole("heading", { name: "Updated incoming sample" });
      expect(title).toHaveAttribute("data-activity-id", "incoming");
      expect(title).toHaveFocus();
      expect(view.getByText("Updated incoming detail")).toBeInTheDocument();
    } finally {
      frames.restore();
    }
  });

  it("cancels captured related focus after selection, query, filter, or Clear controls", () => {
    const frames = captureAnimationFrames();
    try {
      const { incoming, outgoing } = relatedSamplePair();
      const view = render(<><button type="button">Outside focus</button><Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} /></>);
      const outside = view.getByRole("button", { name: "Outside focus" });
      const schedule = () => fireEvent.click(view.getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      const selectOutgoing = () => fireEvent.click(view.getByRole("button", { name: /Outgoing sample.*Fictional sample/i }));
      const assertCapturedIsInert = (index: number) => { outside.focus(); frames.callbacks[index](performance.now()); expect(outside).toHaveFocus(); };

      schedule();
      selectOutgoing();
      assertCapturedIsInert(0);

      schedule();
      fireEvent.change(view.getByLabelText("Search fictional activity"), { target: { value: "Incoming" } });
      assertCapturedIsInert(1);

      fireEvent.click(view.getByRole("button", { name: "Clear sample view" }));
      selectOutgoing();
      schedule();
      fireEvent.change(view.getByLabelText("Sample category"), { target: { value: "category-one" } });
      assertCapturedIsInert(2);

      selectOutgoing();
      schedule();
      fireEvent.click(view.getByRole("button", { name: "Clear sample view" }));
      assertCapturedIsInert(3);
      expect(view.getByRole("heading", { name: "Incoming sample" })).not.toHaveFocus();
    } finally {
      frames.restore();
    }
  });

  it("leaves a captured related-focus callback inert after unmount", () => {
    const frames = captureAnimationFrames();
    const outside = document.createElement("button");
    outside.textContent = "Outside focus";
    document.body.append(outside);
    try {
      const { incoming, outgoing } = relatedSamplePair();
      const view = render(<Activity result={ready(data([outgoing, incoming]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
      fireEvent.click(view.getByRole("button", { name: "View related fictional movement: Incoming sample" }));
      outside.focus();
      view.unmount();
      frames.callbacks[0](performance.now());
      expect(outside).toHaveFocus();
    } finally {
      outside.remove();
      frames.restore();
    }
  });

  it("renders every bounded relationship refusal without a write control", () => {
    const selected = sample("selected", { sample: { ...sample("base").sample, relationships: [{ targetActivityId: "", label: "Blank" }, { targetActivityId: "missing", label: "Missing" }, { targetActivityId: "duplicate", label: "Duplicate" }] } });
    const { getByText, queryByRole } = render(<Activity result={ready(data([selected, sample("duplicate"), sample("duplicate")]))} mode="demo" onOpenEvidence={noAction} onOpenFigure={noAction} />);
    expect(getByText("This fictional relationship does not include an activity identity.")).toBeInTheDocument();
    expect(getByText("The related fictional movement is not present in this sample.")).toBeInTheDocument();
    expect(getByText("More than one fictional movement uses the related activity ID. No related movement was opened.")).toBeInTheDocument();
    expect(queryByRole("button", { name: "View related fictional movement: Blank" })).not.toBeInTheDocument();
    expect(queryByRole("button", { name: /categorize|tag|correct|link|unlink|confirm|review/i })).not.toBeInTheDocument();
  });
});
