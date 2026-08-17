import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleHelp,
  FilePlus2,
  LockKeyhole,
  Menu,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { demoState, destinations, nextDestination, type Destination, type DemoState } from "./model";

const pageCopy: Record<Destination, { title: string; intro: string }> = {
  overview: { title: "Your financial picture", intro: "A quiet view of what is known, what is pending, and what still needs a human decision." },
  accounts: { title: "Accounts", intro: "Each account speaks in its own terms, with measurement dates shown rather than implied." },
  activity: { title: "Activity", intro: "Movement, provenance, and the small tail of things worth checking." },
  documents: { title: "Documents", intro: "Capture comes first. Reading and posting stay separate." },
  review: { title: "Review", intro: "A ranked front door for the questions that need you." },
  trust: { title: "Trust", intro: "What the surface can say, what it cannot, and what stays local." },
};

export function App() {
  const [destination, setDestination] = useState<Destination>("overview");
  const [demo] = useState<DemoState>(demoState);
  const [notice, setNotice] = useState<string | null>(null);
  const [mobileNav, setMobileNav] = useState(false);

  function navigate(next: Destination) {
    setDestination((current) => nextDestination(current, next));
    setMobileNav(false);
  }

  function addDocument() {
    setNotice("Document capture is ready for the local bridge. Nothing has left this device.");
    setDestination("documents");
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

        <nav aria-label="Main navigation">
          <div className="nav-label">Navigate</div>
          {destinations.map((item) => (
            <button key={item.id} className={destination === item.id ? "nav-item active" : "nav-item"} onClick={() => navigate(item.id)}>
              <span>
                <strong>{item.label}</strong>
                <small>{item.eyebrow}</small>
              </span>
              {item.id === "review" && <span className="nav-count">{demo.reviewCount}</span>}
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
          <button className="ask-button" onClick={() => setNotice("Viva will open here when the local conversation bridge is connected.")}>
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
            <button className="primary-button" onClick={addDocument}>
              <FilePlus2 size={17} />
              Add document
            </button>
          </div>

          {destination === "overview" && <Overview state={demo} onNavigate={navigate} />}
          {destination === "accounts" && <Accounts state={demo} />}
          {destination === "documents" && <Documents state={demo} />}
          {destination === "review" && <Review state={demo} onNavigate={navigate} />}
          {destination === "activity" && <Activity state={demo} onNavigate={navigate} />}
          {destination === "trust" && <Trust state={demo} />}
        </div>
      </main>
    </div>
  );
}

function Overview({ state, onNavigate }: { state: DemoState; onNavigate: (destination: Destination) => void }) {
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
          <p>The surface is useful, but it does not pretend the vault is complete.</p>
          <button className="text-button" onClick={() => onNavigate("documents")}>
            See document status <ArrowUpRight size={14} />
          </button>
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
              <button className="secondary-button">{item.action}</button>
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
    </>
  );
}

function Accounts({ state }: { state: DemoState }) {
  return (
    <section className="feature-panel">
      <div className="feature-icon">◎</div>
      <h2>Two accounts in the demo vault</h2>
      <p>Each account keeps its own meaning and measurement date. A liability would speak as owed, never as a balance.</p>
      <div className="account-detail-list">
        {state.accounts.map((account) => (
          <div className="detail-row" key={account.name}>
            <div>
              <strong>{account.name}</strong>
              <span>
                {account.kind} · {account.note}
              </span>
            </div>
            <div className="detail-figure">
              <strong>{account.display}</strong>
              <span>{account.asOf}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Documents({ state }: { state: DemoState }) {
  return (
    <section className="feature-panel">
      <div className="feature-icon">
        <FilePlus2 size={22} />
      </div>
      <h2>Capture before reading</h2>
      <p>Originals are saved privately first. This preview has no reader or network connection, so processing waits honestly.</p>
      <div className="document-list">
        {state.documents.map((doc) => (
          <div className="detail-row" key={doc.name}>
            <div>
              <strong>{doc.name}</strong>
              <span>{doc.detail}</span>
            </div>
            <span className={`state-pill ${doc.state.toLowerCase()}`}>{doc.state}</span>
          </div>
        ))}
      </div>
      <button className="secondary-button">Choose a local file</button>
    </section>
  );
}

function Review({ state, onNavigate }: { state: DemoState; onNavigate: (destination: Destination) => void }) {
  return (
    <section className="feature-panel review-panel">
      <div className="feature-icon">
        <CircleHelp size={22} />
      </div>
      <h2>{state.reviewCount} questions are waiting</h2>
      <p>Review is where the product asks for your judgment. A proposal will always wait for an explicit yes.</p>
      <div className="question-card">
        <span className="question-tag">Needs you</span>
        <strong>Can you identify the held May statement page?</strong>
        <span>It may close the remaining coverage gap in your picture.</span>
        <button className="secondary-button" onClick={() => onNavigate("documents")}>
          Open document review <ArrowUpRight size={15} />
        </button>
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

function EvidenceBadge({ grade }: { grade: string }) {
  return (
    <span className={`evidence-badge ${grade}`}>
      <span className="mini-dot" />
      {grade === "verified" ? "Verified" : "Corroborated"}
    </span>
  );
}
