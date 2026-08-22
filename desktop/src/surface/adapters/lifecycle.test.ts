import { describe, expect, it } from "vitest";
import { adaptLifecycle } from "./lifecycle";

const answered = {
  state: "absent",
  revision: "abcdef123456",
  origin: "packaged",
  origin_sentence: "a sentence about how this copy got here",
  sentence: "a sentence about no channel",
  notes: [{ id: "vault_untouched", sentence: "a sentence about a vault" },
          { id: "recovery", sentence: "a sentence about starting over" }],
};

describe("the update lifecycle read", () => {
  it("carries the engine's own sentences and composes none of its own", () => {
    const read = adaptLifecycle(answered);

    expect(read?.sentence).toBe(answered.sentence);
    expect(read?.originSentence).toBe(answered.origin_sentence);
    expect(read?.notes.map((note) => note.id)).toEqual(["vault_untouched", "recovery"]);
  });

  it("is no read at all without a sentence", () => {
    // A section headed "Updates" with nothing under it says a channel exists
    // and is quiet, which is the one thing this read is here to deny.
    expect(adaptLifecycle({ ...answered, sentence: "" })).toBeNull();
    expect(adaptLifecycle({ ...answered, sentence: "   " })).toBeNull();
    expect(adaptLifecycle({ ...answered, origin_sentence: "" })).toBeNull();
    expect(adaptLifecycle(null)).toBeNull();
    expect(adaptLifecycle("a string")).toBeNull();
  });

  it("drops a note that says nothing rather than rendering a blank line", () => {
    const read = adaptLifecycle({ ...answered, notes: [
      { id: "", sentence: "orphaned" }, { id: "blank", sentence: " " },
      { id: "kept", sentence: "a sentence" }, "not a note",
    ] });

    expect(read?.notes).toEqual([{ id: "kept", sentence: "a sentence" }]);
  });

  it("carries no note list rather than inventing one", () => {
    expect(adaptLifecycle({ ...answered, notes: "not a list" })?.notes).toEqual([]);
  });
});
