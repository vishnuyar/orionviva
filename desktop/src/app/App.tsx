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
import type { Destination, EvidenceLink, SurfaceMode } from "../surface/types";
import { destinations } from "./navigation";
import { useResponsiveNavigation } from "./useResponsiveNavigation";
import { useEvidenceDialog } from "./useEvidenceDialog";
import { useSurfaceSession } from "./useSurfaceSession";

const pageCopy: Record<Destination, { title: string; intro: string }> = {
  overview: { title: "Your financial picture", intro: "A quiet view of what is known, what is pending, and what still needs a human decision." },
  accounts: { title: "Accounts", intro: "Each account speaks in its own terms, with measurement dates shown rather than implied." },
  activity: { title: "Activity", intro: "Movements, their supplied context, and the evidence behind each displayed figure." },
  documents: { title: "Documents", intro: "Capture comes first. Reading and posting stay separate." },
  review: { title: "Review", intro: "One quiet place to inspect questions returned by the current read." },
  trust: { title: "Trust", intro: "What this preview can establish, what is unavailable, and which capabilities are not connected." },
};
type Overlay = null | { kind: "navigation" } | { kind: "conversation"; requestId: number; mode: SurfaceMode } | { kind: "evidence"; selection: { figureId: string; requestId: number; mode: SurfaceMode } };
type PendingDocumentFocus =
  | { target: "document"; documentId: string; requestId: number; mode: SurfaceMode; nonce: number }
  | { target: "capture"; requestId: number; mode: SurfaceMode; nonce: number };
type PendingReviewFocus = { requestId: number; mode: SurfaceMode; questionId: string; nonce: number };

export function ConversationDialogShell({ mode, resetKey, drawerRef, closeRef, onDismiss, children }: { mode: SurfaceMode; resetKey: string; drawerRef: RefObject<HTMLElement | null>; closeRef: RefObject<HTMLButtonElement | null>; onDismiss: () => void; children: ReactNode }) {
  return <><div className="conversation-backdrop" aria-hidden="true" onClick={onDismiss} /><aside ref={drawerRef} id="viva-conversation-drawer" className="conversation-drawer" role="dialog" aria-modal="true" aria-labelledby="viva-conversation-title" aria-describedby="viva-conversation-description" tabIndex={-1}><header className="conversation-topline"><div><div className="detail-panel-label">{mode === "demo" ? "Sample conversation" : "Supplied conversation view"}</div><h2 id="viva-conversation-title">Viva conversation</h2><p id="viva-conversation-description">{mode === "demo" ? "These fictional turns demonstrate citations and refusals. Selecting a sample prompt does not send it." : "This read-only drawer shows only conversation fields supplied to the interface. It cannot accept or send a prompt."}</p></div><button ref={closeRef} className="conversation-close" type="button" onClick={onDismiss} aria-label="Close Viva conversation"><X size={18} /></button></header><FeatureBoundary resetKey={resetKey}>{children}</FeatureBoundary></aside></>;
}

export function App() {
  const control = useSurfaceSession();
  const { session } = control;
  const surface = session.snapshot;
  const [vaultDirectory, setVaultDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [pickingVaultDirectory, setPickingVaultDirectory] = useState(false);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [pendingDocumentFocus, setPendingDocumentFocus] = useState<PendingDocumentFocus | null>(null);
  const [pendingReviewFocus, setPendingReviewFocus] = useState<PendingReviewFocus | null>(null);
  const pendingFocusNonce = useRef(0);
  const activePendingFocusNonce = useRef<number | null>(null);
  const reviewFocusNonce = useRef(0);
  const activeReviewFocusNonce = useRef<number | null>(null);
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
  const evidenceSelection = overlay?.kind === "evidence" && overlay.selection.requestId === session.requestId && overlay.selection.mode === surface.mode ? overlay.selection : null;
  const conversationSelection = overlay?.kind === "conversation" && overlay.requestId === session.requestId && overlay.mode === surface.mode ? overlay : null;
  const conversationOpen = Boolean(conversationSelection);
  const evidenceDialog = useEvidenceDialog({ open: Boolean(evidenceSelection), drawerRef: evidenceDrawerRef, initialFocusRef: evidenceCloseRef, pageTitleRef, onDismiss: () => setOverlay(null) });
  const conversationDialog = useEvidenceDialog({ open: conversationOpen, drawerRef: conversationDrawerRef, initialFocusRef: conversationCloseRef, pageTitleRef, onDismiss: () => setOverlay(null) });

  useEffect(() => { if (overlay?.kind === "evidence" && !evidenceSelection) setOverlay(null); }, [evidenceSelection, overlay]);
  useEffect(() => { if (overlay?.kind === "conversation" && !conversationSelection) setOverlay(null); }, [conversationSelection, overlay]);

  useEffect(() => {
    if (!pendingDocumentFocus) return undefined;
    if (session.requestId !== pendingDocumentFocus.requestId || surface.mode !== pendingDocumentFocus.mode || session.destination !== "documents" || (pendingDocumentFocus.target === "document" && session.selectedDocument !== pendingDocumentFocus.documentId)) {
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
  }, [pendingDocumentFocus, session.destination, session.requestId, session.selectedDocument, surface.mode]);

  useEffect(() => {
    if (!pendingReviewFocus) return undefined;
    if (session.requestId !== pendingReviewFocus.requestId || surface.mode !== pendingReviewFocus.mode || session.destination !== "review" || session.selectedQueue !== pendingReviewFocus.questionId) {
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
  }, [pendingReviewFocus, session.destination, session.requestId, session.selectedQueue, surface.mode]);

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
  function addDocument() {
    if (surface.mode !== "demo") return;
    control.setNotice("Opened the fictional sample document journey. No file was selected, no vault event was written, no model call was made, and nothing was sent.");
    setPendingDocumentFocus({ target: "capture", requestId: session.requestId, mode: surface.mode, nonce: ++pendingFocusNonce.current });
    control.navigate("documents");
  }
  function resetDemoVault() { evidenceDialog.cancelPendingRestore(); conversationDialog.cancelPendingRestore(); control.resetDemo(); setOverlay(null); }
  function openReviewQuestion(questionId: string) {
    control.selectQueue(questionId);
    control.navigate("review");
    setPendingReviewFocus({ requestId: session.requestId, mode: surface.mode, questionId, nonce: ++reviewFocusNonce.current });
  }
  function openFigure(figureId: string) { setOverlay({ kind: "evidence", selection: { figureId, requestId: session.requestId, mode: surface.mode } }); }
  function openEvidenceDocument(link: EvidenceLink, fromDrawer = false) {
    const target = resolveEvidenceTarget(surface.documents, link.targetDocumentId);
    const label = link.label.trim() || "Source label unavailable";
    if (target.state === "missing_identity") { control.setNotice("This evidence reference does not include a document identity."); return; }
    if (target.state === "documents_unavailable") { control.setNotice("Documents are not available in the current vault read."); return; }
    if (target.state === "missing_document") { control.setNotice(`The source document “${label}” is not present in the current vault read.`); return; }
    if (target.state === "conflicted_identity") { control.setNotice(`More than one document has the identity “${link.targetDocumentId}” in the current vault read. No document was opened.`); return; }
    control.selectDocument(target.document.id); control.navigate("documents");
    setPendingDocumentFocus({ target: "document", documentId: target.document.id, requestId: session.requestId, mode: surface.mode, nonce: ++pendingFocusNonce.current });
    if (fromDrawer) evidenceDialog.closeWithoutRestore();
  }
  async function openVault(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!control.hostAvailable || !vaultDirectory.trim() || !passphrase) { control.setNotice("Enter a vault directory and passphrase to open a local vault."); return; }
    control.setNotice(null);
    await control.openVault(vaultDirectory.trim(), passphrase);
    setPassphrase("");
  }
  async function pickVaultDirectory() {
    if (!control.pickerAvailable || pickingVaultDirectory || openingVault) return;
    setPickingVaultDirectory(true); control.setNotice(null);
    try { const selected = await control.pickVaultDirectory(); if (selected) setVaultDirectory(selected); }
    catch { control.setNotice("The folder picker could not be opened. Enter the vault path manually."); }
    finally { setPickingVaultDirectory(false); }
  }

  return <div className="app-shell">
    {isNarrow && mobileNav && <div className="navigation-backdrop" aria-hidden="true" onClick={() => closeNavigation()} />}
    <aside ref={navigationDrawerRef} id="primary-navigation-drawer" className={mobileNav ? "sidebar sidebar-open" : "sidebar"} role={isNarrow && mobileNav ? "dialog" : undefined} aria-modal={isNarrow && mobileNav ? true : undefined} aria-labelledby={isNarrow && mobileNav ? "primary-navigation-title" : undefined} aria-hidden={isNarrow ? !mobileNav : undefined} inert={Boolean(evidenceSelection) || conversationOpen || (isNarrow && !mobileNav) ? true : undefined} tabIndex={-1}>
      <h2 className="visually-hidden" id="primary-navigation-title">Main navigation</h2>
      <div className="brand-row"><div className="brand-mark">O</div><div><div className="brand-name">OrionViva</div><div className="brand-subtitle">Private financial picture</div></div><button ref={navigationCloseRef} className="icon-button mobile-close" onClick={() => closeNavigation()} aria-label="Close navigation"><X size={18} /></button></div>
      <div className="preview-badge"><span className="status-dot" />Preview build</div>
      <div className="vault-source-card">
        <div className="vault-source-topline"><span>Vault source</span><button className="text-button" onClick={resetDemoVault}>{session.source.mode === "demo" ? "Reset sample vault" : "Open sample vault"}</button></div>
        <strong>{session.source.label}</strong><span className="vault-source-subtitle">{session.source.mode === "demo" ? "Fictional sample data" : "Opened on this device"}</span><span className="vault-source-boundary">{session.source.mode === "demo" ? "Sample data boundary" : "Read-only vault surfaces"}</span><p>{session.source.description}</p>
        {control.hostAvailable ? <form className="vault-open-form" onSubmit={openVault}><label>Vault directory<span className="vault-directory-control"><input value={vaultDirectory} onChange={(event) => setVaultDirectory(event.target.value)} placeholder="/path/to/vault" autoComplete="off" />{control.pickerAvailable && <button className="vault-picker-button" type="button" onClick={pickVaultDirectory} disabled={pickingVaultDirectory || openingVault}><FolderOpen size={14} />{pickingVaultDirectory ? "Choosing..." : "Choose folder"}</button>}</span></label><label>Passphrase<input type="password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} placeholder="Enter passphrase" autoComplete="current-password" /></label><button className="secondary-button vault-open-button" type="submit" disabled={openingVault || pickingVaultDirectory}>{openingVault ? "Opening vault..." : "Open local vault"}</button></form> : <span className="vault-host-note">Preview mode. A desktop host bridge will enable local vault opening.</span>}
      </div>
      <nav id="primary-navigation" aria-label="Main navigation"><div className="nav-label">Navigate</div>{destinations.map((item) => <button key={item.id} className={session.destination === item.id ? "nav-item active" : "nav-item"} aria-current={session.destination === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><span><strong>{item.label}</strong><small>{item.eyebrow}</small></span></button>)}</nav>
      <div className="sidebar-footer"><div className="privacy-lock"><Info aria-hidden="true" size={16} /><span>{surface.mode === "demo" ? "Fictional sample" : "Local source"}</span></div><p>{surface.mode === "demo" ? "This fictional sample is bundled with the app. Complete outbound history is not available." : "This vault was opened through the local desktop host. Complete outbound history is not available."}</p></div>
    </aside>
    <main className="main-content" inert={Boolean(evidenceSelection) || conversationOpen || (isNarrow && mobileNav) ? true : undefined}>
      <header className="topbar"><button ref={navigationTriggerRef} id="mobile-navigation-trigger" className="icon-button mobile-menu" onClick={openNavigation} aria-label="Open navigation" aria-controls="primary-navigation-drawer" aria-expanded={isNarrow ? mobileNav : false}><Menu size={20} /></button><div className="breadcrumbs"><span>OrionViva</span><ChevronRight size={14} /><strong>{pageCopy[session.destination].title}</strong></div><button className="ask-button" onClick={() => setOverlay({ kind: "conversation", requestId: session.requestId, mode: surface.mode })}><Sparkles size={16} />Ask Viva</button></header>
      <StatusNotice notice={session.notice} onDismiss={() => control.setNotice(null)} statusIcon={<Check size={16} />} dismissIcon={<X size={15} />} />
      <div className="content-wrap"><div className="page-heading"><div><div className="kicker">{pageCopy[session.destination].intro}</div><h1 ref={pageTitleRef} id="page-title" tabIndex={-1}>{pageCopy[session.destination].title}</h1></div>{session.destination !== "trust" && <div className="page-actions"><button className="primary-button" onClick={addDocument} disabled={surface.mode === "live"} aria-describedby={surface.mode === "live" ? "document-add-unavailable" : undefined}><FilePlus2 size={17} />{surface.mode === "demo" ? "View sample document journey" : "Add document"}</button>{surface.mode === "live" && <span className="action-explanation" id="document-add-unavailable">Document capture is not connected for this vault.</span>}</div>}</div>
        <SourceDisclosure mode={surface.mode} disclosure={surface.disclosure} />
        {session.phase === "reading" ? <section className="feature-panel" aria-live="polite"><div className="empty-state"><strong>Reading private vault</strong><span>Reading available surfaces from this device…</span></div></section> : <FeatureBoundary key={`destination-${session.requestId}-${session.destination}`} resetKey={`${session.requestId}-${session.destination}`}>
          {session.destination === "overview" && <Overview result={surface.overview} reviewResult={surface.review} mode={surface.mode} selectedAccount={session.selectedAccount} onSelectAccount={control.selectAccount} onOpenReviewQuestion={openReviewQuestion} onNavigate={navigate} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onExploreSample={resetDemoVault} />}
          {session.destination === "accounts" && <Accounts result={surface.overview} mode={surface.mode} selectedAccount={session.selectedAccount} onSelectAccount={control.selectAccount} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} onExploreSample={resetDemoVault} />}
          {session.destination === "documents" && <Documents result={surface.documents} mode={surface.mode} selectedDocument={session.selectedDocument} onSelectDocument={control.selectDocument} onOpenEvidence={openEvidenceDocument} onExploreSample={resetDemoVault} />}
          {session.destination === "review" && <Review result={surface.review} mode={surface.mode} selectedQueue={session.selectedQueue} onSelectQueue={control.selectQueue} onOpenEvidence={openEvidenceDocument} />}
          {session.destination === "activity" && <Activity result={surface.activity} mode={surface.mode} onOpenEvidence={openEvidenceDocument} onOpenFigure={openFigure} />}
          {session.destination === "trust" && <Trust result={surface.trust} mode={surface.mode} />}
        </FeatureBoundary>}
      </div>
    </main>
    {conversationOpen && <ConversationDialogShell mode={surface.mode} resetKey={`${session.requestId}-${surface.mode}-conversation`} drawerRef={conversationDrawerRef} closeRef={conversationCloseRef} onDismiss={conversationDialog.dismissAndRestore}><ConversationDrawer result={surface.conversation} mode={surface.mode} selectedPrompt={session.selectedPrompt} onSelectPrompt={control.selectPrompt} /></ConversationDialogShell>}
    {evidenceSelection && <EvidenceDrawer snapshot={surface} selection={evidenceSelection} drawerRef={evidenceDrawerRef} closeRef={evidenceCloseRef} onDismiss={evidenceDialog.dismissAndRestore} onOpenDocument={(link) => openEvidenceDocument(link, true)} renderEvidenceBadge={(grade) => <EvidenceBadge grade={grade.grade} label={grade.label} description={grade.description} />} />}
  </div>;
}
