import { ArrowUpRight, CircleHelp } from "lucide-react";
import { identifiedRows, resolveStableSelection } from "../../app/selection";
import { EvidenceBadge } from "../../components/EvidenceBadge";
import { Figure } from "../../components/Figure";
import { PanelStateView } from "../../components/PanelStateView";
import { ProofLinks } from "../../components/ProofLinks";
import { ProofCaveats, ProofQualifications } from "../../components/ProofCaveats";
import { accountEvidenceFigure, netWorthEvidenceFigure, showCompactProof } from "../../surface/evidence";
import type { AccountView, ActivityData, Destination, EvidenceLink, FeatureResult, OverviewData, ReviewData, ReviewView } from "../../surface/types";

// How much of what moved stands beside the picture. The rest is one click
// away, on the screen that is about it.
const RECENT_SIGNALS = 3;

// A field the read did not supply, said one way. There used to be two of each
// of these — one sentence for the sample vault and one for a private one — and
// the sample's said "was not authored", which was true of a fixture and is
// meaningless about a vault. Both vaults are vaults now, so a blank field is a
// blank field.
function accountName(account: AccountView) {
  return account.name.trim() ? account.name : "Account name was not supplied by this overview read.";
}

function accountKind(account: AccountView) {
  return account.kind.trim() ? account.kind : "Account kind was not supplied by this overview read.";
}

function reviewLabel(item: ReviewView) {
  return item.label.trim() ? item.label : "Question text was not supplied by this review read.";
}

export function Overview({ result, reviewResult, activityResult, selectedAccount, showVerificationDetails, onSelectAccount, onOpenReviewQuestion, onNavigate, onOpenEvidence, onOpenFigure, onExploreSample }: { result: FeatureResult<OverviewData>; reviewResult: FeatureResult<ReviewData>; activityResult: FeatureResult<ActivityData>; selectedAccount: string; showVerificationDetails: boolean; onSelectAccount: (id: string) => void; onOpenReviewQuestion: (id: string) => void; onNavigate: (destination: Destination) => void; onOpenEvidence: (link: EvidenceLink) => void; onOpenFigure: (figureId: string) => void; onExploreSample: () => void }) {
  const reviewData = reviewResult.state === "ready" || reviewResult.state === "partial" || reviewResult.state === "needs_input" ? reviewResult.data : null;
  const activityData = activityResult.state === "ready" || activityResult.state === "partial" || activityResult.state === "needs_input" ? activityResult.data : null;
  // A few, not all. The whole list lives on the screen that is about it, and a
  // second full list here would be a second place a person had to check.
  const recent = (activityData?.movements ?? []).slice(0, RECENT_SIGNALS);
  const activitySentence = activityData?.sentence ?? "";
  return <PanelStateView result={result} copy={{ partial: "Some financial-picture details are unavailable. Available details are shown below.", needsInput: "Some parts of the financial picture need more information. Available details are shown below.", unavailable: { title: "Financial picture unavailable", detail: "The financial picture is not available in this build." }, failed: { title: "Financial picture could not be read", detail: "The financial picture could not be read. The private vault is still open." } }}>{(data) => {
    const accountSelection = resolveStableSelection(data.accounts, selectedAccount);
    // The figures the read stood behind and the currencies it kept back, in one
    // order. Two lists each in currency order, concatenated, is not one list in
    // currency order, and the place a missing total would have been is the cue
    // that it is missing.
    const pictureBlocks = [
      ...data.picture.figures.map((figure) => ({ currency: figure.currency, figure, sentence: "" })),
      ...data.picture.withheld.map((kept) => ({ currency: kept.currency, figure: null, sentence: kept.sentence })),
    ].sort((first, second) => (first.currency < second.currency ? -1 : first.currency > second.currency ? 1 : 0));
    // What the picture says where a number would have been, when it has no
    // number to put there.
    const pictureStanding = data.picture.coverage;
    return <>
      <section className="hero-grid">
        {pictureBlocks.length || pictureStanding.trim() ? <div className="hero-card">
          <div className="card-topline"><h2>Net worth</h2></div>
          {/* One block per currency, in currency order, whether the read stood
              behind that currency or kept it back. A currency kept back takes
              the place its figure would have taken and the weight its figure
              would have carried: a refusal at the end of the list, in the size
              of a footnote, reads as a note about the total above it. */}
          {pictureBlocks.length ? <div className="picture-figures">{pictureBlocks.map((block) => (block.figure
            ? <div className="picture-figure" key={block.currency}>
              <Figure figure={netWorthEvidenceFigure(block.figure)} onOpenEvidence={onOpenFigure} className="hero-amount" />
              {showCompactProof(block.figure.proofPresentation, showVerificationDetails) ? <div className="hero-meta compact-proof"><span>{block.figure.gradeDescription}</span><EvidenceBadge grade={block.figure.grade} label={block.figure.gradeLabel} description={block.figure.gradeDescription} /></div> : null}
              <ProofQualifications proof={block.figure.proofPresentation} alreadyRendered={[block.figure.gradeDescription, block.figure.gradeLabel, ...block.figure.caveats, ...block.figure.coverage]} />
              <ProofCaveats caveats={block.figure.caveats} />
              {block.figure.coverage.map((sentence, line) => <p className="picture-citation" key={`${block.currency}-${line}`}>{sentence}</p>)}
              {/* The way in to this figure's evidence, last, where every other
                  figure on this screen puts one. Its words are the read's own,
                  and where the read wrote none there is no row: a control this
                  side had to name would be this side writing what a person
                  reads, and a refusal is the honest answer to that. */}
              {block.figure.evidenceLabel ? <div className="proof-links"><button type="button" className="proof-link" aria-haspopup="dialog" aria-controls="figure-evidence-drawer" onClick={() => onOpenFigure(netWorthEvidenceFigure(block.figure).id)}>{block.figure.evidenceLabel}</button></div> : null}
            </div>
            : <div className="picture-figure picture-withheld" key={block.currency}><p className="picture-standing">{block.sentence}</p></div>))}</div>
            // With nothing to stand behind and nothing kept back, the panel
            // still renders and says so where the number would have been. A
            // blank card says nothing at all, and a person who saw a total
            // yesterday reads that as the product being broken, which is worse
            // and less true than what actually happened. This is the answer,
            // not a thing that went missing, so it is not dressed as one.
            // A sentence, where there is one. Where the read wrote none and
            // stood behind nothing and kept nothing back, the panel does not
            // render: a card holding a heading and nothing else is not
            // silence, it says something is missing or on its way, and that
            // is a claim and a false one. Three declared conditions, and
            // nothing reads a string to choose between them.
            : <div className="picture-empty"><p className="picture-standing">{pictureStanding}</p></div>}
        </div> : null}
        <div className="coverage-card"><div className="card-topline"><span>Picture coverage</span><CircleHelp size={16} /></div>
          {/* The picture says one thing about how far it reaches, in one
              place. Where there is no figure that sentence stands where the
              figure would have been, so the panel never says it twice. */}
          {data.picture.figures.length && data.picture.coverage.trim() ? <p>{data.picture.coverage}</p> : null}
          {/* An account the read could not place under any currency is on no
              card, in no line and in no drawer. The panel counts rather than
              names where the names are already on the screen; this one is on
              no screen, and a name nowhere is not privacy. */}
          {data.picture.unplaced.length ? <ul className="picture-unplaced">{data.picture.unplaced.map((left) => <li key={left.account}><strong>{left.name}</strong><span>{left.sentence}</span></li>)}</ul> : null}
          {accountSelection.state === "ready" ? <div className="coverage-account"><div className="detail-panel-label">Selected account</div><button type="button" className="coverage-account-title" onClick={() => onNavigate("accounts")}>{accountName(accountSelection.item)}</button><div className="coverage-account-meta"><span>{accountKind(accountSelection.item)}</span>{showCompactProof(accountSelection.item.proofPresentation, showVerificationDetails) ? <span className="compact-proof">{accountSelection.item.gradeLabel}</span> : null}{accountSelection.item.asOf && <span>{accountSelection.item.asOf}</span>}</div>{accountSelection.item.coverage && <p>{accountSelection.item.coverage}</p>}<ProofQualifications proof={accountSelection.item.proofPresentation} alreadyRendered={[accountSelection.item.gradeLabel, accountSelection.item.coverage ?? "", ...(accountSelection.item.caveats ?? [])]} /><ProofCaveats caveats={accountSelection.item.caveats ?? []} /></div>
            : data.accounts.length ? <div className="empty-state"><strong>{accountSelection.state === "missing" ? "Selected account unavailable" : "Account selection unavailable"}</strong><span>{accountSelection.state === "missing" ? "The selected account is no longer present in this overview read." : accountSelection.state === "conflicted_identity" ? "More than one account uses the selected identity, so the interface will not choose between them." : "This accounts read contains rows, but none has a unique nonblank account ID."}</span>{(accountSelection.state === "missing" || accountSelection.state === "conflicted_identity") && <small>Requested account ID: {accountSelection.requestedId}</small>}</div>
              : <div className="empty-state"><strong>No accounts yet</strong><span>No accounts are visible in this vault yet. Add a statement, or open the sample vault to see what one looks like when it is full.</span><button type="button" className="secondary-button" onClick={onExploreSample}>Open the sample vault</button></div>}
          <button type="button" className="text-button" onClick={() => onNavigate("documents")}>See document status <ArrowUpRight size={14} /></button>
        </div>
      </section>
      <section className="section-block"><div className="section-heading"><div><div className="section-kicker">One clean picture</div><h2>Account spotlight</h2></div><button type="button" className="text-button" onClick={() => onNavigate("accounts")}>Open accounts <ArrowUpRight size={14} /></button></div>
        <div className="account-grid">{identifiedRows(data.accounts, "overview-accounts").map((row) => {
          if (row.state === "missing_identity") return <div className="account-card identity-state" key={row.key}><strong>Account identity unavailable</strong><span>One or more accounts have no stable account ID. They cannot be selected or opened as evidence.</span></div>;
          if (row.state === "conflicted_identity") return <div className="account-card identity-state" key={row.key}><strong>Account identity conflicted</strong><span>More than one account uses this account ID. The interface will not choose between them or open their evidence.</span><small>Account ID: {row.id}</small></div>;
          const account = row.item;
          const pressed = accountSelection.state === "ready" && accountSelection.item.id === account.id;
          return <div className={pressed ? "account-card active" : "account-card"} key={row.key}><button type="button" className="account-card-button" aria-pressed={pressed} onClick={() => onSelectAccount(account.id)}><div className="account-icon">{account.name.trim().slice(0, 1) || "?"}</div><div className="account-copy"><div className="account-name">{accountName(account)}</div><div className="account-kind">{accountKind(account)}</div>{showCompactProof(account.proofPresentation, showVerificationDetails) ? <div className="account-note compact-proof"><span className={`mini-dot ${account.grade}`} />{account.gradeLabel}{account.note ? ` · ${account.note}` : ""}</div> : null}</div></button><Figure figure={accountEvidenceFigure(account)} onOpenEvidence={onOpenFigure} className="account-amount" /><ProofQualifications proof={account.proofPresentation} alreadyRendered={[account.gradeLabel, account.note ?? "", ...(account.caveats ?? [])]} /><ProofCaveats caveats={account.caveats ?? []} /><ProofLinks label="View source" links={account.evidenceLinks} onOpen={onOpenEvidence} /></div>;
        })}</div>
      </section>
      <section className="section-block"><div className="section-heading"><div><div className="section-kicker">Current review read</div><h2>Review queue</h2></div><button type="button" className="text-button" onClick={() => onNavigate("review")}>Open review <ArrowUpRight size={14} /></button></div><div className="queue-list">{identifiedRows(reviewData?.queue ?? [], "overview-review").map((row) => {
        if (row.state === "missing_identity") return <div className="queue-row identity-state" key={row.key}><div><strong>Question identity unavailable</strong><span>One or more review rows have no stable question ID. They cannot be opened from Overview.</span></div></div>;
        if (row.state === "conflicted_identity") return <div className="queue-row identity-state" key={row.key}><div><strong>Question identity conflicted</strong><span>More than one review row uses this question ID. No question with this identity was opened.</span><small>Question ID: {row.id}</small></div></div>;
        return <div className="queue-row" key={row.key}><div className="queue-copy"><div className="queue-title"><strong>{reviewLabel(row.item)}</strong></div></div><button type="button" className="secondary-button" onClick={() => onOpenReviewQuestion(row.item.id)}>View question</button></div>;
      })}</div></section>
      {/* The tail of what moved, read off the activity surface rather than
          off the picture. It used to be a field on the overview read that only
          the fixture demo ever filled, so on every real vault this block said
          "Activity unavailable" — a sentence about a connection rather than
          about a vault, and false in both. The rows here are the same rows the
          activity screen shows, cut to a few. */}
      <section className="section-block"><div className="section-heading"><div><div className="section-kicker">A small, useful tail</div><h2>Recent signals</h2></div><button type="button" className="text-button" onClick={() => onNavigate("activity")}>Open activity <ArrowUpRight size={14} /></button></div><div className="signal-list">{recent.length ? recent.map((movement) => <div className="signal-row" key={movement.id}><div className="signal-icon supplied">•</div><div className="signal-copy"><strong>{movement.description || "No description was recorded for this movement."}</strong><span>{movement.date} · {movement.account}</span></div><div className="signal-value"><strong>{movement.display}</strong><small>{movement.direction === "in" ? "in" : "out"}</small></div></div>)
        : <div className="empty-state"><strong>Nothing has moved in this read</strong><span>{activitySentence || "The activity read is not available beside this picture."}</span></div>}</div></section>
    </>;
  }}</PanelStateView>;
}
