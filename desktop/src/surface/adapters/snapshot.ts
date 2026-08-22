import type { ActivityData, DocumentsData, FeatureResult, OverviewData, ReviewData, SurfaceSnapshot, TrustData } from "../types";

const unavailable = <T>(reason: string): FeatureResult<T> => ({ state: "unavailable", reason });
// Which vault this is, said by the side that opened it. It used to be written
// here, so every snapshot said "Private vault" — including the sample one,
// which is the one place a wrong answer matters.
const privateVault: SurfaceSnapshot["disclosure"] = { title: "Private vault", subtitle: "Opened on this device", detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so." };

export function buildLiveSnapshot(overview: FeatureResult<OverviewData>, documents: FeatureResult<DocumentsData>, review: FeatureResult<ReviewData>, trust: FeatureResult<TrustData>, activity: FeatureResult<ActivityData>, disclosure: SurfaceSnapshot["disclosure"] = privateVault): SurfaceSnapshot {
  return {
    disclosure,
    overview,
    documents,
    review,
    activity,
    conversation: unavailable("Viva is not connected to this private vault. No model call was made."),
    trust,
  };
}
