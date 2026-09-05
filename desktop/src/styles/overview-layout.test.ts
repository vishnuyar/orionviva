import { describe, expect, it } from "vitest";
import base from "./surface-base.css?raw";
import picture from "./picture.css?raw";
import responsive from "./surface-responsive.css?raw";

describe("overview picture intrinsic layout", () => {
  it("bounds both desktop columns and lets long authored totals wrap inside their card", () => {
    expect(base).toMatch(/\.hero-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.35fr\)\s+minmax\(15rem,\s*\.9fr\);/s);
    expect(base).toMatch(/\.hero-card,\s*\.coverage-card\s*\{[^}]*min-width:\s*0;/s);
    expect(base).toMatch(/\.hero-amount\s*\{[^}]*max-width:\s*100%;[^}]*overflow-wrap:\s*anywhere;/s);
    expect(picture).toMatch(/\.hero-card\s+\.picture-figure\s+\.hero-amount\s*\{[^}]*max-width:\s*100%;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/s);
  });

  it("stacks the picture before the fixed navigation rail makes two cards collide", () => {
    expect(responsive).toMatch(/@media\s*\(max-width:\s*1199px\)\s*\{\s*\.hero-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s);
    expect(responsive.indexOf("max-width: 1199px")).toBeLessThan(responsive.indexOf("max-width: 760px"));
  });
});
