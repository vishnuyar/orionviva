import type { EvidenceFigureView } from "../surface/evidence";

export function Figure({ figure, onOpenEvidence, className }: { figure: EvidenceFigureView; onOpenEvidence: (figureId: string) => void; className?: string }) {
  return <button type="button" className={["figure-trigger", className].filter(Boolean).join(" ")} aria-haspopup="dialog" aria-controls="figure-evidence-drawer" aria-label={`View evidence for ${figure.label}`} onClick={() => onOpenEvidence(figure.id)}>{figure.display}</button>;
}
