import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AskActionState } from "../surface/types";
import { useConversationContext } from "./useConversationContext";

const idle: AskActionState = { state: "idle" };
const working: AskActionState = { state: "working", question: "What changed?" };
const settled = (authoritative = true, kind: "completed" | "refused" = "completed"): AskActionState => ({ state: "settled", question: "What changed?", authoritative, result: { state: "settled", outcome: { kind, message: "Answer", reason: "" } }, turn: null });

describe("vault session conversation context", () => {
  it("continues only after observing its own authoritative settlement and retains a deliberate new boundary", () => {
    const view = renderHook(({ state }: { state: AskActionState }) => useConversationContext(1, state), { initialProps: { state: idle as AskActionState } });
    act(() => view.result.current.questionSubmitted("What changed?"));
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: working });
    view.rerender({ state: settled(false) });
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("follow_up");
    act(() => view.result.current.startNewConversation());
    expect(view.result.current.contextMode).toBe("new_question");
    view.rerender({ state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
  });
  it("does not revive an old request across vaults or accounting corrections", () => {
    const view = renderHook(({ requestId, state }: { requestId: number; state: AskActionState }) => useConversationContext(requestId, state), { initialProps: { requestId: 1, state: idle as AskActionState } });
    act(() => view.result.current.questionSubmitted("What changed?"));
    view.rerender({ requestId: 1, state: working });
    act(() => view.result.current.startNewConversation());
    view.rerender({ requestId: 1, state: settled(true, "refused") });
    expect(view.result.current.contextMode).toBe("follow_up");
    view.rerender({ requestId: 2, state: idle });
    expect(view.result.current.contextMode).toBe("new_question");
    act(() => view.result.current.questionSubmitted("What changed?", true));
    view.rerender({ requestId: 2, state: working });
    view.rerender({ requestId: 2, state: settled() });
    expect(view.result.current.contextMode).toBe("new_question");
  });
});

it("requires an explicit current-vault opt-in to resume readable saved Ask history", () => {
  const history = { state: "ready" as const, data: { turns: [{ id: "saved-ask", kind: "ask" as const, contextMode: "new_question" as const, occurredAt: "", prompt: "Earlier question", said: "", questionId: "", outcome: "refused" as const, message: "I need a starting amount.", reason: "", answer: null, proposal: null }], questions: { queue: [], count: 0, meta: { total: 0, tail: null, pending: null, invite: "", answeredByDocument: "" } } } };
  const view = renderHook(({ requestId, state, blocked }: { requestId: number; state: AskActionState; blocked: boolean }) => useConversationContext(requestId, state, history, blocked), { initialProps: { requestId: 1, state: idle as AskActionState, blocked: false } });
  expect(view.result.current.contextMode).toBe("new_question");
  act(() => view.result.current.continuePreviousConversation()); expect(view.result.current.contextMode).toBe("follow_up");
  act(() => view.result.current.startNewConversation()); expect(view.result.current.contextMode).toBe("new_question");
  const staleContinue = view.result.current.continuePreviousConversation;
  view.rerender({ requestId: 2, state: idle, blocked: false });
  act(() => staleContinue()); expect(view.result.current.contextMode).toBe("new_question");
  view.rerender({ requestId: 2, state: working, blocked: false });
  act(() => view.result.current.continuePreviousConversation()); expect(view.result.current.contextMode).toBe("new_question");
  view.rerender({ requestId: 2, state: idle, blocked: true });
  act(() => view.result.current.continuePreviousConversation()); expect(view.result.current.contextMode).toBe("new_question");
});
