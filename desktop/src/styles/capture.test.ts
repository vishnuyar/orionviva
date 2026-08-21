import { afterEach, describe, expect, it } from "vitest";
import tokens from "./tokens.css?raw";
import shell from "./shell.css?raw";
import surfaces from "./surfaces.css?raw";
import capture from "./capture.css?raw";

// The four stylesheets in the order the application imports them, so what wins
// here is what wins on the screen. A declaration written against the token set
// resolves to a token reference; one that lost to a stylesheet predating that
// set resolves to that stylesheet's own value, so the two are told apart by
// reading the computed value rather than by counting selectors.
function mount(markup: string): HTMLElement {
  for (const sheet of [tokens, shell, surfaces, capture]) {
    const style = document.createElement("style");
    style.textContent = sheet;
    document.head.append(style);
  }
  const host = document.createElement("div");
  host.innerHTML = markup;
  document.body.append(host);
  return host;
}

afterEach(() => {
  document.head.querySelectorAll("style").forEach((style) => style.remove());
  document.body.replaceChildren();
});

function declarations(element: Element, properties: readonly string[]): Record<string, string> {
  const computed = getComputedStyle(element);
  return Object.fromEntries(properties.map((property) => [property, computed.getPropertyValue(property)]));
}

describe("the stylesheet this cycle authored", () => {
  it("reaches the capture answer rather than losing it to the panel's own paragraph rule", () => {
    const host = mount(`<div class="content-wrap"><section class="feature-panel documents-surface"><div class="document-capture-answer"><strong>Title</strong><p>Sentence</p></div></section></div>`);
    expect(declarations(host.querySelector(".document-capture-answer p")!, ["font-size", "color", "line-height", "margin-bottom"]))
      .toEqual({ "font-size": "var(--text-fine)", color: "var(--muted)", "line-height": "var(--leading-loose)", "margin-bottom": "0px" });
    expect(declarations(host.querySelector(".document-capture-answer strong")!, ["font-size", "color", "font-weight"]))
      .toEqual({ "font-size": "var(--text-fine)", color: "var(--ink)", "font-weight": "var(--weight-strong)" });
    expect(declarations(host.querySelector(".document-capture-answer")!, ["gap", "margin-bottom"]))
      .toEqual({ gap: "var(--space-xs)", "margin-bottom": "var(--space-xl)" });
  });

  it("reaches the passphrase consequence rather than losing it to the vault card's paragraph rule", () => {
    const host = mount(`<aside class="sidebar"><div class="vault-source-card"><form class="vault-open-form"><p class="vault-passphrase-consequence">Sentence</p></form></div></aside>`);
    expect(declarations(host.querySelector(".vault-passphrase-consequence")!, ["font-size", "color", "line-height", "padding-block", "padding-inline", "border-radius", "background", "margin"]))
      .toEqual({ "font-size": "var(--text-body)", color: "var(--ink)", "line-height": "var(--leading-loose)", "padding-block": "var(--space-sm)", "padding-inline": "var(--space-sm)", "border-radius": "var(--radius-sm)", background: "var(--paper)", margin: "0px" });
  });
});
