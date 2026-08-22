import type { Destination, FeatureResult, SurfaceRegistry } from "../surface/types";

// Where a person can stand, and what each place is called. The labels are this
// shell's, because they are the words on its own furniture; whether a place has
// anything behind it is not, and is never written here.
export const destinations: Array<{ id: Destination; label: string; eyebrow: string }> = [
  { id: "overview", label: "Overview", eyebrow: "Your picture" },
  { id: "accounts", label: "Accounts", eyebrow: "Where money sits" },
  { id: "activity", label: "Activity", eyebrow: "What moved" },
  { id: "documents", label: "Documents", eyebrow: "What supports it" },
  { id: "review", label: "Review", eyebrow: "What needs you" },
  { id: "trust", label: "Trust", eyebrow: "How it works" },
];

// How a destination stands to the engine behind the source. `served` is a read
// reaching it; `unserved` is the registry saying no read does; `unclaimed` is
// this shell having a screen the registry does not declare at all, which is a
// fault on this side rather than a capability that has not landed; and
// `unasked` is nobody having put the question yet, which is not any of the
// other three and is never rendered as one.
export type DestinationStanding = "served" | "unserved" | "unclaimed" | "unasked";

// What a destination is owed, read off the registry the sidecar derived. This
// works nothing out: the rule about what "served" means lives where the
// registry does, and a second copy of it here would be a second rule.
export function standingOf(
  registry: FeatureResult<SurfaceRegistry>,
  destination: Destination,
): DestinationStanding {
  if (registry.state !== "ready") return "unasked";
  if (registry.data.undeclared.includes(destination)) return "unclaimed";
  return registry.data.served[destination] ? "served" : "unserved";
}

// What is said beside a destination whose read does not reach it. Nothing is
// said beside one that is served, and nothing is said before the question has
// been put: a mark that appears on every destination while the answer is on its
// way is a mark that stops meaning anything.
export const standingCopy: Record<DestinationStanding, string> = {
  served: "",
  unserved: "Not connected",
  unclaimed: "Not in this build",
  unasked: "",
};
