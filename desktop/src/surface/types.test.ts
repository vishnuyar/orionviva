import { describe, expect, it } from "vitest";
import type { FeatureResult } from "./types";

describe("feature result", () => {
  it("represents exactly six reviewed panel states", () => {
    const results: FeatureResult<string>[] = [
      { state: "absent", reason: "not present" },
      { state: "ready", data: "ready" },
      { state: "partial", data: "partial", issues: [{ code: "partial", message: "Some fields are missing" }] },
      { state: "needs_input", data: "needs input", issues: [{ code: "input", message: "Input required" }] },
      { state: "unavailable", reason: "not connected" },
      { state: "failed", reason: "read_failed" },
    ];
    expect(results.map((result) => result.state)).toEqual(["absent", "ready", "partial", "needs_input", "unavailable", "failed"]);
  });

  it("keeps failed reasons bounded", () => {
    const failures: FeatureResult<never>[] = [{ state: "failed", reason: "read_failed" }, { state: "failed", reason: "invalid_payload" }];
    expect(failures.map((failure) => failure.state === "failed" ? failure.reason : "unexpected")).toEqual(["read_failed", "invalid_payload"]);
  });

  it("keeps data and issues on only their owned union members", () => {
    // @ts-expect-error absent results never carry data
    const absent: FeatureResult<string> = { state: "absent", reason: "missing", data: "leak" };
    // @ts-expect-error unavailable results never carry data
    const unavailable: FeatureResult<string> = { state: "unavailable", reason: "not connected", data: "leak" };
    // @ts-expect-error failed results never carry data
    const failedData: FeatureResult<string> = { state: "failed", reason: "read_failed", data: "leak" };
    // @ts-expect-error ready results never carry issues
    const readyIssues: FeatureResult<string> = { state: "ready", data: "ready", issues: [{ code: "wrong", message: "wrong" }] };
    // @ts-expect-error partial results require issues
    const partialWithoutIssues: FeatureResult<string> = { state: "partial", data: "partial" };
    // @ts-expect-error needs-input results require issues
    const inputWithoutIssues: FeatureResult<string> = { state: "needs_input", data: "input" };
    // @ts-expect-error failed reasons are bounded
    const unboundedFailure: FeatureResult<string> = { state: "failed", reason: "internal_details" };
    expect([absent, unavailable, failedData, readyIssues, partialWithoutIssues, inputWithoutIssues, unboundedFailure]).toHaveLength(7);
  });
});
