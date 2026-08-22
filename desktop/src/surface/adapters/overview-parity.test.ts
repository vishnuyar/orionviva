import { describe, expect, it } from "vitest";
// The same bytes the Python half reads, produced by running the real provider
// through the real dispatch. This side never authors them: a fixture written
// here would describe the contract this side wished for rather than the one
// the backend serves, and two sides each held to their own description agree
// with themselves while disagreeing with each other.
import fixture from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
// The sentences the product ships, read from the pack that ships them. The
// bytes above were composed by the backend out of this pack, so comparing one
// against the other is a claim about provenance rather than a claim that two
// strings this side wrote happen to agree: change a line here and these bytes
// no longer match it.
import moments from "../../../../product/viva/persona/pack-v30/moments.json";
import { resolveEvidenceTarget } from "../evidence";
import type { DocumentsData, FeatureResult } from "../types";
import { adaptDocuments } from "./documents";
import { adaptOverview, adaptOverviewPanel } from "./overview";

const artifact = fixture as {
  artifact: string;
  protocol: string;
  reads: Record<string, { ok: boolean; result: { data: unknown } }>;
};

const overviewPayload = artifact.reads.overview.result.data;
// The rows as the backend wrote them, so every assertion below can compare
// what the interface shows against what it was given rather than against
// something restated here.
const payloadRows = new Map((overviewPayload as { accounts: Array<Record<string, any>> }).accounts.map((row) => [String(row.account), row]));
const documentsPayload = artifact.reads.documents.result.data;
const overview = adaptOverview(overviewPayload);
const documents: FeatureResult<DocumentsData> = { state: "ready", data: adaptDocuments(documentsPayload)! };
const MEASURES = ["balance", "owed"];
// The picture block the same read composed, as the backend wrote it.
const payloadPicture = (overviewPayload as { picture: { coverage: string; read_on: string; withheld: Array<Record<string, any>>; unplaced: Array<Record<string, any>>; figures: Array<Record<string, any>> } }).picture;
const LADDER = ["verified", "corroborated", "unverified", "conflicted"];

describe("the documents a real vault produces, read by the real adapter", () => {
  const rows = (documentsPayload as { documents: Array<Record<string, unknown>> }).documents;
  const sentence = (documentsPayload as { reading_sentence: string }).reading_sentence;

  it("carries the panel sentence the backend wrote, and writes none of its own", () => {
    expect(documents.state).toBe("ready");
    expect(documents.state === "ready" && documents.data.readingSentence).toBe(sentence);
  });

  it("names each row by the file the vault recorded, and carries its reading word unchanged", () => {
    expect(documents.state === "ready" && documents.data.documents.map((document) => document.name)).toEqual(rows.map((row) => row.filename));
    expect(documents.state === "ready" && documents.data.documents.map((document) => document.reading)).toEqual(rows.map((row) => row.reading));
    expect(documents.state === "ready" && documents.data.documents.map((document) => document.id)).toEqual(rows.map((row) => row.id));
  });
});

describe("the overview a real vault produces, read by the real adapter", () => {
  it("is the artifact this contract is written over", () => {
    expect(artifact.artifact).toBe("orionviva.overview-parity-v1");
    expect(artifact.reads.overview.ok).toBe(true);
    expect(overview).not.toBeNull();
    expect(overview!.accounts.length).toBe(8);
  });

  it("shows a person a number on every account", () => {
    for (const account of overview!.accounts) {
      expect(account.display.trim(), account.id).not.toBe("");
      expect(account.exactValue.trim(), account.id).not.toBe("");
      expect(account.currency.trim(), account.id).not.toBe("");
      expect(MEASURES, account.id).toContain(account.measure);
      expect(account.asOf.trim(), account.id).not.toBe("");
      expect(account.coverage?.trim() ?? "", account.id).not.toBe("");
      expect(account.exactness?.trim() ?? "", account.id).not.toBe("");
      expect(account.recordIds?.length ?? 0, account.id).toBeGreaterThan(0);
      expect(account.state, account.id).toBe("ready");
    }
  });

  it("writes no display string of its own", () => {
    for (const account of overview!.accounts) {
      expect(account.display).toBe(payloadRows.get(account.id)!.balance.display);
      expect(account.exactValue).toBe(payloadRows.get(account.id)!.balance.exact_value);
      expect(account.coverage).toBe(payloadRows.get(account.id)!.balance.coverage);
    }
  });

  it("gives every figure a route to the records the backend named, and claims nothing beside them", () => {
    for (const account of overview!.accounts) {
      const cited = payloadRows.get(account.id)!.balance.citations as Array<Record<string, string>>;
      expect(account.evidenceLinks.length, account.id).toBeGreaterThan(0);
      expect(account.evidenceLinks.length, account.id).toBe(cited.length);
      account.evidenceLinks.forEach((link, index) => {
        const target = resolveEvidenceTarget(documents, link.targetDocumentId);
        expect(target.state, `${account.id} → ${link.targetDocumentId}`).toBe("ready");
        // Every part of the citation is the backend's, including the parts it
        // left empty: a page or a label supplied here would be this side
        // saying where a number was printed.
        expect(link.targetDocumentId, account.id).toBe(cited[index].document_id);
        expect(link.relation, account.id).toBe(cited[index].relation);
        expect(link.page, account.id).toBe(cited[index].page);
        expect(link.label, account.id).toBe(cited[index].label);
      });
    }
  });

  it("shows the reviewed grade sentence the backend wrote, never one composed here", () => {
    for (const account of overview!.accounts) {
      const balance = payloadRows.get(account.id)!.balance;
      expect(LADDER, account.id).toContain(account.grade);
      // The ladder word and the whole reviewed sentence are two different
      // fields, and both are the backend's bytes. A sentence built here out
      // of the ladder word would differ from the one it was given, however
      // consistently it was built.
      expect(account.grade, account.id).toBe(balance.grade);
      expect(account.gradeLabel, account.id).toBe(balance.grade_label);
      expect(account.gradeDescription, account.id).toBe(balance.grade_description);
      expect(account.note, account.id).toBe(balance.grade_description);
      expect(account.gradeDescription.trim(), account.id).not.toBe("");
      expect(account.gradeDescription, account.id).not.toContain(`is ${account.gradeLabel}.`);
    }
  });

  it("states each figure's own boundary and no vault-wide count", () => {
    const coverages = overview!.accounts.map((account) => account.coverage);
    expect(new Set(coverages).size).toBe(coverages.length);
    for (const account of overview!.accounts) {
      expect(account.coverage, account.id).toContain(account.name);
      expect(account.coverage, account.id).toContain(account.asOf);
    }
  });

  it("lists no ledger bucket as an account", () => {
    for (const account of overview!.accounts) {
      expect(account.id.startsWith("Expenses:") || account.id.startsWith("Income:"), account.id).toBe(false);
    }
  });

  // The picture is not withheld on a vault that carries a document added and
  // not counted and an account the read could not value: those are exactly the
  // shapes the coverage sentence exists to disclose, and a picture that goes
  // blank in their presence is the way this ships something that blanks on a
  // real vault.
  it("shows a figure for every currency the picture reached, withholding none", () => {
    expect(payloadPicture.figures.length).toBeGreaterThan(1);
    expect(overview!.picture.figures.length).toBe(payloadPicture.figures.length);
    const currencies = overview!.picture.figures.map((figure) => figure.currency);
    expect(new Set(currencies).size).toBe(currencies.length);
    for (const figure of overview!.picture.figures) {
      expect(figure.measure, figure.id).toBe("net_worth");
      expect(figure.display.trim(), figure.id).not.toBe("");
      expect(figure.currency.trim(), figure.id).not.toBe("");
      expect(figure.asOf.trim(), figure.id).not.toBe("");
      expect(figure.coverage.length, figure.id).toBeGreaterThan(0);
      for (const sentence of figure.coverage) expect(sentence.trim(), figure.id).not.toBe("");
      expect(LADDER, figure.id).toContain(figure.grade);
      expect(figure.recordIds?.length ?? 0, figure.id).toBeGreaterThan(0);
      expect(figure.evidenceLinks.length, figure.id).toBeGreaterThan(0);
    }
  });

  it("writes no part of the picture, and adds no figure to any other", () => {
    expect(overview!.picture.coverage).toBe(payloadPicture.coverage);
    expect(overview!.picture.readOn).toBe(payloadPicture.read_on);
    // Every currency the read kept back reaches this side. A bare sentence
    // with no currency beside it carries no sentence this adapter can read, so
    // a transport that changed shape loses entries here rather than rendering
    // a blank where a total would have been.
    expect(overview!.picture.withheld.length).toBe(payloadPicture.withheld.length);
    payloadPicture.withheld.forEach((kept, index) => {
      expect(String(kept.currency ?? "").trim(), `withheld ${index}`).not.toBe("");
      expect(String(kept.sentence ?? "").trim(), `withheld ${index}`).not.toBe("");
      expect(overview!.picture.withheld[index]).toEqual({ currency: kept.currency, sentence: kept.sentence });
    });
    // The loop above walks nothing on this vault, and a loop over an empty set
    // reports a clean bill it could not have withheld. So the emptiness is
    // stated rather than assumed: the shape is walked non-empty by the
    // adapter's own case over a synthetic payload, and the day a real read
    // keeps a currency back, this line goes red and the loop above becomes a
    // check rather than a claim.
    expect(payloadPicture.withheld, "no currency is kept back on this vault; the shape is walked in the adapter's own case").toEqual([]);
    expect(overview!.picture.coverage.trim()).not.toBe("");
    overview!.picture.figures.forEach((figure, index) => {
      const written = payloadPicture.figures[index];
      expect(figure.id).toBe(written.id);
      expect(figure.display).toBe(written.display);
      expect(figure.exactValue).toBe(written.exact_value);
      expect(figure.coverage).toEqual(written.coverage);
      expect(figure.gradeDescription).toBe(written.grade_description);
    });
    // One display per currency and nothing standing for their sum: no rate has
    // a source, a date or a grade of its own, so there is no such number to
    // show and none is composed here or asserted here.
    const displays = overview!.picture.figures.map((figure) => figure.display);
    expect(new Set(displays).size).toBe(displays.length);
  });

  // Two totals in two currencies must never be conflated, so the read writes
  // each figure its own two announcement sentences: what the control that
  // opens its evidence says, and what the drawer it opens is titled. Composed
  // on this side they would be the same words twice, which is the conflation
  // the two figures exist to prevent.
  it("carries an announcement for each figure that names only that figure", () => {
    const labels = overview!.picture.figures.map((figure) => figure.evidenceLabel ?? "");
    const headings = overview!.picture.figures.map((figure) => figure.evidenceHeading ?? "");
    overview!.picture.figures.forEach((figure, index) => {
      expect(labels[index].trim(), `${figure.id} has no evidence_label in the picture the read composed`).not.toBe("");
      expect(headings[index].trim(), `${figure.id} has no evidence_heading in the picture the read composed`).not.toBe("");
    });
    expect(new Set(labels).size).toBe(labels.length);
    expect(new Set(headings).size).toBe(headings.length);
    overview!.picture.figures.forEach((figure, index) => {
      expect(labels[index], figure.id).toContain(figure.currency);
      expect(headings[index], figure.id).toContain(figure.currency);
      expect(labels[index], figure.id).toBe(payloadPicture.figures[index].evidence_label);
      expect(headings[index], figure.id).toBe(payloadPicture.figures[index].evidence_heading);
    });
  });

  // The accounts the read could not value reach the figure's own evidence, each
  // named and each carrying the read's own sentence for why it is not in the
  // total. The panel sentence counts them and never names them; a figure that
  // renders and does not disclose them passes every test about withholding and
  // still leaves a person a total short of the accounts it was never over.
  it("carries every account the read could not value, with the sentence the read wrote for it", () => {
    const declared = payloadPicture.figures.map((figure) => (figure.unmeasured ?? []) as Array<Record<string, string>>);
    expect(declared.some((left) => left.length > 0)).toBe(true);
    overview!.picture.figures.forEach((figure, index) => {
      expect(figure.unmeasured ?? [], figure.id).toEqual(declared[index]);
      for (const left of figure.unmeasured ?? []) {
        expect(left.account.trim(), figure.id).not.toBe("");
        expect(left.sentence.trim(), figure.id).not.toBe("");
        // The name arrives written. Nothing on this side turns a ledger path
        // into something to show a person.
        expect(left.name.trim(), figure.id).not.toBe("");
        expect(left.name, figure.id).not.toBe(left.account);
      }
    });
    // And each of them is an account the same read carried a row for, so the
    // drawer names it rather than printing an identity at a person.
    const rows = new Set(overview!.accounts.map((account) => account.id));
    for (const figure of overview!.picture.figures) for (const left of figure.unmeasured ?? []) expect(rows.has(left.account), left.account).toBe(true);
  });

  // What would settle a refused gap is unreviewed ledger text. It rides the
  // boundary the read declared and reaches a person by no route through here.
  // The fields the picture carries are a closed set, asserted whole: a search
  // for the machinery's own words would miss the same value carried under a
  // harmless name, and on this fixture that value is empty, so a search has
  // nothing to find and would report a clean bill it could not have withheld.
  it("carries the picture's declared fields and nothing else", () => {
    const declared = payloadPicture.figures.flatMap((figure) => (figure.boundary?.unmeasured ?? []) as Array<Record<string, unknown>>);
    expect(declared.length).toBeGreaterThan(0);
    expect(declared.some((row) => "settled_by" in row)).toBe(true);
    expect(Object.keys(overview!.picture).sort()).toEqual(["coverage", "figures", "readOn", "unplaced", "withheld"]);
    // An account beneath no figure says the same three things a figure's own
    // omission says. The token the read decided under chose the sentence and
    // stays where it did that work: a machine token sitting in a payload is a
    // standing invitation for an interface to branch on it, and a field that
    // is not there cannot be branched on. Held in both directions, so adding
    // it back on either side is red.
    for (const left of payloadPicture.unplaced) expect(Object.keys(left as Record<string, unknown>).sort()).toEqual(["account", "name", "sentence"]);
    for (const left of overview!.picture.unplaced) expect(Object.keys(left).sort(), left.account).toEqual(["account", "name", "sentence"]);
    // And this vault has one, so the two loops above walked something.
    expect(payloadPicture.unplaced.length).toBeGreaterThan(0);
    for (const figure of overview!.picture.figures) {
      expect(Object.keys(figure).sort(), figure.id).toEqual([
        "asOf", "caveats", "coverage", "currency", "display", "evidenceHeading", "evidenceLabel",
        "evidenceLinks", "exactValue", "exactness", "grade", "gradeDescription", "gradeLabel",
        "id", "measure", "recordIds", "unmeasured",
      ]);
      for (const left of figure.unmeasured ?? []) expect(Object.keys(left).sort(), left.account).toEqual(["account", "name", "sentence"]);
    }
  });

  // Every picture sentence the committed payload carries, against the pack that
  // ships it. Nothing here retypes a sentence and nothing feeds a pack line in
  // and asserts it comes back out — a test built that way agrees with itself
  // whatever the pack says, and that tautology is what let a pack change leave
  // this suite green while three sentences of nineteen were actually held.
  //
  // A sentence the payload does not carry cannot be compared from this side at
  // all. That is a fact about the fixture, not a gap in the gate, so the ones
  // it cannot reach are listed with the reason each is absent — and the day a
  // read produces one, the list goes red and it joins the comparison.
  const PICTURE_LINES = Object.entries(moments).filter(([key]) => key.startsWith("picture_")) as [string, string][];

  // A pack line as the shape of the sentence it produces: its fixed words
  // exactly, its slots standing for whatever the read put in them.
  function saidBy(sentence: string): string[] {
    const metacharacter = new RegExp("[.*+?^${}()|[\\]\\\\]", "g");
    return PICTURE_LINES.filter(([, line]) => {
      const shape = line.split(new RegExp("\\{\\w+\\}")).map((fixed) => fixed.replace(metacharacter, "\\$&")).join("(.+?)");
      return new RegExp(`^${shape}$`).test(sentence);
    }).map(([key]) => key);
  }

  // Where the payload puts a sentence a person reads, and what it put there.
  function picturePayloadSentences(): [string, string][] {
    const said: [string, string][] = [["coverage", payloadPicture.coverage]];
    for (const kept of payloadPicture.withheld) said.push(["withheld.sentence", String(kept.sentence)]);
    for (const left of payloadPicture.unplaced) said.push(["unplaced.sentence", String(left.sentence)]);
    for (const figure of payloadPicture.figures) {
      const currency = String(figure.currency);
      (figure.coverage as string[]).forEach((line, index) => said.push([`figures[${currency}].coverage[${index}]`, line]));
      for (const left of (figure.unmeasured ?? []) as Array<Record<string, string>>) said.push([`figures[${currency}].unmeasured.sentence`, left.sentence]);
      said.push([`figures[${currency}].evidence_label`, String(figure.evidence_label)]);
      said.push([`figures[${currency}].evidence_heading`, String(figure.evidence_heading)]);
    }
    return said;
  }

  // The lines no read on this vault produces, and why each one is out of
  // reach. Every entry is a branch the fixture does not take, so the moment it
  // takes one this list is wrong and says so.
  const OUT_OF_REACH = new Map([
    ["picture_accounts_all", "this vault counts 7 of 9, so the panel takes the some branch"],
    ["picture_accounts_all_incomplete", "same branch, and nothing here is complete-but-short"],
    ["picture_accounts_one", "more than one account is counted"],
    ["picture_boundary_unmeasured_many", "each figure leaves out exactly one account, so the one branch is taken"],
    ["picture_boundary_unposted_many", "exactly one document is added and not counted"],
    ["picture_no_figure", "the picture stands behind two totals, so it never says it has none"],
    ["picture_withheld_unsayable", "no currency is kept back on this vault"],
    ["picture_unmeasured_refused", "the one account a figure leaves out was never observed, not refused"],
    ["picture_unplaced_unobserved", "the one account under no figure was refused, not unobserved"],
  ]);

  it("says every picture sentence the payload carries in the pack's own words", () => {
    const said = picturePayloadSentences();
    expect(said.length).toBeGreaterThan(0);
    const covered = new Set<string>();
    const matched: string[] = [];
    for (const [where, sentence] of said) {
      const keys = saidBy(sentence);
      // Exactly one: none means the sentence is not the pack's, and more than
      // one means two lines the pack ships cannot be told apart.
      expect(keys, `${where}: ${sentence}`).toHaveLength(1);
      matched.push(...keys);
      for (const key of keys) covered.add(key);
    }
    // One match per sentence, counted rather than gathered. A set hides a bad
    // occurrence behind a good one whenever both say the same pack line, and
    // two figures saying the same line is the ordinary case here — so the
    // count is what holds it, independently of the check above.
    expect(matched.length, "every sentence matched exactly one line").toBe(said.length);
    const uncovered = PICTURE_LINES.map(([key]) => key).filter((key) => !covered.has(key));
    expect([...covered].sort()).toEqual(PICTURE_LINES.map(([key]) => key).filter((key) => !OUT_OF_REACH.has(key)).sort());
    expect(uncovered.sort(), "every line this vault cannot produce is listed with its reason").toEqual([...OUT_OF_REACH.keys()].sort());
    expect(covered.size + uncovered.length).toBe(PICTURE_LINES.length);
  });

  // An account under no figure, on the one vault that has one. It is on no
  // card, in no line and in no drawer: the accounts read never names it,
  // because there is nothing to open it with, and no figure is beneath it.
  // Counting it in the denominator and naming it nowhere is not privacy.
  it("carries an account beneath no figure, named, and reaches it from nowhere else", () => {
    const declared = payloadPicture.unplaced;
    expect(declared.length).toBeGreaterThan(0);
    expect(overview!.picture.unplaced).toEqual(declared);
    const rows = new Set(overview!.accounts.map((account) => account.id));
    const beneath = new Set(overview!.picture.figures.flatMap((figure) => (figure.unmeasured ?? []).map((left) => left.account)));
    for (const left of overview!.picture.unplaced) {
      expect(left.name.trim(), left.account).not.toBe("");
      expect(left.sentence.trim(), left.account).not.toBe("");
      // On no card, and beneath no figure. Those are the two places a person
      // could otherwise have found it, and the reason the panel names it.
      expect(rows.has(left.account), `${left.account} is on a card`).toBe(false);
      expect(beneath.has(left.account), `${left.account} is beneath a figure`).toBe(false);
    }
  });

  // The picture's citation names records and claims no page: the read holds
  // the page of one part, and a part's page offered as the page of a whole is
  // a claim about evidence the record does not support.
  it("routes the picture to documents the same read holds, and claims no page", () => {
    for (const figure of overview!.picture.figures) {
      for (const link of figure.evidenceLinks) {
        expect(resolveEvidenceTarget(documents, link.targetDocumentId).state, `${figure.id} → ${link.targetDocumentId}`).toBe("ready");
        expect(link.page, figure.id).toBe("");
      }
    }
  });

  it("reports the panel state the read declared", () => {
    const withheld = overview!.accounts.filter((account) => account.state !== "ready");
    const panel = adaptOverviewPanel(overviewPayload);
    expect(panel.state).toBe(withheld.length ? "partial" : "ready");
    expect(panel.issues.length).toBe(withheld.length);
  });
});
