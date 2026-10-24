import { ArrowUpRight, CircleHelp } from "lucide-react";
import { PanelStateView } from "../../components/PanelStateView";
import type { FeatureResult, ReviewData, ReviewItem, ReviewTransactionTarget } from "../../surface/types";

type Props = {
  result: FeatureResult<ReviewData>;
  nextItemId?: string;
  onOpenQuestion: (questionId: string, itemId: string) => void;
  onOpenTransaction: (target: ReviewTransactionTarget, itemId: string) => void;
};

function Context({ item }: { item: ReviewItem }) {
  const values = [["Description", item.context.merchant], ["Date", item.context.date], ["Account", item.context.account], ["Amount", item.context.amount]].filter(([, value]) => Boolean(value));
  return values.length ? <dl className="review-center-context">{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : null;
}

export function Review({ result, nextItemId = "", onOpenQuestion, onOpenTransaction }: Props) {
  return <div className="review-center-boundary" aria-live="polite"><PanelStateView result={result} copy={{ partial: "Some review items could not be loaded. The available items are shown below.", needsInput: "Review needs more information before every item can be shown.", unavailable: { title: "Review unavailable", detail: "Review items are unavailable for this vault." }, failed: { title: "Review could not be read", detail: "Review items could not be loaded. Try refreshing your vault." } }}>{(data) => <section className="review-center" aria-labelledby="review-center-title">
    <header className="review-center-header"><div><span className="detail-panel-label">Waiting for your decision</span><h2 id="review-center-title">{data.title}</h2><p>{data.summary}</p></div><div className="review-center-count" aria-label={`${data.actionableCount} actionable review ${data.actionableCount === 1 ? "item" : "items"}`}><strong>{data.actionableCount > 999 ? "999+" : data.actionableCount}</strong><span>Actionable</span></div></header>
    {data.shownCount === 0 ? <div className="empty-state"><strong id="review-empty-title" tabIndex={-1}>{result.state === "ready" && !data.remainingCount ? "Nothing to review" : "No review items loaded"}</strong><span>{data.summary}</span></div> : data.groups.map((group) => <section className="review-center-group" aria-labelledby={`review-group-${group.id}`} key={group.id}><div className="section-heading"><h3 id={`review-group-${group.id}`}>{group.label}</h3><span>{group.count}</span></div><ol>{group.items.map((item) => <li id={`review-item-${item.id}`} tabIndex={-1} key={item.id} className={item.id === nextItemId ? "review-center-row review-center-next" : "review-center-row"}><span className="review-center-marker" role="img" aria-label={item.markerLabel}><CircleHelp aria-hidden="true" /></span><div><div className="review-center-row-heading"><span>{item.typeLabel}</span><strong>{item.label}</strong></div><div className="review-center-reason"><span className="detail-panel-label">Why this needs review</span><p>{item.reason}</p></div><Context item={item} />{item.target.kind === "conversation" ? <small>{item.target.disclosure}</small> : null}</div><button type="button" className="secondary-button" aria-label={item.id === nextItemId ? `Next item: ${item.actionLabel}` : undefined} onClick={() => item.target.kind === "transaction" ? onOpenTransaction(item.target, item.id) : onOpenQuestion(item.target.questionId, item.id)}>{item.id === nextItemId ? "Next item" : item.actionLabel}<ArrowUpRight className="review-center-action-icon" /></button></li>)}</ol></section>)}
    {data.remainingCount ? <p className="review-center-remaining">{data.remainingCount} more review {data.remainingCount === 1 ? "item is" : "items are"} not shown here.</p> : null}
  </section>}</PanelStateView></div>;
}
