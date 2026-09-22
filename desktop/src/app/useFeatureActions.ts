import { useEffect, useRef, useState } from "react";
import { BridgeTimeout } from "../bridge/contracts";
import type { ActionResult, ActivityActionResult, ActivityActions, ActivityCorrectionVerb, ConversationActions, DeclineReason, PlanDraftResult, PlanPayload, QuestionVerb, SettingsProposal, TransferVerb, TrustActions, VaultTransferActions } from "../surface/types";
import { hasAuthoritativeReviewConversationPair } from "./session";
import { dataBearing, authoritativeQuestionReread, reviewHoldsQuestion, conversationHoldsQuestion, interrupted } from "./sessionCoordination";
import type { SessionCoordination } from "./useSessionState";
import type { useSessionReads } from "./useSessionReads";

type Coordination = Pick<SessionCoordination,
  | "session"
  | "dispatch"
  | "requestId"
  | "questionGeneration"
  | "activityLimit"
  | "surfaceRevision"
  | "jobsGeneration"
  | "activityActions"
  | "source"
  | "sourceIdentity"
>;

export function useFeatureActions(context: Coordination, { refreshAfterAction }: Pick<ReturnType<typeof useSessionReads>, "refreshAfterAction">) {
  const {
    session,
    dispatch,
    requestId,
    questionGeneration,
    activityLimit,
    surfaceRevision,
    jobsGeneration,
    activityActions,
    source,
    sourceIdentity,
  } = context;
  const [settingAsideFindingId, setSettingAsideFindingId] = useState("");
  const [findingReceipt, setFindingReceipt] = useState<{ findingId: string; result: ActionResult } | null>(null);
  const transferring = useRef(false);
  const configuring = useRef(false);
  const asking = useRef(false);
  const maintaining = useRef(false);
  const correctingActivity = useRef(false);
  const settingAsideFinding = useRef(false);
  const planning = useRef(false);
  const transferActions = session.source?.transferActions ?? null;
  const settingsActions = session.source?.settingsActions ?? null;
  const conversationActions = session.source?.conversationActions ?? null;
  const trustActions = session.source?.trustActions ?? null;
  const overviewActions = session.source?.overviewActions ?? null;
  const planActions = session.source?.planActions ?? null;

  // What is in force, asked once per source. It is this machine's rather than
  // this vault's, so it is read whenever a source appears and never cleared by
  // one going away.
  useEffect(() => {
    if (!settingsActions) return undefined;
    let gone = false;
    void settingsActions.read()
      .then((settings) => { if (!gone) dispatch({ type: "settings-read", settings }); })
      .catch(() => undefined);
    return () => { gone = true; };
  }, [settingsActions]);

  // What the engine behind this source says about itself, asked once per
  // source. Neither answer changes while one sidecar lives, so asking again
  // per screen would be putting a settled question over and over; a source
  // that is replaced is a different engine and is asked again.
  useEffect(() => {
    if (!source) return undefined;
    let gone = false;
    const asked = requestId.current;
    void source.describe()
      .then((description) => { if (!gone) dispatch({ type: "described", requestId: asked, description }); })
      .catch(() => undefined);
    return () => { gone = true; };
  }, [source]);

  // One question verb at a time. The sidecar answers one request before reading
  // the next, so a second press while the first is in flight would queue behind
  // it and report against a queue that has already moved.
  async function runQuestionVerb(verb: QuestionVerb, questionId: string, run: (actions: ConversationActions) => Promise<ActionResult>) {
    const actions = conversationActions;
    const activeSource = source;
    if (!actions || !activeSource || !questionId.trim() || session.questionAction.state === "working") return;
    const nextRequestId = requestId.current;
    const nextGeneration = questionGeneration.current;
    dispatch({ type: "question-acting", requestId: nextRequestId, questionId, verb });
    let result: ActionResult;
    try { result = await run(actions); }
    catch (failure) {
      result = failure instanceof BridgeTimeout && failure.mayHaveWritten
        ? interrupted("The question response stopped answering and may already have been recorded. Inspect the question queue and its linked movement before trying again. OrionViva did not retry it.")
        : { state: "unanswered" };
    }
    if (requestId.current !== nextRequestId || questionGeneration.current !== nextGeneration) return;
    let authoritative = false;
    let resolved = false;
    if (result.state === "settled" && result.outcome.kind === "completed") {
      const snapshot = await refreshAfterAction(activeSource, nextRequestId, () => questionGeneration.current === nextGeneration);
      authoritative = authoritativeQuestionReread(snapshot);
      resolved = Boolean(authoritative && snapshot && !reviewHoldsQuestion(snapshot, questionId) && !conversationHoldsQuestion(snapshot, questionId));
    }
    if (requestId.current !== nextRequestId || questionGeneration.current !== nextGeneration) return;
    dispatch({ type: "question-acted", requestId: nextRequestId, questionId, verb, result, authoritative, resolved });
  }

  // One exact movement selection correction at a time. The old snapshot remains on screen
  // through both the write and the full read that follows it. An action reply
  // is a receipt, not financial data, so no row is patched from it; only the
  // completed source load may replace the picture.
  async function runActivityCorrection(verb: ActivityCorrectionVerb, movementIds: readonly string[], run: (actions: ActivityActions) => Promise<ActivityActionResult>) {
    const actions = activityActions;
    const activeSource = source;
    const movementId = movementIds[0] ?? "";
    if (!actions || !activeSource || !movementId.trim() || movementIds.some((id) => !id.trim()) || correctingActivity.current) return null;
    correctingActivity.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "activity-correcting", requestId: nextRequestId, movementId, movementIds, verb });
    try {
      const result = await run(actions);
      if (requestId.current === nextRequestId) dispatch({ type: "activity-outcome", requestId: nextRequestId, movementId, movementIds, verb, result });
      try {
        ++surfaceRevision.current;
        const snapshotWork = activeSource.loadCoherent
          ? activeSource.loadCoherent(activityLimit.current, movementId, undefined, true)
          : activeSource.load(activityLimit.current, movementId).then((snapshot) => ({ snapshot, revision: "" }));
        const activeJobs = activeSource.loadJobs ? ++jobsGeneration.current : 0;
        const jobsWork = activeSource.loadJobs
          ? Promise.resolve().then(() => activeSource.loadJobs!()).catch(() => null)
          : null;
        const { snapshot, revision } = await snapshotWork;
        if (requestId.current === nextRequestId) {
          if (!hasAuthoritativeReviewConversationPair(snapshot)) {
            dispatch({ type: "mutation-loaded", requestId: nextRequestId, snapshot, revision });
            dispatch({ type: "activity-refresh-failed", requestId: nextRequestId, movementId, movementIds, verb, result });
            return { result, refresh: "failed" as const };
          } else {
            dispatch({ type: "activity-refreshed", requestId: nextRequestId, movementId, movementIds, verb, result, snapshot, revision });
            if (jobsWork) {
              void jobsWork.then((jobsRead) => {
                if (requestId.current !== nextRequestId || sourceIdentity.current !== activeSource
                    || jobsGeneration.current !== activeJobs) return;
                dispatch(jobsRead?.state === "ready"
                  ? { type: "jobs-read", requestId: nextRequestId, jobs: jobsRead.data.jobs }
                  : { type: "jobs-unavailable", requestId: nextRequestId });
              }).catch(() => {
                if (requestId.current === nextRequestId && sourceIdentity.current === activeSource
                    && jobsGeneration.current === activeJobs) {
                  dispatch({ type: "jobs-unavailable", requestId: nextRequestId });
                }
              });
            }
            return { result, refresh: "refreshed" as const };
          }
        }
      } catch {
        if (requestId.current === nextRequestId) {
          dispatch({ type: "mutation-refresh-failed", requestId: nextRequestId });
          dispatch({ type: "activity-refresh-failed", requestId: nextRequestId, movementId, movementIds, verb, result });
        }
        return { result, refresh: "failed" as const };
      }
      return null;
    } catch (failure) {
      const result: ActivityActionResult = failure instanceof BridgeTimeout && failure.mayHaveWritten
        ? interrupted("The activity correction stopped answering and may already have changed the affected movement. Inspect that movement before trying again. OrionViva did not retry it.")
        : { state: "unanswered" };
      if (requestId.current === nextRequestId) {
        dispatch({ type: "activity-refresh-failed", requestId: nextRequestId, movementId, movementIds, verb, result });
      }
      return { result, refresh: "failed" as const };
    } finally {
      correctingActivity.current = false;
    }
  }

  // One whole-vault copy at a time, out or back. The sidecar answers one
  // request before it reads the next, so a second press while the first is in
  // flight would queue behind it and report against a file that has already
  // been written.
  async function runTransfer(verb: TransferVerb, run: (actions: VaultTransferActions) => Promise<ActionResult>) {
    if (!transferActions || transferring.current) return;
    transferring.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "transferring", requestId: nextRequestId, verb });
    try {
      const result = await run(transferActions);
      if (requestId.current === nextRequestId) dispatch({ type: "transferred", requestId: nextRequestId, verb, result });
    } catch (failure) {
      if (requestId.current === nextRequestId) {
        const message = verb === "export"
          ? "The export stopped answering. The destination archive may or may not have been written; inspect that archive before trying again. The vault itself was unchanged, and OrionViva did not retry the export."
          : "Restoring the vault copy stopped answering and may already have changed the vault. Inspect the chosen restored-vault folder before trying again. OrionViva did not retry it.";
        dispatch({ type: "transferred", requestId: nextRequestId, verb, result: failure instanceof BridgeTimeout ? interrupted(message) : { state: "unanswered" } });
      }
    } finally {
      transferring.current = false;
    }
  }

  async function runTrust(kind: "maintenance" | "diagnostic", run: (actions: TrustActions) => Promise<ActionResult>) {
    const activeSource = source;
    if (!trustActions || !activeSource || maintaining.current) return;
    maintaining.current = true;
    const nextRequestId = requestId.current;
    dispatch({ type: "trust-working", requestId: nextRequestId });
    try {
      const result = await run(trustActions);
      await refreshAfterAction(activeSource, nextRequestId);
      if (requestId.current === nextRequestId) {
        dispatch({ type: "trust-settled", requestId: nextRequestId, result });
      }
    } catch (failure) {
      if (requestId.current === nextRequestId) {
        const message = kind === "maintenance"
          ? "The maintenance run stopped answering and may already have changed its job or usage record. Inspect the maintenance job and usage record before trying again. OrionViva did not retry it."
          : "Writing the diagnostic stopped answering. The named diagnostic file may or may not have been written; inspect that file before trying again. The vault itself was unchanged, and OrionViva did not retry the diagnostic.";
        dispatch({ type: "trust-settled", requestId: nextRequestId, result: failure instanceof BridgeTimeout && failure.mayHaveWritten ? interrupted(message) : { state: "unanswered" } });
        if (failure instanceof BridgeTimeout && failure.mayHaveWritten) {
          if (kind === "maintenance") dispatch({ type: "jobs-unavailable", requestId: nextRequestId });
        }
      }
    } finally {
      maintaining.current = false;
    }
  }

  async function runPlanMutation(run: (actions: NonNullable<typeof planActions>) => Promise<ActionResult>): Promise<ActionResult> {
    const actions = planActions;
    const activeSource = source;
    if (!actions || !activeSource || planning.current) return { state: "unserved" };
    planning.current = true;
    const nextRequestId = requestId.current;
    try {
      const result = await run(actions);
      await refreshAfterAction(activeSource, nextRequestId);
      return result;
    } catch (failure) {
      return failure instanceof BridgeTimeout && failure.mayHaveWritten
        ? interrupted("The plan change stopped answering and may already have changed the vault. Inspect Plans and its linked evidence before trying again. OrionViva did not retry it.")
        : { state: "unanswered" };
    } finally {
      planning.current = false;
    }
  }

  return {
    transferAvailable: Boolean(transferActions),
    settingsAvailable: Boolean(settingsActions),
    askAvailable: Boolean(conversationActions),
    trustAvailable: Boolean(trustActions),
    activityCorrectionAvailable: Boolean(activityActions),
    findingActionsAvailable: Boolean(overviewActions),
    planActionsAvailable: Boolean(planActions),
    async draftPlan(payload: PlanPayload): Promise<PlanDraftResult> {
      if (!planActions || planning.current) return { state: "unserved" };
      planning.current = true;
      try { return await planActions.draft(payload); }
      catch (failure) { return failure instanceof BridgeTimeout && failure.mayHaveWritten
        ? interrupted("Drafting the plan stopped answering and may already have recorded a proposal. Inspect Plans before trying again. OrionViva did not retry it.")
        : { state: "unanswered" }; }
      finally { planning.current = false; }
    },
    proposePlan(payload: PlanPayload) {
      return runPlanMutation((actions) => actions.propose(payload));
    },
    confirmPlan(proposalId: string) {
      return runPlanMutation((actions) => actions.confirm(proposalId));
    },
    declinePlan(proposalId: string) {
      return runPlanMutation((actions) => actions.decline(proposalId));
    },
    async setAsideFinding(findingId: string) {
      const actions = overviewActions;
      const activeSource = source;
      if (!actions || !activeSource || !findingId.trim() || settingAsideFinding.current) return;
      settingAsideFinding.current = true;
      setSettingAsideFindingId(findingId);
      setFindingReceipt(null);
      const nextRequestId = requestId.current;
      try {
        const result = await actions.setAsideFinding(findingId);
        const snapshot = await refreshAfterAction(activeSource, nextRequestId);
        if (requestId.current !== nextRequestId) return;
        if (hasAuthoritativeReviewConversationPair(snapshot)) {
          dispatch({ type: "notice", notice: result.state === "settled"
            ? { kind: result.outcome.kind === "set_aside" ? "acknowledged" : "refused", text: result.outcome.message }
            : { kind: "refused", text: "The finding could not be set aside because the vault did not return a readable answer." } });
        }
      } catch (failure) {
        if (requestId.current === nextRequestId) {
          setFindingReceipt({ findingId, result: failure instanceof BridgeTimeout && failure.mayHaveWritten
            ? interrupted("Setting aside the finding stopped answering and may already have changed its review state. Inspect Review and this finding before trying again. OrionViva did not retry it.")
            : { state: "unanswered" } });
        }
      } finally {
        settingAsideFinding.current = false;
        setSettingAsideFindingId("");
      }
    },
    settingAsideFindingId,
    findingReceipt,
    async assignActivityCategory(movementId: string, categoryId: string) {
      if (!categoryId.trim()) return;
      await runActivityCorrection("category", [movementId], (actions) => actions.assignCategory(movementId, categoryId));
    },
    async assignActivityClassification(movementIds: readonly string[], categoryId: string, subcategoryId: string) {
      if (!categoryId.trim() || !subcategoryId.trim()) return;
      const selection = [...movementIds];
      return await runActivityCorrection("classification", selection, (actions) => actions.assignClassification(selection, categoryId, subcategoryId));
    },
    async assignActivityMeaning(movementId: string, meaning: string, counterparty: string) {
      if (!meaning.trim()) return;
      await runActivityCorrection("meaning", [movementId], (actions) => actions.assignMeaning(movementId, meaning, counterparty));
    },
    async replaceActivityTags(movementId: string, tagIds: readonly string[]) {
      await runActivityCorrection("tags", [movementId], (actions) => actions.replaceTags(movementId, tagIds));
    },
    async addActivityTags(movementIds: readonly string[], tagIds: readonly string[]) {
      if (!tagIds.length) return;
      const selection = [...movementIds];
      return await runActivityCorrection("add_tags", selection, (actions) => actions.addTags(selection, tagIds));
    },
    async removeActivityTags(movementIds: readonly string[], tagIds: readonly string[]) {
      if (!tagIds.length) return;
      const selection = [...movementIds];
      return await runActivityCorrection("remove_tags", selection, (actions) => actions.removeTags(selection, tagIds));
    },
    async confirmActivityTransfer(movementId: string, counterpartId: string) {
      if (!counterpartId.trim()) return;
      await runActivityCorrection("confirm_transfer", [movementId], (actions) => actions.confirmTransfer(movementId, counterpartId));
    },
    async rejectActivityTransfer(movementId: string) {
      await runActivityCorrection("reject_transfer", [movementId], (actions) => actions.rejectTransfer(movementId));
    },
    async unlinkActivityTransfer(movementId: string, counterpartId: string) {
      if (!counterpartId.trim()) return;
      await runActivityCorrection("unlink_transfer", [movementId], (actions) => actions.unlinkTransfer(movementId, counterpartId));
    },
    // One at a time. `spend` is the person's own word and is never inferred:
    // the agent reaches a model, so a run nobody said to spend on plans and
    // stops at the line where money starts.
    async runMaintenance(spend: boolean) {
      if (spend && (session.jobStatus === "unavailable" || session.jobs.some((job) => job.operation === "viva.maintenance.run" && (job.state === "queued" || job.state === "running")))) return;
      await runTrust("maintenance", (actions) => actions.run(spend));
    },
    async writeDiagnostic(file: string) {
      if (!file.trim()) return;
      await runTrust("diagnostic", (actions) => actions.diagnose(file.trim()));
    },
    // One question at a time. `mirrored` says the drawer showing the answer is
    // open, which is a fact about this screen rather than a preference: it is
    // what decides whether anything may be spoken.
    async askViva(question: string, mirrored: boolean, planRequest = false, contextMode: import("../surface/types").AskContextMode = "new_question") {
      const activeSource = source;
      if (!conversationActions || !activeSource || !question.trim() || asking.current) return;
      asking.current = true;
      const nextRequestId = requestId.current;
      dispatch({ type: "asking", requestId: nextRequestId, question: question.trim() });
      try {
        const { result, turn } = await conversationActions.ask(question.trim(), mirrored, planRequest, contextMode);
        const snapshot = await refreshAfterAction(activeSource, nextRequestId);
        if (requestId.current === nextRequestId) {
          dispatch({ type: "asked", requestId: nextRequestId, question: question.trim(), result, turn, authoritative: hasAuthoritativeReviewConversationPair(snapshot) });
        }
      } catch (failure) {
        if (requestId.current === nextRequestId) {
          const message = planRequest
            ? "Asking Viva to draft the plan stopped answering and may already have recorded a proposal or conversation turn. Inspect Plans and the conversation before trying again. OrionViva did not retry it."
            : "Asking Viva stopped answering and may already have recorded a conversation turn. Inspect the conversation before trying again. OrionViva did not retry it.";
          dispatch({ type: "asked", requestId: nextRequestId, question: question.trim(), result: failure instanceof BridgeTimeout && failure.mayHaveWritten ? interrupted(message) : { state: "unanswered" }, turn: null, authoritative: false });
        }
      } finally {
        asking.current = false;
      }
    },
    // Proposing changes nothing. What comes back is either the proposal a
    // person is shown, or the channel's own answer about why there is none.
    async proposeSettings(kind: "presentation" | "model", fields: Record<string, string>) {
      if (!settingsActions || configuring.current) return;
      const activeSettings = settingsActions;
      const activeSource = sourceIdentity.current;
      configuring.current = true;
      dispatch({ type: "settings-working" });
      try {
        const answered = await activeSettings.propose(kind, fields);
        if (sourceIdentity.current !== activeSource) return;
        if ("digest" in answered) dispatch({ type: "settings-proposed", proposal: answered as SettingsProposal });
        else {
          const reread = await activeSettings.read();
          if (sourceIdentity.current !== activeSource) return;
          dispatch({ type: "settings-settled", result: answered, settings: dataBearing(reread) ? reread : session.settings });
        }
      } catch (failure) {
        if (sourceIdentity.current !== activeSource) return;
        dispatch({ type: "settings-settled", result: failure instanceof BridgeTimeout && failure.mayHaveWritten
          ? interrupted("The proposal outcome could not be established. Current settings are unchanged unless a proposal was confirmed; reread or reopen settings before preparing a new proposal. OrionViva did not retry it.")
          : { state: "unanswered" }, settings: session.settings });
      } finally {
        configuring.current = false;
      }
    },
    // The yes names the digest of the proposal that was shown. The key travels
    // in this one call and is held nowhere on this side afterwards.
    async confirmSettings(kind: "presentation" | "model", fields: Record<string, string>, digest: string, key: string) {
      if (!settingsActions || configuring.current) return;
      const activeSettings = settingsActions;
      const activeSource = sourceIdentity.current;
      configuring.current = true;
      dispatch({ type: "settings-working" });
      try {
        const result = await activeSettings.confirm(kind, fields, digest, key);
        if (sourceIdentity.current !== activeSource) return;
        const reread = await activeSettings.read();
        if (sourceIdentity.current !== activeSource) return;
        dispatch({ type: "settings-settled", result, settings: dataBearing(reread) ? reread : session.settings });
      } catch (failure) {
        if (sourceIdentity.current !== activeSource) return;
        dispatch({ type: "settings-settled", result: failure instanceof BridgeTimeout
          ? interrupted("Saving the settings stopped answering and may already have changed the vault. Inspect the settings currently in force before trying again. OrionViva did not retry it.")
          : { state: "unanswered" }, settings: session.settings });
      } finally {
        configuring.current = false;
      }
    },
    async exportVault(archive: string) {
      if (!archive.trim()) return;
      await runTransfer("export", (actions) => actions.export(archive.trim()));
    },
    async restoreVault(archive: string, directory: string, passphrase: string) {
      if (!archive.trim() || !directory.trim() || !passphrase) return;
      await runTransfer("restore", (actions) => actions.restore(archive.trim(), directory.trim(), passphrase));
    },
    async answerQuestion(questionId: string, said: string) {
      await runQuestionVerb("answer", questionId, (actions) => actions.answer(questionId, said));
    },
    async confirmProposal(questionId: string, proposalId: string, said: string, asked: string) {
      await runQuestionVerb("confirm", questionId, (actions) => actions.confirm?.(proposalId, said, asked) ?? Promise.resolve({ state: "unserved" }));
    },
    async declineQuestion(questionId: string, reason: DeclineReason) {
      await runQuestionVerb("decline", questionId, (actions) => actions.decline(questionId, reason));
    },
  };
}
