import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ConversationData, ConversationPrompt, ConversationTurn, FeatureResult } from "../../surface/types";
import { ConversationDrawer } from "./ConversationDrawer";

const prompt = (id: string, label = `Prompt ${id}`, detail = `Detail ${id}`): ConversationPrompt => ({ id, label, detail, state: "ready" });
const turn = (id: string, text = `Turn ${id}`): ConversationTurn => ({ id, speaker: "viva", text, state: "answer" });
const ready = (data: ConversationData): FeatureResult<ConversationData> => ({ state: "ready", data });
const noAction = () => {};

describe("Conversation body", () => {
  it("renders all six states while leaving the absent body empty", () => {
    const { container, getByText, queryByText, rerender } = render(<ConversationDrawer mode="live" result={{ state: "absent", reason: "not_read" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ConversationDrawer mode="live" result={{ state: "unavailable", reason: "not_connected" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Conversation isn’t connected yet")).toBeInTheDocument();
    expect(getByText("Viva is not connected to this vault in this preview. Opening this drawer does not send a prompt or call a model. This unavailable view does not establish whether earlier model activity occurred.")).toBeInTheDocument();
    expect(queryByText(/No prompt was sent and no model call was made/)).not.toBeInTheDocument();
    rerender(<ConversationDrawer mode="live" result={{ state: "failed", reason: "read_failed" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("The conversation view could not be read. Opening this drawer does not send a prompt or call a model. This failed read does not establish whether earlier model activity occurred. The private vault remains open.")).toBeInTheDocument();
    expect(queryByText(/No prompt was sent and no model call was made/)).not.toBeInTheDocument();
    rerender(<ConversationDrawer mode="live" result={{ state: "partial", data: { turns: [turn("partial")], prompts: [] }, issues: [{ code: "partial", message: "bounded" }] }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Some conversation details are unavailable. Supplied read-only content is shown below.")).toBeInTheDocument();
    rerender(<ConversationDrawer mode="live" result={{ state: "needs_input", data: { turns: [turn("needs")], prompts: [] }, issues: [{ code: "needs", message: "bounded" }] }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Some conversation details need input, but this preview cannot accept or send a prompt. Supplied read-only content is shown below.")).toBeInTheDocument();
    expect(queryByText("Conversation isn’t connected yet")).not.toBeInTheDocument();
  });

  it("keeps demo and live truth domains isolated, including honest empties", () => {
    const maliciousLive = { turns: [turn("live-secret", "Live secret")], prompts: [prompt("live-prompt", "Live prompt")] };
    const { getByText, queryByText, rerender } = render(<ConversationDrawer mode="demo" result={ready({ ...maliciousLive, sample: { turns: [], prompts: [] } })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("No sample conversation")).toBeInTheDocument();
    expect(getByText("This fictional sample does not include any turns or prompts. No prompt was sent and no model call was made.")).toBeInTheDocument();
    expect(queryByText("Live secret")).not.toBeInTheDocument();
    rerender(<ConversationDrawer mode="live" result={ready({ turns: [], prompts: [], sample: { turns: [turn("sample-secret", "Sample secret")], prompts: [prompt("sample-prompt", "Sample prompt")] } })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("No conversation content supplied")).toBeInTheDocument();
    expect(getByText("This supplied Conversation view contains no turns or prompts. Empty content does not establish whether a model call occurred.")).toBeInTheDocument();
    expect(queryByText("No model call has been made.")).not.toBeInTheDocument();
    expect(queryByText("Sample secret")).not.toBeInTheDocument();
    expect(queryByText("Sample prompt")).not.toBeInTheDocument();
  });

  it("renders supplied live fields without implying a model call", () => {
    const data = { turns: [{ ...turn("live-turn", "Supplied exact turn"), speaker: "you" as const, citation: "Supplied citation" }], prompts: [prompt("live-prompt", "Supplied exact prompt", "Supplied exact detail")] };
    const { container, getAllByText, getByText, queryByRole } = render(<ConversationDrawer mode="live" result={ready(data)} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Displaying supplied conversation fields does not establish that a model call occurred.")).toBeInTheDocument();
    expect(getByText("Supplied speaker: you")).toBeInTheDocument();
    expect(getByText("Supplied citation text: Supplied citation")).toBeInTheDocument();
    expect(getByText("Citation text is not a document link. This conversation view does not supply a document identity.")).toBeInTheDocument();
    expect(getAllByText("Supplied exact prompt")).toHaveLength(2);
    expect(queryByRole("link")).not.toBeInTheDocument();
    expect(container.querySelector("form, input, textarea, select")).toBeNull();
  });

  it("labels demo speakers as fictional and preserves supplied turn order without claiming chronology", () => {
    const supplied = [turn("second", "Supplied second"), { ...turn("first", "Supplied first"), speaker: "you" as const }];
    const view = render(<ConversationDrawer mode="live" result={ready({ turns: supplied, prompts: [prompt("prompt")] })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getByRole("heading", { name: "Supplied conversation turns" })).toBeInTheDocument();
    expect(view.queryByRole("heading", { name: "Chronological turns" })).not.toBeInTheDocument();
    expect(view.getByText("Turns are shown in the order supplied to this view. The interface does not verify chronology.")).toBeInTheDocument();
    const second = view.getByText("Supplied second");
    const first = view.getByText("Supplied first");
    expect(second.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<ConversationDrawer mode="demo" result={ready({ turns: [], prompts: [], sample: { turns: [{ ...turn("viva"), speaker: "viva" }, { ...turn("person"), speaker: "you" }], prompts: [prompt("prompt")] } })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getByRole("heading", { name: "Fictional conversation turns" })).toBeInTheDocument();
    expect(view.getByText("Fictional Viva")).toBeInTheDocument();
    expect(view.getByText("Fictional person")).toBeInTheDocument();
  });

  it("selects exact prompt IDs with native pressed state and no focus movement", () => {
    const onSelect = vi.fn();
    const prompts = [prompt("one", "Same label"), prompt("two", "Same label")];
    const { getAllByRole, rerender } = render(<ConversationDrawer mode="demo" result={ready({ turns: [], prompts: [], sample: { turns: [], prompts } })} selectedPrompt="" onSelectPrompt={onSelect} />);
    const buttons = getAllByRole("button", { name: /Same label/i });
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    buttons[1].focus();
    fireEvent.click(buttons[1]);
    expect(onSelect).toHaveBeenCalledWith("two");
    expect(buttons[1]).toHaveFocus();
    rerender(<ConversationDrawer mode="demo" result={ready({ turns: [], prompts: [], sample: { turns: [], prompts: [...prompts].reverse() } })} selectedPrompt="two" onSelectPrompt={onSelect} />);
    expect(getAllByRole("button", { name: /Same label/i }).find((button) => button.getAttribute("aria-pressed") === "true")).toHaveTextContent("Detail two");
  });

  it("bounds blank, duplicate, missing, conflicted, and no-selectable prompt identities", () => {
    const unusable = [prompt("", "Blank one"), prompt(" ", "Blank two"), prompt("x", "Duplicate one"), prompt("x", "Duplicate two")];
    const view = render(<ConversationDrawer mode="live" result={ready({ turns: [], prompts: unusable })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getAllByText("Prompt identity unavailable")).toHaveLength(1);
    expect(view.getAllByText("Prompt identity conflicted")).toHaveLength(1);
    expect(view.getByText("This conversation view contains prompts, but none has a unique nonblank prompt ID.")).toBeInTheDocument();
    view.rerender(<ConversationDrawer mode="live" result={ready({ turns: [], prompts: [prompt("present")] })} selectedPrompt="missing" onSelectPrompt={noAction} />);
    expect(view.getByText("Selected prompt unavailable")).toBeInTheDocument();
    expect(view.getByText("missing")).toBeInTheDocument();
    view.rerender(<ConversationDrawer mode="live" result={ready({ turns: [], prompts: [prompt("x"), prompt("x")] })} selectedPrompt="x" onSelectPrompt={noAction} />);
    expect(view.getByText("More than one prompt uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
  });

  it("groups blank and duplicate turns once and states missing text without inference", () => {
    const turns = [turn("", "Blank one"), turn(" ", "Blank two"), turn("x", "Duplicate one"), turn("x", "Duplicate two"), turn("unique", "")];
    const { getAllByText, getByText, queryByText } = render(<ConversationDrawer mode="demo" result={ready({ turns: [], prompts: [], sample: { turns, prompts: [prompt("prompt")] } })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getAllByText("Turn identity unavailable")).toHaveLength(1);
    expect(getAllByText("Turn identity conflicted")).toHaveLength(1);
    expect(getByText("Sample turn text was not authored.")).toBeInTheDocument();
    for (const hidden of ["Blank one", "Blank two", "Duplicate one", "Duplicate two"]) expect(queryByText(hidden)).not.toBeInTheDocument();
  });

  it("preserves long IDs, states missing prompt fields by mode, and keeps the list before detail", () => {
    const longId = `prompt-${"identity".repeat(20)}`;
    const missing = prompt(longId, "", "");
    const view = render(<ConversationDrawer mode="demo" result={ready({ turns: [], prompts: [], sample: { turns: [], prompts: [missing] } })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getAllByText("Sample prompt label was not authored.")).toHaveLength(2);
    expect(view.getAllByText("Sample prompt detail was not authored.")).toHaveLength(2);
    expect(view.getAllByText(new RegExp(longId))).toHaveLength(2);
    const list = view.container.querySelector(".conversation-prompt-list") as HTMLElement;
    const detail = view.container.querySelector(".conversation-selected") as HTMLElement;
    expect(list.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    view.rerender(<ConversationDrawer mode="live" result={ready({ turns: [], prompts: [missing] })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getAllByText("Prompt label was not supplied by this conversation view.")).toHaveLength(2);
    expect(view.getAllByText("Prompt detail was not supplied by this conversation view.")).toHaveLength(2);
  });
});
