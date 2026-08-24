import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { ProofCaveats, ProofQualifications } from "../../components/ProofCaveats";
import { identifiedRows, resolveStableSelection, type StableSelection } from "../../app/selection";
import { accountEvidenceFigure, showCompactProof } from "../../surface/evidence";
import type { AccountView, EvidenceLink, FeatureResult, OverviewData } from "../../surface/types";

function accountName(account: AccountView) {
  return account.name.trim() ? account.name : "Account name was not supplied by this overview read.";
}

function accountKind(account: AccountView) {
  return account.kind.trim() ? account.kind : "Account kind was not supplied by this overview read.";
}

function AccountDetail({ selection, showVerificationDetails, onOpenEvidence, onOpenFigure }: { selection: StableSelection<AccountView>; showVerificationDetails: boolean; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void }) {
  if (selection.state === "ready") {
    const account = selection.item;
    const figure = accountEvidenceFigure(account);
    const showProof = showCompactProof(account.proofPresentation, showVerificationDetails);
    return <aside className="detail-panel" aria-labelledby="selected-account-title"><div className="detail-panel-label">Selected account</div><h3 id="selected-account-title" tabIndex={-1}>{accountName(account)}</h3><Figure figure={figure} onOpenEvidence={onOpenFigure} className="selected-account-figure" />{account.coverage && <p>{account.coverage}</p>}<ProofCaveats caveats={account.caveats ?? []} /><div className="detail-panel-grid"><div><span>Kind</span><strong>{accountKind(account)}</strong></div>{showProof ? <div className="compact-proof"><span>Grade</span><strong>{figure.grade.label}: {figure.grade.description}</strong></div> : null}<div><span>Measured</span><strong>{account.asOf || "Not supplied"}</strong></div>{showProof ? <div className="compact-proof"><span>Note</span><strong>{account.note || "Not supplied"}</strong></div> : null}</div><ProofQualifications proof={account.proofPresentation} alreadyRendered={[figure.grade.label, figure.grade.description, account.note ?? "", account.coverage ?? "", ...(account.caveats ?? [])]} /><ProofLinks label="Supporting documents" links={account.evidenceLinks} onOpen={onOpenEvidence} /></aside>;
  }
  const title = selection.state === "missing" ? "Selected account unavailable" : "Account selection unavailable";
  const detail = selection.state === "missing" ? "The selected account is no longer present in this accounts read."
    : selection.state === "conflicted_identity" ? "More than one account uses the selected identity, so the interface will not choose between them."
      : "This accounts read contains rows, but none has a unique nonblank account ID.";
  const requestedId = selection.state === "missing" || selection.state === "conflicted_identity" ? selection.requestedId : "";
  return <aside className="detail-panel" aria-labelledby="selected-account-title"><div className="detail-panel-label">Selected account</div><h3 id="selected-account-title" tabIndex={-1}>{title}</h3><p>{detail}</p>{requestedId && <dl><div><dt>Requested account ID</dt><dd>{requestedId}</dd></div></dl>}</aside>;
}

export function Accounts({ result, selectedAccount, showVerificationDetails, onSelectAccount, onOpenEvidence, onOpenFigure, onExploreSample }: { result: FeatureResult<OverviewData>; selectedAccount: string; showVerificationDetails: boolean; onSelectAccount: (id: string) => void; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void; onExploreSample: () => void }) {
  return <PanelStateView result={result} copy={{ partial: "Some account details are unavailable. Available accounts are shown below.", needsInput: "Some accounts need more information. Available account details are shown below.", unavailable: { title: "Accounts unavailable", detail: "Account details are not available in this build." }, failed: { title: "Accounts could not be read", detail: "The accounts section could not be read. The private vault is still open." } }}>{(data) => {
    if (!data.accounts.length) return <section className="feature-panel"><div className="empty-state"><strong>No accounts yet</strong><span>No accounts are visible in this vault yet. Add a statement, or open the sample vault to see what one looks like when it is full.</span><button type="button" className="secondary-button" onClick={onExploreSample}>Open the sample vault</button></div></section>;
    const selection = resolveStableSelection(data.accounts, selectedAccount);
    return <section className="feature-panel"><div className="feature-icon">◎</div><h2>Accounts in this read</h2><p>Each account is shown independently with the fields supplied to this view.</p>
      <div className="account-detail-list">{identifiedRows(data.accounts, "accounts-list").map((row) => {
        if (row.state === "missing_identity") return <div className="detail-row identity-state" key={row.key}><div><strong>Account identity unavailable</strong><span>One or more accounts have no stable account ID. They cannot be selected or opened as evidence.</span></div></div>;
        if (row.state === "conflicted_identity") return <div className="detail-row identity-state" key={row.key}><div><strong>Account identity conflicted</strong><span>More than one account uses this account ID. The interface will not choose between them or open their evidence.</span><dl><div><dt>Account ID</dt><dd>{row.id}</dd></div></dl></div></div>;
        const account = row.item;
        const pressed = selection.state === "ready" && selection.item.id === account.id;
        const showProof = showCompactProof(account.proofPresentation, showVerificationDetails);
        return <div className="detail-row" key={row.key}><button type="button" className={pressed ? "detail-row-button active" : "detail-row-button"} aria-pressed={pressed} onClick={() => onSelectAccount(account.id)}><div><strong>{accountName(account)}</strong><span>{accountKind(account)}{showProof && account.note ? ` · ${account.note}` : ""}</span></div></button><div className="detail-figure"><Figure figure={accountEvidenceFigure(account)} onOpenEvidence={onOpenFigure} />{account.asOf && <span>{account.asOf}</span>}</div><ProofQualifications proof={account.proofPresentation} alreadyRendered={[account.note ?? "", ...(account.caveats ?? [])]} /><ProofCaveats caveats={account.caveats ?? []} /></div>;
      })}</div>
      <AccountDetail selection={selection} showVerificationDetails={showVerificationDetails} onOpenEvidence={onOpenEvidence} onOpenFigure={onOpenFigure} />
    </section>;
  }}</PanelStateView>;
}
