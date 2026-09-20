import { useEffect, useRef, useState } from "react";
import { BridgeRefusal, BridgeTimeout, OPEN_REFUSALS } from "../bridge/contracts";
import { privateSource, sampleSource } from "../surface/sources";
import type { SessionCoordination } from "./useSessionState";
import type { useSessionReads } from "./useSessionReads";

const REMEMBERED_OPEN_DEADLINE_MS = 2_000;
const REMEMBER_CREDENTIAL_DEADLINE_MS = 2_000;
const REMEMBER_OUTCOME_UNKNOWN = "This vault is open, but protecting its vaultphrase stopped answering. The protection may still finish. Before restarting OrionViva, keep the vaultphrase available; if automatic opening does not work next time, enter it again here.";

function bounded<T>(work: Promise<T>, milliseconds: number): Promise<T | null> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(null), milliseconds);
    work.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (failure) => { clearTimeout(timer); reject(failure); },
    );
  });
}

type Coordination = Pick<SessionCoordination,
  | "dispatch"
  | "hostBridge"
  | "requestId"
  | "activityLimit"
  | "surfaceRevision"
  | "priorityGeneration"
  | "secondaryGeneration"
  | "destinationGeneration"
  | "retryingDestination"
  | "retryingPriority"
  | "sourceIdentity"
>;

export function useVaultLifecycle(context: Coordination, { readOpenedSource }: Pick<ReturnType<typeof useSessionReads>, "readOpenedSource">) {
  const {
    dispatch,
    hostBridge,
    requestId,
    activityLimit,
    surfaceRevision,
    priorityGeneration,
    secondaryGeneration,
    destinationGeneration,
    retryingDestination,
    retryingPriority,
    sourceIdentity,
  } = context;
  const opening = useRef(false);
  const [rememberedVaultDirectory, setRememberedVaultDirectory] = useState("");
  const [automaticOpenTimedOut, setAutomaticOpenTimedOut] = useState(false);
  const rememberedOpenStarted = useRef(false);
  const rememberWrites = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    if (!hostBridge?.openRememberedVault || rememberedOpenStarted.current) return;
    rememberedOpenStarted.current = true;
    const activeRequest = ++requestId.current;
    dispatch({ type: "opening", requestId: activeRequest });
    void bounded(hostBridge.openRememberedVault(), REMEMBERED_OPEN_DEADLINE_MS)
      .then((result) => {
        if (requestId.current !== activeRequest) return;
        if (result === null) {
          setAutomaticOpenTimedOut(true);
          dispatch({ type: "remembered-open-finished", requestId: activeRequest, said: "Automatic opening stopped answering. Enter the vault directory and vaultphrase below to open it manually; trying manually also replaces the protected default on this device." });
          return;
        }
        if (result.state === "absent") {
          dispatch({ type: "remembered-open-finished", requestId: activeRequest });
          return;
        }
        setRememberedVaultDirectory(result.directory);
        if (result.state === "locked") {
          dispatch({ type: "remembered-open-finished", requestId: activeRequest, said: "The remembered vault is still selected, but it could not be unlocked automatically. Enter its vaultphrase again." });
          return;
        }
        activityLimit.current = 50;
        ++surfaceRevision.current;
        void readOpenedSource(privateSource(hostBridge), activeRequest);
      })
      .catch(() => {
        if (requestId.current === activeRequest) dispatch({ type: "remembered-open-finished", requestId: activeRequest, said: "The remembered vault could not be unlocked automatically. Enter its vaultphrase again to replace the protected credential on this device." });
      });
  }, [hostBridge]);

  return {
    rememberedVaultDirectory,
    automaticOpenTimedOut,
    hostAvailable: Boolean(hostBridge),
    pickerAvailable: Boolean(hostBridge?.pickVaultDirectory),
    async openVault(vaultDirectory: string, passphrase: string, create: boolean) {
      if (!hostBridge || opening.current) return false;
      opening.current = true;
      const nextRequestId = ++requestId.current;
      activityLimit.current = 50;
      ++surfaceRevision.current;
      dispatch({ type: "opening", requestId: nextRequestId });
      try {
        await hostBridge.openVault(vaultDirectory, passphrase, create);
      } catch (refused) {
        // The sidecar's own sentence, and only from the codes whose message is
        // a reviewed sentence about a folder. It is what tells a mistyped path
        // apart from a wrong passphrase. Every other code carries machine text
        // out of an engine, which is never repeated here.
        const said = refused instanceof BridgeTimeout && refused.mayHaveWritten
          ? "Opening or creating this vault stopped answering and may already have changed which vault is active. Inspect the named vault folder, then reopen it before continuing. OrionViva did not retry the open."
          : refused instanceof BridgeRefusal && OPEN_REFUSALS.includes(refused.code) ? refused.message : "";
        if (requestId.current === nextRequestId) dispatch({ type: "open-failed", requestId: nextRequestId, said });
        opening.current = false;
        return false;
      }
      if (requestId.current !== nextRequestId) { opening.current = false; return false; }
      const source = privateSource(hostBridge);
      const reading = readOpenedSource(source, nextRequestId);
      opening.current = false;
      void reading;
      if (hostBridge.rememberVault) {
        const write = rememberWrites.current.then(() => hostBridge.rememberVault!(vaultDirectory, passphrase));
        rememberWrites.current = write.catch(() => undefined);
        void bounded(write, REMEMBER_CREDENTIAL_DEADLINE_MS)
          .then((remembered) => {
            if (remembered === null && requestId.current === nextRequestId) dispatch({ type: "notice", notice: { kind: "refused", text: REMEMBER_OUTCOME_UNKNOWN } });
          })
          .catch(() => {
            if (requestId.current === nextRequestId) dispatch({ type: "notice", notice: { kind: "refused", text: "This vault is open, but this device could not protect its vaultphrase. You will need to enter it again after restarting OrionViva." } });
          });
      }
      return true;
    },
    // The one affordance the sample vault is entered from. It names no
    // directory and no passphrase, because the request carries neither: where
    // the sample vault lives and what opens it are the engine's, so a person
    // pressing this cannot be pointed anywhere except at the sample.
    async openSampleVault() {
      if (!hostBridge || opening.current) return false;
      opening.current = true;
      const nextRequestId = ++requestId.current;
      activityLimit.current = 50;
      ++surfaceRevision.current;
      dispatch({ type: "opening", requestId: nextRequestId });
      let frame;
      try {
        frame = await hostBridge.openSampleVault();
      } catch (failure) {
        // The sidecar's own sentence is not repeated here: the codes a sample
        // open can fail with are about a directory this person never named, so
        // there is nothing in them for them to act on.
        const said = failure instanceof BridgeTimeout && failure.mayHaveWritten ? "Opening the sample vault stopped answering and may already have changed which vault is active. Close and reopen the sample vault before continuing. OrionViva did not retry the open." : "";
        if (requestId.current === nextRequestId) dispatch({ type: "open-failed", requestId: nextRequestId, said });
        opening.current = false;
        return false;
      }
      if (requestId.current !== nextRequestId) { opening.current = false; return false; }
      // No frame, no sample vault. A shell that went in anyway would be
      // showing somebody invented money with nothing saying it was invented.
      if (!frame) { dispatch({ type: "open-failed", requestId: nextRequestId, said: "" }); opening.current = false; return false; }
      const source = sampleSource(hostBridge, frame);
      const reading = readOpenedSource(source, nextRequestId);
      opening.current = false;
      void reading;
      return true;
    },
    async pickVaultDirectory() { return hostBridge?.pickVaultDirectory?.() ?? null; },
    resetDemo() {
      const nextRequestId = ++requestId.current;
      sourceIdentity.current = null;
      retryingDestination.current = null;
      ++destinationGeneration.current;
      retryingPriority.current = null;
      ++priorityGeneration.current;
      ++secondaryGeneration.current;
      activityLimit.current = 50;
      ++surfaceRevision.current;
      dispatch({ type: "reset", requestId: nextRequestId });
    },
  };
}
