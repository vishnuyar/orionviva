import { describe, expect, it } from "vitest";
import fixture from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
import { adaptActivity, adaptActivityActionOutcome } from "./activity";

const baseRow = {
  id: "movement:key", date: "2026-08-01", description: "corner shop", account: "acct:one", direction: "out",
  account_id: "acct:one", account_name: "Everyday account \u2022\u2022\u2022\u20221122",
  exact_value: "12.00", currency: "USD", display: "USD 12.00", nature: "spending", treatment: { kind: "spending", name: "" }, sentence: "",
  decided_by: "default", provisional: false, linked: false,
  category: { id: "groceries", label: "Groceries" }, tags: [{ id: "trip", label: "Trip" }],
  subcategory: { id: "grocery store", label: "grocery store" }, classification: { grade: "corroborated", provenance: "model" },
  evidence_links: [{ document_id: "doc-one", label: "august.pdf", relation: "attests", page: "2", region: "row-3" }],
  transfer: { state: "none" },
  actions: ["assign_category", "assign_meaning", "replace_tags"],
};
const candidate = {
  id: "movement:counterpart", date: "2026-08-02", description: "other account movement", account: "acct:two", direction: "in",
  account_id: "acct:two", account_name: "Savings \u2022\u2022\u2022\u20223344",
  exact_value: "12.00", currency: "USD", display: "USD 12.00", relationship: "Reviewed as the other side of this movement.",
};
const suggested = { state: "suggested", explanation: "A reviewed transfer suggestion is available.", candidates: [candidate], complete: true, limit: 20 };
const linked = {
  state: "linked", explanation: "This movement has a reviewed transfer link.",
  counterpart: Object.fromEntries(Object.entries(candidate).filter(([key]) => key !== "relationship")),
  relationship: "Reviewed as the linked other side of this movement.",
};
const vocabularies = {
  categories: { items: [{ id: "groceries", label: "Groceries" }, { id: "housing", label: "Housing" }], complete: true, limit: 40 },
  subcategories: { items: [{ id: "grocery store", label: "Grocery store", category_id: "groceries" }], complete: true, limit: 40 },
  tags: { items: [{ id: "trip", label: "Trip" }, { id: "tax", label: "Tax" }], complete: true, limit: 40, max_selected: 40, max_label_length: 80 },
};
function payload(over: Record<string, unknown> = {}) { return { sentence: "Everything below came off a document you added.", items: [baseRow], beyond: { count: 0 }, vocabularies, ...over }; }

describe("ActivityMovements.v3 adapter", () => {
  it("accepts only exact completed, refused, and stale Activity receipts", () => {
    expect(adaptActivityActionOutcome({ kind: "completed", message: "Recorded.", state: null, reason: null })).toEqual({ kind: "completed", message: "Recorded.", reason: "" });
    expect(adaptActivityActionOutcome({ kind: "refused", message: "Not recorded.", state: null, reason: "unknown_category" })).toEqual({ kind: "refused", message: "Not recorded.", reason: "unknown_category" });
    expect(adaptActivityActionOutcome({ kind: "stale", message: "Movement changed.", state: null, reason: "movement_missing" })).toEqual({ kind: "stale", message: "Movement changed.", reason: "movement_missing" });
  });

  it.each([
    { kind: "proposal", message: "Consider this.", state: null, reason: null },
    { kind: "waiting", message: "Wait.", state: null, reason: null },
    { kind: "set_aside", message: "Set aside.", state: null, reason: null },
    { kind: "completed", message: "Document posted.", state: { terminal_state: "posted" }, reason: null },
    { kind: "completed", message: "Recorded.", state: null, reason: null, terminal_state: "posted" },
    { kind: "completed", message: "", state: null, reason: null },
    { kind: "completed", message: "Recorded.", state: null },
    { kind: "refused", message: "Not recorded.", state: null, reason: null },
  ])("rejects an impossible or non-exact Activity receipt", (raw) => {
    expect(adaptActivityActionOutcome(raw)).toBeNull();
  });

  it("adapts complete vocabularies, current values, and only closed row actions", () => {
    const read = adaptActivity(payload({ items: [{ ...baseRow, actions: ["replace_tags", "invented", "assign_category"] }] }))!;
    expect(read.vocabularies).toEqual({ categories: { items: vocabularies.categories.items, complete: true, limit: 40 }, subcategories: { items: [{ id: "grocery store", label: "Grocery store", categoryId: "groceries" }], complete: true, limit: 40 }, tags: { items: vocabularies.tags.items, complete: true, limit: 40, maxSelected: 40, maxLabelLength: 80 } });
    expect(read.movements[0]).toMatchObject({ id: "movement:key", accountId: "acct:one", accountName: "Everyday account \u2022\u2022\u2022\u20221122", category: { id: "groceries", label: "Groceries", valid: true }, subcategory: { id: "grocery store", label: "grocery store", valid: true }, classification: { grade: "corroborated", provenance: "model" }, classificationValid: true, evidenceLinks: [{ targetDocumentId: "doc-one", label: "august.pdf", relation: "attests", page: "2", region: "row-3" }], evidenceLinksValid: true, tags: [{ id: "trip", label: "Trip" }], tagsValid: true, actions: ["assign_category", "replace_tags"] });
  });

  it("fails a malformed or duplicate parented subcategory vocabulary closed", () => {
    for (const subcategories of [
      { items: [{ id: "restaurant", label: "Restaurant", category_id: "" }], complete: true, limit: 40 },
      { items: [{ id: "restaurant", label: "Restaurant", category_id: "dining" }, { id: "restaurant", label: "Again", category_id: "dining" }], complete: true, limit: 40 },
    ]) expect(adaptActivity(payload({ vocabularies: { ...vocabularies, subcategories } }))!.vocabularies.subcategories.complete).toBe(false);
  });

  it.each([
    ["blank identity", [{ id: "", label: "Blank" }], 40],
    ["blank label", [{ id: "food", label: "" }], 40],
    ["duplicate identity", [{ id: "food", label: "Food" }, { id: "food", label: "Food again" }], 40],
    ["missing limit", [{ id: "food", label: "Food" }], undefined],
    ["short limit", [{ id: "food", label: "Food" }], 0],
  ])("fails a malformed category vocabulary closed: %s", (_label, items, limit) => {
    const categories = { items, complete: true, ...(limit === undefined ? {} : { limit }) };
    const read = adaptActivity(payload({ vocabularies: { ...vocabularies, categories } }))!;
    expect(read.vocabularies.categories.complete).toBe(false);
    expect(read.movements[0].actions).not.toContain("assign_category");
    expect(read.movements[0].display).toBe("USD 12.00");
  });

  it("withholds all controls when current category or complete current tags are malformed, while retaining safe financial data", () => {
    const rows = [
      { ...baseRow, id: "bad-category", category: { id: "groceries", label: "" }, transfer: suggested, actions: ["confirm_transfer", "reject_transfer"] },
      { ...baseRow, id: "bad-tags", tags: [{ id: "", label: "Trip" }], transfer: linked, actions: ["unlink_transfer"] },
      { ...baseRow, id: "duplicate-tags", tags: [{ id: "trip", label: "Trip" }, { id: "trip", label: "Trip" }] },
    ];
    const read = adaptActivity(payload({ items: rows }))!;
    expect(read.movements.map((row) => row.actions)).toEqual([[], [], []]);
    expect(read.movements.map((row) => row.display)).toEqual(["USD 12.00", "USD 12.00", "USD 12.00"]);
    expect(read.movements[0].category.valid).toBe(false);
    expect(read.movements[1].tagsValid).toBe(false);
  });

  it("withholds tag actions for invalid tag bounds and incomplete vocabularies", () => {
    for (const tags of [
      { ...vocabularies.tags, complete: false },
      { ...vocabularies.tags, max_selected: -1 },
      { ...vocabularies.tags, max_label_length: "80" },
    ]) {
      const read = adaptActivity(payload({ vocabularies: { ...vocabularies, tags } }))!;
      expect(read.vocabularies.tags.complete).toBe(false);
      expect(read.movements[0].actions).not.toContain("replace_tags");
    }
  });

  it("never advertises complete-set replacement when a current tag is outside the complete vocabulary", () => {
    const read = adaptActivity(payload({ items: [{ ...baseRow, tags: [{ id: "hidden", label: "Hidden" }] }] }))!;
    expect(read.movements[0].tags).toEqual([{ id: "hidden", label: "Hidden" }]);
    expect(read.movements[0].tagsValid).toBe(true);
    expect(read.movements[0].actions).not.toContain("replace_tags");
    expect(read.movements[0].actions).toContain("assign_category");
  });

  it("adapts exact none, complete suggested, and linked transfer states only from backend authority", () => {
    const read = adaptActivity(payload({ items: [
      { ...baseRow, id: "none", linked: true, actions: ["assign_category"] },
      { ...baseRow, id: "suggestion", transfer: suggested, actions: ["confirm_transfer", "reject_transfer"] },
      { ...baseRow, id: "linked", transfer: linked, actions: ["unlink_transfer"] },
    ] }))!;
    expect(read.movements[0]).toMatchObject({ linked: true, transfer: { state: "none" }, actions: ["assign_category"] });
    expect(read.movements[0].actions).not.toContain("unlink_transfer");
    expect(read.movements[1].transfer).toEqual({
      state: "suggested", explanation: suggested.explanation, complete: true, limit: 20,
      candidates: [{ id: candidate.id, date: candidate.date, description: candidate.description, account: candidate.account, accountId: candidate.account_id, accountName: candidate.account_name, direction: "in", exactValue: "12.00", currency: "USD", display: "USD 12.00", relationship: candidate.relationship }],
    });
    expect(read.movements[1].actions).toEqual(["confirm_transfer", "reject_transfer"]);
    expect(read.movements[2].transfer).toEqual({
      state: "linked", explanation: linked.explanation,
      counterpart: { id: candidate.id, date: candidate.date, description: candidate.description, account: candidate.account, accountId: candidate.account_id, accountName: candidate.account_name, direction: "in", exactValue: "12.00", currency: "USD", display: "USD 12.00" },
      relationship: linked.relationship,
    });
    expect(read.movements[2].actions).toEqual(["unlink_transfer"]);
  });

  it("keeps a valid incomplete suggestion visible but strips confirm and reject", () => {
    const read = adaptActivity(payload({ items: [{ ...baseRow, transfer: { ...suggested, complete: false }, actions: ["assign_category", "confirm_transfer", "reject_transfer"] }] }))!;
    expect(read.movements[0].transfer).toMatchObject({ state: "suggested", complete: false, explanation: suggested.explanation });
    expect(read.movements[0].actions).toEqual(["assign_category"]);
  });

  it.each([
    ["one of the required suggestion actions is absent", suggested, ["confirm_transfer"]],
    ["a suggestion action is duplicated", suggested, ["confirm_transfer", "confirm_transfer", "reject_transfer"]],
    ["a linked row advertises suggestion actions", linked, ["confirm_transfer", "reject_transfer"]],
    ["a none row advertises unlink", { state: "none" }, ["unlink_transfer"]],
  ])("strips incoherent transfer actions while preserving ordinary corrections: %s", (_label, transfer, actions) => {
    const read = adaptActivity(payload({ items: [{ ...baseRow, transfer, actions: ["assign_category", ...actions] }] }))!;
    expect(read.movements[0].actions).toEqual(["assign_category"]);
    expect(read.movements[0].display).toBe("USD 12.00");
  });

  it.each([
    ["missing field", { ...suggested, explanation: undefined }],
    ["extra field", { ...suggested, invented: true }],
    ["blank copy", { ...suggested, explanation: " " }],
    ["invalid direction", { ...suggested, candidates: [{ ...candidate, direction: "sideways" }] }],
    ["self candidate", { ...suggested, candidates: [{ ...candidate, id: baseRow.id }] }],
    ["duplicate candidate", { ...suggested, candidates: [candidate, candidate] }],
    ["over limit", { ...suggested, candidates: [candidate], limit: 0 }],
    ["complete empty enumeration", { ...suggested, candidates: [] }],
    ["linked self counterpart", { ...linked, counterpart: { ...linked.counterpart, id: baseRow.id } }],
    ["unknown state", { state: "maybe" }],
  ])("fails malformed transfer authority closed without losing safe financial data: %s", (_label, transfer) => {
    const read = adaptActivity(payload({ items: [{ ...baseRow, transfer, actions: ["assign_category", "confirm_transfer", "reject_transfer", "unlink_transfer"] }] }))!;
    expect(read.movements[0].transfer).toBeNull();
    expect(read.movements[0].actions).toEqual(["assign_category"]);
    expect(read.movements[0].display).toBe("USD 12.00");
  });

  it("rejects the Activity payload atomically when any row lacks complete separate account identity", () => {
    expect(adaptActivity(payload({ items: [{ ...baseRow, account_id: undefined }] }))).toBeNull();
    expect(adaptActivity(payload({ items: [{ ...baseRow, account_name: "" }] }))).toBeNull();
    expect(adaptActivity(payload({ items: [{ ...baseRow, account_id: "acct:different" }] }))).toBeNull();
    expect(adaptActivity(payload({ items: [baseRow, { ...baseRow, id: "hidden", account_id: 7 }] }))).toBeNull();
  });

  it.each([
    ["malformed subcategory", { subcategory: { id: "grocery store", label: "" } }],
    ["unknown classification grade", { classification: { grade: "certain", provenance: "model" } }],
    ["missing classification provenance", { classification: { grade: "verified" } }],
  ])("fails malformed classification metadata closed while retaining the row: %s", (_label, over) => {
    const row = adaptActivity(payload({ items: [{ ...baseRow, ...over }] }))!.movements[0];
    expect(row.actions).toEqual([]);
    if ("subcategory" in over) expect(row.subcategory.valid).toBe(false);
    else expect(row.classificationValid).toBe(false);
  });

  it.each([
    ["subcategory without category", { category: { id: null, label: "Uncategorized" }, subcategory: { id: "grocery store", label: "grocery store" } }],
    ["category without provenance", { classification: null }],
    ["provenance without category", { category: { id: null, label: "Uncategorized" }, subcategory: { id: null, label: "" } }],
  ])("withholds actions for an incoherent compound classification: %s", (_label, over) => {
    const row = adaptActivity(payload({ items: [{ ...baseRow, ...over }] }))!.movements[0];
    expect(row.actions).toEqual([]);
    expect(row.classificationValid).toBe(false);
  });

  it("distinguishes an absent subcategory from malformed and absent source links from an explicit empty set", () => {
    const rows = adaptActivity(payload({ items: [
      { ...baseRow, id: "absent-subcategory", subcategory: { id: null, label: "" }, evidence_links: [] },
      { ...baseRow, id: "missing-links", evidence_links: undefined },
    ] }))!.movements;
    expect(rows[0].subcategory).toEqual({ id: null, label: "", valid: true });
    expect(rows[0]).toMatchObject({ evidenceLinks: [], evidenceLinksValid: true });
    expect(rows[1]).toMatchObject({ evidenceLinks: [], evidenceLinksValid: false });
  });

  it.each([
    ["malformed", [{ document_id: "doc-one", label: "one.pdf", relation: "invented", page: "1", region: "" }]],
    ["duplicate", [baseRow.evidence_links[0], baseRow.evidence_links[0]]],
  ])("withholds a %s movement evidence set atomically", (_label, evidence_links) => {
    const row = adaptActivity(payload({ items: [{ ...baseRow, evidence_links }] }))!.movements[0];
    expect(row.evidenceLinks).toEqual([]);
    expect(row.evidenceLinksValid).toBe(false);
  });
});

describe("Activity parity artifact", () => {
  it("adapts the exact backend-produced Activity v3 bytes, including reviewed transfer authority", () => {
    const artifact = fixture as { artifact: string; reads: { activity: { result: { data: unknown } } } };
    const raw = artifact.reads.activity.result.data as { items: Array<{
      id: string; account_id: string; account_name: string;
      category: { id: string | null; label: string };
      subcategory: { id: string | null; label: string };
      classification: { grade: "verified" | "corroborated" | "unverified" | "conflicted"; provenance: string } | null;
      evidence_links: Array<{ document_id: string; label: string; relation: "attests"; page: string; region: string }>;
      tags: Array<{ id: string; label: string }>; transfer: unknown; actions: string[];
    }>; vocabularies: unknown };
    const read = adaptActivity(raw)!;
    expect(artifact.artifact).toBe("orionviva.overview-parity-v1");
    expect(read.movements.map((row) => ({
      id: row.id, account_id: row.accountId, account_name: row.accountName,
      category: { id: row.category.id, label: row.category.label },
      subcategory: { id: row.subcategory.id, label: row.subcategory.label },
      classification: row.classification,
      evidence_links: row.evidenceLinks.map((link) => ({ document_id: link.targetDocumentId, label: link.label, relation: link.relation, page: link.page, region: link.region })),
      tags: row.tags, actions: row.actions,
    }))).toEqual(raw.items.map((row) => ({ id: row.id, account_id: row.account_id, account_name: row.account_name, category: row.category, subcategory: row.subcategory, classification: row.classification, evidence_links: row.evidence_links, tags: row.tags, actions: row.actions })));
    const authoritative = raw.items.find((row) => row.classification !== null && row.subcategory.id !== null && row.evidence_links.length > 0)!;
    expect(authoritative, "the generated vault must exercise classification, subcategory, and evidence with an authoritative ledger row").toBeDefined();
    expect(authoritative.account_id.trim()).not.toBe("");
    expect(authoritative.account_name.trim()).not.toBe("");
    expect(read.movements.map((row) => row.transfer?.state)).toEqual(raw.items.map((row) => (row.transfer as { state: string }).state));
    const suggestion = read.movements.find((row) => row.transfer?.state === "suggested")?.transfer;
    const liveSuggestion = raw.items.find((row) => (row.transfer as { state: string }).state === "suggested")?.transfer as typeof suggested;
    expect(suggestion).toMatchObject({ state: "suggested", explanation: liveSuggestion.explanation, complete: true, limit: 20 });
    if (suggestion?.state === "suggested") expect(suggestion.candidates[0].relationship).toBe(liveSuggestion.candidates[0].relationship);
    const liveLink = raw.items.find((row) => (row.transfer as { state: string }).state === "linked")?.transfer as typeof linked;
    expect(read.movements.find((row) => row.transfer?.state === "linked")?.transfer).toMatchObject({ state: "linked", explanation: liveLink.explanation, relationship: liveLink.relationship });
    expect(read.vocabularies.categories.items).toEqual((raw.vocabularies as { categories: { items: unknown[] } }).categories.items);
    expect(read.vocabularies.tags.items).toEqual((raw.vocabularies as { tags: { items: unknown[] } }).tags.items);
  });
});
