import { describe, expect, it } from "vitest";
import { adaptTurn } from "./conversation";

const reply = {
  question: "what is on that account?",
  text: "You have about USD 1,200 on that account.",
  answered: true,
  refusal: "",
  grade: "verified",
  grade_sentence: "Two independent records agree on this.",
  figures: [{ id: "f1", evidence_id: "conversation:turn-1:f1", written: "about USD 1,200", grade: "verified", what: "the balance", record_ids: ["doc-1"], evidence_links: [{ document_id: "doc-1", label: "Checking statement", relation: "attests", page: "page 1" }] }],
  spoken: { may_speak: true, withheld: "", parts: ["text", "grade", "citations"], text: "You have about USD 1,200 on that account.", grade_sentence: "Two independent records agree on this.", citation_sentence: "What that rests on is on the screen.", local_only: "On this machine or not at all." },
};

describe("one turn, read", () => {
  it("keeps the words the sentence wrote a figure as", () => {
    // Not a second rendering of the same number: the figure under the sentence
    // is the figure in it.
    expect(adaptTurn(reply)?.figures[0].written).toBe("about USD 1,200");
  });

  it("carries the route back to what a figure rests on", () => {
    const figure = adaptTurn(reply)?.figures[0];
    expect(figure?.recordIds).toEqual(["doc-1"]);
    expect(figure?.evidenceId).toBe("conversation:turn-1:f1");
    expect(figure?.evidenceLinks).toEqual([{ targetDocumentId: "doc-1", label: "Checking statement", relation: "attests", page: "page 1" }]);
  });

  it("takes whether anything may be spoken from the read rather than from the text", () => {
    // A turn whose text mirror is not in front of the person carries text and
    // may not be spoken. Those two facts are exactly the pair this keeps apart.
    const withheld = { ...reply, spoken: { ...reply.spoken, may_speak: false, parts: [], text: "", withheld: "Not while it is not in front of you." } };
    const read = adaptTurn(withheld)!;
    expect(read.text).toBe(reply.text);
    expect(read.spoken.maySpeak).toBe(false);
    expect(read.spoken.withheld).toBe("Not while it is not in front of you.");
  });

  it("drops a figure with no identity, because nothing could be followed from it", () => {
    const nameless = { ...reply, figures: [{ written: "about USD 1,200", record_ids: [] }] };
    expect(adaptTurn(nameless)?.figures).toEqual([]);
  });

  it("is read as no turn at all with neither an answer nor a refusal", () => {
    expect(adaptTurn({ ...reply, text: "", refusal: "" })).toBeNull();
    expect(adaptTurn(null)).toBeNull();
  });

  it("says nothing about speech at all when the reply carried none", () => {
    const silent = adaptTurn({ ...reply, spoken: undefined })!;
    expect(silent.spoken.maySpeak).toBe(false);
    expect(silent.spoken.parts).toEqual([]);
  });

  it("carries the exact deterministic goal draft and its Plans route", () => {
    const raw = {
      ...reply,
      goal_draft: {
        kind: "ready", message: "Draft ready. Nothing was recorded.",
        reason: "", verb: "create", review_in_plans: true,
        draft: {
          verb: "create",
          payload: { title: "Trip", currency: "USD", target_amount: "600" },
          calculated: { reserved: "0", remaining: "600", required_monthly: "100", projected_completion_date: "2027-02-28", status: "on_track" },
        },
      },
    };

    expect(adaptTurn(raw)?.goalDraft).toEqual({
      kind: "ready", message: "Draft ready. Nothing was recorded.",
      reason: "", verb: "create", reviewInPlans: true,
      draft: raw.goal_draft.draft,
    });
  });
});
