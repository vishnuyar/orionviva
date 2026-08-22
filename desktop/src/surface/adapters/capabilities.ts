import type { Destination, EngineIdentity, SurfaceRegistry } from "../types";
import { isRecord, textValue } from "./primitives";

// The destinations this shell has screens for. It is not the registry's list
// and it is not meant to be: the registry declares where a capability is
// reached, and this declares where a person can stand. A destination the
// registry declares and this does not is a place the product can serve and
// nothing here shows; a destination here the registry does not declare is a
// screen claiming machinery — and the read below reports the second as
// unserved rather than quietly treating it as fine.
const DESTINATIONS: readonly Destination[] = ["overview", "accounts", "activity", "documents", "review", "trust"];

// Whether a read reaches each destination, as the sidecar derived it. Nothing
// here works it out: the rule lives in the registry, and a second derivation on
// this side is a second rule, of which the one a person meets is the one nobody
// reviewed.
export function adaptRegistry(raw: unknown): SurfaceRegistry | null {
  if (!isRecord(raw) || !isRecord(raw.destinations)) return null;
  const declared = raw.destinations;
  const served: Partial<Record<Destination, boolean>> = {};
  for (const destination of DESTINATIONS) {
    // A destination the sidecar said nothing about is not served. It is the
    // same answer as `false` and a different fact, and the fact is kept: the
    // shell knows a screen it has that the registry does not declare.
    served[destination] = declared[destination] === true;
  }
  const undeclared = DESTINATIONS.filter((destination) => !(destination in declared));
  return { served: served as Record<Destination, boolean>, undeclared };
}

// Which build answered. An empty revision is not a build that said nothing:
// the sidecar answers with a word for not knowing, so a blank here means the
// reply had no such field at all, and the shell says that rather than showing
// an emptiness a person would read as an answer.
export function adaptIdentity(raw: unknown): EngineIdentity | null {
  if (!isRecord(raw)) return null;
  const protocol = textValue(raw.protocol);
  const revision = textValue(raw.revision);
  if (!protocol) return null;
  return { protocol, transport: textValue(raw.transport), revision };
}
