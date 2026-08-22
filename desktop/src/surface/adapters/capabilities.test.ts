import { describe, expect, it } from "vitest";
import { adaptIdentity, adaptRegistry } from "./capabilities";

const declared = { overview: true, accounts: false, activity: false, documents: true, review: true, viva: false, trust: false, settings: false, none: false };

describe("the registry the sidecar derived", () => {
  it("carries the sidecar's answer for every destination this shell has a screen for", () => {
    expect(adaptRegistry({ destinations: declared })).toEqual({
      served: { overview: true, accounts: false, activity: false, documents: true, review: true, trust: false },
      undeclared: [],
    });
  });

  it("keeps a screen the registry never declared apart from one whose read is not connected", () => {
    // Two different faults. One is a capability that has not landed; the other
    // is this shell showing a place the product has never heard of, which is
    // this side's own doing and must not be reported as the product's.
    const { served, undeclared } = adaptRegistry({ destinations: { overview: true, documents: true, review: true } })!;
    expect(undeclared).toEqual(["accounts", "activity", "trust"]);
    expect(served.accounts).toBe(false);
  });

  it("reads nothing at all from a reply that carries no destinations", () => {
    expect(adaptRegistry({ capabilities: [] })).toBeNull();
    expect(adaptRegistry(null)).toBeNull();
  });

  it("treats a destination marked with anything but true as unserved", () => {
    const { served } = adaptRegistry({ destinations: { ...declared, overview: "yes" } })!;
    expect(served.overview).toBe(false);
  });
});

describe("which build answered", () => {
  it("carries the engine's own word for its build, unchanged", () => {
    expect(adaptIdentity({ protocol: "2.0", transport: "json-lines", revision: "abc123def456" }))
      .toEqual({ protocol: "2.0", transport: "json-lines", revision: "abc123def456" });
  });

  it("carries the engine's word for not knowing rather than replacing it", () => {
    expect(adaptIdentity({ protocol: "2.0", transport: "json-lines", revision: "unknown" })?.revision).toBe("unknown");
  });

  it("is read as no identity at all when the reply names no protocol", () => {
    expect(adaptIdentity({ revision: "abc123def456" })).toBeNull();
    expect(adaptIdentity("2.0")).toBeNull();
  });
});
