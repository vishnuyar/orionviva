import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { identifiedRows, resolveStableSelection, type StableSelection } from "../../app/selection";
import { accountEvidenceFigure } from "../../surface/evidence";
import type { AccountView, EvidenceLink, FeatureResult, OverviewData, SurfaceMode } from "../../surface/types";

function accountName(account: AccountView, mode: SurfaceMode) {
  return account.name.trim() ? account.name : mode === "demo" ? "Sample account name was not authored." : "Account name was not supplied by this overview read.";
}

function accountKind(account: AccountView, mode: SurfaceMode) {
  return account.kind.trim() ? account.kind : mode === "demo" ? "Sample account kind was not authored." : "Account kind was not supplied by this overview read.";
}

function AccountDetail({ selection, mode, onOpenEvidence, onOpenFigure }: { selection: StableSelection<AccountView>; mode: SurfaceMode; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void }) {
  if (selection.state === "ready") {
    const account = selection.item;
    const figure = accountEvidenceFigure(account);
    return <aside className="detail-panel" aria-labelledby="selected-account-title"><div className="detail-panel-label">Selected account</div><h3 id="selected-account-title" tabIndex={-1}>{accountName(account, mode)}</h3><Figure figure={figure} onOpenEvidence={onOpenFigure} className="selected-account-figure" />{account.coverage && <p>{account.coverage}</p>}<div className="detail-panel-grid"><div><span>Kind</span><strong>{accountKind(account, mode)}</strong></div><div><span>Grade</span><strong>{figure.grade.label}: {figure.grade.description}</strong></div><div><span>Measured</span><strong>{account.asOf || "Not supplied"}</strong></div><div><span>Note</span><strong>{account.note || "Not supplied"}</strong></div></div><ProofLinks label="Supporting documents" links={account.evidenceLinks} onOpen={onOpenEvidence} /></aside>;
  }
  const title = selection.state === "missing" ? "Selected account unavailable" : "Account selection unavailable";
  const detail = selection.state === "missing" ? "The selected account is no longer present in this accounts read."
    : selection.state === "conflicted_identity" ? "More than one account uses the selected identity, so the interface will not choose between them."
      : "This accounts read contains rows, but none has a unique nonblank account ID.";
  const requestedId = selection.state === "missing" || selection.state === "conflicted_identity" ? selection.requestedId : "";
  return <aside className="detail-panel" aria-labelledby="selected-account-title"><div className="detail-panel-label">Selected account</div><h3 id="selected-account-title" tabIndex={-1}>{title}</h3><p>{detail}</p>{requestedId && <dl><div><dt>Requested account ID</dt><dd>{requestedId}</dd></div></dl>}</aside>;
}

export function Accounts({ result, mode, selectedAccount, onSelectAccount, onOpenEvidence, onOpenFigure, onExploreSample }: { result: FeatureResult<OverviewData>; mode: SurfaceMode; selectedAccount: string; onSelectAccount: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void; onExploreSample: () => void }) {
  return <PanelStateView result={result} copy={{ partial: "Some account details are unavailable. Available accounts are shown below.", needsInput: "Some accounts need more information. Available account details are shown below.", unavailable: { title: "Accounts unavailable", detail: "Account details are not available in this build." }, failed: { title: "Accounts could not be read", detail: "The accounts section could not be read. The private vault is still open." } }}>{(data) => {
    if (!data.accounts.length) return <section className="feature-panel"><div className="empty-state"><strong>{mode === "demo" ? "No sample accounts" : "No accounts yet"}</strong><span>{mode === "demo" ? "This fictional sample does not include any accounts." : "No accounts are visible in this vault yet. Add a statement when document import is available."}</span>{mode === "live" && <button type="button" className="secondary-button" onClick={onExploreSample}>Explore fictional sample data</button>}</div></section>;
    const selection = resolveStableSelection(data.accounts, selectedAccount);
    return <section className="feature-panel"><div className="feature-icon">◎</div><h2>{mode === "demo" ? "Sample accounts" : "Accounts in this read"}</h2><p>Each account is shown independently with the fields supplied to this view.</p>
      <div className="account-detail-list">{identifiedRows(data.accounts, "accounts-list").map((row) => {
        if (row.state === "missing_identity") return <div className="detail-row identity-state" key={row.key}><div><strong>Account identity unavailable</strong><span>One or more accounts have no stable account ID. They cannot be selected or opened as evidence.</span></div></div>;
        if (row.state === "conflicted_identity") return <div className="detail-row identity-state" key={row.key}><div><strong>Account identity conflicted</strong><span>More than one account uses this account ID. The interface will not choose between them or open their evidence.</span><dl><div><dt>Account ID</dt><dd>{row.id}</dd></div></dl></div></div>;
        const account = row.item;
        const pressed = selection.state === "ready" && selection.item.id === account.id;
        return <div className="detail-row" key={row.key}><button type="button" className={pressed ? "detail-row-button active" : "detail-row-button"} aria-pressed={pressed} onClick={() => onSelectAccount(account.id)}><div><strong>{accountName(account, mode)}</strong><span>{accountKind(account, mode)}{account.note ? ` · ${account.note}` : ""}</span></div></button><div className="detail-figure"><Figure figure={accountEvidenceFigure(account)} onOpenEvidence={onOpenFigure} />{account.asOf && <span>{account.asOf}</span>}</div></div>;
      })}</div>
      <AccountDetail selection={selection} mode={mode} onOpenEvidence={onOpenEvidence} onOpenFigure={onOpenFigure} />
    </section>;
  }}</PanelStateView>;
}
