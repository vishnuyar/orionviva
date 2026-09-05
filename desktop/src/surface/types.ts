export type Destination = "overview" | "accounts" | "activity" | "documents" | "plans" | "review" | "trust";
export type FigureGrade = "verified" | "corroborated" | "unverified" | "conflicted" | "unavailable" | "not_applicable";
export type PanelState = "absent" | "ready" | "partial" | "needs_input" | "unavailable" | "failed";
export type ActionOutcome = "completed" | "refused" | "proposal" | "waiting" | "stale" | "set_aside";
export type DocumentTerminalState = "captured_only" | "read_yielded_nothing" | "held" | "posted" | "duplicate";
export type DocumentIngestAction = "posted" | "parked" | "duplicate" | "conflict" | "gap" | "identity" | "awaiting";
// What an action answered with: the kind of thing that happened, the sentence
// Viva would say to the person, and the machine reason a refusal carries.
// `jobId` is the identity the sidecar minted for the work this outcome came
// out of, and it is absent where the reply named none — most replies do, and
// an empty string standing for that would be an identity nothing can hold. It
// is carried beside the sentence rather than found inside it, because the one
// thing a person can do to a job in flight — stop it — needs the identity and
// not the words. A document action also carries the vault's terminal state,
// ingest action, and reading state as separate closed words.
export type ActionOutcomeView = { kind: ActionOutcome; message: string; reason: string; jobId?: string; proposalId?: string; proposalSummary?: string; terminalState?: DocumentTerminalState; ingestAction?: DocumentIngestAction; reading?: DocumentReading };
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
// Where one piece of the sidecar's work stands. The set is the sidecar's and
// is closed on both sides; a word outside it is a job this interface has not
// been taught to render, and is read as no job rather than as the nearest one.
export type JobLifecycle = "queued" | "running" | "completed" | "failed" | "cancelled";
// One job as the registry holds it. `steps` is what the job declared it would
// do, in order, so a stalled job says which step it stopped at without being
// told separately. Nothing here is composed on this side: the count, the step
// and the sentence are all the sidecar's, and this interface neither counts a
// step nor writes a word for one.
export type JobView = { jobId: string; operation: string; state: JobLifecycle; completed: number; total: number; message: string; step: string; attempt: number; steps: readonly string[]; cancellable: boolean };
export type JobsData = { jobs: readonly JobView[]; running: readonly string[] };
// A subscription to what the sidecar is doing, already read into rows. A
// source that carries none is one whose host cannot deliver a statement
// mid-job, so nothing above it waits for one.
export type JobStream = (listen: (job: JobView) => void) => Promise<() => void>;
// Which destinations a read reaches, as the sidecar's own registry derived it,
// and which of this shell's destinations that registry does not declare at all.
// The second is not a rounding of the first: a screen the product has never
// heard of is a different fault from one whose read is not connected yet, and a
// shell that reported them alike would be hiding the one it caused.
export type SurfaceRegistry = { served: Record<Destination, boolean>; undeclared: readonly Destination[] };
// Which build of the engine answered. `revision` is the sidecar's own word,
// including its word for not knowing; empty means the reply carried no such
// field, which is a fact about the build rather than about the tree.
export type EngineIdentity = { protocol: string; transport: string; revision: string };
// What is in force. `keySet` is whether a key exists, never what it is: there
// is no field here a key could travel in, which is what keeps it out of every
// reply this interface can see.
export type SettingsView = { locale: string; currency: string; adapter: string; model: string; baseUrl: string; keySet: boolean; canSend: boolean };
// One reviewed change a person has been shown, and the digest their yes has to
// name. `sends` is the read's own word for whether saying yes makes bytes able
// to leave; nothing here works it out from which fields moved.
export type SettingsProposal = { kind: "presentation" | "model"; changes: Readonly<Record<string, string>>; sends: boolean; digest: string; message: string };
// Where a settings exchange stands. A proposal is held until a person says yes
// to it, which is the whole point: the reply that describes a change is not the
// change.
export type SettingsActionState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "proposed"; proposal: SettingsProposal }
  | { state: "settled"; result: ActionResult };
// Unattended work, and a file somebody can send. A source that carries neither
// renders no controls: the engine has not offered them, and a control that
// would have to refuse is worse than none.
export type TrustActions = {
  run: (spend: boolean) => Promise<ActionResult>;
  diagnose: (file: string) => Promise<ActionResult>;
};
export type TrustActionState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "settled"; result: ActionResult };
export type SettingsActions = {
  read: () => Promise<FeatureResult<SettingsView>>;
  propose: (kind: "presentation" | "model", fields: Record<string, string>) => Promise<SettingsProposal | ActionResult>;
  confirm: (kind: "presentation" | "model", fields: Record<string, string>, digest: string, key: string) => Promise<ActionResult>;
};
// Taking a whole vault out, and bringing one back. A source that carries none
// cannot do either, so the screen renders no control rather than one that would
// have to refuse. Only paths cross, and the passphrase on the way back — the
// copy is verified by being opened, and only the engine can open it.
export type VaultTransferActions = {
  export: (archive: string) => Promise<ActionResult>;
  restore: (archive: string, directory: string, passphrase: string) => Promise<ActionResult>;
};
// What became of the last copy a person asked for, out or back. One at a time,
// because each is one request and one answer.
export type TransferVerb = "export" | "restore";
export type TransferActionState =
  | { state: "idle" }
  | { state: "working"; verb: TransferVerb }
  | { state: "settled"; verb: TransferVerb; result: ActionResult };
// The question actions a screen may reach through an opened-vault bridge.
export type QuestionVerb = "answer" | "confirm" | "decline";
// What became of the last question verb a person used, held beside the question
// it was used on. An outcome belongs to one question, so a screen that moves to
// another must not keep showing it.
export type QuestionActionState =
  | { state: "idle" }
  | { state: "working"; questionId: string; verb: QuestionVerb }
  | { state: "settled"; questionId: string; verb: QuestionVerb; result: ActionResult; authoritative?: boolean; resolved?: boolean };
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
// What became of the last stop a person asked for. It is held apart from the
// capture's own state: a stop is a second piece of work with its own answer,
// and folding it into the capture's would leave one sentence standing for two
// different things that happened.
export type CancelActionState =
  | { state: "idle" }
  | { state: "working"; jobId: string }
  | { state: "settled"; jobId: string; result: ActionResult };

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
export type EvidenceLink = { targetDocumentId: string; label: string; relation: EvidenceRelation; page: string; region?: string };
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
// Whether the compact proof summary may recede is financial presentation
// policy supplied by the product. Reasons are machine audit data; the desktop
// neither renders nor interprets them.
export type ProofPresentation = { emphasis: "routine" | "required"; reasons: readonly string[]; qualifications: readonly string[] };

// A figure carries two reviewed sentences about reaching its own evidence:
// what the control announces and what the drawer that opens is titled. Both
// are written by the read that composed the figure, because two figures held
// in two currencies must be told apart by a person who cannot see them, and a
// name composed here would be the same name twice.
export type FigureView = { id: string; display: string; exactValue: string; currency: string; measure: FigureMeasure; grade: FigureGrade; gradeLabel: string; gradeDescription: string; proofPresentation: ProofPresentation; asOf: string; coverage: readonly string[]; caveats: string[]; evidenceLinks: EvidenceLink[]; exactness?: string | null; recordIds?: readonly string[]; evidenceLabel?: string; evidenceHeading?: string; unmeasured?: readonly UnmeasuredAccount[] };
export type DocumentPhase = "captured" | "queued" | "reading" | "held" | "parked" | "read_ready" | "verified" | "unresolved";
// `contribution` is the reviewed sentence saying what this document put on the
// books — a figure and the account it was attested on, or the line for a
// document nothing rests on. It is per row rather than per panel because it is
// about that document and no other, and it is never composed here.
export type SurfaceDocument = { id: string; name: string; contribution?: string; state: string; phase?: DocumentPhase; phaseLabel: string; detail: string; source: string; pages: string; provenance: string; evidenceLinks: EvidenceLink[]; docType?: string; resolved?: boolean; rawAvailable?: boolean; reading?: DocumentReading; snapshotStatus?: "posted" | "held" | "unavailable"; snapshotSentence?: string; activityStatus?: "complete" | "incomplete" | "unavailable" | "not_applicable"; activitySentence?: string };
export type DocumentCapture = { id: string; label: string; state: "captured" | "processing" | "held" | "ready" | "sent"; detail: string; source: string; note: string };
export type DocumentJob = { id: string; label: string; state: "running" | "paused" | "done"; detail: string; progress: string };
export type OutboundRecord = { id: string; label: string; state: "queued" | "sent" | "blocked"; detail: string; destination: string };
export type AccountView = { id: string; name: string; maskedNumber: string; kind: string; measure: "balance" | "owed" | null; exactValue: string; currency: string; display: string; grade: FigureGrade; gradeLabel: string; gradeDescription: string; proofPresentation: ProofPresentation; note: string | null; asOf: string; coverage: string | null; provenance: string | null; evidenceLinks: EvidenceLink[]; state: PanelState; caveats?: readonly string[]; exactness?: string | null; recordIds?: readonly string[] };
// One thing a question needs back. `wants` is the queue's own sentence saying
// what kind of thing that is, and `choices` is the closed vocabulary an answer
// must land in — the vocabulary tokens. Both are the backend's.
export type QuestionSlot = { name: string; type: string; required: boolean; wants: string; choices: readonly string[] };
export type QuestionReferences = { movement?: string; movements?: readonly string[]; candidates?: readonly string[]; document?: string; doc_id?: string; account?: string };
export type QuestionView = { id: string; slots?: readonly QuestionSlot[]; refs?: QuestionReferences; reviewBinding?: ReviewQuestionBinding; label: string; detail: string; status: string; action: string; type: string; evidence: string; state: "needs_input" | "partial"; outcome: ActionOutcome | null; disposition: "answer" | "decline" | "proposal" | "confirm" | null; count?: number; scope?: string; currency?: string; amount?: string };
export type ConversationProposal = { id: string; summary: string; status: string; outcome: string; message: string; reason: string };
export type ConversationTurn = { id: string; kind: "ask" | "answer" | "decline" | "confirm"; occurredAt: string; prompt: string; said: string; questionId: string; outcome: ActionOutcome; message: string; reason: string; answer: TurnView | null; proposal: ConversationProposal | null };

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
export type ObligationView = { id: string; subject: string; cadence: string; expectedDate: string; status: "due" | "expected"; basis: "confirmed" | "measured" | "observed"; amountDisplay: string; amountMin: string; amountMax: string; currency: string; grade: string; headline: string; explanation: string; coverage: string; recordIds: readonly string[]; evidenceIds: readonly string[]; accountIds: readonly string[]; caveats: readonly string[]; requiredVisibility: boolean; actions: readonly ("inspect" | "ask_viva")[] };
export type FindingView = { id: string; kind: string; subject: string; importance: number; amountDisplay: string; exactValue: string; currency: string; dated: string; headline: string; explanation: string; coverage: string; recordIds: readonly string[]; evidenceIds: readonly string[]; accountIds: readonly string[]; requiredVisibility: boolean; actions: readonly ("inspect" | "ask_viva" | "set_aside")[] };
export type UtilityView = { state: "ready" | "absent"; obligations: readonly ObligationView[]; findings: readonly FindingView[]; findingCount: number };
export type CurrentPeriodCompletenessView = { balances: boolean; income: boolean; obligations: boolean; plannedSpending: boolean; goals: boolean };
export type CurrentPeriodExclusionView = { kind: string; identity: string; reason: string; sentence: string; currency: string; evidenceDates: readonly string[]; recordIds: readonly string[]; evidenceIds: readonly string[]; accountIds: readonly string[] };
export type CurrentPeriodStepView = { date: string; kind: "balance" | "income" | "obligation" | "goal"; subject: string; amountDisplay: string; amountMin: string; amountMax: string; balanceDisplay: string; balanceMin: string; balanceMax: string; tooltip: string; evidenceDates: readonly string[]; recordIds: readonly string[]; evidenceIds: readonly string[]; accountIds: readonly string[] };
export type CurrentPeriodSliceView = { id: string; currency: string; horizonStart: string; horizonEnd: string; headline: string; explanation: string; amountDisplay: string; liquidBalance: string; expectedIncomeMin: string; expectedIncomeMax: string; obligationsMin: string; obligationsMax: string; reservedForGoals?: string; goalContributions?: string; remainderMin: string; remainderMax: string; coverage: string; grade: FigureGrade; gradeLabel: string; gradeDescription: string; proofPresentation: ProofPresentation; evidenceLabel: string; evidenceHeading: string; assumptions: readonly string[]; caveats: readonly string[]; missingInputs: readonly string[]; completeness: CurrentPeriodCompletenessView; exclusions: readonly CurrentPeriodExclusionView[]; evidenceDates: readonly string[]; recordIds: readonly string[]; evidenceLinks: readonly EvidenceLink[]; evidenceIds: readonly string[]; accountIds: readonly string[]; series: readonly CurrentPeriodStepView[]; requiredVisibility: boolean };
export type CurrentPeriodView = { state: "absent" | "ready" | "limited" | "refused"; title: string; kicker: string; horizonStart: string; horizonEnd: string; slices: readonly CurrentPeriodSliceView[]; exclusions: readonly CurrentPeriodExclusionView[]; refusal: string };
export type OverviewData = { picture: PictureView; accounts: AccountView[]; utility?: UtilityView; currentPeriod?: CurrentPeriodView };
export type SpendingPeriodId = "latest_complete_month" | "current_month" | "last_3_months" | "year_to_date" | "custom";
export type SpendingGranularity = "category" | "subcategory";
export type SpendingRequest = { period: SpendingPeriodId; granularity: SpendingGranularity; currency?: string; accountId?: string; startDate?: string; endDate?: string };
export type SpendingBar = { id: string; order: number; label: string; amountDisplay: string; shareBasisPoints: number; barBasisPoints: number; count: number; colorToken: "category-1" | "category-2" | "category-3" | "category-4" | "category-5" | "category-6" };
export type SpendingSection = { currency: string; order: number; includedCount: number; totalDisplay: string; bars: readonly SpendingBar[]; emptyMessage: string };
export type SpendingCoverageGap = { order: number; accountId: string; accountLabel: string; from: string; to: string; reason: "missing_statement_coverage"; sentence: string };
export type SpendingUnsupportedAccount = { order: number; accountId: string; label: string; currency: string; reason: "missing_account_id" | "missing_account_name" | "unsupported_account_kind" | "missing_account_currency"; sentence: string };
export type SpendingBreakdownData = {
  contract: "SpendingBreakdown.v1";
  state: "ready" | "empty";
  title: string;
  asOf: string;
  timezonePolicy: string;
  period: { id: SpendingPeriodId; label: string; startDate: string; endDate: string };
  granularity: SpendingGranularity;
  scopeSummary: string;
  controls: {
    periods: readonly { id: SpendingPeriodId; label: string; requiresCustom: boolean }[];
    granularities: readonly { id: SpendingGranularity; label: string }[];
    accounts: readonly { id: string; label: string; currency: string; order: number }[];
    currencies: readonly { id: string; label: string; order: number }[];
    selectedPeriod: SpendingPeriodId;
    selectedGranularity: SpendingGranularity;
    selectedAccountId: string;
    selectedCurrency: string;
  };
  sections: readonly SpendingSection[];
  coverage: { state: "complete" | "partial" | "unavailable"; label: string; coveredFrom: string; coveredTo: string; includedCount: number; excludedCount: number; gaps: readonly SpendingCoverageGap[]; unsupportedAccounts: readonly SpendingUnsupportedAccount[] };
  exclusions: readonly { kind: string; count: number; sentence: string }[];
  notes: readonly string[];
};
export type SpendingBreakdownReader = { read: (request: SpendingRequest) => Promise<FeatureResult<SpendingBreakdownData>> };
export type PlanVerb = "create" | "change_terms" | "reserve" | "release" | "pause" | "resume" | "set_aside";
export type PlanPayload = Readonly<Record<string, string | number | null>>;
export type GoalAccountView = { id: string; name: string; currency: string; eligible: boolean; balance: string; balanceDisplay: string; reserved: string; reservedDisplay: string; available: string; availableDisplay: string; grade: FigureGrade | ""; gradeDescription: string; dated: string; asOf: string; balanceExplanation: string; sourceDocumentId: string; sourcePage: string; sourceRegion: string; sourceNote: string; caveats: readonly string[]; sentence: string; reason: string; evidenceLinks: readonly EvidenceLink[] };
export type GoalHistoryView = { kind: "reserved" | "released"; accountId: string; amount: string; amountDisplay: string; reason: string; occurredAt: string; sentence: string; valid: boolean };
export type GoalPlanView = { id: string; title: string; group: "active" | "paused" | "complete" | "set_aside"; state: "active" | "paused" | "set_aside"; status: "complete" | "paused" | "ahead" | "on_track" | "at_risk" | "unscheduled"; statusLabel: string; headline: string; explanation: string; currency: string; targetAmount: string; targetDisplay: string; targetDate: string; reserved: string; reservedDisplay: string; remaining: string; remainingDisplay: string; monthlyContribution: string; monthlyDisplay: string; contributionDay: number | null; requiredMonthly: string; requiredMonthlyDisplay: string; projectedCompletionDate: string; deviation: string; deviationDisplay: string; nextContributionDate: string; noMoneyMoved: string; accounts: readonly GoalAccountView[]; history: readonly GoalHistoryView[]; historyNote: string; assumptions: readonly string[]; caveats: readonly string[]; actions: readonly PlanVerb[] };
export type GoalProposalView = { id: string; verb: PlanVerb; goalId: string; summary: string; consequence: string; noMoneyMoved: string; exact: PlanPayload; display: Readonly<Record<string, string>>; assumptions: readonly string[]; actions: readonly ("confirm" | "decline")[] };
export type PlansData = { state: "absent" | "ready" | "partial"; title: string; invitation: { title: string; body: string }; noMoneyMoved: string; goals: readonly GoalPlanView[]; groups: Readonly<Record<string, readonly string[]>>; proposals: readonly GoalProposalView[]; actions: readonly ("draft" | "propose" | "confirm" | "decline")[] };
export type PlanDraftView = { verb: PlanVerb; payload: PlanPayload; calculated: Readonly<Record<string, string>> };
export type PlanDraftResult = { state: "settled"; kind: "ready" | "needs_input" | "refused"; message: string; reason: string; draft: PlanDraftView | null } | Exclude<ActionResult, { state: "settled" }>;
export type ConversationGoalDraft = { kind: "ready" | "needs_input" | "refused"; message: string; reason: string; verb: PlanVerb; draft: PlanDraftView | null; reviewInPlans: boolean };
export type PlanActions = { draft: (payload: PlanPayload) => Promise<PlanDraftResult>; propose: (payload: PlanPayload) => Promise<ActionResult>; confirm: (proposalId: string) => Promise<ActionResult>; decline: (proposalId: string) => Promise<ActionResult> };
// One reviewed sentence for the whole panel, written by the backend, empty
// when the panel has nothing to say. It is never composed here and never
// repeated per row.
export type DocumentsData = { documents: SurfaceDocument[]; readingSentence: string; captureQueue: DocumentCapture[]; processingJobs: DocumentJob[]; outboundRecords: OutboundRecord[] };
export type QuestionQueueData = { queue: QuestionView[]; count: number; meta: { total: number; tail: { count: number; amount: string } | null; pending: { count: number } | null; invite: string; answeredByDocument: string } };
export type ReviewContext = { date: string; amount: string; account: string; merchant: string };
export type ReviewConversationTarget = { kind: "conversation"; questionId: string; disclosure: string };
export type ReviewTransactionTarget = { kind: "transaction"; questionId: string; accountId: string; requestedMovementId: string; canonicalMovementId: string; memberMovementIds: readonly string[] };
export type ReviewTarget = ReviewConversationTarget | ReviewTransactionTarget;
export type ReviewQuestionReferences = { movement: string; movements: readonly string[]; candidates: readonly string[]; document: string; documentId: string; account: string };
export type ReviewQuestionBinding = { itemId: string; questionId: string; questionKind: string; label: string; reason: string; refs: ReviewQuestionReferences; target: ReviewTarget; status: "open"; primaryAction: "open_question" | "open_transaction"; allowedActions: readonly ("open_question" | "open_transaction")[] };
export type ReviewItem = { id: string; type: "question"; typeLabel: string; marker: "?"; markerLabel: string; label: string; reason: string; status: "open"; context: ReviewContext; target: ReviewTarget; primaryAction: "open_question" | "open_transaction"; actionLabel: string; allowedActions: readonly ("open_question" | "open_transaction")[]; binding: ReviewQuestionBinding };
export type ReviewGroup = { id: "questions"; label: string; count: number; items: readonly ReviewItem[] };
export type ReviewData = { contract: "ReviewSummary.v1"; title: string; summary: string; actionableCount: number; shownCount: number; remainingCount: number; types: readonly { id: "questions"; label: string; count: number }[]; groups: readonly ReviewGroup[] };
// One movement as the live read composed it. `direction` is the read's answer
// and comes from the kind of account the money moved on; `amount` is unsigned
// beside it, because a sign and a word saying the same thing are two chances to
// disagree. `sentence` is empty on an ordinary spending row and is never
// composed here.
export type ActivityVocabularyItem = { id: string; label: string };
export type ActivitySubcategoryVocabularyItem = ActivityVocabularyItem & { categoryId: string };
export type ActivityCategoryVocabulary = { items: readonly ActivityVocabularyItem[]; complete: boolean; limit: number };
export type ActivitySubcategoryVocabulary = { items: readonly ActivitySubcategoryVocabularyItem[]; complete: boolean; limit: number };
export type ActivityTagVocabulary = ActivityCategoryVocabulary & { maxSelected: number; maxLabelLength: number };
export type ActivityRowAction = "assign_category" | "assign_meaning" | "replace_tags" | "confirm_transfer" | "reject_transfer" | "unlink_transfer";
export type ActivityTransferReference = { id: string; date: string; description: string; account: string; accountId: string; accountName: string; direction: "in" | "out"; exactValue: string; currency: string; display: string };
export type ActivityTransferState =
  | { state: "none" }
  | { state: "suggested"; explanation: string; candidates: readonly (ActivityTransferReference & { relationship: string })[]; complete: boolean; limit: number }
  | { state: "linked"; explanation: string; counterpart: ActivityTransferReference; relationship: string };
export type ActivityTreatment = { kind: "spending" | "loan" | "loan_repayment" | "settlement" | "mixed" | "not_spending"; name: string };
export type ActivityClassification = { grade: "verified" | "corroborated" | "unverified" | "conflicted"; provenance: string };
export type ActivityClassificationValue = { id: string | null; label: string; valid: boolean };
export type MovementView = { id: string; date: string; description: string; account: string; accountId: string; accountName: string; direction: "in" | "out"; exactValue: string; currency: string; display: string; nature: string; treatment: ActivityTreatment; loanRepaymentChoices: readonly string[]; sentence: string; decidedBy: string; provisional: boolean; linked: boolean; category: ActivityClassificationValue; subcategory: ActivityClassificationValue; classification: ActivityClassification | null; classificationValid: boolean; tags: readonly ActivityVocabularyItem[]; tagsValid: boolean; evidenceLinks: readonly EvidenceLink[]; evidenceLinksValid: boolean; transfer: ActivityTransferState | null; actions: readonly ActivityRowAction[] };
export type ActivityData = { sentence: string; movements: readonly MovementView[]; beyond: { count: number }; vocabularies: { categories: ActivityCategoryVocabulary; subcategories: ActivitySubcategoryVocabulary; tags: ActivityTagVocabulary } };
export type AccountLedgerBalance =
  | { state: "available"; kind: "current_balance" | "amount_owed"; exactValue: string; display: string; asOf: string; grade: "verified" | "corroborated" | "unverified" | "conflicted" }
  | { state: "absent"; reason: "no_authoritative_balance_observation" };
export type AccountLedgerAccount = { id: string; name: string; maskedNumber: string; type: "depository" | "liability" | "investment"; currency: string; balance: AccountLedgerBalance };
export type AccountLedgerCoverageRun = { from: string; to: string; statementIds: readonly string[] };
export type AccountLedgerGap = { from: string; to: string; reason: "missing_statement_coverage" };
export type AccountLedgerRowDeduplication = { state: "single" | "exact_duplicate"; canonicalMovementId: string; memberMovementIds: readonly string[] };
export type AccountLedgerMovement = MovementView & { directionDisplay: "Debit" | "Credit" | "Direction unavailable"; deduplication: AccountLedgerRowDeduplication };
export type AccountLedgerDeduplication = {
  state: "none" | "exact_duplicates_collapsed" | "unresolved_candidates_present" | "exact_duplicates_collapsed_with_unresolved_candidates";
  policy: "exact_economic_posting_in_overlapping_statements_only";
  collapsed: readonly { canonicalMovementId: string; memberMovementIds: readonly string[]; documentIds: readonly string[] }[];
  unresolved: readonly { kind: "probable" | "conflicting"; movementIds: readonly [string, string]; documentIds: readonly [string, string] }[];
};
export type AccountLedgerOverlap = { state: "none_observed" | "overlap_present"; deduplication: AccountLedgerDeduplication; groups: readonly { from: string; to: string; documentIds: readonly [string, string] }[] };
export type AccountLedgerSource = { documentId: string; accountId: string; filename: string; relation: "statement" | "movement_evidence" | "statement_and_movement_evidence"; period: { from: string; to: string } | null };
export type AccountLedgerData = {
  scope: { kind: "account"; accountId: string };
  revision: string;
  account: AccountLedgerAccount;
  coverage: { state: "unavailable" | "continuous" | "gapped" | "discontinuous"; runs: readonly AccountLedgerCoverageRun[]; gaps: readonly AccountLedgerGap[] };
  reconciliation: { balance: "reconciled" | "conflicted" | "not_established"; overlap: AccountLedgerOverlap; runningBalance: { state: "absent"; reason: "not_authoritatively_available" } };
  sources: readonly AccountLedgerSource[];
  groups: readonly { month: string; label: string; movements: readonly AccountLedgerMovement[] }[];
  page: { limit: number; returned: number; remaining: number; nextCursor: string | null };
};
export type AccountLedgerReader = { read: (accountId: string, cursor?: string, limit?: number) => Promise<FeatureResult<AccountLedgerData>> };
export type ActivityCorrectionVerb = "category" | "classification" | "meaning" | "tags" | "add_tags" | "remove_tags" | "confirm_transfer" | "reject_transfer" | "unlink_transfer";
export type ActivityActionOutcome = { kind: "completed" | "refused" | "stale"; message: string; reason: string };
export type ActivityActionResult =
  | { state: "settled"; outcome: ActivityActionOutcome }
  | Exclude<ActionResult, { state: "settled" }>;
export type ActivityCorrectionState =
  | { state: "idle" }
  | { state: "working"; movementId: string; movementIds: readonly string[]; verb: ActivityCorrectionVerb }
  | { state: "refreshing"; movementId: string; movementIds: readonly string[]; verb: ActivityCorrectionVerb; result: ActivityActionResult }
  | { state: "settled"; movementId: string; movementIds: readonly string[]; verb: ActivityCorrectionVerb; result: ActivityActionResult; refresh: "refreshed" | "failed" };
export type ActivityActions = {
  read: (limit: number) => Promise<FeatureResult<ActivityData>>;
  assignCategory: (movementId: string, categoryId: string) => Promise<ActivityActionResult>;
  assignClassification: (movementIds: readonly string[], categoryId: string, subcategoryId: string) => Promise<ActivityActionResult>;
  assignMeaning: (movementId: string, meaning: string, counterparty: string) => Promise<ActivityActionResult>;
  replaceTags: (movementId: string, tagIds: readonly string[]) => Promise<ActivityActionResult>;
  addTags: (movementIds: readonly string[], tagIds: readonly string[]) => Promise<ActivityActionResult>;
  removeTags: (movementIds: readonly string[], tagIds: readonly string[]) => Promise<ActivityActionResult>;
  confirmTransfer: (movementId: string, counterpartId: string) => Promise<ActivityActionResult>;
  rejectTransfer: (movementId: string) => Promise<ActivityActionResult>;
  unlinkTransfer: (movementId: string, counterpartId: string) => Promise<ActivityActionResult>;
};
export type OverviewActions = {
  setAsideFinding: (findingId: string) => Promise<ActionResult>;
};
// One figure a spoken or written answer stated, and the route back to what it
// rests on. `written` is the words the sentence wrote the figure as, so the
// figure under the sentence is the figure in it — not a second rendering of the
// same number.
export type TurnFigure = { id: string; evidenceId: string; written: string; grade: string; what: string; recordIds: readonly string[]; evidenceLinks: readonly EvidenceLink[] };
// What a voice surface may say of one turn, and what it may not. Every sentence
// here was written on the other side of the bridge; a surface that assembled
// its own would be speaking a figure under wording nobody reviewed.
export type SpokenTurn = { maySpeak: boolean; withheld: string; parts: readonly string[]; text: string; gradeSentence: string; citationSentence: string; localOnly: string };
export type AnswerStatus = "answered" | "partial" | "needs_clarification" | "needs_assumption" | "missing_data" | "capability_gap" | "outside_domain" | "failed";
export type AnswerOption = { id: string; label: string };
export type SupportedAnswerKind = { id: string; label: string; example: string };
export type MissingAnswerInput = { tag: string; label: string; question: string; requestedFamily?: string; requestedLabel?: string; supportedFamilies?: readonly SupportedAnswerKind[] };
// One whole turn. The grade sentence is a whole reviewed sentence rather than a
// word in a frame, and it is the read's.
export type TurnView = { question: string; text: string; answered: boolean; status: AnswerStatus; outcomeTag: string; refusal: string; grade: string; gradeSentence: string; figures: readonly TurnFigure[]; options: readonly AnswerOption[]; missing: readonly MissingAnswerInput[]; spoken: SpokenTurn; goalDraft?: ConversationGoalDraft | null };
export type ConversationActions = {
  ask: (question: string, mirrored: boolean, planRequest?: boolean) => Promise<{ result: ActionResult; turn: TurnView | null }>;
  answer: (questionId: string, said: string) => Promise<ActionResult>;
  confirm: (proposalId: string, said: string, asked: string) => Promise<ActionResult>;
  decline: (questionId: string, reason: DeclineReason) => Promise<ActionResult>;
  reread: () => Promise<FeatureResult<ConversationData>>;
  rereadTrust: () => Promise<FeatureResult<TrustData>>;
};
export type AskActionState =
  | { state: "idle" }
  | { state: "working"; question: string }
  | { state: "settled"; question: string; result: ActionResult; turn: TurnView | null; authoritative?: boolean };
export type ConversationData = { turns: ConversationTurn[]; questions: QuestionQueueData };
// What this application says about being updated and about being recovered.
// There is no update channel; every sentence here is the engine's account of
// that, and of how this copy got onto the machine.
export type UpdateLifecycleView = { readonly sentence: string; readonly originSentence: string; readonly revision: string; readonly notes: readonly { readonly id: string; readonly sentence: string }[] };
export type TrustNote = { readonly id: string; readonly title: string; readonly detail: string };
// One line of the outbound record, or one absence it carries. The sentence is
// the read's in every case: a screen that composes its own caveat writes it out
// of date the day the capability lands, and nothing goes red when it does.
export type OutboundLine = { id: string; count: number; sentence: string };
export type OutboundModel = { name: string; count: number };
// What a whole outbound record says. `callCount` of zero with a sentence is a
// vault that has sent nothing — which is the record, not an empty panel.
export type OutboundRecordView = {
  sentence: string;
  callCount: number;
  phases: readonly OutboundLine[];
  models: readonly OutboundModel[];
  reportedModels?: readonly OutboundModel[];
  legacyModels?: readonly OutboundModel[];
  tokens?: { input: number; output: number; total: number; measuredCalls: number };
  modelSentence: string;
  span: { first: string; last: string; sentence: string } | null;
  cost: { exactValue: string; currency: string; display: string; sentence: string } | null;
  absences: readonly { id: string; sentence: string }[];
};
// What nothing on this machine can establish, as the read says it. Each is a
// whole reviewed sentence and none is composed here — an absent capability
// described in a screen's own soft words reads as a capability.
export type TrustAbsence = { id: string; sentence: string };
export type TrustData = { notes: TrustNote[]; absences?: readonly TrustAbsence[]; outbound?: OutboundRecordView };
// The capture verb a screen may use, and the read that follows it. A source
// that cannot capture carries none, so a screen with nothing behind the
// control renders no control.
// One change a pass back over the vault made, or one standing fact it
// reported. The sentence is the backend's: this side has no words for what a
// gap is, and inventing some is exactly what a reviewed read model prevents.
export type RescanChange = { id: string; count: number; sentence: string; movementIds?: readonly string[] };
// What a pass did, as the read model composed it. `changes` is empty for a
// pass that changed nothing, which is why the panel's own sentence is carried
// separately — an empty list and a sweep that found nothing read alike.
export type RescanReport = { sentence: string; changes: readonly RescanChange[]; standing: readonly RescanChange[]; linkCount: number };
// What became of the last pass a person asked for.
export type RescanActionState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "settled"; result: ActionResult; report: RescanReport | null };
export type DocumentActions = {
  // One document per call, and one call per gesture.
  upload: (path: string) => Promise<ActionResult>;
  // Stop one job by the identity the sidecar minted for it, and read the
  // registry back. The read is separate because a stop that reached nothing
  // and a stop that worked both answer, and only the registry says which
  // jobs are left.
  cancel: (jobId: string) => Promise<ActionResult>;
  readJobs: () => Promise<FeatureResult<JobsData>>;
  // A pass back over what is already held, and the read that follows it: the
  // pass writes links and heals, so what the documents screen shows can move
  // under it.
  rescan: () => Promise<{ result: ActionResult; report: RescanReport | null }>;
  reread: () => Promise<FeatureResult<DocumentsData>>;
};
export type SurfaceSnapshot = { disclosure: { title: string; subtitle: string; detail: string }; overview: FeatureResult<OverviewData>; documents: FeatureResult<DocumentsData>; activity: FeatureResult<ActivityData>; conversation: FeatureResult<ConversationData>; review?: FeatureResult<ReviewData>; plans?: FeatureResult<PlansData>; trust: FeatureResult<TrustData> };
