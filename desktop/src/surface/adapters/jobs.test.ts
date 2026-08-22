import { describe, expect, it } from "vitest";
import { adaptJob, adaptJobs, adaptProgress } from "./jobs";

const row = {
  job_id: "viva.documents.upload-1",
  operation: "viva.documents.upload",
  state: "running",
  completed: 1,
  total: 3,
  message: "",
  step: "checked",
  attempt: 1,
  steps: ["checked", "opened", "settled"],
  cancellable: true,
};

describe("the job registry, read", () => {
  it("carries the sidecar's own count, step and steps unchanged", () => {
    expect(adaptJob(row)).toEqual({
      jobId: "viva.documents.upload-1",
      operation: "viva.documents.upload",
      state: "running",
      completed: 1,
      total: 3,
      message: "",
      step: "checked",
      attempt: 1,
      steps: ["checked", "opened", "settled"],
      cancellable: true,
    });
  });

  it("drops a row whose state is a word this interface was not taught", () => {
    // A job reported as completed because nothing here recognised its real
    // word is a lie about a person's work, so the row goes rather than being
    // shown under the nearest one.
    expect(adaptJob({ ...row, state: "paused" })).toBeNull();
    expect(adaptJobs({ jobs: [row, { ...row, job_id: "two", state: "paused" }], running: [] })?.jobs).toHaveLength(1);
  });

  it("drops a row whose count could not be a count of steps", () => {
    expect(adaptJob({ ...row, completed: 4 })).toBeNull();
    expect(adaptJob({ ...row, completed: -1 })).toBeNull();
    expect(adaptJob({ ...row, attempt: 0 })).toBeNull();
  });

  it("treats a job that did not say it can be stopped as one that cannot", () => {
    const { cancellable } = adaptJob({ ...row, cancellable: undefined })!;
    expect(cancellable).toBe(false);
  });

  it("reads no jobs at all from a payload that is not a registry", () => {
    expect(adaptJobs({ running: [] })).toBeNull();
    expect(adaptJobs(null)).toBeNull();
  });
});

describe("one progress frame", () => {
  it("maps each status the channel may send onto where the job stands", () => {
    const statuses = ["started", "progress", "completed", "failed", "cancelled"];
    expect(statuses.map((status) => adaptProgress({ ...row, status })?.state)).toEqual([
      "running", "running", "completed", "failed", "cancelled",
    ]);
  });

  it("declares no steps of its own, because a frame does not carry the list", () => {
    expect(adaptProgress({ ...row, status: "progress" })?.steps).toEqual([]);
  });

  it("is read as no job at all when its status is a word the channel never sends", () => {
    expect(adaptProgress({ ...row, status: "paused" })).toBeNull();
    expect(adaptProgress({ ...row })).toBeNull();
  });
});
