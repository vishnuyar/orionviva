import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EngineIdentity, FeatureResult, OutboundRecordView, SettingsView, TransferActionState, TrustData } from "../../surface/types";
import { Trust } from "./Trust";
import type { MaintenanceControls, SettingsControls, TransferControls } from "./Trust";
import moments from "../../../../product/viva/persona/pack-v31/moments.json";

const note = (id: string, title = "Supplied title", detail = "Supplied detail") => ({ id, title, detail });
const ready = (data: TrustData): FeatureResult<TrustData> => ({ state: "ready", data });
// No engine has been asked in most of these cases, which is what a screen sees
// before the handshake lands and is not the same fact as an engine that would
// not say.
const unasked: FeatureResult<EngineIdentity> = { state: "absent", reason: "not_asked" };
const noTransfer: TransferControls["onExport"] = () => {};
const noRestore: TransferControls["onRestore"] = () => {};

describe("Trust surface", () => {
  it("renders every FeatureResult boundary and the honest empty state", () => {
    const { getByText, queryByText, rerender } = render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={{ state: "absent", reason: "not_read" }} />);
    expect(queryByText("Trust details unavailable")).not.toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={{ state: "unavailable", reason: "not_connected" }} />);
    expect(getByText("Trust and maintenance details are not connected to this vault read.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("Trust details could not be read", { selector: "strong" })).toBeInTheDocument();
    expect(getByText("Trust and maintenance details could not be read. The vault is still open.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={{ state: "partial", data: { notes: [note("partial")] }, issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some Trust details are unavailable. Supplied notes are shown below.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={{ state: "needs_input", data: { notes: [note("needs")] }, issues: [{ code: "needs", message: "bounded" }] }} />);
    expect(getByText("Some Trust details need more information. Supplied notes are shown below.")).toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [] })} />);
    expect(getByText("No Trust notes supplied")).toBeInTheDocument();
    expect(getByText("The supplied Trust view contains no notes. This does not establish zero outbound, model, or maintenance activity, or any integrity or recovery status.")).toBeInTheDocument();
  });



  it("bounds missing and duplicate Trust note identities without merging by label or order", () => {
    const notes = [note("", "Hidden blank one"), note(" ", "Hidden blank two"), note("duplicate", "Hidden duplicate one"), note("duplicate", "Hidden duplicate two"), note("unique-one", "Same label"), note("unique-two", "Same label")];
    const { getAllByText, getByText, queryByText, rerender } = render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes })} />);
    expect(getAllByText("Trust note identity unavailable")).toHaveLength(1);
    expect(getAllByText("Trust note identity conflicted")).toHaveLength(1);
    expect(getByText("duplicate")).toBeInTheDocument();
    expect(getAllByText("Same label")).toHaveLength(2);
    for (const hidden of ["Hidden blank one", "Hidden blank two", "Hidden duplicate one", "Hidden duplicate two"]) expect(queryByText(hidden)).not.toBeInTheDocument();
    rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [...notes].reverse() })} />);
    expect(getAllByText("Same label")).toHaveLength(2);
  });



  it("keeps ready, missing, and conflicted identity keys disjoint across reorder", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const notes = [note("", "Blank hidden"), note("missing-identity", "Ready note named missing"), note("x", "Duplicate note one"), note("x", "Duplicate note two"), note("conflict-x", "Ready note named conflict")];
      const view = render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes })} />);
      const assertComplete = () => {
        expect(view.getAllByText("Trust note identity unavailable")).toHaveLength(1);
        expect(view.getAllByText("Trust note identity conflicted")).toHaveLength(1);
        expect(view.getByText("Ready note named missing")).toBeInTheDocument();
        expect(view.getByText("Ready note named conflict")).toBeInTheDocument();
      };
      assertComplete();
      view.rerender(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [...notes].reverse() })} />);
      assertComplete();
      expect(error).not.toHaveBeenCalled();
    } finally {
      error.mockRestore();
    }
  });

  it("preserves long supplied identities and explanatory copy without truncation attributes", () => {
    const long = `long-${"identity".repeat(20)}`;
    const { container, getByText } = render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [note(long, long, long)] })} />);
    expect(getByText(long, { selector: "strong" })).toBeInTheDocument();
    expect(getByText(long, { selector: "dd" })).toBeInTheDocument();
    expect(container.querySelector("[title]")).not.toBeInTheDocument();
  });
});

describe("a copy of a whole vault", () => {
  const props = { identity: unasked, lifecycle: unasked, settings: null, maintenance: null, result: ready({ notes: [note("only")] }) };
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
    render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [], outbound: record(over) })} />);

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

  it("keeps configured routes separate from provider-reported models", () => {
    const { getByRole, getByText } = withRecord({
      sentence: moments.outbound_some, callCount: 1,
      models: [{ name: "configured-alias", count: 1 }],
      reportedModels: [{ name: "resolved-model-2026", count: 1 }],
      tokens: { input: 120, output: 30, total: 150, measuredCalls: 1 },
    });

    expect(getByRole("heading", { name: "Configured routes" })).toBeInTheDocument();
    expect(getByRole("heading", { name: "Models reported by providers" })).toBeInTheDocument();
    expect(getByText("configured-alias")).toBeInTheDocument();
    expect(getByText("resolved-model-2026")).toBeInTheDocument();
    expect(getByRole("heading", { name: "Provider-reported tokens" })).toBeInTheDocument();
    expect(getByText("150")).toBeInTheDocument();
    expect(getByText("1 of 1")).toBeInTheDocument();
  });

  it("does not relabel historical model names as configured routes", () => {
    const { getByRole, getByText, queryByRole } = withRecord({
      sentence: moments.outbound_some, callCount: 1,
      legacyModels: [{ name: "provider/legacy-revision", count: 1 }],
    });

    expect(getByRole("heading", { name: "Older calls with model role unavailable" })).toBeInTheDocument();
    expect(getByText("provider/legacy-revision")).toBeInTheDocument();
    expect(queryByRole("heading", { name: "Configured routes" })).not.toBeInTheDocument();
    expect(queryByRole("heading", { name: "Models reported by providers" })).not.toBeInTheDocument();
  });

  it("shows no total at all where the read carried none", () => {
    const { queryByText } = withRecord({ sentence: moments.outbound_some, callCount: 1 });
    expect(queryByText(/cost/i)).not.toBeInTheDocument();
  });
});

describe("what this app has been told to do", () => {
  const inForce: SettingsView = { locale: "en-US", currency: "USD", adapter: "", model: "", baseUrl: "", keySet: false, canSend: false };
  const base = { identity: unasked, lifecycle: unasked, transfer: null, maintenance: null, result: ready({ notes: [], outbound: { sentence: moments.outbound_none, callCount: 0, phases: [], models: [], modelSentence: "", span: null, cost: null, absences: [] } }) };
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
    expect(asked).toEqual([["presentation", { locale: "en-IN", currency: "USD" }]]);
  });

  it("fills the model form from what is in force and resyncs after confirmation", () => {
    const first: SettingsView = { locale: "en-US", currency: "USD", adapter: "openai-compatible", model: "a-pinned-1", baseUrl: "https://first.invalid/v1", keySet: true, canSend: true };
    const second: SettingsView = { ...first, model: "a-pinned-2", baseUrl: "https://second.invalid/v1" };
    const settings = controls({ settings: { state: "ready", data: first } });
    const view = render(<Trust {...base} settings={settings} />);

    expect(view.getByLabelText("Reach a model through")).toHaveValue("openai-compatible");
    expect(view.getByLabelText("Named exactly")).toHaveValue("a-pinned-1");
    expect(view.getByLabelText("Where to reach it")).toHaveValue("https://first.invalid/v1");

    view.rerender(<Trust {...base} settings={{ ...settings, settings: { state: "ready", data: second } }} />);

    expect(view.getByLabelText("Named exactly")).toHaveValue("a-pinned-2");
    expect(view.getByLabelText("Where to reach it")).toHaveValue("https://second.invalid/v1");
  });

  it("does not mistake a missing key for a choice that no key is needed", () => {
    const missing: SettingsView = { locale: "en-US", currency: "USD", adapter: "openai-compatible", model: "a-pinned-1", baseUrl: "https://example.invalid/v1", keySet: false, canSend: true };
    const view = render(<Trust {...base} settings={controls({ settings: { state: "ready", data: missing } })} />);

    expect(view.getByLabelText("This model needs no key")).not.toBeChecked();
    expect(view.getByText("No key is in use for this model.")).toBeInTheDocument();
  });

  it("states the blank-key rule and carries only the presence of a new key", () => {
    const asked: Array<[string, Record<string, string>]> = [];
    const view = render(<Trust {...base} settings={controls({ onPropose: (kind, fields) => { asked.push([kind, fields]); } })} />);

    fireEvent.change(view.getByLabelText("Reach a model through"), { target: { value: "anthropic" } });
    fireEvent.change(view.getByLabelText("Named exactly"), { target: { value: "a-pinned-1" } });
    fireEvent.change(view.getByLabelText("Where to reach it"), { target: { value: "https://example.invalid/v1" } });
    fireEvent.change(view.getByLabelText("Its key"), { target: { value: "a-key" } });
    fireEvent.click(view.getAllByRole("button", { name: "Show me what would change" })[1]);

    expect(view.getByText("Leave this blank to keep the key already in use. If no key is in use, paste one or say this model needs no key.")).toBeInTheDocument();
    expect(asked).toEqual([["model", { adapter: "anthropic", model: "a-pinned-1", base_url: "https://example.invalid/v1", key_action: "set" }]]);
    expect(JSON.stringify(asked)).not.toContain("a-key");
  });

  it("lets a person state that the model needs no key without inspecting its address", () => {
    const asked: Array<[string, Record<string, string>]> = [];
    const view = render(<Trust {...base} settings={controls({ onPropose: (kind, fields) => { asked.push([kind, fields]); } })} />);

    fireEvent.change(view.getByLabelText("Reach a model through"), { target: { value: "openai-compatible" } });
    fireEvent.change(view.getByLabelText("Named exactly"), { target: { value: "a-pinned-1" } });
    fireEvent.click(view.getByLabelText("This model needs no key"));
    fireEvent.click(view.getAllByRole("button", { name: "Show me what would change" })[1]);

    expect(asked[0][1].key_action).toBe("none");
  });

  it("offers the existing proposal path for reaching no model", () => {
    const asked: Array<[string, Record<string, string>]> = [];
    const view = render(<Trust {...base} settings={controls({ onPropose: (kind, fields) => { asked.push([kind, fields]); } })} />);

    fireEvent.click(view.getByRole("button", { name: "Reach no model" }));

    expect(asked).toEqual([["model", { adapter: "", model: "", base_url: "", key_action: "" }]]);
  });

  it("shows the proposal's own sentence and every change it names before any yes", () => {
    const proposal = { kind: "model" as const, changes: { adapter: "anthropic", model: "a-pinned-1", base_url: "https://example.invalid/v1", key: "not needed" }, sends: true, digest: "abc123", message: moments.settings_model_proposed };
    const { getByText, getAllByText, getByRole } = render(<Trust {...base} settings={controls({ state: { state: "proposed", proposal } })} />);
    expect(getByText(moments.settings_model_proposed)).toBeInTheDocument();
    expect(getByText("a-pinned-1")).toBeInTheDocument();
    expect(getAllByText("Where to reach it").length).toBeGreaterThan(1);
    expect(getAllByText("Key").length).toBeGreaterThan(1);
    expect(getByText("No key is needed.")).toBeInTheDocument();
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

describe("what this cannot establish, and what it could do on its own", () => {
  const withAbsences = (absences: Array<{ id: string; sentence: string }>) =>
    render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [], absences, outbound: undefined })} />);
  const maintenance = (over: Partial<MaintenanceControls> = {}): MaintenanceControls =>
    ({ state: { state: "idle" }, onRun: () => {}, onDiagnose: () => {}, ...over });
  const withMaintenance = (controls: MaintenanceControls | null) =>
    render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={controls} result={ready({ notes: [note("only")] })} />);

  it("says plainly that nothing is anchored, in the read's own sentence", () => {
    // An absence a person has to open something to find is an absence they
    // will not find.
    const { getByText } = withAbsences([{ id: "anchoring", sentence: moments.trust_no_anchoring }]);
    expect(getByText(moments.trust_no_anchoring)).toBeInTheDocument();
  });

  it("says nothing about absences the read did not name", () => {
    const { queryByRole } = withAbsences([]);
    expect(queryByRole("heading", { name: "What this cannot establish" })).not.toBeInTheDocument();
  });

  it("renders no maintenance controls where the source carries none", () => {
    const { queryByRole } = withMaintenance(null);
    expect(queryByRole("button", { name: "Show me what it would do" })).not.toBeInTheDocument();
  });

  it("keeps planning and spending as two controls with their own words", () => {
    // The difference between them is money leaving.
    const asked: boolean[] = [];
    const { getByRole } = withMaintenance(maintenance({ onRun: (spend: boolean) => { asked.push(spend); } }));
    fireEvent.click(getByRole("button", { name: "Show me what it would do" }));
    fireEvent.click(getByRole("button", { name: "Run it, and spend" }));
    expect(asked).toEqual([false, true]);
  });

  it("hands the diagnostic the path a person typed, and nothing else", () => {
    const asked: string[] = [];
    const { getByLabelText, getByRole } = withMaintenance(maintenance({ onDiagnose: (file: string) => { asked.push(file); } }));
    fireEvent.change(getByLabelText("Write a file I can send"), { target: { value: "/tmp/diagnostic.json" } });
    fireEvent.click(getByRole("button", { name: "Write it" }));
    expect(asked).toEqual(["/tmp/diagnostic.json"]);
  });

  it("says the vault's own sentence about what a run did", () => {
    const settled = { state: "settled" as const, result: { state: "settled" as const, outcome: { kind: "completed" as const, message: moments.maintenance_planned, reason: "" } } };
    const { getAllByText } = withMaintenance(maintenance({ state: settled }));
    expect(getAllByText(moments.maintenance_planned).length).toBeGreaterThan(0);
  });
});

describe("what happens when a new version exists", () => {
  const lifecycle = { state: "ready" as const, data: {
    sentence: "a sentence about no channel",
    originSentence: "a sentence about how this copy got here",
    revision: "abcdef123456",
    notes: [{ id: "vault_untouched", sentence: "a sentence about a vault" },
            { id: "recovery", sentence: "a sentence about starting over" }],
  } };

  it("says there is no channel, in the engine's own words", () => {
    const { getByRole, getByText } = render(<Trust identity={unasked} lifecycle={lifecycle} transfer={null} settings={null} maintenance={null} result={ready({ notes: [] })} />);

    expect(getByRole("heading", { name: "Updates and recovery" })).toBeInTheDocument();
    expect(getByText(lifecycle.data.sentence)).toBeInTheDocument();
    expect(getByText(lifecycle.data.originSentence)).toBeInTheDocument();
  });

  it("says what an update does to a vault, and what to do when one will not start", () => {
    const { getByText } = render(<Trust identity={unasked} lifecycle={lifecycle} transfer={null} settings={null} maintenance={null} result={ready({ notes: [] })} />);

    for (const note of lifecycle.data.notes) expect(getByText(note.sentence)).toBeInTheDocument();
  });

  it("renders no section at all where the read did not answer", () => {
    // A heading with nothing under it says a channel exists and is quiet.
    const { queryByRole } = render(<Trust identity={unasked} lifecycle={unasked} transfer={null} settings={null} maintenance={null} result={ready({ notes: [] })} />);

    expect(queryByRole("heading", { name: "Updates and recovery" })).not.toBeInTheDocument();
  });
});
