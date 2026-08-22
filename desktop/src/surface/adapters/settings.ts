import type { ActionOutcome, SettingsProposal, SettingsView } from "../types";
import { booleanValue, isRecord, textValue } from "./primitives";

// What is in force, read into the shape a screen holds. There is no field here
// a key could travel in: what a screen may know is whether one is set, which is
// what decides whether anything can be sent at all.
export function adaptSettings(raw: unknown): SettingsView | null {
  if (!isRecord(raw)) return null;
  const locale = textValue(raw.locale);
  const currency = textValue(raw.currency);
  if (!locale || !currency) return null;
  return {
    locale,
    currency,
    adapter: textValue(raw.adapter),
    model: textValue(raw.model),
    baseUrl: textValue(raw.base_url),
    keySet: booleanValue(raw.key_set) === true,
    canSend: booleanValue(raw.can_send) === true,
  };
}

// One proposal, read from the reply that held it. The `proposal` outcome word
// is the vocabulary's own for a reply held for a confirmation, so a reply
// carrying any other word is not a proposal and is read as none.
export function adaptProposal(raw: unknown): SettingsProposal | null {
  if (!isRecord(raw)) return null;
  const kind: ActionOutcome | "" = raw.kind === "proposal" ? "proposal" : "";
  if (!kind || !isRecord(raw.state)) return null;
  const state = raw.state;
  const proposalKind = state.kind === "presentation" || state.kind === "model" ? state.kind : null;
  const digest = textValue(state.digest);
  const message = textValue(raw.message);
  // A proposal with no digest cannot be said yes to, and one with no sentence
  // is a change nobody could read before agreeing to it. Neither is shown.
  if (!proposalKind || !digest || !message.trim()) return null;
  const changes: Record<string, string> = {};
  if (isRecord(state.changes)) for (const [name, value] of Object.entries(state.changes)) changes[name] = textValue(value);
  return { kind: proposalKind, changes, sends: booleanValue(state.sends) === true, digest, message };
}
