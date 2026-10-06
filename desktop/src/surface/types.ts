export type Destination = "overview" | "accounts" | "activity" | "documents" | "plans" | "review" | "trust";
export type FigureGrade = "verified" | "corroborated" | "unverified" | "conflicted" | "unavailable" | "not_applicable";
export type PanelState = "absent" | "ready" | "partial" | "needs_input" | "unavailable" | "failed";
export type ActionOutcome = "completed" | "refused" | "proposal" | "waiting" | "stale" | "set_aside";
export type DocumentTerminalState = "captured_only" | "read_yielded_nothing" | "held" | "posted" | "duplicate";
export type DocumentIngestAction = "posted" | "parked" | "duplicate" | "conflict" | "gap" | "identity" | "awaiting";
// Action outcome, reviewed sentence and machine refusal reason. Optional `jobId`
// is the sidecar-supplied identity, separate from the sentence; absent means none
// was supplied. Document actions also carry closed terminal, ingest and read states.
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
  | { state: "unreadable" }
  | { state: "interrupted"; message: string };
// Where one piece of the sidecar's work stands. The set is the sidecar's and
// is closed on both sides; a word outside it is a job this interface has not
// been taught to render, and is read as no job rather than as the nearest one.
export type JobLifecycle = "queued" | "running" | "completed" | "failed" | "cancelled";
// One job as the registry holds it. `steps` is what the job declared it would
// do, in order, so a stalled job says which step it stopped at without being
// told separately. Nothing here is composed on this side: the count, the step
// and the sentence are all the sidecar's, and this interface neither counts a
// step nor writes a word for one.
export type JobView = { jobId: string; operation: string; state: JobLifecycle; completed: number; total: number; message: string; step: string; attempt: number; steps: readonly string[]; cancellable: boolean; recovery?: { state: "available" | "blocked" | "settled"; message: string } };
export type JobsData = { jobs: readonly JobView[]; running: readonly string[] };
// A subscription to what the sidecar is doing, already read into rows. A
// source that carries none is one whose host cannot deliver a statement
// mid-job, so nothing above it waits for one.
export type JobStream = (listen: (job: JobView) => void) => Promise<() => void>;
// Registry-derived read standing and shell destinations absent from that registry
// remain separate fields.
export type SurfaceRegistry = { served: Record<Destination, boolean>; undeclared: readonly Destination[] };
// Which build of the engine answered. `revision` is the sidecar's own word,
// including its word for not knowing; empty means the reply carried no such
// field, which is a fact about the build rather than about the tree.
export type EngineIdentity = { protocol: string; transport: string; revision: string };
// Current machine settings expose key presence through `keySet`, without key bytes.
export type SettingsView = { locale: string; currency: string; adapter: string; model: string; baseUrl: string; keySet: boolean; canSend: boolean };
// One reviewed change a person has been shown, and the digest their yes has to
// name. `sends` is the read's own word for whether saying yes makes bytes able
// to leave; nothing here works it out from which fields moved.
export type SettingsProposal = { kind: "presentation" | "model"; changes: Readonly<Record<string, string>>; sends: boolean; digest: string; message: string };
// Settings exchange state retains a proposal until explicit confirmation.
export type SettingsActionState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "proposed"; proposal: SettingsProposal }
  | { state: "settled"; result: ActionResult };
// Optional unattended-work and diagnostic actions; absent actions render no controls.
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
// Optional export and restore actions. Paths and the restore passphrase cross
// the bridge; the engine verifies the copy by opening it.
export type VaultTransferActions = {
  export: (archive: string) => Promise<ActionResult>;
  restore: (archive: string, directory: string, passphrase: string) => Promise<ActionResult>;
};
// The last export or restore result, with one request in flight at a time.
export type TransferVerb = "export" | "restore";
export type TransferActionState =
  | { state: "idle" }
  | { state: "working"; verb: TransferVerb }
  | { state: "settled"; verb: TransferVerb; result: ActionResult };
// The question actions a screen may reach through an opened-vault bridge.
export type QuestionVerb = "answer" | "confirm" | "decline";
// The last question-action outcome belongs to its selected question and clears
// when that question changes.
export type QuestionActionState =
  | { state: "idle" }
  | { state: "working"; questionId: string; verb: QuestionVerb }
  | { state: "settled"; questionId: string; verb: QuestionVerb; result: ActionResult; authoritative?: boolean; resolved?: boolean };
export type DeclineReason = "not_now" | "dont_know";
// Notice kinds determine presentation directly; the sentence is not classified.
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
// The last stop request has its own outcome, separate from capture state.
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
// `coverage` preserves ordered complete sentences without joining or splitting.
// `unmeasured` carries account names and read-supplied explanations for omitted values.
export type UnmeasuredAccount = { account: string; name: string; sentence: string };
// Whether the compact proof summary may recede is financial presentation
// policy supplied by the product. Reasons are machine audit data; the desktop
// neither renders nor interprets them.
export type ProofPresentation = { emphasis: "routine" | "required"; reasons: readonly string[]; qualifications: readonly string[] };

// The read supplies distinct evidence-control and drawer-title sentences per figure.
export type FigureView = { id: string; display: string; exactValue: string; currency: string; measure: FigureMeasure; grade: FigureGrade; gradeLabel: string; gradeDescription: string; proofPresentation: ProofPresentation; asOf: string; coverage: readonly string[]; caveats: string[]; evidenceLinks: EvidenceLink[]; exactness?: string | null; recordIds?: readonly string[]; evidenceLabel?: string; evidenceHeading?: string; unmeasured?: readonly UnmeasuredAccount[] };
export type DocumentPhase = "captured" | "queued" | "reading" | "held" | "parked" | "read_ready" | "verified" | "unresolved";
// Each document row carries the read-supplied sentence describing its contribution.
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
export type AskContextMode = "new_question" | "follow_up";
export type ConversationTurn = { id: string; kind: "ask" | "answer" | "decline" | "confirm"; contextMode?: AskContextMode | "legacy"; occurredAt: string; prompt: string; said: string; questionId: string; outcome: ActionOutcome; message: string; reason: string; answer: TurnView | null; proposal: ConversationProposal | null };

// The Overview read supplies population coverage, read date and per-currency figures
// and withheld-total sentences. Each figure retains its own evidence date; currencies
// are not added together.
export type WithheldCurrency = { currency: string; sentence: string };
// Accounts lacking any currency are named at the panel because no currency card
// or drawer contains them.
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
export type AccountingLine = { existingExplanation?: string; supportingComponents?: readonly { label: string; display: string }[]; documentIds?: readonly string[]; id: string; label: string; account: string; date: string; currency: string; display: string; provisional: boolean; amountEvidence: string; classificationEvidence: string; classifiedBy: string; origin: string };
export type AccountingNode = { label: string; display: string; children: AccountingNode[] };
export type AccountingView = { asOf: string; start: string; end: string; balanceComplete: boolean; profitComplete: boolean; balanceTotals: { currency: string; values: Record<string, string> }[]; profitTotals: { currency: string; values: Record<string, string> }[]; balances: AccountingLine[]; lines: AccountingLine[]; unresolved: AccountingLine[]; missing: { label: string; reason: string }[]; heldCount: number; hierarchy: { currency: string; roots: AccountingNode[] }[] };
export type OverviewData = { accounting?: AccountingView; picture: PictureView; accounts: AccountView[]; utility?: UtilityView; currentPeriod?: CurrentPeriodView };
export type AccountingReader = (start: string, end: string) => Promise<FeatureResult<AccountingView>>;
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
// A movement retains its read-supplied account-kind direction, unsigned amount and
// sentence. Ordinary spending has an empty sentence.
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
export type ActivityPage = { version: 1; revision: string; nextCursor: string | null; cumulativeCount: number; remainingCount: number; focus: string };
export type ActivityData = { sentence: string; movements: readonly MovementView[]; beyond: { count: number }; page?: ActivityPage; loadingMore?: boolean; continuationFailed?: boolean; continuationInvalidated?: boolean; vocabularies: { categories: ActivityCategoryVocabulary; subcategories: ActivitySubcategoryVocabulary; tags: ActivityTagVocabulary } };
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
  read: (limit: number, cursor?: string, focus?: string) => Promise<FeatureResult<ActivityData>>;
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
// An answer figure carries its source route and the exact `written` rendering
// used in the answer sentence.
export type TurnFigure = { id: string; evidenceId: string; written: string; grade: string; what: string; recordIds: readonly string[]; evidenceLinks: readonly EvidenceLink[] };
// Voice output carries complete read-supplied sentences for the turn.
export type SpokenTurn = { maySpeak: boolean; withheld: string; parts: readonly string[]; text: string; gradeSentence: string; citationSentence: string; localOnly: string };
export type AnswerStatus = "answered" | "partial" | "needs_clarification" | "needs_assumption" | "missing_data" | "capability_gap" | "outside_domain" | "failed";
export type AnswerOption = { id: string; label: string };
export type SupportedAnswerKind = { id: string; label: string; example: string };
export type MissingAnswerInput = { tag: string; label: string; question: string; requestedFamily?: string; requestedLabel?: string; supportedFamilies?: readonly SupportedAnswerKind[] };
// One whole turn. The grade sentence is a whole reviewed sentence rather than a
// word in a frame, and it is the read's.
export type TurnView = { question: string; text: string; answered: boolean; status: AnswerStatus; outcomeTag: string; refusal: string; grade: string; gradeSentence: string; figures: readonly TurnFigure[]; options: readonly AnswerOption[]; missing: readonly MissingAnswerInput[]; spoken: SpokenTurn; goalDraft?: ConversationGoalDraft | null; accountingCorrection?: { id: string; movementIds: readonly string[]; ruleId: string } | null };
export type ConversationActions = {
  undoCorrection?: (correctionId: string) => Promise<ActionResult>;
  ask: (question: string, mirrored: boolean, planRequest?: boolean, contextMode?: AskContextMode, movementIds?: readonly string[]) => Promise<{ result: ActionResult; turn: TurnView | null }>;
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
// Each outbound record or declared absence carries its read-supplied sentence.
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
// Unsupported local capabilities carry complete read-supplied explanations.
export type TrustAbsence = { id: string; sentence: string };
export type TrustData = { notes: TrustNote[]; absences?: readonly TrustAbsence[]; outbound?: OutboundRecordView };
// Optional document capture and the subsequent read; absent actions render no control.
export type RescanChange = { id: string; count: number; sentence: string; movementIds?: readonly string[] };
// A rescan report carries its own sentence separately from its possibly empty changes.
export type RescanReport = { sentence: string; changes: readonly RescanChange[]; standing: readonly RescanChange[]; linkCount: number };
// What became of the last pass a person asked for.
export type RescanActionState =
  | { state: "idle" }
  | { state: "working" }
  | { state: "settled"; result: ActionResult; report: RescanReport | null };
export type DocumentActions = {
  // One document per call, and one call per gesture.
  upload: (path: string) => Promise<ActionResult>;
  recover?: (jobId: string) => Promise<ActionResult>;
  // Stop a sidecar job by identity, then read the authoritative job registry.
  cancel: (jobId: string) => Promise<ActionResult>;
  readJobs: () => Promise<FeatureResult<JobsData>>;
  // A pass back over what is already held, and the read that follows it: the
  // pass writes links and heals, so what the documents screen shows can move
  // under it.
  rescan: () => Promise<{ result: ActionResult; report: RescanReport | null }>;
  reread: () => Promise<FeatureResult<DocumentsData>>;
};
export type SurfaceSnapshot = { disclosure: { title: string; subtitle: string; detail: string }; overview: FeatureResult<OverviewData>; documents: FeatureResult<DocumentsData>; activity: FeatureResult<ActivityData>; conversation: FeatureResult<ConversationData>; review?: FeatureResult<ReviewData>; plans?: FeatureResult<PlansData>; trust: FeatureResult<TrustData> };

export type AccountingReportsView = AccountingView;
