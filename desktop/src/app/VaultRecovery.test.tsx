import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VaultRecovery } from "./VaultRecovery";
import type { ActionResult } from "../surface/types";
function enter(view: ReturnType<typeof render>) {
  for (const [label, value] of [["Backup file", "/synthetic/copy.orionvault"], ["Empty destination folder", "/synthetic/restored"], ["Backup passphrase", "synthetic phrase"]]) fireEvent.change(view.getByLabelText(label), { target: { value } });
}
function submit(view: ReturnType<typeof render>) { fireEvent.submit(view.getByRole("button", { name: "Restore backup" }).closest("form")!); }
describe("welcome recovery", () => {
  it("guards duplicate submissions, clears the phrase and waits for explicit opening", async () => {
    let finish!: (result: ActionResult) => void;
    const restore = vi.fn(() => new Promise<ActionResult>((resolve) => { finish = resolve; }));
    const onOpen = vi.fn();
    const view = render(<VaultRecovery restore={restore} onBack={vi.fn()} onOpen={onOpen} />);
    expect(view.getByRole("heading", { name: "Restore your backup" })).toHaveFocus();
    enter(view); submit(view); submit(view);
    expect(restore).toHaveBeenCalledExactlyOnceWith("/synthetic/copy.orionvault", "/synthetic/restored", "synthetic phrase");
    expect(view.getByLabelText("Backup passphrase")).toHaveValue("");
    expect(view.getByRole("button", { name: "Back to getting started" })).toHaveAttribute("aria-disabled", "true");
    finish({ state: "settled", outcome: { kind: "completed", message: "Synthetic backup restored.", reason: "" } });
    await waitFor(() => expect(view.getByRole("button", { name: "Open restored vault" })).toBeVisible());
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(view.getByRole("button", { name: "Open restored vault" }));
    expect(onOpen).toHaveBeenCalledWith("/synthetic/restored");
  });
  it.each(["refused", "unreadable", "unanswered", "timeout"])("does not open or replay after %s", async (channel) => {
    const restore = vi.fn(async (): Promise<ActionResult> => {
      if (channel === "timeout") throw new Error("unknown outcome");
      if (channel === "refused") return { state: "settled", outcome: { kind: "refused", message: "Synthetic refusal.", reason: "archive_unreadable" } };
      return { state: channel as "unreadable" | "unanswered" };
    });
    const onOpen = vi.fn();
    const view = render(<VaultRecovery restore={restore} onBack={vi.fn()} onOpen={onOpen} />);
    enter(view); submit(view);
    await waitFor(() => expect(view.getByRole("button", { name: "Restore backup" })).toHaveAttribute("aria-disabled", "false"));
    expect(view.queryByRole("button", { name: "Open restored vault" })).not.toBeInTheDocument();
    expect(restore).toHaveBeenCalledOnce(); expect(onOpen).not.toHaveBeenCalled();
    expect(view.getByLabelText("Backup passphrase")).toHaveValue("");
    if (channel === "timeout") expect(view.getByRole("status")).toHaveTextContent("Inspect the destination before trying again");
  });
  it("preserves typed paths on picker cancellation and offers fallback after failure", async () => {
    const view = render(<VaultRecovery restore={vi.fn()} onBack={vi.fn()} onOpen={vi.fn()} pickArchive={async () => null} pickDirectory={async () => { throw new Error("native detail"); }} />);
    enter(view);
    fireEvent.click(view.getByRole("button", { name: "Choose backup file" }));
    await waitFor(() => expect(view.getByRole("button", { name: "Choose backup file" })).toHaveAttribute("aria-disabled", "false"));
    expect(view.getByLabelText("Backup file")).toHaveValue("/synthetic/copy.orionvault");
    fireEvent.click(view.getByRole("button", { name: "Choose restore folder" }));
    await waitFor(() => expect(view.getByRole("status")).toHaveTextContent("enter the path below"));
    expect(view.queryByText("native detail")).not.toBeInTheDocument();
  });
});
