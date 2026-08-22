import { PanelStateView } from "../../components/PanelStateView";
import type { ActivityData, EvidenceLink, FeatureResult } from "../../surface/types";

type ActivityProps = { result: FeatureResult<ActivityData>; onOpenEvidence: (link: EvidenceLink) => void };

// What moved, as the read composed it. Every word here is the backend's: the
// direction, the sentence saying what a row is where it is not plain spending,
// and the panel's own line about where the rows came from and where direction
// is read from. Nothing here counts, signs or names anything.
//
// This screen used to have a second implementation beside this one — a search
// box, seven facet filters and a relationship graph, all over rows composed in
// the shell for the sample vault. The sample is a vault now, so it arrives
// through this read like every other vault, and the second implementation is
// gone rather than left as the path one vault takes.
function Movements({ data }: { data: ActivityData }) {
  const movements = data.movements ?? [];
  return <section className="feature-panel activity-panel">
    <header className="activity-header"><div className="detail-panel-label">Current vault read</div><h2>What moved</h2><p>{data.sentence}</p></header>
    {!movements.length ? <div className="empty-state"><strong>No movements in this read</strong><span>{data.sentence}</span></div> : <>
      <ul className="activity-movements">{movements.map((movement) => <li key={movement.id} className={movement.direction === "in" ? "activity-movement inflow" : "activity-movement outflow"}>
        <span className="activity-movement-when">{movement.date}</span>
        <span className="activity-movement-what"><strong>{movement.description || "No description was recorded for this movement."}</strong><small>{movement.account}</small></span>
        <span className="activity-movement-amount"><strong>{movement.display}</strong><small>{movement.direction === "in" ? "in" : "out"}</small></span>
        {movement.sentence ? <p className="activity-movement-note">{movement.sentence}</p> : null}
      </li>)}</ul>
      {data.beyond && data.beyond.count > 0 ? <p className="activity-beyond">{data.beyond.count} more are in this vault and not in this list.</p> : null}
    </>}
  </section>;
}

export function Activity({ result }: ActivityProps) {
  return <PanelStateView result={result} copy={{ partial: "Some activity details are unavailable. Available movements are shown below.", needsInput: "Some activity details need more information. Available movements are shown below.", unavailable: { title: "Activity unavailable", detail: "Activity is not connected to this vault read." }, failed: { title: "Activity could not be read", detail: "Activity could not be read. The vault is still open." } }}>{(data) => <Movements data={data} />}</PanelStateView>;
}
