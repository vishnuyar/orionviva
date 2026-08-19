import type { FigureGrade } from "../surface/types";
export function EvidenceBadge({ grade, label, description }: { grade: FigureGrade; label: string; description: string }) { return <span className={`evidence-badge ${grade}`} title={description} aria-label={`${label}. ${description}`}><span className="mini-dot" />{label}</span>; }
