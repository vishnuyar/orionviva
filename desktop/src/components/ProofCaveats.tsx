import type { ProofPresentation } from "../surface/types";

export function ProofCaveats({ caveats, className }: { caveats: readonly string[]; className?: string }) {
  if (!caveats.length) return null;
  return <ul className={["proof-caveats", className].filter(Boolean).join(" ")} aria-label="Qualifications">{caveats.map((caveat, index) => <li key={`${index}-${caveat}`}>{caveat}</li>)}</ul>;
}

export function ProofQualifications({ proof, alreadyRendered = [] }: { proof: ProofPresentation; alreadyRendered?: readonly string[] }) {
  if (proof.emphasis !== "required") return null;
  const visible = new Set(alreadyRendered);
  const qualifications = proof.qualifications.filter((qualification) => !visible.has(qualification));
  if (!qualifications.length) return null;
  return <ul className="proof-qualifications" aria-label="Required qualifications">{qualifications.map((qualification, index) => <li key={`${index}-${qualification}`}>{qualification}</li>)}</ul>;
}
