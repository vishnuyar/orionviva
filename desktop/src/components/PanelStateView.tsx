import type { ReactNode } from "react";
import type { FeatureResult } from "../surface/types";

export type PanelStateCopy = { partial: string; needsInput: string; unavailable: { title: string; detail: string }; failed: { title: string; detail: string } };
export function PanelStateView<T>({ result, copy, children }: { result: FeatureResult<T>; copy: PanelStateCopy; children: (data: T) => ReactNode }) {
  if (result.state === "absent") return null;
  if (result.state === "unavailable" || result.state === "failed") { const bounded = result.state === "unavailable" ? copy.unavailable : copy.failed; return <div className="empty-state"><strong>{bounded.title}</strong><span>{bounded.detail}</span></div>; }
  return <>{result.state === "partial" && <div className="unavailable-callout">{copy.partial}</div>}{result.state === "needs_input" && <div className="unavailable-callout">{copy.needsInput}</div>}{children(result.data)}</>;
}
