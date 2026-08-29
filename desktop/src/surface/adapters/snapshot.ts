import type { ActivityData, ConversationData, DocumentsData, FeatureResult, OverviewData, SurfaceSnapshot, TrustData } from "../types";

// Which vault this is, said by the side that opened it. It used to be written
// here, so every snapshot said "Private vault" — including the sample one,
// which is the one place a wrong answer matters.
const privateVault: SurfaceSnapshot["disclosure"] = { title: "Private vault", subtitle: "Opened on this device", detail: "The surfaces below are read from this vault. Features that are not connected stay hidden or say so." };

export function buildLiveSnapshot(overview: FeatureResult<OverviewData>, documents: FeatureResult<DocumentsData>, conversation: FeatureResult<ConversationData>, trust: FeatureResult<TrustData>, activity: FeatureResult<ActivityData>, disclosure: SurfaceSnapshot["disclosure"] = privateVault): SurfaceSnapshot {
  return {
    disclosure,
    overview,
    documents,
    activity,
    conversation,
    trust,
  };
}
