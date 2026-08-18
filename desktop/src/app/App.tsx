import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleHelp,
  FilePlus2,
  FolderOpen,
  LockKeyhole,
  Menu,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { demoState, destinations, nextDestination, type Destination, type DemoState } from "./model";
import { createBridgeReadySource, readSurface, syntheticSurfaceData } from "./data";
import { createDetectedBridgeClient, hasHostBridge, type BridgeClient } from "./bridge-client";

const pageCopy: Record<Destination, { title: string; intro: string }> = {
  overview: { title: "Your financial picture", intro: "A quiet view of what is known, what is pending, and what still needs a human decision." },
  accounts: { title: "Accounts", intro: "Each account speaks in its own terms, with measurement dates shown rather than implied." },
  activity: { title: "Activity", intro: "Movement, provenance, and the small tail of things worth checking." },
  documents: { title: "Documents", intro: "Capture comes first. Reading and posting stay separate." },
  review: { title: "Review", intro: "A ranked front door for the questions that need you." },
  trust: { title: "Trust", intro: "What the surface can say, what it cannot, and what stays local." },
};

export function App() {
  const [vaultSource, setVaultSource] = useState(syntheticSurfaceData);
  const [surface, setSurface] = useState<DemoState>(demoState);
  const [hostBridge] = useState<BridgeClient | null>(() => hasHostBridge() ? createDetectedBridgeClient() : null);
  const [vaultDirectory, setVaultDirectory] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [pickingVaultDirectory, setPickingVaultDirectory] = useState(false);
  const [openingVault, setOpeningVault] = useState(false);
  const [destination, setDestination] = useState<Destination>("overview");
  const [notice, setNotice] = useState<string | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState(surface.documents[0].name);
  const [selectedQueue, setSelectedQueue] = useState(surface.queue[0].label);
  const [selectedAccount, setSelectedAccount] = useState(surface.accounts[0].id);
  const [reviewFeedback, setReviewFeedback] = useState("No action taken yet.");
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const [conversationOpen, setConversationOpen] = useState(false);
  const [conversationPrompt, setConversationPrompt] = useState(surface.conversationPrompts[0].label);

  useEffect(() => {
    let alive = true;
    readSurface(vaultSource).then((nextSurface) => {
      if (!alive) {
        return;
      }
      setSurface(nextSurface);
      setSelectedDocument(nextSurface.documents[0]?.name ?? "");
      setSelectedQueue(nextSurface.queue[0]?.label ?? "");
      setSelectedAccount(nextSurface.accounts[0]?.id ?? "");
      setConversationPrompt(nextSurface.conversationPrompts[0]?.label ?? "");
    }).catch(() => {
      if (alive) {
        setNotice("The local vault opened, but its surface data could not be loaded.");
      }
    });
    return () => {
      alive = false;
    };
  }, [vaultSource]);

  function navigate(next: Destination) {
    setDestination((current) => nextDestination(current, next));
    setMobileNav(false);
  }

  function addDocument() {
    setNotice("Document capture is staged locally. Nothing has left this device.");
    setDestination("documents");
  }

  function resetDemoVault() {
    setVaultSource(syntheticSurfaceData);
    setDestination("overview");
    setNotice("Demo vault reset to the checked-in fixture snapshot.");
  }

  function refreshReviewFeedback(action: string) {
    setReviewRefresh((value) => value + 1);
    setReviewFeedback(`${action} recorded. The queue refreshed from the synthetic surface.`);
  }

  async function openVault(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hostBridge || !vaultDirectory.trim() || !passphrase) {
      setNotice("Enter a vault directory and passphrase to open a local vault.");
      return;
    }
    setOpeningVault(true);
    setNotice(null);
    try {
      await hostBridge.openVault(vaultDirectory.trim(), passphrase);
      setPassphrase("");
      setVaultSource(createBridgeReadySource(hostBridge));
      setDestination("overview");
      setNotice("Local vault opened. Surface data is now coming from the bridge.");
    } catch {
      setPassphrase("");
      setNotice("The local vault could not be opened. Check the directory and passphrase, then try again.");
    } finally {
      setOpeningVault(false);
    }
  }

  async function pickVaultDirectory() {
    if (!hostBridge?.pickVaultDirectory || pickingVaultDirectory || openingVault) {
      return;
    }
    setPickingVaultDirectory(true);
    setNotice(null);
    try {
      const selected = await hostBridge.pickVaultDirectory();
      if (selected) {
        setVaultDirectory(selected);
      }
    } catch {
      setNotice("The folder picker could not be opened. Enter the vault path manually.");
    } finally {
      setPickingVaultDirectory(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className={mobileNav ? "sidebar sidebar-open" : "sidebar"}>
        <div className="brand-row">
          <div className="brand-mark">O</div>
          <div>
            <div className="brand-name">OrionViva</div>
            <div className="brand-subtitle">Private financial picture</div>
          </div>
          <button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <div className="preview-badge">
          <span className="status-dot" />
          Preview build
        </div>

        <div className="vault-source-card">
          <div className="vault-source-topline">
            <span>Vault source</span>
            <button className="text-button" onClick={resetDemoVault}>
              Reset demo vault
            </button>
          </div>
          <strong>{vaultSource.label}</strong>
          <span className="vault-source-boundary">{vaultSource.boundary === "fixture" ? "Fixture boundary" : "Bridge-ready boundary"}</span>
          <p>{vaultSource.description}</p>
          {hostBridge ? (
            <form className="vault-open-form" onSubmit={openVault}>
              <label>
                Vault directory
                <span className="vault-directory-control">
                  <input
                    value={vaultDirectory}
                    onChange={(event) => setVaultDirectory(event.target.value)}
                    placeholder="/path/to/vault"
                    autoComplete="off"
                  />
                  {hostBridge.pickVaultDirectory && (
                    <button
                      className="vault-picker-button"
                      type="button"
                      onClick={pickVaultDirectory}
                      disabled={pickingVaultDirectory || openingVault}
                    >
                      <FolderOpen size={14} />
                      {pickingVaultDirectory ? "Choosing..." : "Choose folder"}
                    </button>
                  )}
                </span>
              </label>
              <label>
                Passphrase
                <input
                  type="password"
                  value={passphrase}
                  onChange={(event) => setPassphrase(event.target.value)}
                  placeholder="Enter passphrase"
                  autoComplete="current-password"
                />
              </label>
              <button className="secondary-button vault-open-button" type="submit" disabled={openingVault || pickingVaultDirectory}>
                {openingVault ? "Opening vault..." : "Open local vault"}
              </button>
            </form>
          ) : (
            <span className="vault-host-note">Preview mode. A desktop host bridge will enable local vault opening.</span>
          )}
        </div>

        <nav aria-label="Main navigation">
          <div className="nav-label">Navigate</div>
          {destinations.map((item) => (
            <button key={item.id} className={destination === item.id ? "nav-item active" : "nav-item"} onClick={() => navigate(item.id)}>
              <span>
                <strong>{item.label}</strong>
                <small>{item.eyebrow}</small>
              </span>
              {item.id === "review" && <span className="nav-count">{surface.reviewCount}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="privacy-lock">
            <LockKeyhole size={16} />
            <span>Local by default</span>
          </div>
          <p>Your vault and documents stay on this device.</p>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <div className="breadcrumbs">
            <span>OrionViva</span>
            <ChevronRight size={14} />
            <strong>{pageCopy[destination].title}</strong>
          </div>
          <button className="ask-button" onClick={() => setConversationOpen(true)}>
            <Sparkles size={16} />
            Ask Viva
          </button>
        </header>

        {notice && (
          <div className="notice" role="status">
            <Check size={16} />
            <span>{notice}</span>
            <button className="notice-close" onClick={() => setNotice(null)} aria-label="Dismiss notice">
              <X size={15} />
            </button>
          </div>
        )}

        <div className="content-wrap">
          <div className="page-heading">
            <div>
              <div className="kicker">{pageCopy[destination].intro}</div>
              <h1>{pageCopy[destination].title}</h1>
            </div>
            <div className="page-actions">
              <button className="primary-button" onClick={addDocument}>
                <FilePlus2 size={17} />
                Add document
              </button>
            </div>
          </div>

          {destination === "overview" && (
            <Overview
              state={surface}
              selectedAccount={selectedAccount}
              onSelectAccount={setSelectedAccount}
              onNavigate={navigate}
            />
          )}
          {destination === "accounts" && (
            <Accounts
              state={surface}
              selectedAccount={selectedAccount}
              onSelectAccount={setSelectedAccount}
            />
          )}
          {destination === "documents" && (
            <Documents state={surface} selectedDocument={selectedDocument} onSelectDocument={setSelectedDocument} />
          )}
          {destination === "review" && (
            <Review
              state={surface}
              selectedQueue={selectedQueue}
              onSelectQueue={setSelectedQueue}
              onNavigate={navigate}
              reviewFeedback={reviewFeedback}
              reviewRefresh={reviewRefresh}
              onReviewAction={refreshReviewFeedback}
            />
          )}
          {destination === "activity" && <Activity state={surface} onNavigate={navigate} />}
          {destination === "trust" && <Trust state={surface} />}
        </div>
        {conversationOpen && (
          <ConversationDrawer
            state={surface}
            selectedPrompt={conversationPrompt}
            onSelectPrompt={setConversationPrompt}
            onClose={() => setConversationOpen(false)}
          />
        )}
      </main>
    </div>
  );
}

function Overview({
  state,
  selectedAccount,
  onSelectAccount,
  onNavigate,
}: {
  state: DemoState;
  selectedAccount: string;
  onSelectAccount: (name: string) => void;
  onNavigate: (destination: Destination) => void;
}) {
  const activeAccount = state.accounts.find((account) => account.id === selectedAccount) ?? state.accounts[0];
  return (
    <>
      <section className="hero-grid">
        <div className="hero-card">
          <div className="card-topline">
            <span>Net worth</span>
            <EvidenceBadge grade={state.netWorth.grade} />
          </div>
          <div className="hero-amount">{state.netWorth.display}</div>
          <div className="hero-meta">
            <span>Corroborated · {state.netWorth.asOf}</span>
            <button onClick={() => onNavigate("trust")}>
              View evidence <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="sparkline" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </div>
          <div className="figure-footnote">
            <span>{state.netWorth.coverage}</span>
            <small>{state.netWorth.caveats[0]}</small>
          </div>
        </div>

        <div className="coverage-card">
          <div className="card-topline">
            <span>Picture coverage</span>
            <CircleHelp size={16} />
          </div>
          <div className="coverage-number">{state.coverage}</div>
          <div className="coverage-track">
            <span />
          </div>
          <p>{state.corpusCoverage}. The surface is useful, but it does not pretend the vault is complete.</p>
          <div className="coverage-account">
            <div className="detail-panel-label">Selected account</div>
            <button className="coverage-account-title" onClick={() => onNavigate("accounts")}>
              {activeAccount.name}
            </button>
            <div className="coverage-account-meta">
              <span>{activeAccount.kind}</span>
              <span>{activeAccount.gradeLabel}</span>
              <span>{activeAccount.asOf}</span>
            </div>
            <p>{activeAccount.coverage}</p>
          </div>
          <button className="text-button" onClick={() => onNavigate("documents")}>
            See document status <ArrowUpRight size={14} />
          </button>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">One clean picture</div>
            <h2>Account spotlight</h2>
          </div>
          <button className="text-button" onClick={() => onNavigate("accounts")}>
            Open accounts <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="account-grid">
          {state.accounts.map((account) => (
            <button
              className={selectedAccount === account.name ? "account-card account-card-button active" : "account-card account-card-button"}
              key={account.name}
              onClick={() => onSelectAccount(account.id)}
            >
              <div className="account-icon">{account.name.slice(0, 1)}</div>
              <div className="account-copy">
                <div className="account-name">{account.name}</div>
                <div className="account-kind">{account.kind}</div>
                <div className="account-note">
                  <span className={`mini-dot ${account.grade}`} />
                  {account.note}
                </div>
                <div className="account-date">As of {account.asOf}</div>
              </div>
              <div className="account-amount">{account.display}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">What Viva needs</div>
            <h2>Ranked review queue</h2>
          </div>
          <button className="text-button" onClick={() => onNavigate("review")}>
            Open review <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="queue-list">
          {state.queue.map((item, index) => (
            <div className="queue-row" key={item.label}>
              <div className="queue-rank">{index + 1}</div>
              <div className="queue-copy">
                <div className="queue-title">
                  <strong>{item.label}</strong>
                  <span>{item.status}</span>
                </div>
                <p>{item.detail}</p>
              </div>
          <button className="secondary-button" onClick={() => onSelectAccount(state.accounts[index % state.accounts.length].name)}>
            {item.action}
          </button>
        </div>
      ))}
      </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">The places money sits</div>
            <h2>Accounts</h2>
          </div>
          <button className="text-button" onClick={() => onNavigate("accounts")}>
            All accounts <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="account-grid">
          {state.accounts.map((account) => (
            <div className="account-card" key={account.name}>
              <div className="account-icon">{account.name.slice(0, 1)}</div>
              <div className="account-copy">
                <div className="account-name">{account.name}</div>
                <div className="account-kind">{account.kind}</div>
                <div className="account-note">
                  <span className={`mini-dot ${account.grade}`} />
                  {account.note}
                </div>
                <div className="account-date">As of {account.asOf}</div>
              </div>
              <div className="account-amount">{account.display}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">A small, useful tail</div>
            <h2>Recent signals</h2>
          </div>
          <button className="text-button" onClick={() => onNavigate("activity")}>
            Open activity <ArrowUpRight size={14} />
          </button>
        </div>
        <div className="signal-list">
          {state.recent.map((item) => (
            <div className="signal-row" key={item.label}>
              <div className={`signal-icon ${item.tone}`}>{item.tone === "inflow" ? "↑" : item.tone === "outflow" ? "↓" : "!"}</div>
              <div className="signal-copy">
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </div>
              <div className={`signal-value ${item.tone}`}>{item.display}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="quiet-note">
        <ShieldCheck size={18} />
        <div>
          <strong>Nothing is silently inferred.</strong>
          <span>Every figure carries its date, scope, and evidence. Uncertainty stays visible.</span>
        </div>
      </div>
      <div className="corpus-note">
        <span>{state.corpusSource}</span>
        <span>Range {state.currentThrough} · bridge boundary ready, no live vault connected</span>
      </div>
    </>
  );
}

function Accounts({
  state,
  selectedAccount,
  onSelectAccount,
}: {
  state: DemoState;
  selectedAccount: string;
  onSelectAccount: (name: string) => void;
}) {
  const activeAccount = state.accounts.find((account) => account.id === selectedAccount) ?? state.accounts[0];
  return (
    <section className="feature-panel">
      <div className="feature-icon">◎</div>
      <h2>{state.accounts.length} accounts in the demo vault</h2>
      <p>Each account keeps its own meaning and measurement date. A liability would speak as owed, never as a balance.</p>
      <div className="account-detail-list">
        {state.accounts.map((account) => (
          <button
            className={selectedAccount === account.name ? "detail-row detail-row-button active" : "detail-row detail-row-button"}
            key={account.name}
            onClick={() => onSelectAccount(account.id)}
          >
            <div>
              <strong>{account.name}</strong>
              <span>
                {account.kind} · {account.measure} · {account.gradeLabel} · {account.note}
              </span>
            </div>
            <div className="detail-figure">
              <strong>{account.display}</strong>
              <span>{account.asOf}</span>
            </div>
          </button>
        ))}
      </div>
      <div className="detail-panel">
        <div className="detail-panel-label">Selected account</div>
        <h3>{activeAccount.name}</h3>
        <p>{activeAccount.coverage}</p>
        <div className="detail-panel-grid">
          <div>
            <span>Kind</span>
            <strong>{activeAccount.kind}</strong>
          </div>
          <div>
            <span>Grade</span>
            <strong>{activeAccount.gradeLabel}</strong>
          </div>
          <div>
            <span>Measured</span>
            <strong>{activeAccount.asOf}</strong>
          </div>
          <div>
            <span>Note</span>
            <strong>{activeAccount.note}</strong>
          </div>
        </div>
      </div>
    </section>
  );
}

function Documents({
  state,
  selectedDocument,
  onSelectDocument,
}: {
  state: DemoState;
  selectedDocument: string;
  onSelectDocument: (name: string) => void;
}) {
  const activeDocument = state.documents.find((doc) => doc.name === selectedDocument) ?? state.documents[0];

  return (
    <section className="feature-panel">
      <div className="feature-icon">
        <FilePlus2 size={22} />
      </div>
          <h2>Capture before reading</h2>
      <p>Originals are saved privately first. This preview shows the capture, processing, recovery, and outbound steps separately, so nothing is blurred together.</p>
      <div className="journey-band">
        <div className="journey-card">
          <div className="detail-panel-label">Capture queue</div>
          <div className="journey-list">
            {state.captureQueue.map((item) => (
              <div className={`journey-row ${item.state}`} key={item.id}>
                <div>
                  <strong>{item.label}</strong>
                  <span>{item.detail}</span>
                </div>
                <div className="journey-meta">
                  <span>{item.source}</span>
                  <small>{item.note}</small>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="journey-card">
          <div className="detail-panel-label">Processing and recovery</div>
          <div className="journey-list">
            {state.processingJobs.map((job) => (
              <div className={`journey-row ${job.state}`} key={job.id}>
                <div>
                  <strong>{job.label}</strong>
                  <span>{job.detail}</span>
                </div>
                <div className="journey-meta">
                  <span>{job.progress}</span>
                  <small>{job.state === "paused" ? "Recovery resumes on relaunch" : job.state === "done" ? "Finished" : "Running"}</small>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="journey-card">
          <div className="detail-panel-label">Outbound records</div>
          <div className="journey-list">
            {state.outboundRecords.map((record) => (
              <div className={`journey-row ${record.state}`} key={record.id}>
                <div>
                  <strong>{record.label}</strong>
                  <span>{record.detail}</span>
                </div>
                <div className="journey-meta">
                  <span>{record.destination}</span>
                  <small>{record.state}</small>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="detail-split">
        <div className="document-list">
          {state.documents.map((doc) => (
            <button
              className={selectedDocument === doc.name ? "detail-row detail-row-button active" : "detail-row detail-row-button"}
              key={doc.name}
              onClick={() => onSelectDocument(doc.name)}
            >
              <div>
                <strong>{doc.name}</strong>
                <span>
                  {doc.detail} · {doc.source}
                </span>
              </div>
              <span className={`state-pill ${doc.state.toLowerCase()}`}>{doc.state}</span>
            </button>
          ))}
        </div>
        <aside className="detail-panel">
          <div className="detail-panel-label">Selected document</div>
          <h3>{activeDocument.name}</h3>
          <p>{activeDocument.detail}</p>
          <div className="detail-panel-grid">
            <div>
              <span>Source</span>
              <strong>{activeDocument.source}</strong>
            </div>
            <div>
              <span>Length</span>
              <strong>{activeDocument.pages}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{activeDocument.state}</strong>
            </div>
            <div>
              <span>Lifecycle</span>
              <strong>{activeDocument.phaseLabel}</strong>
            </div>
          </div>
          <div className="document-provenance">
            <span>Provenance</span>
            <strong>{activeDocument.provenance}</strong>
          </div>
          <div className="related-evidence">
            <div className="detail-panel-label">Related evidence</div>
            {activeDocument.evidenceLinks.map((link) => (
              <button
                className="text-button related-evidence-button"
                key={link.documentName}
                onClick={() => onSelectDocument(link.documentName)}
              >
                <span>{link.label}</span>
                <small>{link.relation.replace("_", " ")} · {link.page}</small>
              </button>
            ))}
          </div>
          <button className="secondary-button">Open page review</button>
        </aside>
      </div>
      <button className="secondary-button">Choose a local file</button>
    </section>
  );
}

function Review({
  state,
  selectedQueue,
  onSelectQueue,
  onNavigate,
  reviewFeedback,
  reviewRefresh,
  onReviewAction,
}: {
  state: DemoState;
  selectedQueue: string;
  onSelectQueue: (label: string) => void;
  onNavigate: (destination: Destination) => void;
  reviewFeedback: string;
  reviewRefresh: number;
  onReviewAction: (action: string) => void;
}) {
  const activeQueue = state.queue.find((item) => item.label === selectedQueue) ?? state.queue[0];

  return (
    <section className="feature-panel review-panel">
      <div className="feature-icon">
        <CircleHelp size={22} />
      </div>
      <h2>{state.reviewCount} questions are waiting</h2>
      <p>Review is where the product asks for your judgment. A proposal will always wait for an explicit yes.</p>
      <div className="detail-split">
        <div className="queue-list queue-list-compact">
          {state.queue.map((item) => (
            <button
              className={selectedQueue === item.label ? "queue-row queue-row-button active" : "queue-row queue-row-button"}
              key={item.label}
              onClick={() => onSelectQueue(item.label)}
            >
              <div className="queue-rank">{state.queue.indexOf(item) + 1}</div>
              <div className="queue-copy">
                <div className="queue-title">
                  <strong>{item.label}</strong>
                  <span>{item.status}</span>
                </div>
                <p>{item.detail}</p>
              </div>
              <span className="queue-action">{item.action}</span>
            </button>
          ))}
        </div>
        <aside className="detail-panel">
          <div className="detail-panel-label">Selected question</div>
          <h3>{activeQueue.label}</h3>
          <p>{activeQueue.detail}</p>
          <div className="review-action-strip">
            <span className={`review-action-state ${activeQueue.disposition}`}>{activeQueue.disposition}</span>
            <span className={`review-action-outcome ${activeQueue.outcome}`}>{activeQueue.outcome}</span>
          </div>
          <div className="detail-panel-grid">
            <div>
              <span>Type</span>
              <strong>{activeQueue.type}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{activeQueue.status}</strong>
            </div>
            <div>
              <span>Evidence</span>
              <strong>{activeQueue.evidence}</strong>
            </div>
            <div>
              <span>Outcome</span>
              <strong>{activeQueue.outcome}</strong>
            </div>
          </div>
          <div className="review-feedback" role="status" aria-live="polite">
            <strong>Refresh {reviewRefresh}</strong>
            <span>{reviewFeedback}</span>
          </div>
          <div className="review-actions">
            <button className="secondary-button" onClick={() => onReviewAction(`Answer for ${activeQueue.label}`)}>
              Answer
            </button>
            <button className="secondary-button" onClick={() => onReviewAction(`Decline for ${activeQueue.label}`)}>
              Decline
            </button>
            <button className="secondary-button" onClick={() => onReviewAction(`Proposal for ${activeQueue.label}`)}>
              Proposal
            </button>
            <button className="secondary-button" onClick={() => onReviewAction(`Confirmation for ${activeQueue.label}`)}>
              Confirm
            </button>
          </div>
          <button className="secondary-button" onClick={() => onNavigate("documents")}>
            Open document review <ArrowUpRight size={15} />
          </button>
        </aside>
      </div>
    </section>
  );
}

function Activity({ state, onNavigate }: { state: DemoState; onNavigate: (destination: Destination) => void }) {
  return (
    <section className="feature-panel activity-panel">
      <div className="feature-icon">
        <ArrowUpRight size={22} />
      </div>
      <h2>Movement with context</h2>
      <p>The activity lane shows the tail of spending and income, plus the parts that need another look before they can become fact.</p>
      <div className="activity-grid">
        {state.recent.map((item) => (
          <div className="activity-card" key={item.label}>
            <div className={`signal-icon ${item.tone}`}>{item.tone === "inflow" ? "↑" : item.tone === "outflow" ? "↓" : "!"}</div>
            <div>
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
              <small>{item.measure} · {item.provenance}</small>
            </div>
            <strong className={`signal-value ${item.tone}`}>{item.display}</strong>
          </div>
        ))}
      </div>
      <button className="secondary-button" onClick={() => onNavigate("review")}>
        Go to review queue
      </button>
    </section>
  );
}

function Trust({ state }: { state: DemoState }) {
  return (
    <section className="trust-grid">
      {state.trustNotes.map((note) => (
        <div className="trust-card" key={note.title}>
          <ShieldCheck size={20} />
          <strong>{note.title}</strong>
          <span>{note.detail}</span>
        </div>
      ))}
    </section>
  );
}

function ConversationDrawer({
  state,
  selectedPrompt,
  onSelectPrompt,
  onClose,
}: {
  state: DemoState;
  selectedPrompt: string;
  onSelectPrompt: (label: string) => void;
  onClose: () => void;
}) {
  const activePrompt = state.conversationPrompts.find((prompt) => prompt.label === selectedPrompt) ?? state.conversationPrompts[0];
  return (
    <div className="conversation-drawer" role="dialog" aria-modal="true" aria-label="Viva conversation">
      <div className="conversation-topline">
        <div>
          <div className="detail-panel-label">Viva conversation</div>
          <h2>Ask Viva</h2>
        </div>
        <button className="icon-button conversation-close" onClick={onClose} aria-label="Close Viva conversation">
          <X size={18} />
        </button>
      </div>
      <p className="conversation-intro">
        This preview is synthetic and local-only. Viva can surface cited turns and refusals, but there is no live model connection yet.
      </p>
      <div className="conversation-layout">
        <div className="conversation-thread">
          {state.conversationTurns.map((turn) => (
            <div className={turn.speaker === "viva" ? `conversation-turn ${turn.state}` : "conversation-turn user"} key={turn.id}>
              <div className="conversation-turn-meta">
                <strong>{turn.speaker === "viva" ? "Viva" : "You"}</strong>
                <span>{turn.state}</span>
              </div>
              <p>{turn.text}</p>
              {turn.citation && <small>Source: {turn.citation}</small>}
            </div>
          ))}
        </div>
        <aside className="conversation-panel">
          <div className="detail-panel-label">Synthetic prompts</div>
          <div className="conversation-prompt-list">
            {state.conversationPrompts.map((prompt) => (
              <button
                className={selectedPrompt === prompt.label ? "conversation-prompt active" : "conversation-prompt"}
                key={prompt.id}
                onClick={() => onSelectPrompt(prompt.label)}
              >
                <strong>{prompt.label}</strong>
                <span>{prompt.detail}</span>
                <small>{prompt.state}</small>
              </button>
            ))}
          </div>
          <div className="detail-panel">
            <div className="detail-panel-label">Selected prompt</div>
            <h3>{activePrompt.label}</h3>
            <p>{activePrompt.detail}</p>
            <div className="review-action-strip">
              <span className={`review-action-state ${activePrompt.state}`}>{activePrompt.state}</span>
            </div>
            <div className="detail-panel-grid">
              <div>
                <span>State</span>
                <strong>{activePrompt.state}</strong>
              </div>
              <div>
                <span>Turns</span>
                <strong>{state.conversationTurns.length}</strong>
              </div>
              <div>
                <span>Mode</span>
                <strong>Local preview</strong>
              </div>
              <div>
                <span>Safety</span>
                <strong>Refusals stay visible</strong>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function EvidenceBadge({ grade }: { grade: string }) {
  return (
    <span className={`evidence-badge ${grade}`}>
      <span className="mini-dot" />
      {grade === "verified" ? "Verified" : "Corroborated"}
    </span>
  );
}
