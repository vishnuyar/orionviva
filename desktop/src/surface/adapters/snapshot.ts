import type { DocumentsData, FeatureResult, OverviewData, ReviewData, SurfaceSnapshot, TrustData } from "../types";

const unavailable = <T>(reason: string): FeatureResult<T> => ({ state: "unavailable", reason });
export function buildLiveSnapshot(overview: FeatureResult<OverviewData>, documents: FeatureResult<DocumentsData>, review: FeatureResult<ReviewData>, trust: FeatureResult<TrustData>): SurfaceSnapshot {
  return {
    mode: "live",
    disclosure: { title: "Private vault", subtitle: "Opened on this device", detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so." },
    overview,
    documents,
    review,
    activity: unavailable("Activity is not connected to this private-vault read."),
    conversation: unavailable("Viva is not connected to this private vault. No model call was made."),
    trust,
  };
}
