import { describe, expect, it } from "vitest";
import desktopDetails from "./surface-details.css?raw";
import responsive from "./surface-responsive.css?raw";
import accountLedger from "./account-ledger.css?raw";

describe("account index responsive layout rules", () => {
  it("declares usable 1280-wide grid geometry and an explicit one-column narrow fallback", () => {
    expect(desktopDetails).toMatch(/\.account-detail-row\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(240px,\s*1fr\)\s+minmax\(160px,\s*34%\);[^}]*width:\s*100%;/s);
    expect(desktopDetails).toMatch(/\.account-detail-row\s*>\s*\.detail-row-button\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*240px;[^}]*min-height:\s*var\(--control-min-height\);/s);
    expect(responsive).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*?\.account-detail-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);[^}]*grid-template-areas:\s*"account"\s*"figure"\s*"qualifications"\s*"caveats";/s);
    expect(responsive).toMatch(/\.account-detail-row\s*>\s*\.detail-row-button\s*\{\s*min-width:\s*0;/);
  });

  it("switches the real ledger row to a zero-minimum stacked layout before the desktop sidebar can squeeze it", () => {
    expect(accountLedger).toMatch(/\.account-ledger-row\s*\{[^}]*grid-template-columns:\s*var\(--control-min-height\)\s+minmax\(28px,\s*auto\)\s+minmax\(0,\s*1fr\);[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*min-width:\s*0;/s);
    expect(accountLedger).toMatch(/\.account-ledger-row-button\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*min-width:\s*0;/s);
    const constrained = accountLedger.slice(accountLedger.indexOf("@media (max-width: 900px)"), accountLedger.indexOf("@media (max-width: 620px)"));
    expect(constrained).toMatch(/\.account-ledger-row-button\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s);
    expect(constrained).toContain(".account-ledger-date, .account-ledger-description, .account-ledger-amount { grid-column: 1; }");
    expect(constrained).toContain(".account-ledger-amount { text-align: left; }");
    expect(accountLedger).toContain(".account-ledger-description, .account-ledger-amount { display: grid;");
    expect(accountLedger).toContain("overflow-wrap: anywhere;");
  });

  it("keeps the real selection label and transaction close selector at the shared 44px target floor after the zero-minimum reset", () => {
    const reset = accountLedger.indexOf(".account-ledger-page, .account-ledger-page *");
    const targets = accountLedger.indexOf(".account-ledger-page .account-ledger-check, .account-transaction-drawer .conversation-close");
    expect(targets).toBeGreaterThan(reset);
    expect(accountLedger.slice(targets)).toMatch(/min-width:\s*var\(--control-min-height\);\s*min-height:\s*var\(--control-min-height\);/);
    expect(accountLedger).not.toContain("grid-template-columns: 42px");
  });
});
