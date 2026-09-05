export function isRecord(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
export function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}
export function textValue(value: unknown): string { return typeof value === "string" || typeof value === "number" ? String(value) : ""; }
export function booleanValue(value: unknown): boolean | undefined { return typeof value === "boolean" ? value : undefined; }
export function optionalNonNegativeInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}
export function nextCalendarDay(value: string): string | null {
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) return null;
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}
export function previousCalendarDay(value: string): string | null {
  const parsed = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) return null;
  parsed.setUTCDate(parsed.getUTCDate() - 1);
  return parsed.toISOString().slice(0, 10);
}
export function uniqueRecordsById(values: unknown[], idField = "id"): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  return values.map(record).filter((item) => { const id = textValue(item[idField]); if (!id || seen.has(id)) return false; seen.add(id); return true; });
}
