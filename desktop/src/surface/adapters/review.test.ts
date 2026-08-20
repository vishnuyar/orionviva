import { describe, expect, it } from "vitest";
import { adaptActionOutcome, adaptReview } from "./review";

describe("review adapter", () => {
  it("rejects malformed payloads", () => {
    expect(adaptReview(null)).toBeNull();
    expect(adaptReview([])).toBeNull();
    expect(adaptReview({})).toBeNull();
    expect(adaptReview({ wrong: [], total: 0 })).toBeNull();
    expect(adaptReview({ questions: "not-an-array" })).toBeNull();
    expect(adaptReview({ questions: [], total: "0" })).toBeNull();
    expect(adaptReview({ questions: [] })).toBeNull();
    expect(adaptReview({ questions: [{ text: "missing stable id" }], total: 1 })).toBeNull();
    expect(adaptReview({ questions: [], total: 0, tail: "invalid" })).toBeNull();
  });

  it("accepts only an explicit empty reviewed queue and count", () => {
    expect(adaptReview({ questions: [], total: 0 })).toMatchObject({ queue: [], meta: { tail: null, pending: null } });
  });

  it("keeps live questions read only", () => {
    expect(adaptReview({ questions: [{ id: "q", text: "Question" }], total: 1 })?.queue[0]).toMatchObject({ id: "q", outcome: null, disposition: null });
  });

  it("maps only actual summary fields", () => {
    const result = adaptReview({ questions: [], total: 4, tail: { count: 2, amount: "1.25" }, pending: { count: 1 }, invite: "Write an answer", answered_by_document: "A document answers this" });
    expect(result).toEqual({ queue: [], count: 4, meta: { total: 4, tail: { count: 2, amount: "1.25" }, pending: { count: 1 }, invite: "Write an answer", answeredByDocument: "A document answers this" } });
  });

  it("preserves real zero and positive summary counts exactly", () => {
    expect(adaptReview({ questions: [], total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 } })?.meta).toMatchObject({ tail: { count: 0, amount: "0" }, pending: { count: 0 } });
    expect(adaptReview({ questions: [], total: 0, tail: { count: 12, amount: "exact amount" }, pending: { count: 7 } })?.meta).toMatchObject({ tail: { count: 12, amount: "exact amount" }, pending: { count: 7 } });
  });

  it("rejects every malformed present tail count instead of defaulting to zero", () => {
    for (const count of [null, -1, 1.5, "0", Number.NaN, {}, [], true, ""]) {
      expect(adaptReview({ questions: [], total: 0, tail: { count } })).toBeNull();
    }
    for (const tail of [null, {}, [], "", false]) expect(adaptReview({ questions: [], total: 0, tail })).toBeNull();
    expect(adaptReview({ questions: [], total: 0, tail: undefined })).toBeNull();
  });

  it("rejects every malformed present pending count instead of defaulting to zero", () => {
    for (const count of [null, -1, 1.5, "0", Number.NaN, {}, [], true, ""]) {
      expect(adaptReview({ questions: [], total: 0, pending: { count } })).toBeNull();
    }
    for (const pending of [null, {}, [], "", false]) expect(adaptReview({ questions: [], total: 0, pending })).toBeNull();
    expect(adaptReview({ questions: [], total: 0, pending: undefined })).toBeNull();
  });

  it("rejects the whole review payload when either supplied summary is malformed", () => {
    expect(adaptReview({ questions: [], total: 0, tail: { count: 2, amount: "kept only if atomic" }, pending: { count: -1 } })).toBeNull();
    expect(adaptReview({ questions: [], total: 0, tail: { count: "2" }, pending: { count: 1 } })).toBeNull();
  });

  it("deduplicates questions by stable id", () => {
    const result = adaptReview({ questions: [{ id: "q2" }, { id: "q1" }, { id: "q2" }], total: 3 });
    expect(result?.queue.map((question) => question.id)).toEqual(["q2", "q1"]);
  });

  it("reads only the closed vocabulary an action answers in", () => {
    expect(adaptActionOutcome({ kind: "completed", message: "Recorded.", state: null, reason: null }))
      .toEqual({ kind: "completed", message: "Recorded.", reason: "" });
    expect(adaptActionOutcome({ kind: "refused", message: "Not now.", state: null, reason: "not_open" }))
      .toEqual({ kind: "refused", message: "Not now.", reason: "not_open" });
    for (const kind of ["proposal", "waiting", "stale"]) {
      expect(adaptActionOutcome({ kind, message: "Held.", state: null, reason: null })?.kind).toBe(kind);
    }
    for (const raw of [null, "completed", [], {}, { kind: "ok" }, { kind: "" }, { kind: "completed " }]) {
      expect(adaptActionOutcome(raw)).toBeNull();
    }
  });

  it("refuses to read a refusal that carries no machine reason", () => {
    expect(adaptActionOutcome({ kind: "refused", message: "Not recorded.", state: null, reason: null })).toBeNull();
    expect(adaptActionOutcome({ kind: "refused", message: "Not recorded.", state: null, reason: "" })).toBeNull();
  });
});
