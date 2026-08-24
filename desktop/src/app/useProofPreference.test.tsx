import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SHOW_VERIFICATION_DETAILS_KEY, readShowVerificationDetails, useProofPreference, writeShowVerificationDetails } from "./useProofPreference";

function Harness() {
  const preference = useProofPreference();
  return <label><input type="checkbox" checked={preference.showVerificationDetails} onChange={(event) => preference.setShowVerificationDetails(event.target.checked)} />Show verification details</label>;
}

class MemoryStorage implements Storage {
  readonly values = new Map<string, string>();

  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, String(value)); }
}

const storage = new MemoryStorage();

beforeEach(() => {
  storage.clear();
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
});

afterEach(() => vi.restoreAllMocks());

describe("the device-local proof preference", () => {
  it("defaults off and survives a fresh app mount under one versioned product key", async () => {
    const user = userEvent.setup();
    const first = render(<Harness />);
    expect(first.getByRole("checkbox", { name: "Show verification details" })).not.toBeChecked();
    await user.click(first.getByRole("checkbox", { name: "Show verification details" }));
    expect(window.localStorage).toHaveLength(1);
    expect(window.localStorage.getItem(SHOW_VERIFICATION_DETAILS_KEY)).toBe("true");
    first.unmount();

    const restarted = render(<Harness />);
    expect(restarted.getByRole("checkbox", { name: "Show verification details" })).toBeChecked();
  });

  it.each(["not json", "null", "{}", "1", "\"true\""])('falls back off for malformed stored data: %s', (stored) => {
    window.localStorage.setItem(SHOW_VERIFICATION_DETAILS_KEY, stored);
    expect(readShowVerificationDetails()).toBe(false);
  });

  it("falls back off when storage cannot be read or written", () => {
    const unavailable = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readShowVerificationDetails(unavailable)).toBe(false);
    expect(writeShowVerificationDetails(true, unavailable)).toBe(false);
    expect(readShowVerificationDetails(null)).toBe(false);
    expect(writeShowVerificationDetails(true, null)).toBe(false);
  });

  it("stays off for the session when a device write fails", async () => {
    vi.spyOn(storage, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const user = userEvent.setup();
    const view = render(<Harness />);
    const checkbox = view.getByRole("checkbox", { name: "Show verification details" });
    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();
  });
});
