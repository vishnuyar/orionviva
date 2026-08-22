import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
// The sentences the product ships, read from the pack that ships them. A
// sentence typed out here would be an assertion about words nobody released.
import moments from "../../../../product/viva/persona/pack-v23/moments.json";
import { EvidenceDrawer } from "../../components/EvidenceDrawer";
import type { FeatureResult, FigureView, OverviewData, PictureView, ReviewData, SurfaceSnapshot } from "../../surface/types";
import { Overview } from "./Overview";

// The one slot the announcement lines take. Naming it here keeps the test
// filling the pack's own frame rather than restating anything it says.
const SLOT = "{currency}";

const actions = { onSelectAccount: vi.fn(), onOpenReviewQuestion: vi.fn(), onNavigate: vi.fn(), onOpenEvidence: vi.fn(), onOpenFigure: vi.fn(), onExploreSample: vi.fn() };
const noReview: FeatureResult<ReviewData> = { state: "absent", reason: "not_read" };

function figure(overrides: Partial<FigureView> = {}): FigureView {
  return {
    id: "figure",
    display: "1.00",
    exactValue: "",
    currency: "",
    measure: "net_worth",
    grade: "corroborated",
    gradeLabel: "corroborated",
    gradeDescription: "One reviewed sentence about how well this is stood behind.",
    asOf: "",
    coverage: [],
    caveats: [],
    evidenceLinks: [],
    ...overrides,
  };
}

function overview(picture: Partial<PictureView> = {}): FeatureResult<OverviewData> {
  return { state: "ready", data: { picture: { coverage: "", readOn: "", figures: [], withheld: [], unplaced: [], ...picture }, corpusCoverage: "", accounts: [], recent: [] } };
}

function view(result: FeatureResult<OverviewData>) {
  return render(<Overview {...actions} result={result} reviewResult={noReview} mode="live" selectedAccount="" />);
}

function snapshotOf(result: FeatureResult<OverviewData>): SurfaceSnapshot {
  return { mode: "live", disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "" }, overview: result, documents: { state: "absent", reason: "not_read" }, review: noReview, activity: { state: "absent", reason: "not_read" }, conversation: { state: "absent", reason: "not_read" }, trust: { state: "absent", reason: "not_read" } };
}

describe("the picture on the overview", () => {
  it("shows the sentence the read supplied, byte for byte", () => {
    const supplied = "A distinctive sentence the backend composed and this side did not.";
    expect(view(overview({ coverage: supplied })).getByText(supplied)).toBeInTheDocument();
  });

  // With nothing to say about the picture, the panel says nothing about it:
  // no sentence of the interface's own stands where the read supplied none.
  it("puts no sentence of its own where the read supplied none", () => {
    const rendered = view(overview({ figures: [figure()] }));
    expect(rendered.container.querySelectorAll(".coverage-card p")).toHaveLength(0);
    expect(rendered.queryByText("Coverage totals were not supplied by this overview read. Available accounts are shown individually.")).not.toBeInTheDocument();
  });

  // Silence is not a refusal. A person who saw a total yesterday and sees an
  // empty screen today learns that the product is broken, which is worse and
  // less true than what actually happened.
  it("renders with no figure, carrying the read's own sentence and no number", () => {
    const rendered = view(overview({ coverage: moments.picture_no_figure }));
    expect(rendered.container).not.toBeEmptyDOMElement();
    expect(rendered.container.querySelectorAll(".hero-amount")).toHaveLength(0);
    expect(rendered.container.querySelectorAll(".evidence-badge")).toHaveLength(0);
    expect(rendered.getByText("Net worth")).toBeInTheDocument();
    // The answer is not a thing that went missing, so it does not borrow the
    // chrome this app uses to say something is absent.
    expect(rendered.container.querySelectorAll(".picture-empty.empty-state")).toHaveLength(0);
    // Exactly one sentence, and it stands where the number would have stood.
    // A card holding a heading and nothing else, beside a sentence in the card
    // next door, is a blank the largest object on the screen.
    const said = rendered.getAllByText(moments.picture_no_figure);
    expect(said).toHaveLength(1);
    expect(rendered.container.querySelector(".hero-card")!.contains(said[0])).toBe(true);
    expect(rendered.container.querySelectorAll(".coverage-card p")).toHaveLength(0);
  });

  // One figure per currency, under one heading, and nothing anywhere adds
  // them: no rate has a source, a date or a grade of its own.
  it("renders one figure per currency and no total across them", () => {
    for (const held of [1, 2, 3, 4]) {
      const figures = Array.from({ length: held }, (_unused, index) => figure({ id: `currency-${index}`, display: `${index}.00`, currency: `C${index}`, coverage: [`Boundary of currency ${index}.`] }));
      const rendered = view(overview({ figures }));
      expect(rendered.container.querySelectorAll(".picture-figure"), `${held} currencies`).toHaveLength(held);
      expect(rendered.container.querySelectorAll(".hero-amount"), `${held} currencies`).toHaveLength(held);
      for (const one of figures) {
        expect(rendered.getByText(one.display), one.id).toBeInTheDocument();
        expect(rendered.getByText(one.coverage[0]), one.id).toBeInTheDocument();
      }
      rendered.unmount();
    }
  });

  // Every sentence the read wrote, one line each, in the order it wrote them.
  // Sentences two figures share are left where they are: a line dropped
  // because it also appears above would be this side deciding by comparing
  // text, and the one line that differs is the last one a person reaches.
  it("gives the citation one line per sentence and drops none of the repetition", () => {
    const shared = ["A sentence both figures carry.", "A second sentence both figures carry.", "A third sentence both figures carry."];
    const first = figure({ id: "AAA", currency: "AAA", display: "AAA 1.00", coverage: ["What the AAA total is over.", ...shared, "Good as of the first day."] });
    const second = figure({ id: "BBB", currency: "BBB", display: "BBB 2.00", coverage: ["What the BBB total is over.", ...shared, "Good as of the second day."] });
    const rendered = view(overview({ figures: [first, second] }));
    const blocks = [...rendered.container.querySelectorAll(".picture-figure")];
    [first, second].forEach((one, index) => {
      const lines = [...blocks[index].querySelectorAll(".picture-citation")].map((line) => line.textContent);
      expect(lines, one.id).toEqual(one.coverage);
    });
    expect(rendered.getAllByText(shared[0])).toHaveLength(2);
  });

  // A currency whose total was kept back leaves a trace where its figure would
  // have been. Without one, the totals that remain read as the whole of what a
  // person holds.
  it("says where a kept-back currency would have been", () => {
    const sentence = moments.picture_withheld_unsayable.replace(SLOT, "BBB");
    const rendered = view(overview({ figures: [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00" })], withheld: [{ currency: "BBB", sentence }] }));
    expect(rendered.getByText(sentence)).toBeInTheDocument();
    expect(rendered.container.querySelectorAll(".picture-figure")).toHaveLength(2);
    expect(rendered.container.querySelectorAll(".hero-amount")).toHaveLength(1);
  });

  // The currency rides beside the sentence and is never read out of it. It
  // tells one kept-back currency from another, and it is what puts each one
  // where its figure would have been.
  it("tells one kept-back currency from another without reading either sentence", () => {
    const kept = ["BBB", "CCC"].map((currency) => ({ currency, sentence: moments.picture_withheld_unsayable.replace(SLOT, currency) }));
    const rendered = view(overview({ withheld: kept }));
    const blocks = [...rendered.container.querySelectorAll(".picture-withheld")].map((block) => block.textContent);
    expect(blocks).toEqual(kept.map((one) => one.sentence));
    expect(new Set(blocks).size).toBe(blocks.length);
  });

  // A currency kept back leaves its place empty, and a place is only a place
  // if the panel still renders. Both lists empty is the only state with
  // nothing to show, and it is read off two declared fields.
  it("renders the picture whenever any currency has something to say", () => {
    const kept = [{ currency: "BBB", sentence: "A currency kept back." }];
    const rendered = view(overview({ figures: [], withheld: kept, coverage: moments.picture_no_figure }));
    expect(rendered.getByText("A currency kept back.")).toBeInTheDocument();
    // The panel's own sentence is not stood in front of a currency that was
    // kept back: there is something to say, so the empty case is not the case.
    expect(rendered.queryByText(moments.picture_no_figure)).not.toBeInTheDocument();
  });

  // Two figures held in two currencies are shown in one order with the places
  // the kept-back ones would have taken left in it. Two lists each in currency
  // order, concatenated, is not one list in currency order.
  it("puts a kept-back currency in the place its figure would have taken", () => {
    const figures = [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00" }), figure({ id: "CCC", currency: "CCC", display: "CCC 3.00" })];
    const withheld = [{ currency: "BBB", sentence: "The BBB total was kept back." }];
    const rendered = view(overview({ figures, withheld, coverage: "A panel sentence." }));
    const blocks = [...rendered.container.querySelectorAll(".picture-figure")];
    expect(blocks).toHaveLength(3);
    expect(blocks[1].classList.contains("picture-withheld")).toBe(true);
    expect(blocks[1].textContent).toBe("The BBB total was kept back.");
  });

  // An account the read could not place under any currency is on no card, in
  // no line and in no drawer. Counting it and naming it nowhere is not
  // privacy: a person holding something the product recorded, that sits in no
  // total and is called nothing, cannot verify it, act on it, or discover it.
  it("names an account the picture could not place anywhere else", () => {
    const unplaced = [
      { account: "acct:one", name: "A Named Liability", sentence: "The read's sentence about why it sits in no total." },
      { account: "acct:two", name: "A Second Named Thing", sentence: "The read's sentence about the second one." },
    ];
    const rendered = view(overview({ figures: [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00" })], coverage: "The panel's one sentence about how far this reaches.", unplaced }));
    for (const left of unplaced) {
      expect(rendered.getByText(left.name), left.account).toBeInTheDocument();
      expect(rendered.getByText(left.sentence), left.account).toBeInTheDocument();
    }
    // And it is a property of the picture placed beside its coverage, not a
    // second absence sentence taking the place of the first.
    expect(rendered.getByText("The panel's one sentence about how far this reaches.")).toBeInTheDocument();
    expect(rendered.container.querySelectorAll(".picture-unplaced li")).toHaveLength(2);
  });

  // One route, in the shape every other figure on this screen uses, and no row
  // of controls whose name is the word "unavailable". The read gives a picture
  // figure's citations no labels, so a control per citation would be a stack
  // of identical buttons announcing an absence — the visual form of "every
  // number has a receipt", reading as broken links.
  it("gives the picture's figure a visible route and no unlabelled controls", () => {
    const links = [
      { targetDocumentId: "doc-1", label: "", relation: "attests" as const, page: "" },
      { targetDocumentId: "doc-2", label: "", relation: "attests" as const, page: "" },
    ];
    const said = moments.picture_evidence_label.replace(SLOT, "AAA");
    const rendered = view(overview({ figures: [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00", evidenceLabel: said, coverage: ["A boundary."], evidenceLinks: links })] }));
    expect(rendered.queryByText("Source label unavailable")).not.toBeInTheDocument();
    // Last in the block, where every other figure on this screen puts one.
    const block = rendered.container.querySelector(".picture-figure")!;
    expect(block.lastElementChild!.classList.contains("proof-links")).toBe(true);
    // The row is the precedent's: same class, same place. Its words are the
    // words the control is named by — a control cannot have two names, or a
    // person who reads the screen and a person who hears it are told about
    // different things and only one of them can be right.
    const route = [...rendered.container.querySelectorAll(".picture-figure .proof-links .proof-link")];
    expect(route).toHaveLength(1);
    expect(route[0].textContent).toBe(said);
    expect(route[0]).toHaveAccessibleName(said);
    // And it opens the figure's own evidence, which is where its sources are
    // named, because the read named none of them here.
    (route[0] as HTMLElement).click();
    expect(actions.onOpenFigure).toHaveBeenCalledWith("net-worth:AAA");
  });

  // The words on that row are the read's. Where the read wrote none there is
  // no row: a control this side had to name would be this side writing what a
  // person reads, and a refusal is the honest answer to that.
  it("renders no route where the read wrote no words for one", () => {
    const rendered = view(overview({ figures: [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00", evidenceLabel: "" })] }));
    expect(rendered.container.querySelectorAll(".picture-figure .proof-links")).toHaveLength(0);
    expect(rendered.container.querySelectorAll(".picture-figure .hero-amount")).toHaveLength(1);
  });

  // A panel earns its existence from data. It renders with a figure, with a
  // currency kept back, or with a sentence — and where the read gave it none
  // of the three it does not render, because a card holding a heading and
  // nothing else says something is missing or on its way, and that is a claim.
  it("renders the panel on any of its three grounds and on none of them does not", () => {
    for (const [ground, picture] of [
      ["a figure", { figures: [figure({ id: "AAA", currency: "AAA", display: "AAA 1.00" })] }],
      ["a currency kept back", { withheld: [{ currency: "BBB", sentence: "Kept back." }] }],
      ["a sentence", { coverage: moments.picture_no_figure }],
    ] as [string, Partial<PictureView>][]) {
      const rendered = view(overview(picture));
      expect(rendered.container.querySelectorAll(".hero-card"), ground).toHaveLength(1);
      expect(rendered.getByRole("heading", { name: "Net worth" }), ground).toBeInTheDocument();
      rendered.unmount();
    }
    const none = view(overview());
    expect(none.container.querySelectorAll(".hero-card")).toHaveLength(0);
    expect(none.queryByRole("heading", { name: "Net worth" })).not.toBeInTheDocument();
    // And the rest of the overview is untouched: one panel standing down is
    // not the screen going quiet.
    expect(none.getByText("Activity is not connected to this private-vault read.")).toBeInTheDocument();
  });

  // The badge follows the ladder word the read supplied. A word the ladder
  // does not hold renders the unavailable state rather than a guess.
  it("dresses the grade badge by the word the read supplied and guesses at none", () => {
    const known = view(overview({ figures: [figure({ grade: "corroborated" })] }));
    expect(known.container.querySelector(".evidence-badge")?.className).toContain("corroborated");
    known.unmount();
    const unknown = view(overview({ figures: [figure({ grade: "unavailable", gradeLabel: "Evidence status unavailable" })] }));
    expect(unknown.container.querySelector(".evidence-badge")?.className).toContain("unavailable");
  });

  // Two totals held in two currencies must never be conflated, and two
  // controls announcing identically conflate them at the moment a person acts
  // on one. The control is named by the amount it shows, so a person who
  // cannot see the screen hears the number rather than only an invitation to
  // leave it, and the invitation is carried beside it in the read's own words.
  it("announces each currency's figure and its drawer distinctly, in the read's own words", () => {
    const currencies = ["AAA", "BBB"];
    const figures = currencies.map((currency) => figure({
      id: currency,
      currency,
      display: `${currency} 1.00`,
      coverage: [`A boundary over ${currency}.`],
      evidenceLabel: moments.picture_evidence_label.replace(SLOT, currency),
      evidenceHeading: moments.picture_evidence_heading.replace(SLOT, currency),
    }));
    const result = overview({ figures });
    const rendered = view(result);
    const controls = [...rendered.container.querySelectorAll(".hero-amount")];
    expect(controls).toHaveLength(currencies.length);
    // The name begins with the amount, so it is heard at all, and continues
    // with what the figure is of, so two figures showing the same amount are
    // not the same announcement. Neither half is written here.
    controls.forEach((control, index) => expect(control).toHaveAccessibleName(`${figures[index].display} ${figures[index].evidenceHeading}`));
    const names = controls.map((control) => control.textContent ?? "");
    controls.forEach((control, index) => expect(control.getAttribute("aria-labelledby")?.startsWith(control.id), names[index]).toBe(true));
    // The invitation rides beside it, and it is what tells the two apart.
    const invitations = controls.map((control) => control.getAttribute("aria-describedby") ?? "");
    const announced = invitations.map((id) => rendered.container.querySelector(`[id="${id}"]`)?.textContent ?? "");
    expect(new Set(announced).size).toBe(announced.length);
    announced.forEach((name, index) => expect(name, name).toContain(currencies[index]));
    expect(announced).toEqual(figures.map((one) => one.evidenceLabel));
    rendered.unmount();

    const headings = figures.map((one) => {
      const drawer = render(<EvidenceDrawer snapshot={snapshotOf(result)} selection={{ figureId: `net-worth:${one.id}` }} onDismiss={vi.fn()} onOpenDocument={vi.fn()} renderEvidenceBadge={() => null} />);
      const title = drawer.getByRole("heading", { level: 2 }).textContent ?? "";
      drawer.unmount();
      return title;
    });
    expect(new Set(headings).size).toBe(headings.length);
    headings.forEach((title, index) => expect(title, title).toContain(currencies[index]));
    expect(headings).toEqual(figures.map((one) => one.evidenceHeading));
  });

  // No two triggers on this screen announce identically. An account card and a
  // currency's total can show the same amount, and a person acting on one has
  // to know which they are opening.
  it("announces no two triggers on the screen alike", () => {
    const shared = "EUR 642.10";
    const result: FeatureResult<OverviewData> = { state: "ready", data: {
      picture: { coverage: "A panel sentence.", readOn: "", withheld: [], unplaced: [], figures: [figure({ id: "EUR", currency: "EUR", display: shared, evidenceHeading: "Net worth in EUR" })] },
      corpusCoverage: "",
      accounts: [{ id: "acct:abroad", name: "Abroad Current", kind: "Depository", measure: "balance", exactValue: "", currency: "EUR", display: shared, grade: "verified", gradeLabel: "verified", gradeDescription: "One reviewed sentence.", note: null, asOf: "", coverage: null, provenance: null, evidenceLinks: [], state: "ready" }],
      recent: [],
    } };
    const rendered = render(<Overview {...actions} result={result} reviewResult={noReview} mode="live" selectedAccount="" />);
    const announced = [...rendered.container.querySelectorAll("button")].map((control) => (control.getAttribute("aria-labelledby") ?? "")
      .split(" ").map((id) => rendered.container.querySelector(`[id="${id}"]`)?.textContent ?? "").join(" ").trim() || control.textContent || "");
    const figuresNamed = announced.filter((name) => name.startsWith(shared));
    expect(figuresNamed.length).toBeGreaterThan(1);
    expect(new Set(figuresNamed).size, figuresNamed.join(" | ")).toBe(figuresNamed.length);
  });

  // Recent activity is deferred by decision, and the admission that stands in
  // its place stays exactly as it is until something can carry it.
  it("leaves the activity admission word for word", () => {
    expect(view(overview()).getByText("Activity is not connected to this private-vault read.")).toBeInTheDocument();
  });

  // Nothing on this screen speaks direction while the site that derives it
  // from a posted sign is still open.
  it("renders no direction on the picture", () => {
    const rendered = view(overview({ figures: [figure({ coverage: ["A boundary."] })] }));
    for (const tone of ["inflow", "outflow", "neutral"]) expect(rendered.container.querySelectorAll(`.${tone}`), tone).toHaveLength(0);
  });
});
