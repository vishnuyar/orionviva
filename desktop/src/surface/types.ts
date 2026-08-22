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
// What kind of thing a notice is, as a closed word the notice carries. How a
// notice is dressed follows this word; nothing reads the sentence itself to
// decide, because a mark that has only ever meant benign must not be able to
// arrive on a sentence saying something did not happen.
export type NoticeKind = "acknowledged" | "refused";
export type Notice = { kind: NoticeKind; text: string };
// What is known about whether a document was read, as a closed set of three
// words derived from what the vault already recorded. The word is the
// backend's; nothing here turns one into a sentence.
export type DocumentReading = "never_read" | "read_yielded_nothing" | "read";
// What became of the last capture a person asked for. One gesture captures one
// document, so one answer is what there is to hold. A capture in flight
// carries what the one before it answered, so a receipt is not taken off the
// screen by the next request.
export type CaptureActionState =
  | { state: "idle" }
  | { state: "working"; result: ActionResult | null }
  | { state: "settled"; result: ActionResult };

export type FeatureIssue = { code: string; message: string };
export type FeatureResult<T> =
  | { state: "absent"; reason: string }
  | { state: "ready"; data: T }
  | { state: "partial"; data: T; issues: readonly FeatureIssue[] }
  | { state: "needs_input"; data: T; issues: readonly FeatureIssue[] }
  | { state: "unavailable"; reason: string }
  | { state: "failed"; reason: "read_failed" | "invalid_payload" };

// What a figure measures, as a closed set of words the backend supplies. It
// widens only when a read starts emitting a new one, so a word outside it is a
// read this interface has not been taught to label.
export type FigureMeasure = "balance" | "owed" | "spending" | "income" | "net_worth";

// How a document stands to the figure that cites it. `attests` is the first
// witness — the figure was read from this document; `corroborates` is a
// second one. The set is the backend's and is closed on both sides.
export type EvidenceRelation = "attests" | "corroborates" | "same_period" | "same_account" | "settles_question";
export type EvidenceLink = { targetDocumentId: string; label: string; relation: EvidenceRelation; page: string };
// `coverage` is an ordered list of whole sentences, one line each, and is
// never joined or split here: three of the sentences two figures carry can be
// identical while the one that differs is the last, and a person who meets
// them as a paragraph stops reading before the fact that differs.
// `unmeasured` names the accounts the read could not value and carries, for
// each, the reviewed sentence saying why it is not in the total. Both are the
// read's: a machine's word for why a person's money is missing tells them
// nothing, and nothing here maps one into words.
//
// One account a figure could not value, the name it is written under, and the
// whole reviewed sentence saying why. Nothing on this side composes it, chooses
// between wordings, reads it, or works out what to call the account: an account
// is written once, by the one writer of accounts, and two sides each resolving
// a path is two systems describing one fact.
export type UnmeasuredAccount = { account: string; name: string; sentence: string };

// A figure carries two reviewed sentences about reaching its own evidence:
// what the control announces and what the drawer that opens is titled. Both
// are written by the read that composed the figure, because two figures held
// in two currencies must be told apart by a person who cannot see them, and a
// name composed here would be the same name twice.
export type FigureView = { id: string; display: string; exactValue: string; currency: string; measure: FigureMeasure; grade: FigureGrade; gradeLabel: string; gradeDescription: string; asOf: string; coverage: readonly string[]; caveats: string[]; evidenceLinks: EvidenceLink[]; exactness?: string | null; recordIds?: readonly string[]; evidenceLabel?: string; evidenceHeading?: string; unmeasured?: readonly UnmeasuredAccount[] };
export type DocumentPhase = "captured" | "queued" | "reading" | "held" | "parked" | "read_ready" | "verified" | "unresolved";
export type SurfaceDocument = { id: string; name: string; state: string; phase?: DocumentPhase; phaseLabel: string; detail: string; source: string; pages: string; provenance: string; evidenceLinks: EvidenceLink[]; docType?: string; resolved?: boolean; rawAvailable?: boolean; reading?: DocumentReading; sample?: { region?: string; contribution?: string; waitReason?: string } };
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

// The whole picture as the read composed it: one reviewed sentence about how
// far it reaches, the day it was read on, one figure per currency, and one
// sentence for each currency whose total was kept back — a currency that
// vanishes without a trace leaves the totals that remain reading as the whole
// of what a person holds. How old
// the evidence beneath a figure is belongs to that figure and is said in its
// own sentence, because a date taken over the whole picture would be untrue of
// every currency but one. Nothing here is composed on this side, and
// nothing anywhere adds the figures together — they are held in different
// currencies and no rate has a source, a date or a grade of its own.
// One currency whose total was kept back, and the reviewed sentence saying so.
// The currency travels beside the sentence rather than being findable in it:
// reading a sentence to learn which currency it is about is the one way this
// side could come to know it, and that door is better closed than watched. It
// is what puts the sentence in the place its figure would have taken.
export type WithheldCurrency = { currency: string; sentence: string };
// One account the read could not place under any currency. It is on no card,
// in no line and in no drawer, so the panel names it rather than counting it:
// the rule that suppresses names suppresses them where the names are already
// on the screen, and a name nowhere is not privacy, it is concealment.
export type UnplacedAccount = { account: string; name: string; sentence: string };
export type PictureView = {
  coverage: string;
  readOn: string;
  figures: readonly FigureView[];
  withheld: readonly WithheldCurrency[];
  unplaced: readonly UnplacedAccount[];
};
export type OverviewData = { picture: PictureView; corpusCoverage: string; accounts: AccountView[]; recent: ActivityView[] };
// One reviewed sentence for the whole panel, written by the backend, empty
// when the panel has nothing to say. It is never composed here and never
// repeated per row.
export type DocumentsData = { documents: SurfaceDocument[]; readingSentence: string; captureQueue: DocumentCapture[]; processingJobs: DocumentJob[]; outboundRecords: OutboundRecord[] };
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
// The capture verb a screen may use, and the read that follows it. A source
// that cannot capture carries none, so a screen with nothing behind the
// control renders no control.
export type DocumentActions = {
  upload: (path: string) => Promise<ActionResult>;
  // One document per call, and one call per gesture.
  reread: () => Promise<FeatureResult<DocumentsData>>;
};
export type SurfaceSnapshot = { mode: SurfaceMode; disclosure: { title: string; subtitle: string; detail: string }; overview: FeatureResult<OverviewData>; documents: FeatureResult<DocumentsData>; review: FeatureResult<ReviewData>; activity: FeatureResult<ActivityData>; conversation: FeatureResult<ConversationData>; trust: FeatureResult<TrustData> };
