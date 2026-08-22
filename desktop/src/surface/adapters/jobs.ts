import type { JobLifecycle, JobView, JobsData } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue } from "./primitives";

// The words a job's state may be, closed on both sides. A word outside the set
// is a job this interface has not been taught to render, and the row is
// dropped rather than shown under the nearest word — a job reported as
// `completed` because nothing here recognised `cancelled` is a lie about a
// person's work.
const LIFECYCLES: readonly JobLifecycle[] = ["queued", "running", "completed", "failed", "cancelled"];

function lifecycle(value: unknown): JobLifecycle | null {
  return LIFECYCLES.find((candidate) => candidate === value) ?? null;
}

// Nothing here counts a step, names one, or decides whether a job can still be
// stopped. Every one of those is the sidecar's, and a second derivation of one
// on this side is a second author of the same fact.
export function adaptJob(raw: unknown): JobView | null {
  if (!isRecord(raw)) return null;
  const jobId = textValue(raw.job_id);
  const state = lifecycle(raw.state);
  const completed = optionalNonNegativeInteger(raw.completed);
  const total = optionalNonNegativeInteger(raw.total);
  const attempt = optionalNonNegativeInteger(raw.attempt);
  if (!jobId || state === null || completed === undefined || total === undefined) return null;
  if (completed > total || attempt === undefined || attempt < 1) return null;
  const steps = Array.isArray(raw.steps) ? raw.steps.map(textValue).filter((step) => step) : [];
  return {
    jobId,
    operation: textValue(raw.operation),
    state,
    completed,
    total,
    message: textValue(raw.message),
    step: textValue(raw.step),
    attempt,
    steps,
    // A job whose reply did not say whether it can still be stopped is treated
    // as one that cannot, so nothing offers a control that would reach
    // nothing.
    cancellable: raw.cancellable === true,
  };
}

export function adaptJobs(raw: unknown): JobsData | null {
  if (!isRecord(raw) || !Array.isArray(raw.jobs)) return null;
  const jobs = raw.jobs.map(adaptJob).filter((job): job is JobView => job !== null);
  const running = Array.isArray(raw.running) ? raw.running.map(textValue).filter((id) => id) : [];
  return { jobs, running };
}

// One progress frame, read into the same shape a registry row has. The frame
// carries no step list of its own — the registry holds that — so a row built
// from a frame alone declares none rather than inventing one.
export function adaptProgress(raw: unknown): JobView | null {
  if (!isRecord(raw)) return null;
  const status = textValue(raw.status);
  const state: JobLifecycle | null =
    status === "started" || status === "progress" ? "running"
      : status === "completed" ? "completed"
        : status === "failed" ? "failed"
          : status === "cancelled" ? "cancelled"
            : null;
  if (state === null) return null;
  return adaptJob({ ...raw, state, steps: [], cancellable: state === "running" });
}
