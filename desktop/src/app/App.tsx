import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import bulkCopy from "../features/documents/bulk-upload-v1.json";
import { createPortal } from "react-dom";
import { ArrowUpRight, Check, ChevronRight, FilePlus2, FolderOpen, Info, Menu, Sparkles, X } from "lucide-react";
import { FeatureBoundary } from "../components/FeatureBoundary";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { SourceDisclosure } from "../components/SourceDisclosure";
import { StatusNotice } from "../components/StatusNotice";
import { Accounts } from "../features/accounts/Accounts";
import { AccountLedger } from "../features/accounts/AccountLedger";
import { Activity } from "../features/activity/Activity";
import { ConversationDrawer } from "../features/conversation/ConversationDrawer";
import { Documents } from "../features/documents/Documents";
import { Overview } from "../features/overview/Overview";
import { Plans } from "../features/plans/Plans";
import { Review } from "../features/review/Review";
import { Trust } from "../features/trust/Trust";
import { resolveEvidenceTarget } from "../surface/evidence";
import type { ActionResult, ConversationData, ConversationGoalDraft, DeclineReason, Destination, EvidenceLink, FeatureResult, NoticeKind, PlanDraftResult, PlanPayload, QuestionActionState, ReviewTransactionTarget } from "../surface/types";
import { destinations, standingCopy, standingOf } from "./navigation";
import type { LazyDestination } from "./session";
import { useResponsiveNavigation } from "./useResponsiveNavigation";
import { useEvidenceDialog } from "./useEvidenceDialog";
import { useProofPreference } from "./useProofPreference";
import { useConversationContext } from "./useConversationContext";
import { VaultRecovery } from "./VaultRecovery";
import { useDocumentsPage } from "./useDocumentsPage";
import { useSurfaceSession } from "./useSurfaceSession";
import type { CaptureGesture } from "./useSurfaceSession";

const pageCopy: Record<Destination, { title: string; intro: string }> = {
  overview: { title: "Your financial picture", intro: "Your balances, their sources, and what needs your attention." },
  accounts: { title: "Accounts", intro: "Balances and transactions for each account, with dates and sources." },
  activity: { title: "Transactions", intro: "Search what moved, review its context, and make available corrections." },
  documents: { title: "Statements & documents", intro: "Add statements and check what the vault has finished reading." },
  plans: { title: "Plans", intro: "Targets, local reservations, and future contributions remain separate." },
  review: { title: "Review", intro: "Check the records that need your answer." },
  trust: { title: "Trust & settings", intro: "Privacy, verification preferences, and tools for this local vault." },
};
// Notice kinds select their marks. Success uses a tick; refusal uses only its border.
const noticeIcons: Record<NoticeKind, ReactNode> = { acknowledged: <Check />, refused: null };
type Overlay = null | { kind: "navigation" } | { kind: "conversation"; requestId: number; mode: "ask" | "review" } | { kind: "evidence"; selection: { figureId: string; requestId: number } } | { kind: "account_transaction"; requestId: number; accountId: string };
type AccountOrigin = { kind: "overview" | "accounts"; accountId: string };
type ConversationReturn = { kind: "review"; itemId: string } | { kind: "ledger"; accountId: string; movementId: string; reviewItemId: string };
type PendingDocumentFocus =
  | { target: "document"; documentId: string; requestId: number; nonce: number }
  | { target: "capture"; requestId: number; nonce: number };
type PendingReviewFocus = { requestId: number; questionId: string; nonce: number };

// Whether the question a verb was used on is still being asked. Only the
// read's own states carry a queue; anything else cannot say either way, and
// reports false so that focus is left where it is.
function conversationHoldsQuestion(conversation: FeatureResult<ConversationData>, questionId: string): boolean {
  if (conversation.state !== "ready" && conversation.state !== "partial" && conversation.state !== "needs_input") return false;
  return conversation.data.questions.queue.some((question) => question.id === questionId);
}

export function restoreAccountIndexFocus(accountId: string, fallback: HTMLElement | null) {
  const account = [...document.querySelectorAll<HTMLElement>("[data-account-id]")].find((candidate) => candidate.dataset.accountId === accountId);
  (account ?? document.getElementById("accounts-index-heading") ?? fallback)?.focus();
}

export function ConversationDialogShell({ resetKey, drawerRef, closeRef, onDismiss, children, mode = "ask" }: { resetKey: string; drawerRef: RefObject<HTMLElement | null>; closeRef: RefObject<HTMLButtonElement | null>; onDismiss: () => void; children: ReactNode; mode?: "ask" | "review" }) {
  const title = mode === "review" ? "Review question" : "Ask Viva";
  const description = mode === "review" ? "Answer an existing question from the Review queue." : "Start or continue a conversation about the records in this vault.";
  return <><div className="conversation-backdrop" aria-hidden="true" onClick={onDismiss} /><aside ref={drawerRef} id="viva-conversation-drawer" className="conversation-drawer" role="dialog" aria-modal="true" aria-labelledby="viva-conversation-title" aria-describedby="viva-conversation-description" tabIndex={-1}><header className="conversation-topline"><div><h2 id="viva-conversation-title">{title}</h2><p id="viva-conversation-description">{description}</p></div><button ref={closeRef} className="conversation-close" type="button" onClick={onDismiss} aria-label={`Close ${title}`}><X size={18} /></button></header><FeatureBoundary resetKey={resetKey}>{children}</FeatureBoundary></aside></>;
}

export function App() {
  const control = useSurfaceSession((gesture) => documentDropped(gesture));
  const proofPreference = useProofPreference();
  const { session } = control;
  const documentPages = useDocumentsPage(session.snapshot.documents, session.source?.documentsPageReader, session.source, session.selectedDocument, `${session.requestId}:${session.destination}`);
  const surface = { ...session.snapshot, documents: documentPages.result };
  const plansResult = surface.plans ?? { state: "absent" as const, reason: "not_read" };
  const reviewResult = surface.review ?? { state: "unavailable" as const, reason: "not_served" };
  const [vaultDirectory, setVaultDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const passphraseRef = useRef<HTMLInputElement>(null);
  const [makeVault, setMakeVault] = useState(false);
  const [vaultSetup, setVaultSetup] = useState(false);
  const [vaultRecovery, setVaultRecovery] = useState(false);
  const setupHeadingRef = useRef<HTMLHeadingElement>(null);
  const setupChoiceRef = useRef<HTMLButtonElement>(null);
  const restoreChoiceRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (control.rememberedVaultDirectory || control.automaticOpenTimedOut) setVaultSetup(true);
  }, [control.rememberedVaultDirectory, control.automaticOpenTimedOut]);
  useEffect(() => {
    if (vaultSetup && !session.source) {
      if (control.automaticOpenTimedOut || control.rememberedVaultDirectory) passphraseRef.current?.focus();
      else setupHeadingRef.current?.focus();
    }
  }, [vaultSetup, session.source, control.automaticOpenTimedOut, control.rememberedVaultDirectory]);
  useEffect(() => {
    if (!vaultDirectory && control.rememberedVaultDirectory) {
      setVaultDirectory(control.rememberedVaultDirectory);
    }
  }, [control.rememberedVaultDirectory, vaultDirectory]);
  useEffect(() => {
    if (control.automaticOpenTimedOut) passphraseRef.current?.focus();
  }, [control.automaticOpenTimedOut]);
  const [pickingVaultDirectory, setPickingVaultDirectory] = useState(false);
  const [conversationPlanDraft, setConversationPlanDraft] = useState<PlanDraftResult | null>(null);
  const [planActionReceipt, setPlanActionReceipt] = useState<ActionResult | null>(null);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const overlayRef = useRef(overlay);
  overlayRef.current = overlay;
  const [readySourcePageNonce, setReadySourcePageNonce] = useState<number | null>(null);
  const [sourcePageRequest, setSourcePageRequest] = useState<{ documentId: string; page: number; nonce: number; requestId: typeof session.requestId; source: typeof session.source } | undefined>();
  const [pendingDocumentFocus, setPendingDocumentFocus] = useState<PendingDocumentFocus | null>(null);
  const [pendingReviewFocus, setPendingReviewFocus] = useState<PendingReviewFocus | null>(null);
  const [selectedMovement, setSelectedMovement] = useState("");
  const [accountingContext, setAccountingContext] = useState<{movementIds: readonly string[]; label: string} | null>(null);
  const conversationContext = useConversationContext(session.requestId, session.askAction, session.source && session.phase !== "opening" ? surface.conversation : null, Boolean(accountingContext) || session.phase === "opening" || control.closingVault);
  useEffect(() => { setAccountingContext(null); }, [session.requestId]);
  const [openedAccount, setOpenedAccount] = useState("");
  const [accountOrigin, setAccountOrigin] = useState<AccountOrigin | null>(null);
  const [reviewTransaction, setReviewTransaction] = useState<{ target: ReviewTransactionTarget; itemId: string } | null>(null);
  const pendingFocusNonce = useRef(0);
  const explicitVaultOpen = useRef(false);
  const anyVaultOpen = useRef(false);
  const activePendingFocusNonce = useRef<number | null>(null);
  const reviewFocusNonce = useRef(0);
  const activeReviewFocusNonce = useRef<number | null>(null);
  const settledReviewAction = useRef<QuestionActionState | null>(null);
  const conversationReturn = useRef<ConversationReturn | null>(null);
  const mobileNav = overlay?.kind === "navigation";
  const isNarrow = useResponsiveNavigation();
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const navigationDrawerRef = useRef<HTMLElement>(null);
  const navigationCloseRef = useRef<HTMLButtonElement>(null);
  const pageTitleRef = useRef<HTMLHeadingElement>(null);
  const priorityRetryRef = useRef<HTMLButtonElement>(null);
  // Focus ownership is recorded while Retry exists and ends when focus or context moves.
  const destinationRetryFocus = useRef<{ source: typeof session.source; requestId: number; destination: Destination; button: HTMLButtonElement; navigationDestination?: Destination } | null>(null);
  useLayoutEffect(() => {
    const held = destinationRetryFocus.current;
    if (!held) return;
    if (held.source !== session.source || held.requestId !== session.requestId || overlay) {
      destinationRetryFocus.current = null;
      return;
    }
    if (held.destination !== session.destination) {
      destinationRetryFocus.current = null;
      if (held.navigationDestination === session.destination && !held.button.isConnected) pageTitleRef.current?.focus();
      return;
    }
    if (session.destinationReads[held.destination as LazyDestination] === "ready" && !held.button.isConnected) {
      destinationRetryFocus.current = null;
      pageTitleRef.current?.focus();
    }
  }, [session.source, session.requestId, session.destination, session.destinationReads, overlay]);
  const destinationRef = useRef(session.destination);
  destinationRef.current = session.destination;
  const evidenceDrawerRef = useRef<HTMLElement>(null);
  const evidenceCloseRef = useRef<HTMLButtonElement>(null);
  const conversationDrawerRef = useRef<HTMLElement>(null);
  const conversationCloseRef = useRef<HTMLButtonElement>(null);
  // Authentication is exclusive. Once it succeeds, the shell remains usable
  // while each destination receives its own read state.
  const openingVault = session.phase === "opening";
  const priorityLoading = session.phase === "reading";
  const priorityHasPreviousData = surface.overview.state === "ready" || surface.overview.state === "partial" || surface.overview.state === "needs_input";
  // The capture control targets the newest capture reported by the sidecar registry.
  const capturedJob = [...session.jobs].reverse().find((job) => (job.operation === "viva.documents.upload" || job.operation === "viva.documents.upload_many" || job.operation === "viva.documents.recover")) ?? null;
  const maintenanceJob = [...session.jobs].reverse().find((job) => job.operation === "viva.maintenance.run") ?? null;
  const evidenceSelection = overlay?.kind === "evidence" && overlay.selection.requestId === session.requestId ? overlay.selection : null;
  const conversationSelection = overlay?.kind === "conversation" && overlay.requestId === session.requestId ? overlay : null;
  const conversationOpen = Boolean(conversationSelection);
  useEffect(() => { setSourcePageRequest(undefined); }, [session.requestId, session.source]);
  useEffect(() => { if (session.destination !== "documents") setSourcePageRequest(undefined); }, [session.destination]);
  useEffect(() => {
    setSourcePageRequest((request) => request && request.documentId !== session.selectedDocument ? undefined : request);
  }, [session.selectedDocument]);
  useEffect(() => {
    if (documentPages.detail.state === "missing" || documentPages.detail.state === "unavailable" || documentPages.detail.state === "conflicted_identity") {
      setSourcePageRequest((request) => request?.documentId === documentPages.detail.id ? undefined : request);
    }
  }, [documentPages.detail]);
  useEffect(() => {
    setReadySourcePageNonce(session.destination === "documents" && session.destinationReads.documents === "ready" && documentPages.detail.state === "ready" && documentPages.detail.document?.id === sourcePageRequest?.documentId ? sourcePageRequest?.nonce ?? null : null);
  }, [session.destination, session.destinationReads.documents, documentPages.detail, sourcePageRequest]);
  useEffect(() => { conversationContext.clearContinuationRecovery(); }, [session.requestId, session.source, conversationOpen]);
  const accountTransactionOpen = overlay?.kind === "account_transaction" && overlay.requestId === session.requestId && overlay.accountId === openedAccount;
  const evidenceDialog = useEvidenceDialog({ open: Boolean(evidenceSelection), drawerRef: evidenceDrawerRef, initialFocusRef: evidenceCloseRef, pageTitleRef, onDismiss: () => setOverlay(null) });
  const conversationDialog = useEvidenceDialog({ open: conversationOpen, drawerRef: conversationDrawerRef, initialFocusRef: conversationCloseRef, pageTitleRef, onDismiss: dismissConversation, restoreTarget: conversationReturnTarget });

  useEffect(() => () => documentPages.cancelPending(), [session.requestId, session.destination, overlay?.kind]);
  useEffect(() => { if (overlay?.kind === "evidence" && !evidenceSelection) setOverlay(null); }, [evidenceSelection, overlay]);
  useEffect(() => { if (overlay?.kind === "conversation" && !conversationSelection) setOverlay(null); }, [conversationSelection, overlay]);
  useEffect(() => { if (overlay?.kind === "account_transaction" && !accountTransactionOpen) setOverlay(null); }, [accountTransactionOpen, overlay]);
  useEffect(() => { setConversationPlanDraft(null); setPlanActionReceipt(null); }, [session.requestId]);
  useEffect(() => { setSelectedMovement(""); setOpenedAccount(""); setAccountOrigin(null); setReviewTransaction(null); conversationReturn.current = null; }, [session.requestId]);

  useEffect(() => {
    if (!pendingDocumentFocus) return undefined;
    if (session.requestId !== pendingDocumentFocus.requestId || session.destination !== "documents" || (pendingDocumentFocus.target === "document" && session.selectedDocument !== pendingDocumentFocus.documentId)) {
      activePendingFocusNonce.current = null;
      setPendingDocumentFocus(null);
      return undefined;
    }
    activePendingFocusNonce.current = pendingDocumentFocus.nonce;
    const targetId = pendingDocumentFocus.target === "capture" ? "document-capture-status" : "selected-document-title";
    const frame = requestAnimationFrame(() => {
      if (activePendingFocusNonce.current !== pendingDocumentFocus.nonce) return;
      activePendingFocusNonce.current = null;
      document.getElementById(targetId)?.focus();
      setPendingDocumentFocus(null);
    });
    return () => {
      cancelAnimationFrame(frame);
      if (activePendingFocusNonce.current === pendingDocumentFocus.nonce) activePendingFocusNonce.current = null;
    };
  }, [pendingDocumentFocus, session.destination, session.requestId, session.selectedDocument]);

  useEffect(() => {
    if (!pendingReviewFocus) return undefined;
    if (session.requestId !== pendingReviewFocus.requestId || !conversationOpen || session.selectedQueue !== pendingReviewFocus.questionId) {
      activeReviewFocusNonce.current = null;
      setPendingReviewFocus(null);
      return undefined;
    }
    activeReviewFocusNonce.current = pendingReviewFocus.nonce;
    const frame = requestAnimationFrame(() => {
      if (activeReviewFocusNonce.current !== pendingReviewFocus.nonce) return;
      activeReviewFocusNonce.current = null;
      document.getElementById("selected-question-title")?.focus();
      setPendingReviewFocus(null);
    });
    return () => {
      cancelAnimationFrame(frame);
      if (activeReviewFocusNonce.current === pendingReviewFocus.nonce) activeReviewFocusNonce.current = null;
    };
  }, [conversationOpen, pendingReviewFocus, session.requestId, session.selectedQueue]);

  // After a successful write, move focus on the next rendered frame to the next question,
  // empty state, or failed-refresh outcome. Refused writes retain control focus.
  useEffect(() => {
    const acted = session.questionAction;
    if (acted.state !== "settled" || settledReviewAction.current === acted) return undefined;
    settledReviewAction.current = acted;
    if (!conversationOpen || conversationHoldsQuestion(surface.conversation, acted.questionId)) return undefined;
    const frame = requestAnimationFrame(() => {
      (document.getElementById("selected-question-title") ?? document.getElementById("review-empty-title") ?? document.getElementById("conversation-action-outcome"))?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [conversationOpen, session.questionAction, surface.conversation]);

  useEffect(() => {
    if (!isNarrow && mobileNav) {
      setOverlay(null);
      requestAnimationFrame(() => {
        const currentDestination = navigationDrawerRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
        (currentDestination ?? pageTitleRef.current)?.focus();
      });
    }
  }, [isNarrow, mobileNav]);

  useEffect(() => {
    if (!isNarrow || !mobileNav) return undefined;
    const priorRootOverflow = document.documentElement.style.overflow;
    const priorBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    navigationCloseRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOverlay(null);
        requestAnimationFrame(() => navigationTriggerRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(navigationDrawerRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href], select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []).filter((element) => !element.hasAttribute("hidden") && !element.closest("[hidden], [inert], [aria-hidden=\"true\"]"));
      if (focusable.length === 0) {
        event.preventDefault();
        navigationDrawerRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!focusable.includes(document.activeElement as HTMLElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.documentElement.style.overflow = priorRootOverflow;
      document.body.style.overflow = priorBodyOverflow;
    };
  }, [isNarrow, mobileNav]);

  function closeNavigation(restoreFocus = true) { setOverlay(null); if (restoreFocus) requestAnimationFrame(() => navigationTriggerRef.current?.focus()); }
  function openNavigation() { if (openingVault || !isNarrow) return; setOverlay({ kind: "navigation" }); }
  function navigate(destination: Destination) { if (openingVault) return; const retryFocus = destinationRetryFocus.current; if (retryFocus && document.activeElement === retryFocus.button) retryFocus.navigationDestination = destination; const focusHeading = isNarrow && mobileNav; if (destination === "accounts") { setOpenedAccount(""); setAccountOrigin(null); setReviewTransaction(null); } control.navigate(destination); if (mobileNav) setOverlay(null); if (focusHeading) requestAnimationFrame(() => pageTitleRef.current?.focus()); }
  async function retryPriorityRead() {
    const retryDestination = session.destination;
    const moveFocusOnSuccess = document.activeElement === priorityRetryRef.current;
    const outcome = await control.retryPriorityRead();
    if (outcome === "succeeded" && moveFocusOnSuccess && destinationRef.current === retryDestination) requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  function openDocuments() {
    if (openingVault) return;
    setPendingDocumentFocus({ target: "capture", requestId: session.requestId, nonce: ++pendingFocusNonce.current });
    control.navigate("documents");
  }
  // Leaving a vault is one action, and it takes everything with it: the
  // overlays go, the session is rebuilt from nothing, and no row from the
  // vault that was open survives into the one that is not.
  async function leaveVault() { if (openingVault) return; if (control.hostCloseAvailable && !(await control.closeVault())) return; evidenceDialog.cancelPendingRestore(); conversationDialog.cancelPendingRestore(); setConversationPlanDraft(null); setPlanActionReceipt(null); control.resetDemo(); setVaultSetup(false); setPassphrase(""); setOverlay(null); requestAnimationFrame(() => pageTitleRef.current?.focus()); }
  async function openSampleVault() {
    if (anyVaultOpen.current || openingVault || !control.hostAvailable) return;
    anyVaultOpen.current = true;
    evidenceDialog.cancelPendingRestore();
    conversationDialog.cancelPendingRestore();
    setConversationPlanDraft(null);
    setPlanActionReceipt(null);
    setOverlay(null);
    try {
      const opened = await control.openSampleVault();
      if (opened) requestAnimationFrame(() => pageTitleRef.current?.focus());
    } finally {
      anyVaultOpen.current = false;
    }
  }
  function openAskViva() { if (openingVault) return; setAccountingContext(null); conversationReturn.current = null; const selection: Overlay = { kind: "conversation", requestId: session.requestId, mode: "ask" }; setOverlay(selection); void control.ensureDestination("review", () => overlayRef.current === selection); }
  function openExplainMovement(movementId: string) {
    if (openingVault || !control.askAvailable) return;
    const activity = surface.activity;
    if (activity.state !== "ready" && activity.state !== "partial" && activity.state !== "needs_input") return;
    const movement = activity.data.movements.find((item) => item.id === movementId);
    if (!movement) return;
    openAskViva();
    setSelectedMovement(movementId);
    control.selectMovement(movementId);
    setAccountingContext({ movementIds: [movementId], label: [movement.date, movement.description, movement.display].filter(Boolean).join(" · ") });
  }
  function openReviewQuestion(questionId: string, itemId = "", movementId = "") {
    if (!(reviewResult.state === "ready" && surface.conversation.state === "ready")) void control.ensureDestination("review");
    conversationReturn.current = movementId ? { kind: "ledger", accountId: openedAccount, movementId, reviewItemId: reviewTransaction?.itemId ?? itemId }
      : itemId ? { kind: "review", itemId } : null;
    control.selectQueue(questionId);
    setOverlay({ kind: "conversation", requestId: session.requestId, mode: "review" });
    setPendingReviewFocus({ requestId: session.requestId, questionId, nonce: ++reviewFocusNonce.current });
  }
  function openReviewTransaction(target: ReviewTransactionTarget, itemId: string) {
    control.selectAccount(target.accountId);
    setAccountOrigin(null);
    setReviewTransaction({ target, itemId });
    setOpenedAccount(target.accountId);
    control.navigate("accounts");
    requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  function returnToReview() {
    const itemId = reviewTransaction?.itemId ?? "";
    setOpenedAccount("");
    setReviewTransaction(null);
    control.navigate("review");
    requestAnimationFrame(() => {
      const item = itemId ? document.getElementById(`review-item-${itemId}`) : null;
      (item ?? pageTitleRef.current)?.focus();
    });
  }
  function reviewMovement(movementId: string) {
    setOverlay(null);
    setSelectedMovement(movementId);
    control.selectMovement(movementId);
    control.navigate("activity");
  }
  async function inspectOverviewDocument(documentId: string) {
    control.navigate("documents");
    if (!await control.ensureDestination("documents")) return;
    control.selectDocument(documentId);
    setPendingDocumentFocus({ target: "document", documentId, requestId: session.requestId, nonce: ++pendingFocusNonce.current });
  }
  async function inspectOverviewAccount(accountId: string) {
    await Promise.all([control.ensureDestination("review"), control.ensureDestination("activity")]);
    control.selectAccount(accountId);
    setAccountOrigin({ kind: "overview", accountId });
    setOpenedAccount(accountId);
    control.navigate("accounts");
    requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  function declineQuestion(questionId: string, reason: DeclineReason) { void control.declineQuestion(questionId, reason); }
  function answerQuestion(questionId: string, said: string) { void control.answerQuestion(questionId, said); }
  function confirmProposal(questionId: string, proposalId: string, said: string, asked: string) { void control.confirmProposal(questionId, proposalId, said, asked); }
  function conversationReturnTarget(): HTMLElement | null {
    const target = conversationReturn.current;
    if (target?.kind === "ledger") {
      const row = document.getElementById(`ledger-row-${target.movementId}`);
      if (row) return row;
      if (target.reviewItemId) return document.getElementById(`review-item-${target.reviewItemId}`);
    }
    if (target?.kind === "review") return document.getElementById(`review-item-${target.itemId}`) ?? pageTitleRef.current;
    return null;
  }
  function dismissConversation() {
    const target = conversationReturn.current;
    if (target?.kind === "ledger" && !document.getElementById(`ledger-row-${target.movementId}`)) {
      setOpenedAccount("");
      setAccountOrigin(null);
      setReviewTransaction(null);
      control.navigate("review");
    }
    setOverlay(null);
  }
  function setAccountTransactionOverlay(open: boolean) {
    setOverlay((current) => open
      ? { kind: "account_transaction", requestId: session.requestId, accountId: openedAccount }
      : current?.kind === "account_transaction" ? null : current);
  }
  function returnFromAccount() {
    const origin = accountOrigin;
    const returningTo = openedAccount;
    setOpenedAccount("");
    setAccountOrigin(null);
    if (origin?.kind === "overview") {
      control.navigate("overview");
      requestAnimationFrame(() => ([...document.querySelectorAll<HTMLElement>("[data-overview-account-id]")].find((candidate) => candidate.dataset.overviewAccountId === origin.accountId) ?? pageTitleRef.current)?.focus());
      return;
    }
    requestAnimationFrame(() => restoreAccountIndexFocus(returningTo, pageTitleRef.current));
  }
  // File drops use destination navigation, dismiss open drawers and focus the heading.
  function refuseSeveral() { control.setNotice({ kind: "refused", text: "This takes one document at a time. Nothing was added." }); }
  function documentDropped(gesture: CaptureGesture) {
    if (gesture === "none") return;
    evidenceDialog.cancelPendingRestore();
    conversationDialog.cancelPendingRestore();
    setOverlay(null);
    if (gesture === "several") { refuseSeveral(); return; }
    if (gesture === "over_limit") { control.setNotice({ kind: "refused", text: bulkCopy.overLimit }); return; }
    navigate("documents");
    requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  async function chooseDocuments() {
    const gesture = await control.chooseDocuments();
    if (gesture === "unopened") control.setNotice({ kind: "refused", text: "The file picker could not be opened, so nothing was chosen and nothing was added to this vault." });
    if (gesture === "several") refuseSeveral();
  }
  async function chooseBulkDocuments() {
    const gesture = await control.chooseBulkDocuments();
    if (gesture === "unopened") control.setNotice({ kind: "refused", text: bulkCopy.pickerFailed });
    if (gesture === "over_limit") control.setNotice({ kind: "refused", text: bulkCopy.overLimit });
  }
  function openFigure(figureId: string) { setOverlay({ kind: "evidence", selection: { figureId, requestId: session.requestId } }); void control.ensureDestination("documents"); }
  function openConversationFigure(figureId: string) { conversationDialog.cancelPendingRestore(); setOverlay({ kind: "evidence", selection: { figureId, requestId: session.requestId } }); void control.ensureDestination("documents"); }
  async function openEvidenceDocument(link: EvidenceLink, fromDrawer = false, sourcePage?: number) {
    if (session.source?.documentsPageReader) {
      const target = await documentPages.resolve(link.targetDocumentId);
      if (!target) return;
      if (target.state !== "ready" || !target.document) {
        control.setNotice({ kind: "refused", text: target.state === "missing" ? "This source identity was not found in the active vault." : target.state === "conflicted_identity" ? "The captured source identity conflicts. No document was opened." : "The source details could not be read. You can retry this source link." });
        return;
      }
      if (sourcePage !== undefined) {
        if (!Number.isInteger(sourcePage) || sourcePage < 1 || sourcePage > 200) return;
        setSourcePageRequest({ documentId: target.document.id, page: sourcePage, nonce: ++pendingFocusNonce.current, requestId: session.requestId, source: session.source });
        conversationDialog.cancelPendingRestore(); setOverlay(null);
      }
      control.selectDocument(target.document.id); control.navigate("documents");
      if (sourcePage === undefined) setPendingDocumentFocus({ target: "document", documentId: target.document.id, requestId: session.requestId, nonce: ++pendingFocusNonce.current });
      if (fromDrawer) evidenceDialog.closeWithoutRestore();
      return;
    }
    const loaded = await control.ensureDestination("documents");
    if (!loaded && surface.documents.state === "unavailable") {
      control.setNotice({ kind: "refused", text: "Documents could not be read from the current vault." });
      return;
    }
    const documents = loaded && "documents" in loaded && loaded.documents ? loaded.documents : surface.documents;
    const target = resolveEvidenceTarget(documents, link.targetDocumentId);
    const label = link.label.trim() || "Source label unavailable";
    if (target.state === "missing_identity") { control.setNotice({ kind: "refused", text: "This evidence reference does not include a document identity." }); return; }
    if (target.state === "documents_unavailable") { control.setNotice({ kind: "refused", text: "Documents are not available in the current vault read." }); return; }
    if (target.state === "missing_document") { control.setNotice({ kind: "refused", text: `The source document “${label}” is not present in the current vault read.` }); return; }
    if (target.state === "pending") return;
    if (target.state === "conflicted_identity") { control.setNotice({ kind: "refused", text: `More than one document has the identity “${link.targetDocumentId}” in the current vault read. No document was opened.` }); return; }
    control.selectDocument(target.document.id); control.navigate("documents");
    setPendingDocumentFocus({ target: "document", documentId: target.document.id, requestId: session.requestId, nonce: ++pendingFocusNonce.current });
    if (fromDrawer) evidenceDialog.closeWithoutRestore();
  }
  // This form opens a vault and creates one only when the person selected the
  // creation option. An invalid path is reported without opening an empty vault.
  //
  // The transport answers one request before it reads the next, so a second
  // press while the vault is answering sends nothing. What the control says
  // while it waits is the words beside it.
  async function openVault(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (explicitVaultOpen.current || anyVaultOpen.current || openingVault) return;
    if (!control.hostAvailable || !vaultDirectory.trim() || !passphrase) { control.setNotice({ kind: "refused", text: "Enter a vault directory and passphrase to open a local vault." }); return; }
    explicitVaultOpen.current = true;
    anyVaultOpen.current = true;
    control.setNotice(null);
    setConversationPlanDraft(null);
    setPlanActionReceipt(null);
    try {
      await control.openVault(vaultDirectory.trim(), passphrase, makeVault);
      setPassphrase("");
    } finally {
      explicitVaultOpen.current = false;
      anyVaultOpen.current = false;
    }
  }
  async function pickVaultDirectory() {
    if (!control.pickerAvailable || pickingVaultDirectory || openingVault) return;
    setPickingVaultDirectory(true); control.setNotice(null);
    try { const selected = await control.pickVaultDirectory(); if (selected) setVaultDirectory(selected); }
    catch { control.setNotice({ kind: "refused", text: "The folder picker could not be opened. Enter the vault path manually." }); }
    finally { setPickingVaultDirectory(false); }
  }

  const frame = session.source?.frame ?? null;
  const plansServed = standingOf(session.description.registry, "plans") === "served";
  const reviewData = reviewResult.state === "ready" || reviewResult.state === "partial" || reviewResult.state === "needs_input" ? reviewResult.data : null;
  const reviewAction = session.questionAction;
  const resolvedReview = reviewAction.state === "settled" && reviewAction.authoritative === true && reviewAction.resolved === true && reviewAction.result.state === "settled" && (reviewAction.result.outcome.kind === "completed" || reviewAction.result.outcome.kind === "set_aside") && reviewResult.state === "ready";
  const reviewReceipt = reviewAction.state === "settled" && reviewAction.result.state === "settled" && reviewAction.result.outcome.kind === "set_aside" ? "The item was set aside." : "Your answer was saved.";
  const nextReviewItem = resolvedReview ? reviewData?.groups.flatMap((group) => group.items)[0] : undefined;
  const starterQuestions = control.askAvailable && surface.overview.state === "ready" && surface.overview.data.picture.figures.length
    ? ["What does my net worth include?"] : [];
  const reviewCount = reviewData?.actionableCount ?? 0;
  const reviewCountLabel = reviewData ? `${reviewCount} actionable ${reviewCount === 1 ? "item" : "items"}` : "count unavailable";
  const shownDestinations = destinations.filter((item) => item.placement === "primary" && (item.id !== "plans" || plansServed));
  const utilityDestinations = destinations.filter((item) => item.placement === "utility");
  const lazyDestination = session.destination in session.destinationReads ? session.destination as LazyDestination : null;
  const destinationRead = lazyDestination ? session.destinationReads[lazyDestination] : "idle";
  const destinationResult = lazyDestination ? surface[lazyDestination] : null;
  const destinationHasPreviousData = Boolean(destinationResult && (destinationResult.state === "ready" || destinationResult.state === "partial" || destinationResult.state === "needs_input")
    && (lazyDestination !== "review" || (surface.conversation.state === "ready" || surface.conversation.state === "partial" || surface.conversation.state === "needs_input")));
  function focusPlanResult(result: ActionResult) {
    requestAnimationFrame(() => {
      const proposalId = result.state === "settled" && result.outcome.kind === "proposal" ? result.outcome.proposalId : "";
      (proposalId ? document.getElementById(`proposal-${proposalId}`) : document.getElementById("plan-action-outcome"))?.focus();
    });
  }
  const planControls = control.planActionsAvailable ? {
    draft: async (payload: PlanPayload) => { setPlanActionReceipt(null); return control.draftPlan(payload); },
    propose: async (payload: PlanPayload) => {
      const result = await control.proposePlan(payload); setPlanActionReceipt(result);
      if (result.state === "settled" && result.outcome.kind === "proposal") setConversationPlanDraft(null);
      focusPlanResult(result); return result;
    },
    confirm: async (proposalId: string) => { const result = await control.confirmPlan(proposalId); setPlanActionReceipt(result); focusPlanResult(result); return result; },
    decline: async (proposalId: string) => { const result = await control.declinePlan(proposalId); setPlanActionReceipt(result); focusPlanResult(result); return result; },
  } : null;
  const vaultForm = (<form className="vault-open-form" onSubmit={openVault}><fieldset className="vault-start-choice"><legend>Start with a private vault</legend><label className="vault-create-choice"><input type="radio" name="vault-mode" checked={!makeVault} onChange={() => setMakeVault(false)} />Open an existing vault</label><label className="vault-create-choice"><input type="radio" name="vault-mode" checked={makeVault} onChange={() => setMakeVault(true)} />Make a new vault in that folder</label></fieldset><p>{makeVault ? "Choose a folder for your new vault and a passphrase you can keep safely. The vault holds encrypted records on this computer." : "Choose the folder containing your vault, then enter its passphrase."}</p><label>Vault directory<span className="vault-directory-control"><input value={vaultDirectory} onChange={(event) => setVaultDirectory(event.target.value)} placeholder="/path/to/vault" autoComplete="off" />{control.pickerAvailable && <button className="vault-picker-button" type="button" onClick={pickVaultDirectory} aria-disabled={openingVault} aria-describedby={openingVault ? "vault-open-waiting" : undefined}><FolderOpen size={14} />{pickingVaultDirectory ? "Choosing..." : "Choose folder"}</button>}</span></label><label>Passphrase<input ref={passphraseRef} type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} placeholder="Enter passphrase" autoComplete={makeVault ? "new-password" : "current-password"} aria-describedby="vault-passphrase-consequence" /></label><p className="vault-passphrase-consequence" id="vault-passphrase-consequence">Keep your passphrase somewhere safe. You need it to open a copy of this vault on another device.</p><details className="vault-protection-details"><summary>How your vault is protected</summary><p>Records are encrypted on this computer. Opening an existing vault never creates one. {control.remembersVault ? "After a successful open, this device protects the vaultphrase in macOS Keychain or Windows Credential Manager and opens this vault by default. Choosing another vault replaces that default." : "This session does not save the vaultphrase for automatic opening after restarting OrionViva."} The vault file never stores the vaultphrase.</p></details><button className="secondary-button vault-open-button" type="submit" aria-disabled={openingVault} aria-describedby={openingVault ? "vault-passphrase-consequence vault-open-waiting" : "vault-passphrase-consequence"}>{openingVault ? "Opening vault..." : makeVault ? "Make and open vault" : "Open local vault"}</button>{openingVault ? <span className="action-explanation" id="vault-open-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}</form>);
  function chooseVaultSetup(create: boolean) {
    if (openingVault || !control.hostAvailable) return;
    setMakeVault(create);
    setVaultSetup(true);
  }
  const samplePreparationStatus = control.samplePreparation?.state === "preparing" ? <section id="vault-application-waiting" className="welcome-status" role="status" aria-live="polite"><strong>Preparing Alex Morgan’s five-year sample</strong><p>{control.samplePreparation.completed_documents} of {control.samplePreparation.total_documents} documents processed · {control.samplePreparation.posted_documents} posted · {control.samplePreparation.held_documents} held.</p><p>{control.samplePreparation.phase === "validating" ? "Checking the synthetic source documents." : control.samplePreparation.phase === "capturing" ? "Importing the synthetic records on this computer." : "Checking the completed financial picture before opening."} The sample will open when preparation is complete.</p></section> : null;
  if (!session.source) return <main className="welcome-screen">
    <div className="welcome-brand"><span className="brand-mark" aria-hidden="true">O</span><strong>OrionViva</strong><span>Private financial picture</span></div>
    <StatusNotice notice={session.notice} onDismiss={() => control.setNotice(null)} icons={noticeIcons} dismissIcon={<X />} />
    {openingVault ? samplePreparationStatus || <p className="welcome-status" role="status">Opening your vault… Your records will appear when it is ready.</p> : null}
    <section className="welcome-card" aria-labelledby="page-title" aria-busy={openingVault}>
      <div className="welcome-intro"><p className="section-kicker">Your records. Your understanding.</p><h1 ref={pageTitleRef} id="page-title" tabIndex={-1}>Your financial picture</h1><p>Bring your statements together, understand your money, and see the sources behind every figure.</p></div>
      {vaultRecovery ? <VaultRecovery restore={control.restoreBackup} pickArchive={control.backupPickerAvailable ? control.pickBackupArchive : undefined} pickDirectory={control.pickerAvailable ? control.pickVaultDirectory : undefined} onBack={() => { setVaultRecovery(false); requestAnimationFrame(() => restoreChoiceRef.current?.focus()); }} onOpen={(directory) => { setVaultDirectory(directory); setPassphrase(""); setMakeVault(false); setVaultRecovery(false); setVaultSetup(true); }} /> : vaultSetup ? <div className="welcome-setup"><button className="text-button" type="button" aria-disabled={openingVault} onClick={() => { if (openingVault) return; setVaultSetup(false); setPassphrase(""); requestAnimationFrame(() => setupChoiceRef.current?.focus()); }}>Back to getting started</button><h2 ref={setupHeadingRef} tabIndex={-1}>{makeVault ? "Set up your private vault" : "Open your existing vault"}</h2>{vaultForm}</div> : <>
        <div className="welcome-choices">
          <article><h2>See how it works</h2><p>Explore Alex Morgan’s fictional finances from 2021–2025. Institution and security names are real; records and transactions are synthetic.</p><button className="secondary-button" type="button" aria-disabled={openingVault || !control.hostAvailable} aria-describedby={!control.hostAvailable ? "welcome-host-note" : undefined} onClick={openSampleVault}>{openingVault ? "Opening sample vault…" : "Try sample data"}</button></article>
          <article><h2>Start with your statements</h2><p>Create an encrypted vault on this computer, then add your first statement.</p><button ref={setupChoiceRef} className="primary-button" type="button" aria-disabled={openingVault || !control.hostAvailable} aria-describedby={!control.hostAvailable ? "welcome-host-note" : undefined} onClick={() => chooseVaultSetup(true)}>Set up my vault</button></article>
        </div>
        {control.hostAvailable ? <button className="text-button welcome-existing" type="button" aria-disabled={openingVault} onClick={() => chooseVaultSetup(false)}>Open existing vault</button> : <p id="welcome-host-note">To use sample data or your own vault, open the desktop app or use its Open in browser action.</p>}
        {control.hostAvailable ? <button ref={restoreChoiceRef} className="text-button welcome-existing" type="button" aria-disabled={openingVault} onClick={() => { if (openingVault) return; setPassphrase(""); setVaultRecovery(true); }}>Restore a backup</button> : null}
      </>}
      <p className="welcome-privacy">Your vault stays on this computer. Connecting a model is optional; requests to a configured service may send relevant content and incur charges.</p>
    </section>
  </main>;
  return <div className={frame ? "app-shell app-shell-sample" : "app-shell"} inert={accountTransactionOpen ? true : undefined} aria-hidden={accountTransactionOpen ? true : undefined}>
    {/* One frame, said once, around the whole place — never a qualifier on
        each sentence inside it. A qualifier on one figure quietly claims the
        unqualified figures beside it are different, and a person weighing up
        this product ends up reading our disclaimers instead of the picture we
        say we can draw. Its words are the engine's, and leaving is the one
        action beside them. */}
    {openingVault ? samplePreparationStatus || <div className="action-explanation" id="vault-application-waiting" role="status">The vault is opening and its first authoritative read is still pending. Other actions are unavailable until it answers.</div> : null}
    {control.closingVault && <div className="action-explanation" id="vault-close-waiting" role="status">Closing vault… Wait for OrionViva to end access.</div>}
    {frame ? <div className="sample-frame" role="note" aria-label={frame.title}><div className="sample-frame-copy"><strong>{frame.title}</strong><span>{frame.detail}</span></div><button className="secondary-button sample-frame-leave" type="button" aria-disabled={openingVault || control.closingVault} aria-describedby={control.closingVault ? "vault-close-waiting" : openingVault ? "vault-application-waiting" : undefined} onClick={leaveVault}>{control.closingVault ? "Closing vault…" : frame.leave}</button></div> : null}
    {isNarrow && mobileNav && <div className="navigation-backdrop" aria-hidden="true" onClick={() => closeNavigation()} />}
    <aside ref={navigationDrawerRef} id="primary-navigation-drawer" className={mobileNav ? "sidebar sidebar-open" : "sidebar"} role={isNarrow && mobileNav ? "dialog" : undefined} aria-modal={isNarrow && mobileNav ? true : undefined} aria-labelledby={isNarrow && mobileNav ? "primary-navigation-title" : undefined} aria-hidden={isNarrow ? !mobileNav : accountTransactionOpen ? true : undefined} inert={openingVault || Boolean(evidenceSelection) || conversationOpen || accountTransactionOpen || (isNarrow && !mobileNav) ? true : undefined} tabIndex={-1}>
      <h2 className="visually-hidden" id="primary-navigation-title">Main navigation</h2>
      <div className="brand-row"><div className="brand-mark">O</div><div><div className="brand-name">OrionViva</div><div className="brand-subtitle">Private financial picture</div></div><button ref={navigationCloseRef} className="icon-button mobile-close" onClick={() => closeNavigation()} aria-label="Close navigation"><X size={18} /></button></div>
      <div className="preview-badge"><span className="status-dot" />Preview build</div>
      {session.source ? <div className="vault-session-actions"><span>Vault open</span><button className="text-button" type="button" aria-disabled={control.closingVault} aria-describedby={control.closingVault ? "vault-close-waiting" : undefined} onClick={leaveVault}>{control.closingVault ? "Closing vault…" : session.source.frame ? session.source.frame.leave : "Close this vault"}</button></div> : null}
      <details className="vault-source-disclosure" open={!session.source}>
        <summary><span>Vault & privacy</span><small>Source and access</small></summary>
      <div className="vault-source-card">
        <div className="vault-source-topline"><span>Vault source</span>{session.source ? null : <button className="text-button" type="button" aria-disabled={openingVault} aria-describedby={openingVault ? "vault-open-waiting" : undefined} onClick={openSampleVault}>{openingVault ? "Opening sample vault…" : "Open the sample vault"}</button>}</div>
        <strong>{surface.disclosure.title}</strong><span className="vault-source-subtitle">{surface.disclosure.subtitle}</span><p>{surface.disclosure.detail}</p>
        {control.hostAvailable ? vaultForm : <span className="vault-host-note">Preview mode. A desktop host bridge will enable local vault opening.</span>}
      </div>
      </details>
      <nav id="primary-navigation" aria-label="Primary navigation"><div className="nav-label">Money</div>{shownDestinations.map((item) => {
        // Destination marks use registry standing; an unanswered registry read carries no mark.
        const standing = standingOf(session.description.registry, item.id);
        const said = standingCopy[standing];
        const reviewBadge = item.id === "review" && reviewData ? (reviewCount > 999 ? "999+" : String(reviewCount)) : "";
        return <button key={item.id} className={session.destination === item.id ? "nav-item active" : "nav-item"} aria-current={session.destination === item.id ? "page" : undefined} aria-label={item.id === "review" ? `${item.label}, ${reviewCountLabel}` : undefined} title={item.description} onClick={() => navigate(item.id)}><strong>{item.label}</strong>{reviewBadge ? <span className="review-badge" aria-hidden="true">{reviewBadge}</span> : said ? <span className="nav-standing">{said}</span> : null}</button>;
      })}</nav>
      <nav className="utility-navigation" aria-label="Vault and privacy">{utilityDestinations.map((item) => <button key={item.id} className={session.destination === item.id ? "nav-item utility-nav-item active" : "nav-item utility-nav-item"} aria-current={session.destination === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><Info aria-hidden="true" size={16} /><strong>{item.label}</strong></button>)}</nav>
      <div className="sidebar-footer"><div className="privacy-lock"><Info aria-hidden="true" size={16} /><span>Local source</span></div><p>Vaults stay on this machine unless an action explicitly says otherwise.</p></div>
    </aside>
    <main className="main-content" aria-hidden={accountTransactionOpen ? true : undefined} inert={openingVault || Boolean(evidenceSelection) || conversationOpen || accountTransactionOpen || (isNarrow && mobileNav) ? true : undefined}>
      <header className="topbar"><button ref={navigationTriggerRef} id="mobile-navigation-trigger" className="icon-button mobile-menu" type="button" onClick={openNavigation} aria-label="Open navigation" aria-controls="primary-navigation-drawer" aria-expanded={isNarrow ? mobileNav : false}><Menu size={20} /></button><div className="breadcrumbs"><span>OrionViva</span><ChevronRight size={14} /><strong>{pageCopy[session.destination].title}</strong></div><div className="topbar-actions"><button className="primary-button add-statement-button" type="button" onClick={openDocuments}><FilePlus2 className="action-icon" />Add statement</button><button className="ask-button" type="button" onClick={openAskViva}><Sparkles size={16} />Ask Viva</button></div></header>
      <StatusNotice notice={session.notice} onDismiss={() => control.setNotice(null)} icons={noticeIcons} dismissIcon={<X size={15} />} />
      {documentPages.detail.state === "pending" && !evidenceSelection ? <p className="action-explanation" role="status">Finding the source document in the active vault…</p> : null}
      <div className="content-wrap" data-read-revision={session.readRevision || undefined}><div className="page-heading"><div><div className="kicker">{pageCopy[session.destination].intro}</div><h1 ref={pageTitleRef} id="page-title" tabIndex={-1}>{pageCopy[session.destination].title}</h1></div></div>
        <SourceDisclosure disclosure={surface.disclosure} />
        {session.destination === "overview" && session.source && !session.source.frame && !priorityLoading && !session.priorityRetryable && surface.overview.state === "ready" && surface.overview.data.accounts.length === 0 ? <section className="feature-panel first-statement-guide" aria-labelledby="first-statement-title"><h2 id="first-statement-title">Start with a statement</h2><p>Add your first statement to begin building your financial picture.</p><ol><li>Check the document-reading settings. A configured model may send document content to its service and incur charges.</li><li>Add one statement. Its original is encrypted and saved in your vault.</li><li>Check the result in Statements &amp; documents. Saving a file does not by itself mean its figures were verified.</li></ol><div className="first-statement-actions">{control.settingsAvailable ? <button className="secondary-button" type="button" onClick={() => { navigate("trust"); requestAnimationFrame(() => pageTitleRef.current?.focus()); }}>Check document-reading settings</button> : null}<button className="primary-button" type="button" onClick={openDocuments}>Go to statements</button></div></section> : null}
        {session.source && lazyDestination && (destinationRead === "loading" || destinationRead === "retrying" || destinationRead === "failed") ? <div className="feature-panel priority-read-callout">
          <div className="empty-state"><div role="status" aria-live="polite" aria-atomic="true"><strong>{destinationRead === "retrying" ? `Retrying ${pageCopy[lazyDestination].title}` : destinationRead === "loading" ? `Reading ${pageCopy[lazyDestination].title}` : destinationHasPreviousData ? `${pageCopy[lazyDestination].title} could not be refreshed` : `${pageCopy[lazyDestination].title} could not be read`}</strong><span>{destinationRead === "loading" ? "This screen is loading. Other screens remain available." : destinationRead === "retrying" ? "Trying this screen again." : destinationHasPreviousData ? "The last complete view remains below and may be stale." : "Try loading this screen again."}</span></div>{destinationRead !== "loading" ? <button onFocus={(event) => { if (!overlay) destinationRetryFocus.current = { source: session.source, requestId: session.requestId, destination: session.destination, button: event.currentTarget }; }} onBlur={() => { destinationRetryFocus.current = null; }} className="secondary-button" type="button" aria-disabled={destinationRead === "retrying"} onClick={() => { if (destinationRead === "failed") void control.retryDestinationRead(lazyDestination); }}>Retry this screen</button> : null}</div>
        </div> : null}
        <section className="priority-destination" aria-busy={(session.destination === "overview" || session.destination === "accounts") && (priorityLoading || session.priorityRetrying) ? true : undefined}>
        {session.source && (session.destination === "overview" || session.destination === "accounts") ? <div className="priority-read-status">
          {priorityLoading ? <div className="feature-panel"><div className="empty-state" role="status" aria-live="polite" aria-atomic="true"><strong>Reading your financial picture</strong><span>Loading Overview and Accounts from this vault…</span></div></div>
            : session.priorityRetryable ? <div className="feature-panel priority-read-callout"><div className="empty-state"><div role="status" aria-live="polite" aria-atomic="true"><strong>{session.priorityLifecycle === "rebuilding" ? "Preparing your financial picture" : session.priorityFreshness === "stale" ? "Showing the last complete read" : "Financial picture unavailable"}</strong><span>{session.priorityRetrying ? "Trying the financial picture again…" : session.priorityLifecycle === "rebuilding" ? "The vault is open. OrionViva is preparing its private on-device read, and you can keep using the app." : session.priorityFreshness === "stale" ? "The latest changes could not be read yet. The last complete figures remain visible." : "The vault is open, but no complete financial picture is available. No empty values have been substituted."}</span>{session.priorityRetryOutcome === "failed" ? <span>{priorityHasPreviousData ? "Your financial picture still could not be brought up to date. The last complete read remains shown." : "Your financial picture still could not be brought up to date. No complete picture is available yet."}</span> : null}</div><button ref={priorityRetryRef} className="secondary-button" type="button" aria-disabled={session.priorityRetrying} onClick={() => { if (!session.priorityRetrying) void retryPriorityRead(); }}>{session.priorityRetrying ? "Retrying…" : "Retry"}</button></div></div>
            : session.priorityRetryOutcome === "succeeded" ? <span role="status" aria-live="polite">Your financial picture is up to date.</span> : null}
        </div> : null}
        {priorityLoading && (session.destination === "overview" || session.destination === "accounts") ? null : <FeatureBoundary key={`destination-${session.requestId}-${session.destination}`} resetKey={`${session.requestId}-${session.destination}`}>
          {session.destination === "overview" && <Overview key={session.requestId} accountingReader={session.source?.accountingReader ?? undefined} result={surface.overview} reviewResult={reviewResult} activityResult={surface.activity} readSpendingBreakdown={control.readSpendingBreakdown} selectedAccount={session.selectedAccount} showVerificationDetails={proofPreference.showVerificationDetails} onNavigate={navigate} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onInspectDocument={inspectOverviewDocument} onInspectAccount={inspectOverviewAccount} onAskViva={control.askAvailable ? openAskViva : null} onSetAsideFinding={control.findingActionsAvailable ? (findingId) => void control.setAsideFinding(findingId) : null} settingAsideFindingId={control.settingAsideFindingId} findingReceipt={control.findingReceipt} onExploreSample={openSampleVault} openingSample={openingVault} />}
          {session.destination === "review" && resolvedReview ? <p className="review-next-step" role="status">{reviewReceipt} {nextReviewItem ? "The next available item is marked below." : reviewData && reviewData.remainingCount === 0 && reviewData.actionableCount === 0 ? "Nothing else needs your review." : "Check the review list for remaining items."}</p> : null}
          {session.destination === "review" && <Review onOpenSourceDocument={(documentId, page) => void openEvidenceDocument({ targetDocumentId: documentId, label: "Source section needing review", relation: "attests", page: String(page ?? 1) }, false, page)} nextItemId={nextReviewItem?.id} result={reviewResult} onOpenQuestion={openReviewQuestion} onOpenTransaction={openReviewTransaction} />}
          {session.destination === "accounts" && openedAccount && (surface.overview.state === "ready" || surface.overview.state === "partial" || surface.overview.state === "needs_input") ? <AccountLedger accountId={openedAccount} loadingAccountName={surface.overview.data.accounts.find((account) => account.id === openedAccount)?.name} requestedReviewTarget={reviewTransaction?.target} backLabel={reviewTransaction ? "Back to Review" : accountOrigin?.kind === "overview" ? "Back to Overview" : undefined} read={control.readAccountLedger} activityResult={surface.activity} conversationResult={surface.conversation} correction={control.activityCorrectionAvailable ? { state: session.activityAction, onAssignClassification: async (movementIds, categoryId, subcategoryId) => await control.assignActivityClassification(movementIds, categoryId, subcategoryId) ?? null, onAddTags: async (movementIds, tagIds) => await control.addActivityTags(movementIds, tagIds) ?? null, onRemoveTags: async (movementIds, tagIds) => await control.removeActivityTags(movementIds, tagIds) ?? null } : null} onBack={reviewTransaction ? returnToReview : returnFromAccount} onOpenEvidence={openEvidenceDocument} onOpenQuestion={(questionId, movementId) => openReviewQuestion(questionId, reviewTransaction?.itemId ?? "", movementId)} onReviewTransfer={reviewMovement} onDrawerOpenChange={setAccountTransactionOverlay} drawerActive={accountTransactionOpen} renderOverlay={(content) => createPortal(content, document.body)} pageTitleRef={pageTitleRef} /> : session.destination === "accounts" ? <Accounts result={surface.overview} selectedAccount={session.selectedAccount} onOpenAccount={(accountId) => { setAccountOrigin({ kind: "accounts", accountId }); setOpenedAccount(accountId); }} showVerificationDetails={proofPreference.showVerificationDetails} onSelectAccount={control.selectAccount} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onExploreSample={openSampleVault} openingSample={openingVault} /> : null}
          {session.destination === "documents" && <Documents retained={control.retainedAvailable ? { selection: control.retainedSelection, blocked: control.retainedBlocked, canSelect: control.canSelectRetained, onAdd: control.addRetainedReading, onRemove: control.removeRetainedReading, onConfirm: control.confirmRetainedReadings } : undefined} bulk={control.bulkPickerAvailable || control.bulkSession ? { session: control.bulkSession, working: session.captureAction.state === "working", onChoose: control.bulkPickerAvailable ? () => void chooseBulkDocuments() : null, onStop: control.stopBulkDocuments } : undefined} onSourcePageConsumed={(nonce) => setSourcePageRequest((request) => request?.nonce === nonce ? undefined : request)} sourcePageRequest={sourcePageRequest?.requestId === session.requestId && sourcePageRequest.source === session.source && readySourcePageNonce === sourcePageRequest?.nonce && session.destinationReads.documents === "ready" && documentPages.detail.state === "ready" ? sourcePageRequest : undefined} key={session.requestId} paging={documentPages} previewReader={session.source?.documentPreviewReader} subscribePreviewEnd={session.source?.subscribePreviewEnd} recoveryJobs={session.jobs} onOpenReview={() => navigate("review")} onRecoverDocument={control.recoveryAvailable ? (jobId) => void control.recoverDocument(jobId) : undefined} onOpenSettings={control.settingsAvailable ? () => { navigate("trust"); requestAnimationFrame(() => pageTitleRef.current?.focus()); } : undefined} result={surface.documents} selectedDocument={session.selectedDocument} capture={control.captureAvailable ? { state: session.captureAction, onChoose: control.filePickerAvailable ? () => void chooseDocuments() : null, job: capturedJob, cancel: session.cancelAction, onStop: (jobId: string) => { if (capturedJob?.operation === "viva.documents.upload_many") control.stopBulkDocuments(); else void control.cancelJob(jobId); } } : null} rescan={control.captureAvailable ? { state: session.rescanAction, onRescan: () => void control.rescanDocuments(), onReviewMovement: reviewMovement } : null} jobStatus={control.jobStatus} jobCheck={control.jobCheck} onRecheckJobs={() => void control.recheckJobs()} onSelectDocument={control.selectDocument} onOpenEvidence={openEvidenceDocument} onExploreSample={openSampleVault} openingSample={openingVault} />}
          {session.destination === "activity" && <Activity onExplainMovement={control.askAvailable ? openExplainMovement : undefined} result={surface.activity} selectedMovement={selectedMovement} correction={control.activityCorrectionAvailable ? { state: session.activityAction, onAssignCategory: (movementId, categoryId) => void control.assignActivityCategory(movementId, categoryId), onAssignMeaning: (movementId, meaning, counterparty) => void control.assignActivityMeaning(movementId, meaning, counterparty), onReplaceTags: (movementId, tagIds) => void control.replaceActivityTags(movementId, tagIds), onConfirmTransfer: (movementId, counterpartId) => void control.confirmActivityTransfer(movementId, counterpartId), onRejectTransfer: (movementId) => void control.rejectActivityTransfer(movementId), onUnlinkTransfer: (movementId, counterpartId) => void control.unlinkActivityTransfer(movementId, counterpartId) } : null} onOpenEvidence={openEvidenceDocument} onLoadMore={() => void control.loadMoreActivity()} />}
          {session.destination === "plans" && <Plans result={plansResult} controls={planControls} initialDraft={conversationPlanDraft} receipt={planActionReceipt} onOpenEvidence={openEvidenceDocument} />}
          {session.destination === "trust" && <Trust result={surface.trust} identity={session.description.identity} lifecycle={session.description.lifecycle} displayPreference={{ showVerificationDetails: proofPreference.showVerificationDetails, onChange: proofPreference.setShowVerificationDetails }} transfer={control.transferAvailable ? { state: session.transferAction, onPickExport: control.backupSavePickerAvailable ? control.pickBackupSavePath : undefined, onPickArchive: control.backupPickerAvailable ? control.pickBackupArchive : undefined, onPickDirectory: control.pickerAvailable ? control.pickVaultDirectory : undefined, onExport: (archive: string) => void control.exportVault(archive), onRestore: (archive: string, directory: string, passphrase: string) => void control.restoreVault(archive, directory, passphrase) } : null} settings={control.settingsAvailable ? { settings: session.settings, state: session.settingsAction, onPropose: (kind, fields) => void control.proposeSettings(kind, fields), onConfirm: (kind, fields, digest, key) => void control.confirmSettings(kind, fields, digest, key) } : null} maintenance={control.trustAvailable ? { state: session.trustAction, job: maintenanceJob, jobStatus: control.jobStatus, jobCheck: control.jobCheck, cancel: session.cancelAction, onRun: (spend: boolean) => void control.runMaintenance(spend), onDiagnose: (file: string) => void control.writeDiagnostic(file), onStop: (jobId: string) => void control.cancelJob(jobId), onRecheck: () => void control.recheckJobs() } : null} />}
        </FeatureBoundary>}
        </section>
      </div>
    </main>
    {conversationOpen && <ConversationDialogShell mode={conversationSelection?.mode} resetKey={`${session.requestId}-conversation-${conversationSelection?.mode}`} drawerRef={conversationDrawerRef} closeRef={conversationCloseRef} onDismiss={conversationDialog.dismissAndRestore}><ConversationDrawer onOpenSourceDocument={(documentId: string, page: number) => void openEvidenceDocument({ targetDocumentId: documentId, label: "Saved source", relation: "attests", page: String(page) }, false, page)} onContinueAllocation={conversationContext.continueAllocation} context={{ mode: conversationContext.contextMode, onNewConversation: conversationContext.startNewConversation, canContinue: conversationContext.canContinuePreviousConversation, onContinueConversation: conversationContext.continuePreviousConversation }} starterQuestions={starterQuestions} onClearAccountingContext={() => setAccountingContext(null)} accountingContext={accountingContext} onUndoCorrection={control.undoAccountingCorrection} mode={conversationSelection?.mode} result={surface.conversation} selectedQueue={session.selectedQueue} onSelectQueue={control.selectQueue} onOpenFigure={openConversationFigure} onReviewPlan={(draft: ConversationGoalDraft) => { conversationDialog.cancelPendingRestore(); setPlanActionReceipt(null); setConversationPlanDraft({ state: "settled", kind: draft.kind, message: draft.message, reason: draft.reason, draft: draft.draft }); control.navigate("plans"); setOverlay(null); requestAnimationFrame(() => (document.getElementById("plans-draft-title") ?? pageTitleRef.current)?.focus()); }} ask={control.askAvailable ? { state: session.askAction, onAsk: (question: string, mirrored: boolean, planRequest = false, contextMode = "new_question", movementIds?: readonly string[]) => { const recovery = conversationContext.consumeContinuationRecovery(contextMode, Boolean(movementIds?.length)); conversationContext.questionSubmitted(question, Boolean(movementIds?.length)); void control.askViva(question, mirrored, planRequest, contextMode, movementIds, recovery); } } : null} controls={{ state: session.questionAction, onAnswer: answerQuestion, onConfirm: confirmProposal, onDecline: declineQuestion }} />{conversationSelection?.mode === "review" && resolvedReview && nextReviewItem ? <div className="review-next-step"><span>{reviewReceipt}</span><button className="secondary-button" type="button" onClick={() => {
      if (nextReviewItem.target.kind === "transaction") { conversationDialog.cancelPendingRestore(); setOverlay(null); openReviewTransaction(nextReviewItem.target, nextReviewItem.id); }
      else openReviewQuestion(nextReviewItem.target.questionId, nextReviewItem.id);
    }}>Next item</button></div> : null}</ConversationDialogShell>}
    {evidenceSelection && <EvidenceDrawer documentDetail={documentPages.detail} snapshot={surface} selection={evidenceSelection} drawerRef={evidenceDrawerRef} closeRef={evidenceCloseRef} onDismiss={evidenceDialog.dismissAndRestore} onOpenDocument={(link) => openEvidenceDocument(link, true)} renderEvidenceBadge={(grade) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />} />}
  </div>;
}
