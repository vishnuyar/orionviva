import { describe, expect, it } from "vitest";
import type { ConversationPrompt, ConversationTurn } from "../../surface/types";
import { presentConversationRows, resolveConversationPrompt } from "./conversationPresentation";

const prompt = (id: string, label = id): ConversationPrompt => ({ id, label, detail: `Detail ${label}`, state: "ready" });
const turn = (id: string, text = id): ConversationTurn => ({ id, speaker: "viva", text, state: "answer" });

describe("conversation presentation", () => {
  it("selects only exact unique prompt identities", () => {
    const prompts = [prompt("first"), prompt("second")];
    expect(resolveConversationPrompt(prompts, "")).toEqual({ state: "ready", prompt: prompts[0] });
    expect(resolveConversationPrompt(prompts, "second")).toEqual({ state: "ready", prompt: prompts[1] });
    expect(resolveConversationPrompt(prompts, "missing")).toEqual({ state: "missing", requestedId: "missing" });
    expect(resolveConversationPrompt([prompt("x"), prompt("x")], "x")).toEqual({ state: "conflicted_identity", requestedId: "x" });
    expect(resolveConversationPrompt([], "")).toEqual({ state: "empty", reason: "no_prompts" });
  });

  it("treats whitespace selection as empty while preserving exact nonblank bytes", () => {
    const unique = prompt("unique");
    const spaced = prompt(" exact ");
    expect(resolveConversationPrompt([prompt(" "), unique], " ")).toEqual({ state: "ready", prompt: unique });
    expect(resolveConversationPrompt([], "   ")).toEqual({ state: "empty", reason: "no_prompts" });
    expect(resolveConversationPrompt([prompt(""), prompt(" "), prompt("x"), prompt("x")], "")).toEqual({ state: "empty", reason: "no_selectable_identity" });
    expect(resolveConversationPrompt([prompt(""), prompt(" "), prompt("x"), prompt("x")], "   ")).toEqual({ state: "empty", reason: "no_selectable_identity" });
    expect(resolveConversationPrompt([spaced, prompt("exact")], " exact ")).toEqual({ state: "ready", prompt: spaced });
    expect(resolveConversationPrompt([spaced, prompt("exact")], "exact ")).toEqual({ state: "missing", requestedId: "exact " });
  });

  it("presents one bounded blank and duplicate group at first occurrence", () => {
    const prompts = [prompt("", "blank one"), prompt("unique"), prompt(" ", "blank two"), prompt("x", "duplicate one"), prompt("x", "duplicate two")];
    expect(presentConversationRows(prompts, "prompt").map((row) => row.state)).toEqual(["missing_identity", "ready", "conflicted_identity"]);
    expect(presentConversationRows([...prompts].reverse(), "prompt").map((row) => row.state).sort()).toEqual(["conflicted_identity", "missing_identity", "ready"]);
    const turns = [turn("", "blank one"), turn("t"), turn("t", "duplicate"), turn(" ", "blank two")];
    expect(presentConversationRows(turns, "turn").map((row) => row.state)).toEqual(["missing_identity", "conflicted_identity"]);
  });

  it("keeps duplicate labels with distinct IDs as separate ready rows", () => {
    const prompts = [prompt("one", "Same label"), prompt("two", "Same label")];
    expect(presentConversationRows(prompts, "prompt").map((row) => row.state)).toEqual(["ready", "ready"]);
  });
});
