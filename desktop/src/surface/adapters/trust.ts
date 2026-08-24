import type { OutboundLine, OutboundModel, OutboundRecordView, TrustAbsence, TrustData, TrustNote } from "../types";
import { isRecord, optionalNonNegativeInteger, textValue, uniqueRecordsById } from "./primitives";

// One line of the record. A line with no sentence is dropped rather than shown
// as a bare number: this side has no words for what a classify pass sends, and
// a count on its own is a figure a person has to guess the meaning of.
function line(raw: unknown): OutboundLine | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const count = optionalNonNegativeInteger(raw.count);
  const sentence = textValue(raw.sentence);
  if (!id || count === undefined || !sentence.trim()) return null;
  return { id, count, sentence };
}

function model(raw: unknown): OutboundModel | null {
  if (!isRecord(raw)) return null;
  const name = textValue(raw.name);
  const count = optionalNonNegativeInteger(raw.count);
  if (!name || count === undefined) return null;
  return { name, count };
}

function absence(raw: unknown): { id: string; sentence: string } | null {
  if (!isRecord(raw)) return null;
  const id = textValue(raw.id);
  const sentence = textValue(raw.sentence);
  return id && sentence.trim() ? { id, sentence } : null;
}

// The record, read into the shape a screen holds. Its own sentence is required:
// a record with no sentence is one this side would have to narrate, and
// narrating what a vault has sent is the exact claim this panel exists to stop
// the interface making.
export function adaptOutbound(raw: unknown): OutboundRecordView | null {
  if (!isRecord(raw)) return null;
  const sentence = textValue(raw.sentence);
  const callCount = optionalNonNegativeInteger(raw.call_count);
  if (!sentence.trim() || callCount === undefined) return null;
  const span = isRecord(raw.span) && textValue(raw.span.sentence).trim()
    ? { first: textValue(raw.span.first), last: textValue(raw.span.last), sentence: textValue(raw.span.sentence) }
    : null;
  // A total with no sentence is not shown. A vault whose calls recorded no
  // price gets no total at all, because nothing was measured and a zero is a
  // measurement.
  const cost = isRecord(raw.cost) && textValue(raw.cost.sentence).trim()
    ? { exactValue: textValue(raw.cost.exact_value), currency: textValue(raw.cost.currency), display: textValue(raw.cost.display), sentence: textValue(raw.cost.sentence) }
    : null;
  const inputTokens = isRecord(raw.tokens) ? optionalNonNegativeInteger(raw.tokens.input) : undefined;
  const outputTokens = isRecord(raw.tokens) ? optionalNonNegativeInteger(raw.tokens.output) : undefined;
  const totalTokens = isRecord(raw.tokens) ? optionalNonNegativeInteger(raw.tokens.total) : undefined;
  const measuredCalls = isRecord(raw.tokens) ? optionalNonNegativeInteger(raw.tokens.measured_calls) : undefined;
  const tokens = inputTokens !== undefined && outputTokens !== undefined && totalTokens !== undefined && measuredCalls !== undefined
    ? { input: inputTokens, output: outputTokens, total: totalTokens, measuredCalls }
    : undefined;
  return {
    sentence,
    callCount,
    phases: (Array.isArray(raw.phases) ? raw.phases : []).map(line).filter((row): row is OutboundLine => row !== null),
    models: (Array.isArray(raw.models) ? raw.models : []).map(model).filter((row): row is OutboundModel => row !== null),
    reportedModels: (Array.isArray(raw.reported_models) ? raw.reported_models : []).map(model).filter((row): row is OutboundModel => row !== null),
    legacyModels: (Array.isArray(raw.legacy_models) ? raw.legacy_models : []).map(model).filter((row): row is OutboundModel => row !== null),
    tokens,
    modelSentence: textValue(raw.model_sentence),
    span,
    cost,
    absences: (Array.isArray(raw.absences) ? raw.absences : []).map(absence).filter((row): row is { id: string; sentence: string } => row !== null),
  };
}

export function adaptTrust(raw: unknown): TrustData | null {
  if (!isRecord(raw)) return null;
  const notes: TrustNote[] = Array.isArray(raw.notes)
    ? uniqueRecordsById(raw.notes).map((item) => ({ id: textValue(item.id), title: textValue(item.title), detail: textValue(item.detail) }))
    : [];
  const absences: TrustAbsence[] = (Array.isArray(raw.absences) ? raw.absences : [])
    .map(absence).filter((row): row is TrustAbsence => row !== null);
  const outbound = adaptOutbound(raw.outbound);
  // A trust read that carried no record at all is read as no trust data. The
  // record is the whole of what this build's Trust destination is for, and a
  // panel rendering notes without it would say less than the read knows.
  if (!outbound) return null;
  return { notes, absences, outbound };
}
