import type { BridgeClient } from "../bridge/contracts";
import { adaptDocuments } from "./adapters/documents";
import { adaptOverview } from "./adapters/overview";
import { adaptReview } from "./adapters/review";
import { buildLiveSnapshot } from "./adapters/snapshot";
import type { FeatureResult, SurfaceSnapshot } from "./types";

function settled<TRaw, TData>(result: PromiseSettledResult<TRaw>, adapt: (raw: TRaw) => TData | null): FeatureResult<TData> {
  if (result.status === "rejected") return { state: "failed", reason: "read_failed" };
  const data = adapt(result.value);
  return data === null ? { state: "failed", reason: "invalid_payload" } : { state: "ready", data };
}
export async function loadPrivateSnapshot(client: BridgeClient): Promise<SurfaceSnapshot> {
  const [overviewRead, documentsRead, reviewRead] = await Promise.allSettled([client.readOverview(), client.readDocuments(), client.readReview()]);
  return buildLiveSnapshot(
    settled(overviewRead, (read) => adaptOverview(read.data)),
    settled(documentsRead, (read) => adaptDocuments(read.data)),
    settled(reviewRead, (read) => adaptReview(read.data)),
  );
}
