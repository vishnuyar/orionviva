import { useId } from "react";
import type { EvidenceFigureView } from "../surface/evidence";

// The control a person opens a figure's evidence with, and — where the figure
// asks for one — the visible row that says the evidence is there.
//
// The control's accessible name begins with the amount it shows and continues
// with what the figure is of. The amount first, because a name that replaces
// the visible text with an invitation leaves a person who cannot see the
// screen hearing the invitation and never the number; what it is of after,
// because two figures on one screen may show the same amount and a person
// acting on one has to know which. Neither half is written here: the amount is
// the read's and what it is of is the read's where the read said it.
//
// The accessibility layer joins the two, so nothing composes a sentence.
export function Figure({ figure, onOpenEvidence, className }: { figure: EvidenceFigureView; onOpenEvidence: (figureId: string) => void; className?: string }) {
  // Identities this component mints. A figure's own identity comes from the
  // vault and may hold a space, and a space in an identity list silently
  // detaches what it points at from the control.
  const own = useId();
  const ofWhat = useId();
  const invitation = useId();
  const named = figure.heading.trim() ? figure.heading : figure.label;
  const said = figure.actionLabel.trim() ? figure.actionLabel : `View evidence for ${figure.label}`;
  return <>
    <button id={own} type="button" className={["figure-trigger", className].filter(Boolean).join(" ")} aria-haspopup="dialog" aria-controls="figure-evidence-drawer" aria-labelledby={`${own} ${ofWhat}`} aria-describedby={invitation} onClick={() => onOpenEvidence(figure.id)}>{figure.display}</button>
    <span className="figure-invitation" id={ofWhat}>{named}</span>
    <span className="figure-invitation" id={invitation}>{said}</span>
  </>;
}
