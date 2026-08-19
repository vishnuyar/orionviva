import type { SurfaceMode, SurfaceSnapshot } from "../surface/types";

export function SourceDisclosure({ mode, disclosure }: { mode: SurfaceMode; disclosure: SurfaceSnapshot["disclosure"] }) {
  return <aside className="source-disclosure corpus-note" aria-label="Vault source">
    <span>{disclosure.title} · {disclosure.subtitle}</span>
    <span>{mode === "demo" ? "Every name, document, and figure here is fictional." : "The surfaces below are read from this vault. Features that are not connected stay hidden or say so."}</span>
  </aside>;
}
