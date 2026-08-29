import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { ArrowUpRight, Check, ChevronRight, FilePlus2, FolderOpen, Info, Menu, Sparkles, X } from "lucide-react";
import { FeatureBoundary } from "../components/FeatureBoundary";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { SourceDisclosure } from "../components/SourceDisclosure";
import { StatusNotice } from "../components/StatusNotice";
import { Accounts } from "../features/accounts/Accounts";
import { Activity } from "../features/activity/Activity";
import { ConversationDrawer } from "../features/conversation/ConversationDrawer";
import { Documents } from "../features/documents/Documents";
import { Overview } from "../features/overview/Overview";
import { Review } from "../features/review/Review";
import { Trust } from "../features/trust/Trust";
import { resolveEvidenceTarget } from "../surface/evidence";
import type { DeclineReason, Destination, EvidenceLink, FeatureResult, NoticeKind, ReviewActionState, ReviewData } from "../surface/types";
import { destinations, standingCopy, standingOf } from "./navigation";
import { useResponsiveNavigation } from "./useResponsiveNavigation";
import { useEvidenceDialog } from "./useEvidenceDialog";
import { useProofPreference } from "./useProofPreference";
import { useSurfaceSession } from "./useSurfaceSession";
import type { CaptureGesture } from "./useSurfaceSession";

const pageCopy: Record<Destination, { title: string; intro: string }> = {
  overview: { title: "Your financial picture", intro: "A quiet view of what is known, what is pending, and what still needs a human decision." },
  accounts: { title: "Accounts", intro: "Each account speaks in its own terms, with measurement dates shown rather than implied." },
  activity: { title: "Activity", intro: "Movements, their supplied context, and the evidence behind each displayed figure." },
  documents: { title: "Documents", intro: "Capture comes first. Reading and posting stay separate." },
  review: { title: "Review", intro: "One quiet place to inspect questions returned by the current read." },
  trust: { title: "Trust", intro: "What this preview can establish, what is unavailable, and which capabilities are not connected." },
};
// One mark per kind of notice, chosen by the word the notice declares. The
// tick is reachable only from the kind that means something happened, and a
// refusal carries no mark at all: its border says what it is, as it does on
// the review screen.
const noticeIcons: Record<NoticeKind, ReactNode> = { acknowledged: <Check />, refused: null };
type Overlay = null | { kind: "navigation" } | { kind: "conversation"; requestId: number } | { kind: "evidence"; selection: { figureId: string; requestId: number } };
type PendingDocumentFocus =
  | { target: "document"; documentId: string; requestId: number; nonce: number }
  | { target: "capture"; requestId: number; nonce: number };
type PendingReviewFocus = { requestId: number; questionId: string; nonce: number };

// Whether the question a verb was used on is still being asked. Only the
// read's own states carry a queue; anything else cannot say either way, and
// reports false so that focus is left where it is.
function reviewQueueHolds(review: FeatureResult<ReviewData>, questionId: string): boolean {
  if (review.state !== "ready" && review.state !== "partial" && review.state !== "needs_input") return false;
  return review.data.queue.some((question) => question.id === questionId);
}

export function ConversationDialogShell({ resetKey, drawerRef, closeRef, onDismiss, children }: { resetKey: string; drawerRef: RefObject<HTMLElement | null>; closeRef: RefObject<HTMLButtonElement | null>; onDismiss: () => void; children: ReactNode }) {
  return <><div className="conversation-backdrop" aria-hidden="true" onClick={onDismiss} /><aside ref={drawerRef} id="viva-conversation-drawer" className="conversation-drawer" role="dialog" aria-modal="true" aria-labelledby="viva-conversation-title" aria-describedby="viva-conversation-description" tabIndex={-1}><header className="conversation-topline"><div><h2 id="viva-conversation-title">Viva conversation</h2><p id="viva-conversation-description">Ask Viva a question about the records in this vault.</p></div><button ref={closeRef} className="conversation-close" type="button" onClick={onDismiss} aria-label="Close Viva conversation"><X size={18} /></button></header><FeatureBoundary resetKey={resetKey}>{children}</FeatureBoundary></aside></>;
}

export function App() {
  const control = useSurfaceSession((gesture) => documentDropped(gesture));
  const proofPreference = useProofPreference();
  const { session } = control;
  const surface = session.snapshot;
  const [vaultDirectory, setVaultDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [makeVault, setMakeVault] = useState(false);
  const [pickingVaultDirectory, setPickingVaultDirectory] = useState(false);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [pendingDocumentFocus, setPendingDocumentFocus] = useState<PendingDocumentFocus | null>(null);
  const [pendingReviewFocus, setPendingReviewFocus] = useState<PendingReviewFocus | null>(null);
  const pendingFocusNonce = useRef(0);
  const activePendingFocusNonce = useRef<number | null>(null);
  const reviewFocusNonce = useRef(0);
  const activeReviewFocusNonce = useRef<number | null>(null);
  const settledReviewAction = useRef<ReviewActionState | null>(null);
  const mobileNav = overlay?.kind === "navigation";
  const isNarrow = useResponsiveNavigation();
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const navigationDrawerRef = useRef<HTMLElement>(null);
  const navigationCloseRef = useRef<HTMLButtonElement>(null);
  const pageTitleRef = useRef<HTMLHeadingElement>(null);
  const evidenceDrawerRef = useRef<HTMLElement>(null);
  const evidenceCloseRef = useRef<HTMLButtonElement>(null);
  const conversationDrawerRef = useRef<HTMLElement>(null);
  const conversationCloseRef = useRef<HTMLButtonElement>(null);
  const openingVault = session.phase === "opening";
  // The one job this screen has a control for: the newest capture the sidecar
  // has said anything about. The registry holds more than one, and a screen
  // that showed all of them would be showing work a person did not start from
  // here; the stop belongs beside the thing they did start.
  const capturedJob = [...session.jobs].reverse().find((job) => job.operation === "viva.documents.upload") ?? null;
  const evidenceSelection = overlay?.kind === "evidence" && overlay.selection.requestId === session.requestId ? overlay.selection : null;
  const conversationSelection = overlay?.kind === "conversation" && overlay.requestId === session.requestId ? overlay : null;
  const conversationOpen = Boolean(conversationSelection);
  const evidenceDialog = useEvidenceDialog({ open: Boolean(evidenceSelection), drawerRef: evidenceDrawerRef, initialFocusRef: evidenceCloseRef, pageTitleRef, onDismiss: () => setOverlay(null) });
  const conversationDialog = useEvidenceDialog({ open: conversationOpen, drawerRef: conversationDrawerRef, initialFocusRef: conversationCloseRef, pageTitleRef, onDismiss: () => setOverlay(null) });

  useEffect(() => { if (overlay?.kind === "evidence" && !evidenceSelection) setOverlay(null); }, [evidenceSelection, overlay]);
  useEffect(() => { if (overlay?.kind === "conversation" && !conversationSelection) setOverlay(null); }, [conversationSelection, overlay]);

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
    if (session.requestId !== pendingReviewFocus.requestId || session.destination !== "review" || session.selectedQueue !== pendingReviewFocus.questionId) {
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
  }, [pendingReviewFocus, session.destination, session.requestId, session.selectedQueue]);

  // A write that took leaves focus on a control that has gone with the
  // question it belonged to. Focus therefore moves, one frame later once the
  // read that followed the write has rendered, to the question the queue moved
  // to, or to the empty state when the queue holds nothing more, or to what
  // became of the write when that read failed and neither of those exists. A
  // write that was refused moved nothing, so focus stays on the control the
  // person must use again.
  useEffect(() => {
    const acted = session.reviewAction;
    if (acted.state !== "settled" || settledReviewAction.current === acted) return undefined;
    settledReviewAction.current = acted;
    if (session.destination !== "review" || reviewQueueHolds(surface.review, acted.questionId)) return undefined;
    const frame = requestAnimationFrame(() => {
      (document.getElementById("selected-question-title") ?? document.getElementById("review-empty-title") ?? document.getElementById("review-outcome-title"))?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [session.destination, session.reviewAction, surface.review]);

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
  function openNavigation() { if (!isNarrow) return; setOverlay({ kind: "navigation" }); }
  function navigate(destination: Destination) { const focusHeading = isNarrow && mobileNav; control.navigate(destination); if (mobileNav) setOverlay(null); if (focusHeading) requestAnimationFrame(() => pageTitleRef.current?.focus()); }
  function openDocuments() {
    setPendingDocumentFocus({ target: "capture", requestId: session.requestId, nonce: ++pendingFocusNonce.current });
    control.navigate("documents");
  }
  // Leaving a vault is one action, and it takes everything with it: the
  // overlays go, the session is rebuilt from nothing, and no row from the
  // vault that was open survives into the one that is not.
  function leaveVault() { evidenceDialog.cancelPendingRestore(); conversationDialog.cancelPendingRestore(); control.resetDemo(); setOverlay(null); }
  function openSampleVault() { evidenceDialog.cancelPendingRestore(); conversationDialog.cancelPendingRestore(); setOverlay(null); void control.openSampleVault(); }
  function openReviewQuestion(questionId: string) {
    control.selectQueue(questionId);
    control.navigate("review");
    setPendingReviewFocus({ requestId: session.requestId, questionId, nonce: ++reviewFocusNonce.current });
  }
  function inspectOverviewDocument(documentId: string) {
    control.selectDocument(documentId);
    control.navigate("documents");
    setPendingDocumentFocus({ target: "document", documentId, requestId: session.requestId, nonce: ++pendingFocusNonce.current });
  }
  function inspectOverviewAccount(accountId: string) {
    control.selectAccount(accountId);
    control.navigate("accounts");
    requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  function declineQuestion(questionId: string, reason: DeclineReason) { void control.declineQuestion(questionId, reason); }
  function answerQuestion(questionId: string, said: string) { void control.answerQuestion(questionId, said); }
  function confirmProposal(questionId: string, proposalId: string, said: string, asked: string) { void control.confirmProposal(questionId, proposalId, said, asked); }
  // A dropped file changed the screen without the person asking, so the move
  // goes through the same navigation every other screen change goes through,
  // any open drawer is dismissed so the receipt is neither inert nor hidden
  // behind it, and the heading is focused so the move is announced.
  // What a gesture carrying more than one document is told, wherever it came
  // from. One sentence, one place.
  function refuseSeveral() { control.setNotice({ kind: "refused", text: "This takes one document at a time. Nothing was added." }); }
  function documentDropped(gesture: CaptureGesture) {
    if (gesture === "none") return;
    evidenceDialog.cancelPendingRestore();
    conversationDialog.cancelPendingRestore();
    setOverlay(null);
    if (gesture === "several") { refuseSeveral(); return; }
    navigate("documents");
    requestAnimationFrame(() => pageTitleRef.current?.focus());
  }
  async function chooseDocuments() {
    const gesture = await control.chooseDocuments();
    if (gesture === "unopened") control.setNotice({ kind: "refused", text: "The file picker could not be opened, so nothing was chosen and nothing was added to this vault." });
    if (gesture === "several") refuseSeveral();
  }
  function openFigure(figureId: string) { setOverlay({ kind: "evidence", selection: { figureId, requestId: session.requestId } }); }
  function openEvidenceDocument(link: EvidenceLink, fromDrawer = false) {
    const target = resolveEvidenceTarget(surface.documents, link.targetDocumentId);
    const label = link.label.trim() || "Source label unavailable";
    if (target.state === "missing_identity") { control.setNotice({ kind: "refused", text: "This evidence reference does not include a document identity." }); return; }
    if (target.state === "documents_unavailable") { control.setNotice({ kind: "refused", text: "Documents are not available in the current vault read." }); return; }
    if (target.state === "missing_document") { control.setNotice({ kind: "refused", text: `The source document “${label}” is not present in the current vault read.` }); return; }
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
    if (openingVault) return;
    if (!control.hostAvailable || !vaultDirectory.trim() || !passphrase) { control.setNotice({ kind: "refused", text: "Enter a vault directory and passphrase to open a local vault." }); return; }
    control.setNotice(null);
    await control.openVault(vaultDirectory.trim(), passphrase, makeVault);
    setPassphrase("");
  }
  async function pickVaultDirectory() {
    if (!control.pickerAvailable || pickingVaultDirectory || openingVault) return;
    setPickingVaultDirectory(true); control.setNotice(null);
    try { const selected = await control.pickVaultDirectory(); if (selected) setVaultDirectory(selected); }
    catch { control.setNotice({ kind: "refused", text: "The folder picker could not be opened. Enter the vault path manually." }); }
    finally { setPickingVaultDirectory(false); }
  }

  const frame = session.source?.frame ?? null;
  return <div className={frame ? "app-shell app-shell-sample" : "app-shell"}>
    {/* One frame, said once, around the whole place — never a qualifier on
        each sentence inside it. A qualifier on one figure quietly claims the
        unqualified figures beside it are different, and a person weighing up
        this product ends up reading our disclaimers instead of the picture we
        say we can draw. Its words are the engine's, and leaving is the one
        action beside them. */}
    {frame ? <div className="sample-frame" role="note" aria-label={frame.title}><div className="sample-frame-copy"><strong>{frame.title}</strong><span>{frame.detail}</span></div><button className="secondary-button sample-frame-leave" type="button" onClick={leaveVault}>{frame.leave}</button></div> : null}
    {isNarrow && mobileNav && <div className="navigation-backdrop" aria-hidden="true" onClick={() => closeNavigation()} />}
    <aside ref={navigationDrawerRef} id="primary-navigation-drawer" className={mobileNav ? "sidebar sidebar-open" : "sidebar"} role={isNarrow && mobileNav ? "dialog" : undefined} aria-modal={isNarrow && mobileNav ? true : undefined} aria-labelledby={isNarrow && mobileNav ? "primary-navigation-title" : undefined} aria-hidden={isNarrow ? !mobileNav : undefined} inert={Boolean(evidenceSelection) || conversationOpen || (isNarrow && !mobileNav) ? true : undefined} tabIndex={-1}>
      <h2 className="visually-hidden" id="primary-navigation-title">Main navigation</h2>
      <div className="brand-row"><div className="brand-mark">O</div><div><div className="brand-name">OrionViva</div><div className="brand-subtitle">Private financial picture</div></div><button ref={navigationCloseRef} className="icon-button mobile-close" onClick={() => closeNavigation()} aria-label="Close navigation"><X size={18} /></button></div>
      <div className="preview-badge"><span className="status-dot" />Preview build</div>
      <div className="vault-source-card">
        <div className="vault-source-topline"><span>Vault source</span>{session.source ? <button className="text-button" onClick={leaveVault}>{session.source.frame ? session.source.frame.leave : "Close this vault"}</button> : <button className="text-button" aria-disabled={openingVault} onClick={openSampleVault}>Open the sample vault</button>}</div>
        <strong>{surface.disclosure.title}</strong><span className="vault-source-subtitle">{surface.disclosure.subtitle}</span><p>{surface.disclosure.detail}</p>
        {control.hostAvailable ? <form className="vault-open-form" onSubmit={openVault}><label>Vault directory<span className="vault-directory-control"><input value={vaultDirectory} onChange={(event) => setVaultDirectory(event.target.value)} placeholder="/path/to/vault" autoComplete="off" />{control.pickerAvailable && <button className="vault-picker-button" type="button" onClick={pickVaultDirectory} aria-disabled={openingVault} aria-describedby={openingVault ? "vault-open-waiting" : undefined}><FolderOpen size={14} />{pickingVaultDirectory ? "Choosing..." : "Choose folder"}</button>}</span></label><label>Passphrase<input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} placeholder="Enter passphrase" autoComplete="current-password" aria-describedby="vault-passphrase-consequence" /></label><label className="vault-create-choice"><input type="checkbox" checked={makeVault} onChange={(event) => setMakeVault(event.target.checked)} />Make a new vault in that folder</label><p className="vault-passphrase-consequence" id="vault-passphrase-consequence">This opens the vault in the folder you name. If there is none there, nothing is made unless you say so above — a folder named by mistake would otherwise look like an empty vault. Your passphrase is the only key to it. It is not stored anywhere, it cannot be reset, and there is no recovery phrase. If you lose it, everything in this vault is lost with it.</p><button className="secondary-button vault-open-button" type="submit" aria-disabled={openingVault} aria-describedby={openingVault ? "vault-passphrase-consequence vault-open-waiting" : "vault-passphrase-consequence"}>{openingVault ? "Opening vault..." : makeVault ? "Make and open vault" : "Open local vault"}</button>{openingVault ? <span className="action-explanation" id="vault-open-waiting">Your vault is answering the last request. Pressing again does nothing until it has.</span> : null}</form> : <span className="vault-host-note">Preview mode. A desktop host bridge will enable local vault opening.</span>}
      </div>
      <nav id="primary-navigation" aria-label="Main navigation"><div className="nav-label">Navigate</div>{destinations.map((item) => {
        // What the engine's own registry says about this place, said beside
        // it. Nothing here decides it, and a destination whose standing has
        // not been asked for carries no mark: a mark on everything while an
        // answer is on its way is a mark that stops meaning anything.
        const standing = standingOf(session.description.registry, item.id);
        const said = standingCopy[standing];
        return <button key={item.id} className={session.destination === item.id ? "nav-item active" : "nav-item"} aria-current={session.destination === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><span><strong>{item.label}</strong><small>{item.eyebrow}</small></span>{said ? <span className="nav-standing">{said}</span> : null}</button>;
      })}</nav>
      <div className="sidebar-footer"><div className="privacy-lock"><Info aria-hidden="true" size={16} /><span>Local source</span></div><p>Every vault this app opens, the sample one included, is opened through the local desktop host on this machine.</p></div>
    </aside>
    <main className="main-content" inert={Boolean(evidenceSelection) || conversationOpen || (isNarrow && mobileNav) ? true : undefined}>
      <header className="topbar"><button ref={navigationTriggerRef} id="mobile-navigation-trigger" className="icon-button mobile-menu" onClick={openNavigation} aria-label="Open navigation" aria-controls="primary-navigation-drawer" aria-expanded={isNarrow ? mobileNav : false}><Menu size={20} /></button><div className="breadcrumbs"><span>OrionViva</span><ChevronRight size={14} /><strong>{pageCopy[session.destination].title}</strong></div><button className="ask-button" onClick={() => setOverlay({ kind: "conversation", requestId: session.requestId })}><Sparkles size={16} />Ask Viva</button></header>
      <StatusNotice notice={session.notice} onDismiss={() => control.setNotice(null)} icons={noticeIcons} dismissIcon={<X size={15} />} />
      <div className="content-wrap"><div className="page-heading"><div><div className="kicker">{pageCopy[session.destination].intro}</div><h1 ref={pageTitleRef} id="page-title" tabIndex={-1}>{pageCopy[session.destination].title}</h1></div>{session.destination !== "trust" && <div className="page-actions"><button className="primary-button" onClick={openDocuments}><FilePlus2 size={17} />Go to documents</button></div>}</div>
        <SourceDisclosure disclosure={surface.disclosure} />
        {session.phase === "reading" ? <section className="feature-panel" aria-live="polite"><div className="empty-state"><strong>Reading private vault</strong><span>Reading available surfaces from this device…</span></div></section> : <FeatureBoundary key={`destination-${session.requestId}-${session.destination}`} resetKey={`${session.requestId}-${session.destination}`}>
          {session.destination === "overview" && <Overview result={surface.overview} reviewResult={surface.review} activityResult={surface.activity} selectedAccount={session.selectedAccount} showVerificationDetails={proofPreference.showVerificationDetails} onSelectAccount={control.selectAccount} onOpenReviewQuestion={openReviewQuestion} onNavigate={navigate} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onInspectDocument={inspectOverviewDocument} onInspectAccount={inspectOverviewAccount} onAskViva={control.askAvailable ? () => setOverlay({ kind: "conversation", requestId: session.requestId }) : null} onSetAsideFinding={control.findingActionsAvailable ? (findingId) => void control.setAsideFinding(findingId) : null} settingAsideFindingId={control.settingAsideFindingId} onExploreSample={openSampleVault} />}
          {session.destination === "accounts" && <Accounts result={surface.overview} selectedAccount={session.selectedAccount} showVerificationDetails={proofPreference.showVerificationDetails} onSelectAccount={control.selectAccount} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onExploreSample={openSampleVault} />}
          {session.destination === "documents" && <Documents result={surface.documents} selectedDocument={session.selectedDocument} capture={control.captureAvailable ? { state: session.captureAction, onChoose: control.filePickerAvailable ? () => void chooseDocuments() : null, job: capturedJob, cancel: session.cancelAction, onStop: (jobId: string) => void control.cancelJob(jobId) } : null} rescan={control.captureAvailable ? { state: session.rescanAction, onRescan: () => void control.rescanDocuments() } : null} onSelectDocument={control.selectDocument} onOpenEvidence={openEvidenceDocument} onExploreSample={openSampleVault} />}
          {session.destination === "review" && <Review result={surface.review} selectedQueue={session.selectedQueue} onSelectQueue={control.selectQueue} actions={{ state: session.reviewAction, onAnswer: answerQuestion, onConfirm: confirmProposal, onDecline: declineQuestion }} />}
          {session.destination === "activity" && <Activity result={surface.activity} correction={control.activityCorrectionAvailable ? { state: session.activityAction, onAssignCategory: (movementId, categoryId) => void control.assignActivityCategory(movementId, categoryId), onReplaceTags: (movementId, tagIds) => void control.replaceActivityTags(movementId, tagIds), onConfirmTransfer: (movementId, counterpartId) => void control.confirmActivityTransfer(movementId, counterpartId), onRejectTransfer: (movementId) => void control.rejectActivityTransfer(movementId), onUnlinkTransfer: (movementId, counterpartId) => void control.unlinkActivityTransfer(movementId, counterpartId) } : null} onOpenEvidence={openEvidenceDocument} />}
          {session.destination === "trust" && <Trust result={surface.trust} identity={session.description.identity} lifecycle={session.description.lifecycle} displayPreference={{ showVerificationDetails: proofPreference.showVerificationDetails, onChange: proofPreference.setShowVerificationDetails }} transfer={control.transferAvailable ? { state: session.transferAction, onExport: (archive: string) => void control.exportVault(archive), onRestore: (archive: string, directory: string, passphrase: string) => void control.restoreVault(archive, directory, passphrase) } : null} settings={control.settingsAvailable ? { settings: session.settings, state: session.settingsAction, onPropose: (kind, fields) => void control.proposeSettings(kind, fields), onConfirm: (kind, fields, digest, key) => void control.confirmSettings(kind, fields, digest, key) } : null} maintenance={control.trustAvailable ? { state: session.trustAction, onRun: (spend: boolean) => void control.runMaintenance(spend), onDiagnose: (file: string) => void control.writeDiagnostic(file) } : null} />}
        </FeatureBoundary>}
      </div>
    </main>
    {conversationOpen && <ConversationDialogShell resetKey={`${session.requestId}-conversation`} drawerRef={conversationDrawerRef} closeRef={conversationCloseRef} onDismiss={conversationDialog.dismissAndRestore}><ConversationDrawer result={surface.conversation} selectedPrompt={session.selectedPrompt} onSelectPrompt={control.selectPrompt} ask={control.askAvailable ? { state: session.askAction, onAsk: (question: string, mirrored: boolean) => void control.askViva(question, mirrored) } : null} /></ConversationDialogShell>}
    {evidenceSelection && <EvidenceDrawer snapshot={surface} selection={evidenceSelection} drawerRef={evidenceDrawerRef} closeRef={evidenceCloseRef} onDismiss={evidenceDialog.dismissAndRestore} onOpenDocument={(link) => openEvidenceDocument(link, true)} renderEvidenceBadge={(grade) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />} />}
  </div>;
}
