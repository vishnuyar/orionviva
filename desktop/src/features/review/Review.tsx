import { ArrowUpRight, CircleHelp } from "lucide-react";
import { PanelStateView } from "../../components/PanelStateView";
import type { FeatureResult, ReviewData, ReviewItem, ReviewTransactionTarget } from "../../surface/types";

type Props = {
  result: FeatureResult<ReviewData>;
  onOpenQuestion: (questionId: string, itemId: string) => void;
  onOpenTransaction: (target: ReviewTransactionTarget, itemId: string) => void;
};

function Context({ item }: { item: ReviewItem }) {
  const values = [item.context.merchant, item.context.date, item.context.account, item.context.amount].filter(Boolean);
  return values.length ? <p className="review-center-context">{values.map((value, index) => <span key={`${value}-${index}`}>{value}</span>)}</p> : null;
}

export function Review({ result, onOpenQuestion, onOpenTransaction }: Props) {
  return <div className="review-center-boundary" aria-live="polite"><PanelStateView result={result} copy={{ partial: "Some review items are unavailable. Available authored items are shown.", needsInput: "Review needs more information before every item can be shown.", unavailable: { title: "Review unavailable", detail: "This vault does not provide an authored Review queue." }, failed: { title: "Review could not be read", detail: "No items from the failed Review read are being shown." } }}>{(data) => <section className="review-center" aria-labelledby="review-center-title">
    <header className="review-center-header"><div><span className="detail-panel-label">Waiting for your decision</span><h2 id="review-center-title">{data.title}</h2><p>{data.summary}</p></div><div className="review-center-count" aria-label={`${data.actionableCount} actionable review ${data.actionableCount === 1 ? "item" : "items"}`}><strong>{data.actionableCount > 999 ? "999+" : data.actionableCount}</strong><span>Actionable</span></div></header>
    {data.shownCount === 0 ? <div className="empty-state"><strong id="review-empty-title" tabIndex={-1}>Nothing to review</strong><span>{data.summary}</span></div> : data.groups.map((group) => <section className="review-center-group" aria-labelledby={`review-group-${group.id}`} key={group.id}><div className="section-heading"><h3 id={`review-group-${group.id}`}>{group.label}</h3><span>{group.count}</span></div><ol>{group.items.map((item) => <li id={`review-item-${item.id}`} tabIndex={-1} key={item.id} className="review-center-row"><span className="review-center-marker" role="img" aria-label={item.markerLabel}><CircleHelp aria-hidden="true" /></span><div><div className="review-center-row-heading"><span>{item.typeLabel}</span><strong>{item.label}</strong></div><p>{item.reason}</p><Context item={item} />{item.target.kind === "conversation" ? <small>{item.target.disclosure}</small> : null}</div><button type="button" className="secondary-button" onClick={() => item.target.kind === "transaction" ? onOpenTransaction(item.target, item.id) : onOpenQuestion(item.target.questionId, item.id)}>{item.actionLabel}<ArrowUpRight className="review-center-action-icon" /></button></li>)}</ol></section>)}
    {data.remainingCount ? <p className="review-center-remaining">{data.remainingCount} more authored {data.remainingCount === 1 ? "item is" : "items are"} outside this bounded read.</p> : null}
  </section>}</PanelStateView></div>;
}
