export type Destination = "overview" | "accounts" | "activity" | "documents" | "review" | "trust";
export type SurfaceMode = "demo" | "live";
export type FigureGrade = "verified" | "corroborated" | "unverified" | "conflicted" | "unavailable" | "not_applicable";
export type PanelState = "absent" | "ready" | "partial" | "needs_input" | "unavailable" | "failed";
export type ActionOutcome = "completed" | "refused" | "proposal" | "waiting" | "stale";
// What an action answered with: the kind of thing that happened, the sentence
// Viva would say to the person, and the machine reason a refusal carries.
export type ActionOutcomeView = { kind: ActionOutcome; message: string; reason: string };
// Four channels one verb can come back through. `settled` is the vault's own
// answer in its own sentence, and the only one that tells a person the vault
// said no. `unserved` is the sidecar reading the request and refusing to take
// it. `unanswered` is nothing coming back. `unreadable` is something coming
// back that no outcome word describes, which may be a handler that raised
// after writing, so nothing under it claims the vault is as it was.
export type ActionResult =
  | { state: "settled"; outcome: ActionOutcomeView }
  | { state: "unserved" }
  | { state: "unanswered" }
  | { state: "unreadable" };
// The review actions a screen may reach. The registry declares `answer` too and
// this build serves no handler for it, so nothing here can name it.
export type ReviewVerb = "decline";
// What became of the last review verb a person used, held beside the question
// it was used on. An outcome belongs to one question, so a screen that moves to
// another must not keep showing it.
export type ReviewActionState =
  | { state: "idle" }
  | { state: "working"; questionId: string; verb: ReviewVerb }
  | { state: "settled"; questionId: string; verb: ReviewVerb; result: ActionResult };
export type DeclineReason = "not_now" | "dont_know";

export type FeatureIssue = { code: string; message: string };
export type FeatureResult<T> =
  | { state: "absent"; reason: string }
  | { state: "ready"; data: T }
  | { state: "partial"; data: T; issues: readonly FeatureIssue[] }
  | { state: "needs_input"; data: T; issues: readonly FeatureIssue[] }
  | { state: "unavailable"; reason: string }
  | { state: "failed"; reason: "read_failed" | "invalid_payload" };

// How a document stands to the figure that cites it. `attests` is the first
// witness — the figure was read from this document; `corroborates` is a
// second one. The set is the backend's and is closed on both sides.
export type EvidenceRelation = "attests" | "corroborates" | "same_period" | "same_account" | "settles_question";
export type EvidenceLink = { targetDocumentId: string; label: string; relation: EvidenceRelation; page: string };
export type FigureView = { id: string; display: string; exactValue: string; currency: string; measure: "balance" | "owed" | "spending" | "income"; grade: FigureGrade; gradeLabel: string; gradeDescription: string; asOf: string; coverage: string; caveats: string[]; evidenceLinks: EvidenceLink[]; exactness?: string | null; recordIds?: readonly string[] };
export type DocumentPhase = "captured" | "queued" | "reading" | "held" | "parked" | "read_ready" | "verified" | "unresolved";
export type SurfaceDocument = { id: string; name: string; state: string; phase?: DocumentPhase; phaseLabel: string; detail: string; source: string; pages: string; provenance: string; evidenceLinks: EvidenceLink[]; docType?: string; resolved?: boolean; rawAvailable?: boolean; sample?: { region?: string; contribution?: string; waitReason?: string } };
export type DocumentCapture = { id: string; label: string; state: "captured" | "processing" | "held" | "ready" | "sent"; detail: string; source: string; note: string };
export type DocumentJob = { id: string; label: string; state: "running" | "paused" | "done"; detail: string; progress: string };
export type OutboundRecord = { id: string; label: string; state: "queued" | "sent" | "blocked"; detail: string; destination: string };
export type AccountView = { id: string; name: string; kind: string; measure: "balance" | "owed" | null; exactValue: string; currency: string; display: string; grade: FigureGrade; gradeLabel: string; gradeDescription: string; note: string | null; asOf: string; coverage: string | null; provenance: string | null; evidenceLinks: EvidenceLink[]; state: PanelState; caveats?: readonly string[]; exactness?: string | null; recordIds?: readonly string[] };
export type ActivityView = { id: string; label: string; exactValue: string; display: string; measure: "income" | "spending"; detail: string; tone: "inflow" | "outflow" | "neutral"; state: PanelState; provenance: string; evidenceLinks: EvidenceLink[]; grade: "not_applicable"; exactness?: string | null; recordIds?: readonly string[]; sample?: SampleActivityDetails };
export type SampleActivityFacet = { readonly id: string; readonly label: string };
export type SampleActivityRelationship = { readonly targetActivityId: string; readonly label: string };
export type SampleActivityFilterCatalog = { readonly dates: readonly SampleActivityFacet[]; readonly accounts: readonly SampleActivityFacet[]; readonly merchants: readonly SampleActivityFacet[]; readonly categories: readonly SampleActivityFacet[]; readonly tags: readonly SampleActivityFacet[]; readonly natures: readonly SampleActivityFacet[]; readonly directions: readonly SampleActivityFacet[] };
export type SampleActivityDetails = { readonly date?: SampleActivityFacet; readonly account?: SampleActivityFacet; readonly merchant?: SampleActivityFacet; readonly category?: SampleActivityFacet; readonly tags?: readonly SampleActivityFacet[]; readonly nature?: SampleActivityFacet; readonly direction?: SampleActivityFacet; readonly relationships?: readonly SampleActivityRelationship[] };
export type ReviewSampleAnatomy = "answer" | "decline" | "proposal" | "confirmation";
export type ReviewView = { id: string; label: string; detail: string; status: string; action: string; type: string; evidence: string; state: "needs_input" | "partial"; outcome: ActionOutcome | null; disposition: "answer" | "decline" | "proposal" | "confirm" | null; count?: number; scope?: string; currency?: string; amount?: string; sample?: { anatomy?: ReviewSampleAnatomy; proposedValue?: string; confirmationPrompt?: string; evidenceLinks?: EvidenceLink[] } };
export type ConversationTurn = { id: string; speaker: "you" | "viva"; text: string; state: "answer" | "refusal" | "citation" | "prompt"; citation?: string };
export type ConversationPrompt = { id: string; label: string; detail: string; state: "ready" | "refusal" | "citation" };

export type OverviewData = { currentThrough: string; coverage: string; corpusCoverage: string; corpusSource: string; netWorth: FigureView | null; accounts: AccountView[]; recent: ActivityView[] };
export type DocumentsData = { documents: SurfaceDocument[]; captureQueue: DocumentCapture[]; processingJobs: DocumentJob[]; outboundRecords: OutboundRecord[] };
export type ReviewData = { queue: ReviewView[]; count: number; meta: { total: number; tail: { count: number; amount: string } | null; pending: { count: number } | null; invite: string; answeredByDocument: string } };
export type ActivityData = { items: ActivityView[]; sample?: { readonly filters?: SampleActivityFilterCatalog } };
export type ConversationData = { turns: ConversationTurn[]; prompts: ConversationPrompt[]; sample?: { turns: ConversationTurn[]; prompts: ConversationPrompt[] } };
export type TrustNote = { readonly id: string; readonly title: string; readonly detail: string };
export type TrustCapabilityGroup = "source" | "outbound_models" | "integrity" | "continuity" | "build_support";
export type TrustCapabilityState = "fictional_sample" | "preview_limitation" | "not_connected" | "not_supplied" | "not_implemented";
export type TrustSampleCapability = { readonly id: string; readonly group: TrustCapabilityGroup; readonly label: string; readonly state: TrustCapabilityState; readonly detail: string };
export type TrustData = { notes: TrustNote[]; sample?: { capabilities: TrustSampleCapability[] } };
// The review verbs a screen may use, and the read that follows one. A screen
// holds these rather than a transport, so nothing above this line knows an
// action is a frame.
export type ReviewActions = {
  decline: (questionId: string, reason: DeclineReason) => Promise<ActionResult>;
  reread: () => Promise<FeatureResult<ReviewData>>;
};
export type SurfaceSnapshot = { mode: SurfaceMode; disclosure: { title: string; subtitle: string; detail: string }; overview: FeatureResult<OverviewData>; documents: FeatureResult<DocumentsData>; review: FeatureResult<ReviewData>; activity: FeatureResult<ActivityData>; conversation: FeatureResult<ConversationData>; trust: FeatureResult<TrustData> };
