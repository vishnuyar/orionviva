export const SHOW_VERIFICATION_DETAILS_KEY = "orionviva.display.show-verification-details.v1";

export type DevicePreferenceStorage = Pick<Storage, "getItem" | "setItem">;

function deviceStorage(): DevicePreferenceStorage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readShowVerificationDetails(storage: DevicePreferenceStorage | null = deviceStorage()): boolean {
  if (!storage) return false;
  try {
    const parsed: unknown = JSON.parse(storage.getItem(SHOW_VERIFICATION_DETAILS_KEY) ?? "null");
    return typeof parsed === "boolean" ? parsed : false;
  } catch {
    return false;
  }
}

export function writeShowVerificationDetails(value: boolean, storage: DevicePreferenceStorage | null = deviceStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(SHOW_VERIFICATION_DETAILS_KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
