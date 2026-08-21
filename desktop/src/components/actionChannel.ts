import type { ActionResult } from "../surface/types";

// The three channels a verb can come back through without the vault ever
// answering. `settled` is not among them: there the vault spoke for itself.
export type UnansweredChannel = Exclude<ActionResult, { state: "settled" }>;
export type ChannelPresentation = { title: string; detail: string };

// The vault answered and its own sentence stands; this is what is said when
// the reply carried no sentence at all.
export const UNSPOKEN_REPLY = "Your vault recorded no sentence for this reply.";

// What a request that never reached an answer is called, in words no verb
// appears in, so every screen that writes to the vault says the same thing
// about the same channel. Each is titled by what did not happen to the
// request, because the code carrying a refused request also carries a handler
// that raised, and a handler can raise after it has written.
export function channelPresentation(result: UnansweredChannel): ChannelPresentation {
  if (result.state === "unserved") return { title: "Your vault would not take this request", detail: "Your vault refused the request as this screen sent it. Whether anything was recorded is not something this screen can tell you." };
  if (result.state === "unanswered") return { title: "Your vault did not answer", detail: "Nothing came back, so this screen will not say whether anything was recorded." };
  return { title: "The reply could not be read", detail: "Your vault answered in a way this screen does not recognise, so it will not say whether anything was recorded." };
}
