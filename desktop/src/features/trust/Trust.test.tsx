import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EngineIdentity, FeatureResult, OutboundRecordView, SettingsView, TransferActionState, TrustData, TrustSampleCapability } from "../../surface/types";
import { Trust } from "./Trust";
import type { SettingsControls, TransferControls } from "./Trust";
import moments from "../../../../product/viva/persona/pack-v28/moments.json";

const note = (id: string, title = "Supplied title", detail = "Supplied detail") => ({ id, title, detail });
const capability = (id: string, state: TrustSampleCapability["state"], label = `Capability ${id}`, detail = `Detail ${id}`): TrustSampleCapability => ({ id, group: "source", label, state, detail });
const ready = (data: TrustData): FeatureResult<TrustData> => ({ state: "ready", data });
// No engine has been asked in most of these cases, which is what a screen sees
// before the handshake lands and is not the same fact as an engine that would
// not say.
const unasked: FeatureResult<EngineIdentity> = { state: "absent", reason: "not_asked" };
const noTransfer: TransferControls["onExport"] = () => {};
const noRestore: TransferControls["onRestore"] = () => {};

describe("Trust surface", () => {
  it("renders every FeatureResult boundary and both honest empty modes", () => {
    const { getByText, queryByText, rerender } = render(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={{ state: "absent", reason: "not_read" }} />);
    expect(queryByText("Trust details unavailable")).not.toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={{ state: "unavailable", reason: "not_connected" }} />);
    expect(getByText("Trust and maintenance details are not connected to this private-vault read.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("Trust details could not be read", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("Trust and maintenance details could not be read. The private vault is still open.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={{ state: "partial", data: { notes: [note("partial")] }, issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some Trust details are unavailable. Supplied notes and preview limitations are shown below.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={{ state: "needs_input", data: { notes: [note("needs")] }, issues: [{ code: "needs", message: "bounded" }] }} />);
    expect(getByText("Some Trust details need more information. Supplied notes and preview limitations are shown below.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes: [] })} />);
    expect(getByText("No Trust notes supplied")).toBeInTheDocument();
    expect(getByText("The supplied Trust view contains no notes. This does not establish zero outbound, model, or maintenance activity, or any integrity or recovery status.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [], sample: { capabilities: [] } })} />);
    expect(getByText("No sample Trust details")).toBeInTheDocument();
  });

  it("renders the exact preview boundary, all availability labels, and no settings actions", () => {
    const capabilities = [
      capability("fictional", "fictional_sample"),
      capability("limitation", "preview_limitation"),
      capability("connection", "not_connected"),
      capability("supply", "not_supplied"),
      capability("implementation", "not_implemented"),
    ];
    const { container, getByText } = render(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [note("preview", "Preview boundary")], sample: { capabilities } })} />);
    expect(getByText("Preview-owned explanation")).toBeInTheDocument();
    expect(getByText("This destination explains what the fictional preview can and cannot establish. It is not a trust report for a private vault.")).toBeInTheDocument();
    for (const label of ["Fictional sample", "Preview limitation", "Not connected", "Not supplied", "Not implemented"]) expect(getByText(label)).toBeInTheDocument();
    expect(getByText("No settings are changed here")).toBeInTheDocument();
    expect(container.querySelectorAll("button, input, select, textarea")).toHaveLength(0);
    const disclosures = [...container.querySelectorAll("details")];
    expect(disclosures).toHaveLength(5);
    expect(disclosures.map((disclosure) => disclosure.open)).toEqual([true, false, false, false, false]);
    fireEvent.click(disclosures[1].querySelector("summary") as HTMLElement);
    expect(disclosures[1]).toHaveAttribute("open");
  });

  it("shows only supplied live notes and hides malicious preview capabilities", () => {
    const malicious = capability("secret", "fictional_sample", "Secret fictional capability", "Secret fictional detail");
    const { getByText, queryByText } = render(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes: [note("live-note", "Backend supplied note", "Backend supplied detail")], sample: { capabilities: [malicious] } })} />);
    expect(getByText("Supplied Trust view")).toBeInTheDocument();
    expect(getByText("Backend supplied note")).toBeInTheDocument();
    expect(getByText("Backend supplied detail")).toBeInTheDocument();
    expect(getByText("Supplied note")).toBeInTheDocument();
    expect(getByText("live-note")).toBeInTheDocument();
    expect(getByText("A supplied note is displayed text, not an independently verified guarantee or complete history.")).toBeInTheDocument();
    expect(queryByText("Secret fictional capability")).not.toBeInTheDocument();
    expect(queryByText("What this preview can say")).not.toBeInTheDocument();
  });

  it("bounds missing and duplicate Trust note identities without merging by label or order", () => {
    const notes = [note("", "Hidden blank one"), note(" ", "Hidden blank two"), note("duplicate", "Hidden duplicate one"), note("duplicate", "Hidden duplicate two"), note("unique-one", "Same label"), note("unique-two", "Same label")];
    const { getAllByText, getByText, queryByText, rerender } = render(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes })} />);
    expect(getAllByText("Trust note identity unavailable")).toHaveLength(1);
    expect(getAllByText("Trust note identity conflicted")).toHaveLength(1);
    expect(getByText("duplicate")).toBeInTheDocument();
    expect(getAllByText("Same label")).toHaveLength(2);
    for (const hidden of ["Hidden blank one", "Hidden blank two", "Hidden duplicate one", "Hidden duplicate two"]) expect(queryByText(hidden)).not.toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes: [...notes].reverse() })} />);
    expect(getAllByText("Same label")).toHaveLength(2);
  });

  it("renders missing note fields and bounded capability identity rows", () => {
    const capabilities = [capability("", "not_supplied"), { ...capability(" ", "not_connected"), group: "outbound_models" as const }, capability("duplicate", "not_supplied"), { ...capability("duplicate", "not_implemented"), group: "integrity" as const }, capability("missing-fields", "preview_limitation", "", "")];
    const { getAllByText, getByText, rerender } = render(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [note("missing-note", "", "")], sample: { capabilities } })} />);
    expect(getByText("Note title was not supplied by this Trust view.")).toBeInTheDocument();
    expect(getByText("Note detail was not supplied by this Trust view.")).toBeInTheDocument();
    expect(getAllByText("Capability identity unavailable")).toHaveLength(1);
    expect(getAllByText("Capability identity conflicted")).toHaveLength(1);
    expect(getByText("Capability label was not authored for this preview row.")).toBeInTheDocument();
    expect(getByText("Capability detail was not authored for this preview row.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [note("missing-note", "", "")], sample: { capabilities: [...capabilities].reverse() } })} />);
    expect(getAllByText("Capability identity unavailable")).toHaveLength(1);
    expect(getAllByText("Capability identity conflicted")).toHaveLength(1);
  });

  it("bounds inherited, future, and blank availability states without indexing the state map", () => {
    const unknownStates = ["constructor", "toString", "hasOwnProperty", "__proto__", "future_state_128-EXACT", ""];
    const capabilities = unknownStates.map((state, position) => ({ ...capability(`unknown-state-${position}`, "preview_limitation"), state } as unknown as TrustSampleCapability));
    const { getAllByText, getByText } = render(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [], sample: { capabilities } })} />);
    expect(getAllByText("Status unavailable")).toHaveLength(unknownStates.length);
    expect(getAllByText("This preview row supplied an unrecognized availability state. No capability claim is made.")).toHaveLength(unknownStates.length);
    expect(getAllByText("Unrecognized supplied status value")).toHaveLength(unknownStates.length);
    for (const state of unknownStates.filter(Boolean)) expect(getByText(state)).toBeInTheDocument();
    expect(getByText("Status value was not supplied.")).toBeInTheDocument();
  });

  it("keeps ready, missing, and conflicted identity keys disjoint across reorder", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const notes = [note("", "Blank hidden"), note("missing-identity", "Ready note named missing"), note("x", "Duplicate note one"), note("x", "Duplicate note two"), note("conflict-x", "Ready note named conflict")];
      const capabilities = [capability("", "not_supplied", "Blank capability hidden"), capability("missing-identity", "not_connected", "Ready capability named missing"), capability("x", "not_supplied", "Duplicate capability one"), { ...capability("x", "not_implemented", "Duplicate capability two"), group: "integrity" as const }, capability("conflict-x", "preview_limitation", "Ready capability named conflict")];
      const view = render(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes, sample: { capabilities } })} />);
      const assertComplete = () => {
        expect(view.getAllByText("Trust note identity unavailable")).toHaveLength(1);
        expect(view.getAllByText("Trust note identity conflicted")).toHaveLength(1);
        expect(view.getByText("Ready note named missing")).toBeInTheDocument();
        expect(view.getByText("Ready note named conflict")).toBeInTheDocument();
        expect(view.getAllByText("Capability identity unavailable")).toHaveLength(1);
        expect(view.getAllByText("Capability identity conflicted")).toHaveLength(1);
        expect(view.getByText("Ready capability named missing")).toBeInTheDocument();
        expect(view.getByText("Ready capability named conflict")).toBeInTheDocument();
      };
      assertComplete();
      view.rerender(<Trust identity={unasked} transfer={null} settings={null} mode="demo" result={ready({ notes: [...notes].reverse(), sample: { capabilities: [...capabilities].reverse() } })} />);
      assertComplete();
      expect(error).not.toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });

  it("preserves long supplied identities and explanatory copy without truncation attributes", () => {
    const long = `long-${"identity".repeat(20)}`;
    const { container, getByText } = render(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes: [note(long, long, long)] })} />);
    expect(getByText(long, { selector: "strong" })).toBeInTheDocument();
    expect(getByText(long, { selector: "dd" })).toBeInTheDocument();
    expect(container.querySelector("[title]")).not.toBeInTheDocument();
  });
});

describe("a copy of a whole vault", () => {
  const props = { mode: "live" as const, identity: unasked, settings: null, result: ready({ notes: [note("only")] }) };
  const controls = (state: TransferActionState = { state: "idle" }, onExport = noTransfer, onRestore = noRestore): TransferControls => ({ state, onExport, onRestore });

  it("offers no control at all where the source cannot take a copy", () => {
    const { queryByRole } = render(<Trust {...props} transfer={null} />);
    expect(queryByRole("button", { name: "Take a copy" })).not.toBeInTheDocument();
  });

  it("hands the path a person typed over, and nothing else", () => {
    const asked: string[] = [];
    const { getByLabelText, getByRole } = render(<Trust {...props} transfer={controls({ state: "idle" }, (archive: string) => { asked.push(archive); })} />);
    fireEvent.change(getByLabelText("Write the copy to"), { target: { value: "/copies/mine.orionvault" } });
    fireEvent.click(getByRole("button", { name: "Take a copy" }));
    expect(asked).toEqual(["/copies/mine.orionvault"]);
  });

  it("hands a restore all three of the things it needs", () => {
    const asked: string[][] = [];
    const { getByLabelText, getByRole } = render(<Trust {...props} transfer={controls({ state: "idle" }, noTransfer, (...args: string[]) => { asked.push(args); })} />);
    fireEvent.change(getByLabelText("Bring back the copy at"), { target: { value: "/copies/mine.orionvault" } });
    fireEvent.change(getByLabelText("Into the empty folder"), { target: { value: "/vaults/back" } });
    fireEvent.change(getByLabelText("Its passphrase"), { target: { value: "the-passphrase" } });
    fireEvent.click(getByRole("button", { name: "Bring it back" }));
    expect(asked).toEqual([["/copies/mine.orionvault", "/vaults/back", "the-passphrase"]]);
  });

  it("keeps both controls in the tab order while the vault is answering", () => {
    const { getByRole, getByText } = render(<Trust {...props} transfer={controls({ state: "working", verb: "export" })} />);
    expect(getByRole("button", { name: "Take a copy" })).toHaveAttribute("aria-disabled", "true");
    expect(getByText("Your vault is answering the last request. Pressing again does nothing until it has.")).toBeInTheDocument();
  });

  it("says the vault's own sentence about the copy, and composes none of its own", () => {
    const settled: TransferActionState = { state: "settled", verb: "export", result: { state: "settled", outcome: { kind: "completed", message: moments.vault_exported, reason: "" } } };
    const { getAllByText } = render(<Trust {...props} transfer={controls(settled)} />);
    expect(getAllByText(moments.vault_exported).length).toBeGreaterThan(0);
  });

  it("says what channel answered when the vault itself never did", () => {
    const settled: TransferActionState = { state: "settled", verb: "restore", result: { state: "unanswered" } };
    const { getAllByText } = render(<Trust {...props} transfer={controls(settled)} />);
    expect(getAllByText(/did not answer/).length).toBeGreaterThan(0);
  });
});

describe("everything this vault has sent", () => {
  const record = (over: Partial<OutboundRecordView> = {}): OutboundRecordView => ({
    sentence: moments.outbound_none, callCount: 0, phases: [], models: [], modelSentence: "", span: null, cost: null,
    absences: [{ id: "scope", sentence: moments.outbound_scope }, { id: "anchoring", sentence: moments.outbound_no_anchor }],
    ...over,
  });
  const withRecord = (over: Partial<OutboundRecordView> = {}) =>
    render(<Trust identity={unasked} transfer={null} settings={null} mode="live" result={ready({ notes: [], outbound: record(over) })} />);

  it("renders the record of a vault that has sent nothing with the same prominence", () => {
    // Hiding it would keep the promise by having nothing to show rather than
    // by showing it.
    const { getByRole, getByText } = withRecord();
    expect(getByRole("heading", { name: "Everything this vault has sent" })).toBeInTheDocument();
    expect(getByText(moments.outbound_none)).toBeInTheDocument();
  });

  it("says both absences with the read's own words", () => {
    const { getByText } = withRecord();
    expect(getByText(moments.outbound_scope)).toBeInTheDocument();
    expect(getByText(moments.outbound_no_anchor)).toBeInTheDocument();
  });

  it("renders one line per pass and composes none of them", () => {
    const { getByText } = withRecord({
      sentence: moments.outbound_some, callCount: 3,
      phases: [{ id: "extract", count: 2, sentence: "Twice, pages were sent." }],
      span: { first: "2026-07-01", last: "2026-08-05", sentence: "First on one day, last on another." },
      cost: { exactValue: "0.30", currency: "USD", display: "USD 0.30", sentence: "It cost USD 0.30." },
    });
    expect(getByText("Twice, pages were sent.")).toBeInTheDocument();
    expect(getByText("First on one day, last on another.")).toBeInTheDocument();
    expect(getByText("It cost USD 0.30.")).toBeInTheDocument();
  });

  it("shows no total at all where the read carried none", () => {
    const { queryByText } = withRecord({ sentence: moments.outbound_some, callCount: 1 });
    expect(queryByText(/cost/i)).not.toBeInTheDocument();
  });
});

describe("what this app has been told to do", () => {
  const inForce: SettingsView = { locale: "en-US", currency: "USD", adapter: "", model: "", baseUrl: "", keySet: false, canSend: false };
  const base = { mode: "live" as const, identity: unasked, transfer: null, result: ready({ notes: [], outbound: { sentence: moments.outbound_none, callCount: 0, phases: [], models: [], modelSentence: "", span: null, cost: null, absences: [] } }) };
  const controls = (over: Partial<SettingsControls> = {}): SettingsControls => ({
    settings: { state: "ready", data: inForce }, state: { state: "idle" },
    onPropose: () => {}, onConfirm: () => {}, ...over,
  });

  it("renders no form at all where the engine offered none", () => {
    const { queryByLabelText } = render(<Trust {...base} settings={null} />);
    expect(queryByLabelText("Write numbers as")).not.toBeInTheDocument();
  });

  it("says plainly that nothing can be sent while no model is named", () => {
    const { getByText } = render(<Trust {...base} settings={controls()} />);
    expect(getByText("None. Nothing can be sent anywhere.")).toBeInTheDocument();
  });

  it("asks for a proposal rather than changing anything when a form is submitted", () => {
    const asked: Array<[string, Record<string, string>]> = [];
    const { getAllByRole, getByLabelText } = render(<Trust {...base} settings={controls({ onPropose: (kind, fields) => { asked.push([kind, fields]); } })} />);
    fireEvent.change(getByLabelText("Write numbers as"), { target: { value: "en-IN" } });
    fireEvent.click(getAllByRole("button", { name: "Show me what would change" })[0]);
    expect(asked).toEqual([["presentation", { locale: "en-IN", currency: "" }]]);
  });

  it("shows the proposal's own sentence and every change it names before any yes", () => {
    const proposal = { kind: "model" as const, changes: { adapter: "anthropic", model: "a-pinned-1" }, sends: true, digest: "abc123", message: moments.settings_model_proposed };
    const { getByText, getByRole } = render(<Trust {...base} settings={controls({ state: { state: "proposed", proposal } })} />);
    expect(getByText(moments.settings_model_proposed)).toBeInTheDocument();
    expect(getByText("a-pinned-1")).toBeInTheDocument();
    expect(getByRole("button", { name: "Yes, do that" })).toBeInTheDocument();
  });

  it("hands the yes the digest of the proposal that was shown", () => {
    const proposal = { kind: "presentation" as const, changes: { locale: "en-IN" }, sends: false, digest: "abc123", message: moments.settings_presentation_proposed };
    const agreed: string[] = [];
    const { getByRole } = render(<Trust {...base} settings={controls({ state: { state: "proposed", proposal }, onConfirm: (_kind, _fields, digest) => { agreed.push(digest); } })} />);
    fireEvent.click(getByRole("button", { name: "Yes, do that" }));
    expect(agreed).toEqual(["abc123"]);
  });

  it("says the vault's own sentence about what was applied", () => {
    const settled = { state: "settled" as const, result: { state: "settled" as const, outcome: { kind: "completed" as const, message: moments.settings_model_confirmed, reason: "" } } };
    const { getAllByText } = render(<Trust {...base} settings={controls({ state: settled })} />);
    expect(getAllByText(moments.settings_model_confirmed).length).toBeGreaterThan(0);
  });
});
