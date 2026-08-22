import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ActivityData, FeatureResult, MovementView } from "../../surface/types";
import { Activity } from "./Activity";
import moments from "../../../../product/viva/persona/pack-v30/moments.json";

const movement = (over: Partial<MovementView> = {}): MovementView => ({ id: "m1", date: "2026-07-01", description: "a shop", account: "acct:one", direction: "out", exactValue: "10.00", currency: "USD", display: "USD 10.00", nature: "spending", sentence: "", decidedBy: "default", provisional: false, linked: false, ...over });
const read = (movements: MovementView[]): ActivityData => ({ sentence: movements.length ? moments.activity_scope : moments.activity_empty, movements, beyond: { count: 0 } });
const ready = (value: ActivityData): FeatureResult<ActivityData> => ({ state: "ready", data: value });
const noAction = () => {};

describe("Activity surface", () => {
  it("renders every FeatureResult state, and an empty read in the read's own words", () => {
    const props = { onOpenEvidence: noAction };
    const { getByText, queryByText, rerender } = render(<Activity {...props} result={{ state: "absent", reason: "none" }} />);
    expect(queryByText("Activity unavailable")).not.toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "unavailable", reason: "not_connected" }} />);
    expect(getByText("Activity is not connected to this vault read.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "failed", reason: "read_failed" }} />);
    expect(getByText("Activity could not be read. The vault is still open.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "partial", data: read([]), issues: [{ code: "partial", message: "bounded" }] }} />);
    expect(getByText("Some activity details are unavailable. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={{ state: "needs_input", data: read([]), issues: [{ code: "input", message: "bounded" }] }} />);
    expect(getByText("Some activity details need more information. Available movements are shown below.")).toBeInTheDocument();
    rerender(<Activity {...props} result={ready(read([]))} />);
    // The read composes its own sentence about knowing of nothing that moved,
    // and it is not the same as nothing having moved.
    expect(getByText(moments.activity_empty, { selector: "span" })).toBeInTheDocument();
  });

  it("has one way to draw a movement, and no second path for a sample vault", () => {
    // This screen used to carry a search box, seven facet filters and a
    // relationship graph over rows composed in the shell for the sample
    // vault. The sample is a vault now and arrives through this read, so
    // there is one implementation and this is what says so.
    const { getByText, queryByRole } = render(<Activity result={ready(read([movement()]))} onOpenEvidence={noAction} />);
    expect(getByText("What moved")).toBeInTheDocument();
    expect(getByText("a shop")).toBeInTheDocument();
    expect(queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says which way the money went in the read's own word, and shows no sign", () => {
    const { getByText, queryByText } = render(<Activity result={ready(read([movement({ direction: "out", display: "USD 120.00" })]))} onOpenEvidence={noAction} />);
    expect(getByText("out")).toBeInTheDocument();
    expect(getByText("USD 120.00")).toBeInTheDocument();
    expect(queryByText("-USD 120.00")).not.toBeInTheDocument();
  });

  it("shows the read's own line for a row that is not plain spending", () => {
    const { getByText } = render(<Activity result={ready(read([movement({ sentence: moments.activity_transfer })]))} onOpenEvidence={noAction} />);
    expect(getByText(moments.activity_transfer)).toBeInTheDocument();
  });

  it("says how many movements are in the vault and not in this list", () => {
    const { getByText } = render(<Activity result={ready({ sentence: moments.activity_scope, movements: [movement()], beyond: { count: 6 } })} onOpenEvidence={noAction} />);
    expect(getByText("6 more are in this vault and not in this list.")).toBeInTheDocument();
  });

  it("names a movement the vault recorded nothing for, rather than leaving the row blank", () => {
    const { getByText } = render(<Activity result={ready(read([movement({ description: "" })]))} onOpenEvidence={noAction} />);
    expect(getByText("No description was recorded for this movement.")).toBeInTheDocument();
  });
});
