import type { SurfaceSnapshot } from "../surface/types";

// What this source is, said once. The second line used to be a dialect switch:
// a sample vault said "everything here is fictional" and a private one said
// what a private one says. There is one sentence now, because the fact that a
// vault is the sample one is said by the frame around the whole place rather
// than restated on every surface inside it.
export function SourceDisclosure({ disclosure }: { disclosure: SurfaceSnapshot["disclosure"] }) {
  return <aside className="source-disclosure corpus-note" aria-label="Vault source">
    <span>{disclosure.title} · {disclosure.subtitle}</span>
    <span>{disclosure.detail}</span>
  </aside>;
}
