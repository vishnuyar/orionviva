import { describe, expect, it } from "vitest";
import type { ReviewView } from "../../surface/types";
import { anatomyPresentation, resolveReviewSelection } from "./reviewPresentation";

const question = (id: string, label = "Question"): ReviewView => ({ id, label, detail: "", status: "", action: "", type: "", evidence: "", state: "needs_input", outcome: null, disposition: null });

describe("review presentation", () => {
  it("maps all four static fictional anatomy types", () => {
    expect(["answer", "decline", "proposal", "confirmation"].map((value) => anatomyPresentation(value).state)).toEqual(["ready", "ready", "ready", "ready"]);
    expect(anatomyPresentation("answer")).toMatchObject({ title: "Answer boundary" });
    expect(anatomyPresentation("decline")).toMatchObject({ title: "Decline / set aside boundary" });
    expect(anatomyPresentation("proposal")).toMatchObject({ title: "Proposal — not applied" });
    expect(anatomyPresentation("confirmation")).toMatchObject({ title: "Confirmation required" });
  });

  it("keeps missing and unknown sample anatomy bounded", () => {
    expect(anatomyPresentation(undefined)).toMatchObject({ state: "missing", title: "Sample anatomy unavailable" });
    expect(anatomyPresentation("future-action")).toMatchObject({ state: "unrecognized", title: "Sample action type unavailable" });
  });

  it("resolves exact stable IDs independently of labels and order", () => {
    const queue = [question("question-a", "Duplicate"), question("question-b", "Duplicate")];
    expect(resolveReviewSelection(queue, "question-b")).toMatchObject({ state: "ready", question: { id: "question-b" } });
    expect(resolveReviewSelection([...queue].reverse(), "question-b")).toMatchObject({ state: "ready", question: { id: "question-b" } });
  });

  it("distinguishes empty, unselectable, missing, and conflicting selection", () => {
    expect(resolveReviewSelection([], "")).toEqual({ state: "empty", reason: "queue_empty" });
    expect(resolveReviewSelection([question(""), question(" ")], "")).toEqual({ state: "empty", reason: "no_selectable_identity" });
    expect(resolveReviewSelection([question("duplicate"), question("duplicate")], "")).toEqual({ state: "empty", reason: "no_selectable_identity" });
    expect(resolveReviewSelection([question("present")], "missing")).toEqual({ state: "missing", requestedId: "missing" });
    expect(resolveReviewSelection([question("duplicate"), question("duplicate")], "duplicate")).toEqual({ state: "conflicted_identity", requestedId: "duplicate" });
  });
});
