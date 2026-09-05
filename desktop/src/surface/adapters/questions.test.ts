import { describe, expect, it } from "vitest";
import fixture from "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
import { adaptActionOutcome, adaptQuestions } from "./questions";

const reviewBinding = () => ({
  item_id: "question:q", question_id: "q", question_kind: "identity",
  label: "Question", reason: "The records do not say.",
  refs: { movement: "", movements: [], candidates: [], document: "doc-1", doc_id: "doc-1", account: "" },
  target: { kind: "conversation", question_id: "q", disclosure: "No exact transaction was supplied." },
  status: "open", primary_action: "open_question", allowed_actions: ["open_question"],
});

describe("review adapter", () => {
  it("rejects malformed payloads", () => {
    expect(adaptQuestions(null)).toBeNull();
    expect(adaptQuestions([])).toBeNull();
    expect(adaptQuestions({})).toBeNull();
    expect(adaptQuestions({ wrong: [], total: 0 })).toBeNull();
    expect(adaptQuestions({ questions: "not-an-array" })).toBeNull();
    expect(adaptQuestions({ questions: [], total: "0" })).toBeNull();
    expect(adaptQuestions({ questions: [] })).toBeNull();
    expect(adaptQuestions({ questions: [{ text: "missing stable id" }], total: 1 })).toBeNull();
    expect(adaptQuestions({ questions: [], total: 0, tail: "invalid" })).toBeNull();
  });

  it("accepts only an explicit empty reviewed queue and count", () => {
    expect(adaptQuestions({ questions: [], total: 0 })).toMatchObject({ queue: [], meta: { tail: null, pending: null } });
  });

  it("keeps live questions read only", () => {
    expect(adaptQuestions({ questions: [{ id: "q", text: "Question" }], total: 1 })?.queue[0]).toMatchObject({ id: "q", outcome: null, disposition: null });
  });

  it("accepts only a closed Review binding that repeats the exact question semantics", () => {
    const question = { id: "q", kind: "identity", text: "Question", why: "The records do not say.", refs: { document: "doc-1", doc_id: "doc-1" }, review_binding: reviewBinding() };
    expect(adaptQuestions({ questions: [question], total: 1 })?.queue[0].reviewBinding).toMatchObject({ questionId: "q", label: "Question", refs: { document: "doc-1", documentId: "doc-1" } });
    for (const binding of [
      { ...reviewBinding(), surprise: true },
      { ...reviewBinding(), label: "Changed" },
      { ...reviewBinding(), reason: "Changed" },
      { ...reviewBinding(), refs: { ...reviewBinding().refs, document: "doc-2" } },
      { ...reviewBinding(), primary_action: "open_transaction" },
    ]) expect(adaptQuestions({ questions: [{ ...question, review_binding: binding }], total: 1 })).toBeNull();
  });

  it("carries movement, transfer, document, and account references without translating their identities", () => {
    const refs = { movement: "movement:one", movements: ["movement:one", "movement:two"], candidates: ["movement:three"], document: "statement", doc_id: "doc-one", account: "acct:one" };
    expect(adaptQuestions({ questions: [{ id: "q", kind: "transfer", refs }], total: 1 })?.queue[0].refs).toEqual(refs);
  });

  it("distinguishes absent references, an explicit empty reference object, and explicit empty movement sets", () => {
    const queue = adaptQuestions({ questions: [
      { id: "absent" },
      { id: "empty-object", refs: {} },
      { id: "empty-sets", refs: { movements: [] } },
    ], total: 3 })!.queue;
    expect("refs" in queue[0]).toBe(false);
    expect(queue[1].refs).toEqual({});
    expect(queue[2].refs).toEqual({ movements: [] });
  });

  it.each([
    ["missing object", null],
    ["blank movement", { movement: "" }],
    ["malformed movement list", { movements: "movement:one" }],
    ["malformed candidate", { candidates: ["movement:one", 2] }],
    ["duplicate movement", { movements: ["movement:one", "movement:one"] }],
    ["duplicate candidate", { candidates: ["movement:two", "movement:two"] }],
    ["blank account", { account: " " }],
  ])("rejects a present malformed or duplicate reference set atomically: %s", (_label, refs) => {
    expect(adaptQuestions({ questions: [{ id: "q", refs }], total: 1 })).toBeNull();
  });

  it.each([
    ["scalar absent from list", "nature", { movement: "movement:one", movements: ["movement:two"] }],
    ["candidates without source", "merchant", { candidates: ["movement:two"] }],
    ["source repeated as candidate", "transfer", { movement: "movement:one", candidates: ["movement:one"] }],
    ["transfer without candidates", "transfer", { movement: "movement:one" }],
    ["transfer with empty candidates", "transfer", { movement: "movement:one", candidates: [] }],
  ])("rejects an incoherent relationship between question references: %s", (_label, kind, refs) => {
    expect(adaptQuestions({ questions: [{ id: "q", kind, refs }], total: 1 })).toBeNull();
  });

  it("does not impose transfer-only completeness on coherent non-transfer references", () => {
    expect(adaptQuestions({ questions: [
      { id: "one", kind: "nature", refs: { movement: "movement:one" } },
      { id: "many", kind: "merchant", refs: { movements: ["movement:two"] } },
    ], total: 2 })?.queue.map((question) => question.refs)).toEqual([
      { movement: "movement:one" }, { movements: ["movement:two"] },
    ]);
  });

  it("maps only actual summary fields", () => {
    const questions = [{ id: "q-1" }, { id: "q-2" }];
    const result = adaptQuestions({ questions, total: 4, tail: { count: 2, amount: "1.25" }, pending: { count: 1 }, invite: "Write an answer", answered_by_document: "A document answers this" });
    expect(result).toMatchObject({ count: 4, queue: [{ id: "q-1" }, { id: "q-2" }], meta: { total: 4, tail: { count: 2, amount: "1.25" }, pending: { count: 1 }, invite: "Write an answer", answeredByDocument: "A document answers this" } });
  });

  it("preserves real zero and positive summary counts exactly", () => {
    expect(adaptQuestions({ questions: [], total: 0, tail: { count: 0, amount: "0" }, pending: { count: 0 } })?.meta).toMatchObject({ tail: { count: 0, amount: "0" }, pending: { count: 0 } });
    expect(adaptQuestions({ questions: [], total: 12, tail: { count: 12, amount: "exact amount" }, pending: { count: 7 } })?.meta).toMatchObject({ tail: { count: 12, amount: "exact amount" }, pending: { count: 7 } });
  });

  it("rejects every malformed present tail count instead of defaulting to zero", () => {
    for (const count of [null, -1, 1.5, "0", Number.NaN, {}, [], true, ""]) {
      expect(adaptQuestions({ questions: [], total: 0, tail: { count } })).toBeNull();
    }
    for (const tail of [null, {}, [], "", false]) expect(adaptQuestions({ questions: [], total: 0, tail })).toBeNull();
    expect(adaptQuestions({ questions: [], total: 0, tail: undefined })).toBeNull();
  });

  it("rejects every malformed present pending count instead of defaulting to zero", () => {
    for (const count of [null, -1, 1.5, "0", Number.NaN, {}, [], true, ""]) {
      expect(adaptQuestions({ questions: [], total: 0, pending: { count } })).toBeNull();
    }
    for (const pending of [null, {}, [], "", false]) expect(adaptQuestions({ questions: [], total: 0, pending })).toBeNull();
    expect(adaptQuestions({ questions: [], total: 0, pending: undefined })).toBeNull();
  });

  it("rejects the whole review payload when either supplied summary is malformed", () => {
    expect(adaptQuestions({ questions: [], total: 0, tail: { count: 2, amount: "kept only if atomic" }, pending: { count: -1 } })).toBeNull();
    expect(adaptQuestions({ questions: [], total: 0, tail: { count: "2" }, pending: { count: 1 } })).toBeNull();
  });

  it("rejects duplicate question identities atomically", () => {
    expect(adaptQuestions({ questions: [{ id: "q2" }, { id: "q1" }, { id: "q2" }], total: 3 })).toBeNull();
  });

  it("rejects incoherent shown, total, and tail counts", () => {
    expect(adaptQuestions({ questions: [{ id: "q-1" }, { id: "q-2" }], total: 1 })).toBeNull();
    expect(adaptQuestions({ questions: [{ id: "q-1" }], total: 3, tail: { count: 1, amount: "" } })).toBeNull();
    expect(adaptQuestions({ questions: [{ id: "q-1" }], total: 3, tail: { count: 2, amount: "" } })?.meta.total).toBe(3);
  });

  it("does not let deduplication hide malformed references on a duplicate question", () => {
    expect(adaptQuestions({ questions: [
      { id: "q", refs: { movement: "movement:one" } },
      { id: "q", refs: { movements: ["movement:one", "movement:one"] } },
    ], total: 2 })).toBeNull();
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

  it("keeps an inspectable proposal and its opaque confirmation identity", () => {
    expect(adaptActionOutcome({ kind: "proposal", message: "Nothing changed.",
      state: { proposal_id: "proposal-1", summary: "Open Sample Loan." }, reason: null }))
      .toEqual({ kind: "proposal", message: "Nothing changed.", reason: "",
        proposalId: "proposal-1", proposalSummary: "Open Sample Loan." });
  });

  it("keeps the document terminal state as a client-readable barrier", () => {
    expect(adaptActionOutcome({ kind: "completed", message: "Saved but not read.",
      state: { job_id: "upload-1", terminal_state: "read_yielded_nothing",
        ingest_action: "parked", reading: "read_yielded_nothing" }, reason: null }))
      .toEqual({ kind: "completed", message: "Saved but not read.", reason: "",
        jobId: "upload-1", terminalState: "read_yielded_nothing",
        ingestAction: "parked", reading: "read_yielded_nothing" });
  });

  it("rejects partial or unknown document terminal states", () => {
    const outcome = { kind: "completed", message: "Finished.", reason: null };
    expect(adaptActionOutcome({ ...outcome, state: { terminal_state: "posted" } })).toBeNull();
    expect(adaptActionOutcome({ ...outcome, state: { ingest_action: "posted" } })).toBeNull();
    expect(adaptActionOutcome({ ...outcome, state: { terminal_state: "finished", ingest_action: "posted" } })).toBeNull();
    expect(adaptActionOutcome({ ...outcome, state: { terminal_state: "posted", ingest_action: "done" } })).toBeNull();
    expect(adaptActionOutcome({ ...outcome, state: { terminal_state: "posted", ingest_action: "posted", reading: "maybe" } })).toBeNull();
  });

  it("refuses to read a refusal that carries no machine reason", () => {
    expect(adaptActionOutcome({ kind: "refused", message: "Not recorded.", state: null, reason: null })).toBeNull();
    expect(adaptActionOutcome({ kind: "refused", message: "Not recorded.", state: null, reason: "" })).toBeNull();
  });
});

describe("Question parity artifact", () => {
  it("preserves the generated transfer references byte-for-byte", () => {
    const artifact = fixture as { reads: { conversation: { result: { data: unknown } } } };
    const raw = artifact.reads.conversation.result.data as { questions: Array<{ id: string; kind: string; refs?: { movement?: string; movements?: string[]; candidates?: string[] } }>; total: number };
    const read = adaptQuestions(raw)!;
    const source = raw.questions.find((question) => question.kind === "transfer" && question.refs?.movement && question.refs.candidates?.length)!;
    expect(source, "the generated vault must carry a coherent transfer question").toBeDefined();
    const adapted = read.queue.find((question) => question.id === source.id)!;
    expect(adapted.refs).toEqual({ movement: source.refs!.movement, candidates: source.refs!.candidates });
  });
});
