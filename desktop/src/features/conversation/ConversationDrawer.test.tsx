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
    const { container, getByText, queryByText, rerender } = render(<ConversationDrawer ask={null} result={{ state: "absent", reason: "not_read" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ConversationDrawer ask={null} result={{ state: "unavailable", reason: "not_connected" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Conversation isn’t connected yet")).toBeInTheDocument();
    expect(getByText("Viva is not connected to this vault in this preview. Opening this drawer does not send a prompt or call a model. This unavailable view does not establish whether earlier model activity occurred.")).toBeInTheDocument();
    expect(queryByText(/No prompt was sent and no model call was made/)).not.toBeInTheDocument();
    rerender(<ConversationDrawer ask={null} result={{ state: "failed", reason: "read_failed" }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("The conversation view could not be read. Opening this drawer does not send a prompt or call a model. This failed read does not establish whether earlier model activity occurred. The private vault remains open.")).toBeInTheDocument();
    expect(queryByText(/No prompt was sent and no model call was made/)).not.toBeInTheDocument();
    rerender(<ConversationDrawer ask={null} result={{ state: "partial", data: { turns: [turn("partial")], prompts: [] }, issues: [{ code: "partial", message: "bounded" }] }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Some conversation details are unavailable. Supplied read-only content is shown below.")).toBeInTheDocument();
    rerender(<ConversationDrawer ask={null} result={{ state: "needs_input", data: { turns: [turn("needs")], prompts: [] }, issues: [{ code: "needs", message: "bounded" }] }} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Some conversation details need input, but this preview cannot accept or send a prompt. Supplied read-only content is shown below.")).toBeInTheDocument();
    expect(queryByText("Conversation isn’t connected yet")).not.toBeInTheDocument();
  });


  it("renders supplied live fields without implying a model call", () => {
    const data = { turns: [{ ...turn("live-turn", "Supplied exact turn"), speaker: "you" as const, citation: "Supplied citation" }], prompts: [prompt("live-prompt", "Supplied exact prompt", "Supplied exact detail")] };
    const { container, getAllByText, getByText, queryByRole } = render(<ConversationDrawer ask={null} result={ready(data)} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getByText("Displaying supplied conversation fields does not establish that a model call occurred.")).toBeInTheDocument();
    expect(getByText("Supplied speaker: you")).toBeInTheDocument();
    expect(getByText("Supplied citation text: Supplied citation")).toBeInTheDocument();
    expect(getByText("Citation text is not a document link. This conversation view does not supply a document identity.")).toBeInTheDocument();
    expect(getAllByText("Supplied exact prompt")).toHaveLength(2);
    expect(queryByRole("link")).not.toBeInTheDocument();
    expect(container.querySelector("form, input, textarea, select")).toBeNull();
  });


  it("selects exact prompt IDs with native pressed state and no focus movement", () => {
    const onSelect = vi.fn();
    const prompts = [prompt("one", "Same label"), prompt("two", "Same label")];
    const { getAllByRole, rerender } = render(<ConversationDrawer ask={null} result={ready({ turns: [], prompts })} selectedPrompt="" onSelectPrompt={onSelect} />);
    const buttons = getAllByRole("button", { name: /Same label/i });
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    buttons[1].focus();
    fireEvent.click(buttons[1]);
    expect(onSelect).toHaveBeenCalledWith("two");
    expect(buttons[1]).toHaveFocus();
    rerender(<ConversationDrawer ask={null} result={ready({ turns: [], prompts })} selectedPrompt="two" onSelectPrompt={onSelect} />);
    expect(getAllByRole("button", { name: /Same label/i }).find((button) => button.getAttribute("aria-pressed") === "true")).toHaveTextContent("Detail two");
  });

  it("bounds blank, duplicate, missing, conflicted, and no-selectable prompt identities", () => {
    const unusable = [prompt("", "Blank one"), prompt(" ", "Blank two"), prompt("x", "Duplicate one"), prompt("x", "Duplicate two")];
    const view = render(<ConversationDrawer ask={null} result={ready({ turns: [], prompts: unusable })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(view.getAllByText("Prompt identity unavailable")).toHaveLength(1);
    expect(view.getAllByText("Prompt identity conflicted")).toHaveLength(1);
    expect(view.getByText("This conversation view contains prompts, but none has a unique nonblank prompt ID.")).toBeInTheDocument();
    view.rerender(<ConversationDrawer ask={null} result={ready({ turns: [], prompts: [prompt("present")] })} selectedPrompt="missing" onSelectPrompt={noAction} />);
    expect(view.getByText("Selected prompt unavailable")).toBeInTheDocument();
    expect(view.getByText("missing")).toBeInTheDocument();
    view.rerender(<ConversationDrawer ask={null} result={ready({ turns: [], prompts: [prompt("x"), prompt("x")] })} selectedPrompt="x" onSelectPrompt={noAction} />);
    expect(view.getByText("More than one prompt uses the selected identity, so the interface will not choose between them.")).toBeInTheDocument();
  });

  it("groups blank and duplicate turns once and states missing text without inference", () => {
    const turns = [turn("", "Blank one"), turn(" ", "Blank two"), turn("x", "Duplicate one"), turn("x", "Duplicate two"), turn("unique", "")];
    const { getAllByText, getByText, queryByText } = render(<ConversationDrawer ask={null} result={ready({ turns, prompts: [] })} selectedPrompt="" onSelectPrompt={noAction} />);
    expect(getAllByText("Turn identity unavailable")).toHaveLength(1);
    expect(getAllByText("Turn identity conflicted")).toHaveLength(1);
    expect(getByText("Turn text was not supplied by this conversation view.")).toBeInTheDocument();
    for (const hidden of ["Blank one", "Blank two", "Duplicate one", "Duplicate two"]) expect(queryByText(hidden)).not.toBeInTheDocument();
  });

});
