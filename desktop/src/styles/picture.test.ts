import { afterEach, describe, expect, it } from "vitest";
import tokens from "./tokens.css?raw";
import shell from "./shell.css?raw";
import surfaceBase from "./surface-base.css?raw";
import documents from "./documents.css?raw";
import surfacePrimitives from "./surface-primitives.css?raw";
import review from "./questions.css?raw";
import surfaceDetails from "./surface-details.css?raw";
import conversation from "./conversation.css?raw";
import activity from "./activity.css?raw";
import trust from "./trust.css?raw";
import evidence from "./evidence.css?raw";
import surfaceResponsive from "./surface-responsive.css?raw";
import capture from "./capture.css?raw";
import picture from "./picture.css?raw";

const surfaces = [surfaceBase, documents, surfacePrimitives, review,
  surfaceDetails, conversation, activity, trust, evidence,
  surfaceResponsive].join("\n");

// The five stylesheets in the order the application imports them, so what wins
// here is what wins on the screen. A declaration written against the token set
// resolves to a token reference; one that lost to a stylesheet predating that
// set resolves to that stylesheet's own value.
function mount(markup: string): HTMLElement {
  for (const sheet of [tokens, shell, surfaces, capture, picture]) {
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

// The rules a stylesheet holds, headers split on commas, at-rules skipped.
// Read from the source rather than from the cascade, because the defect this
// file exists to catch is a shorthand the cascade under it does not expand.
function styleRules(source: string): { selectors: string[]; body: string }[] {
  const text = source.replace(new RegExp("/\\*[\\s\\S]*?\\*/", "g"), " ");
  const found: { selectors: string[]; body: string }[] = [];
  const open: { header: string; from: number }[] = [];
  let mark = 0;
  for (let at = 0; at < text.length; at += 1) {
    if (text[at] === "{") { open.push({ header: text.slice(mark, at).trim(), from: at + 1 }); mark = at + 1; continue; }
    if (text[at] !== "}") continue;
    const rule = open.pop();
    // A rule nested inside an at-rule is a variation for one page width. The
    // base rule is what the cascade starts from, and mixing the two would read
    // a narrow-viewport override as the declaration of record.
    if (rule && !rule.header.startsWith("@") && !open.some((outer) => outer.header.startsWith("@"))) found.push({ selectors: rule.header.split(",").map((one) => one.trim().replace(new RegExp("\\s+", "g"), " ")), body: text.slice(rule.from, at) });
    mark = at + 1;
  }
  return found;
}

function declarationsOf(body: string): [string, string][] {
  return body.split(";").map((declaration) => declaration.split(":"))
    .filter((parts) => parts.length > 1 && parts[0].trim())
    .map((parts) => [parts[0].trim(), parts.slice(1).join(":").trim()] as [string, string]);
}

function ruleFor(source: string, selector: string): string {
  const bodies = styleRules(source).filter((rule) => rule.selectors.includes(selector)).map((rule) => rule.body);
  if (!bodies.length) throw new Error(`no rule for ${selector}`);
  return bodies.join(";");
}

function declarations(element: Element, properties: readonly string[]): Record<string, string> {
  const computed = getComputedStyle(element);
  return Object.fromEntries(properties.map((property) => [property, computed.getPropertyValue(property)]));
}

const twoFigures = `<div class="hero-card"><div class="picture-figures">
  <div class="picture-figure"><button class="figure-trigger hero-amount">AAA 1.00</button><p class="picture-citation">First.</p></div>
  <div class="picture-figure"><button class="figure-trigger hero-amount">BBB 2.00</button><p class="picture-citation">Second.</p></div>
</div></div>
<div class="account-card"><button class="figure-trigger account-amount">AAA 3.00</button></div>`;

describe("the picture's own stylesheet", () => {
  // Two totals held in two currencies are never added, and the layout says so
  // with space rather than with a rule. A rule would be a graphical object a
  // person has to see in order to follow the content, and one of those is held
  // to a contrast floor; space has no ratio to clear.
  it("separates one currency from the next with space and no graphical object", () => {
    const host = mount(twoFigures);
    for (const block of host.querySelectorAll(".picture-figure")) {
      expect(declarations(block, ["border-top-style", "border-bottom-style", "outline-style"]))
        .toEqual({ "border-top-style": "none", "border-bottom-style": "none", "outline-style": "none" });
    }
    // The room between two currencies against the room inside one. What reads
    // as two things rather than one is the difference between them, so the
    // difference is what this asserts.
    const between = declarations(host.querySelector(".picture-figures")!, ["gap"]).gap;
    const within = declarations(host.querySelector(".picture-figure")!, ["gap"]).gap;
    expect({ between, within }).toEqual({ between: "var(--space-3xl)", within: "var(--space-sm)" });
  });

  // The route to a figure's evidence is a row beneath it, in the place and the
  // words every other figure on this screen uses. It is not a mark on the
  // number: a mark under a numeral set in a serif face is cut into fragments
  // by its descenders and reads as damage to the total rather than as a way in.
  it("leaves the total unmarked and bounds an unusually long total inside its card", () => {
    const host = mount(twoFigures);
    expect(declarations(host.querySelector(".hero-amount")!, ["text-decoration-line"])).toEqual({ "text-decoration-line": "none" });
    // The ordinary figure stays together when it fits. A longer authored
    // currency-and-amount label may wrap rather than cross the card boundary
    // and obscure the picture coverage beside it.
    expect(declarations(host.querySelector(".hero-amount")!, ["max-width", "white-space", "overflow-wrap"]))
      .toEqual({ "max-width": "100%", "white-space": "normal", "overflow-wrap": "anywhere" });
    for (const rule of styleRules(picture)) for (const [property] of declarationsOf(rule.body)) {
      expect(property.startsWith("text-decoration"), `${rule.selectors.join(", ")} { ${property} }`).toBe(false);
      expect(property.startsWith("text-underline"), `${rule.selectors.join(", ")} { ${property} }`).toBe(false);
    }
  });

  // A currency kept back, and a picture with nothing to stand behind at all,
  // both stand where a number would have stood. A refusal laid out as a
  // footnote reads as a footnote about the total above it, which is a refusal
  // about the wrong thing.
  it("stands a refusal where a number would have stood", () => {
    const host = mount(`<div class="hero-card"><div class="picture-figures">
      <div class="picture-figure"><button class="figure-trigger hero-amount">AAA 1.00</button><p class="picture-citation">A boundary.</p></div>
      <div class="picture-figure picture-withheld"><p class="picture-standing">Kept back.</p></div>
    </div><div class="empty-state picture-empty"><span class="picture-standing">Nothing to stand behind.</span></div></div>`);
    for (const selector of [".picture-withheld", ".picture-empty"]) {
      expect(declarations(host.querySelector(selector)!, ["min-height"]), selector).toEqual({ "min-height": "var(--space-3xl)" });
    }
    // It opens its block rather than sitting where a footnote would, and it
    // carries the weight of the figure it stands in for.
    for (const selector of [".picture-withheld", ".picture-empty"]) {
      expect(declarations(host.querySelector(selector)!, ["align-content"]), selector).toEqual({ "align-content": "start" });
    }
    for (const standing of host.querySelectorAll(".picture-standing")) {
      expect(declarations(standing, ["font-size", "color"]))
        .toEqual({ "font-size": "var(--text-section)", color: "var(--ink)" });
    }
    // And it is not the size the citation beneath a figure is set at.
    const citation = declarations(host.querySelector(".picture-citation")!, ["font-size"]);
    expect(citation["font-size"]).toBe("var(--text-caption)");
  });

  // The citation is a stack of whole sentences, one line each, and the line
  // that differs between two figures is the last one a person reaches.
  it("gives each sentence of the citation its own line, in ordinary ink", () => {
    const host = mount(twoFigures);
    expect(declarations(host.querySelector(".picture-citation")!, ["display", "color", "font-size", "line-height", "margin"]))
      .toEqual({ display: "block", color: "var(--ink)", "font-size": "var(--text-caption)", "line-height": "var(--leading-body)", margin: "0px" });
  });

  // The number keeps its own spacing from the list rather than from the rule
  // that spaced a single hero figure.
  it("takes the space between currencies out of the list rather than the number", () => {
    const host = mount(twoFigures);
    expect(declarations(host.querySelector(".hero-amount")!, ["margin"])).toEqual({ margin: "0px" });
  });

  // The total is the largest thing on the screen and is set in the figure
  // face. It is a control as well as a number, and a rule that resets a
  // control's typography must not be able to outrank the rule that says what
  // the number looks like — so the reset lives on the element and never on a
  // class beside it.
  //
  // This is read off the stylesheets rather than off the computed style,
  // deliberately: the mechanism is the `font` shorthand, which sets family and
  // size at once, and the cascade this test can mount does not expand it. A
  // gate that asked the computed value here would agree with itself and miss
  // exactly the defect it exists for.
  it("sets the total in the figure face at the figure size, and lets no reset outrank it", () => {
    // The rules that reach a figure's control by naming nothing but the
    // control itself. Those are resets, and a reset may say nothing about
    // type: it ties on specificity with the class that says what the number
    // looks like and wins on order, so a number set in the figure face
    // survives only by where its rule happens to sit in the file. A rule that
    // scopes the control to a place — a detail panel, a card — is the class
    // that says it, and is not this.
    //
    // The `font` shorthand is the sharpest form of the hazard: it sets family
    // and size at once while appearing to name neither.
    const classesOf = (selector: string) => [...selector.matchAll(new RegExp("\\.(-?[_a-zA-Z][\\w-]*)", "g"))].map((match) => match[1]);
    const resets = [shell, surfaces, capture, picture].flatMap((sheet) => styleRules(sheet))
      .filter((rule) => rule.selectors.some((selector) => { const classes = classesOf(selector); return classes.length === 1 && classes[0] === "figure-trigger"; }));
    expect(resets.length).toBeGreaterThan(0);
    for (const rule of resets) for (const [property] of declarationsOf(rule.body)) {
      expect(property === "font" || property.startsWith("font-"), `${rule.selectors.join(", ")} { ${property} }`).toBe(false);
    }
    // And the class that does say it, says both.
    const declared = new Map(declarationsOf(ruleFor(surfaces, ".hero-amount")));
    expect(declared.get("font-family")).toContain("serif");
    expect(declared.get("font-size")).toBeDefined();
    expect(declared.get("font-size")).not.toBe("inherit");
    // The cascade this file can mount agrees, once nothing outranks it. It
    // cannot be the whole gate — it does not expand the shorthand — but it is
    // the half that reads what a person would get, and it reads the total
    // against the account figure beside it rather than against a number typed
    // here: the total is the largest thing on the screen or it is not the
    // total.
    const host = mount(twoFigures);
    const total = declarations(host.querySelector(".hero-amount")!, ["font-family", "font-size"]);
    const account = declarations(host.querySelector(".account-amount")!, ["font-family", "font-size"]);
    expect(total["font-family"]).toContain("serif");
    expect(total["font-family"]).toBe(account["font-family"]);
    expect(parseFloat(total["font-size"]), `${total["font-size"]} against ${account["font-size"]}`).toBeGreaterThan(parseFloat(account["font-size"]));
  });
});

describe("the rules this cycle changed beside the picture", () => {
  // The type scale is closed: a size that is not one of its steps is not a
  // size this product has. Every size the picture sets, and the two classes it
  // took over from the stylesheet that predates the scale, come off the scale
  // rather than being invented one class at a time. A raw value that happens
  // to equal a step is invisible to a ratchet that only sees a rise, so it is
  // the token that is asserted and not the number.
  it("sets every size it declares from the closed type scale", () => {
    const scale = [...styleRules(tokens).filter((rule) => rule.selectors.includes(":root"))
      .flatMap((rule) => declarationsOf(rule.body))
      .filter(([property]) => property.startsWith("--text-"))
      .map(([property]) => `var(${property})`)];
    expect(scale.length).toBeGreaterThan(0);
    const sized = [...styleRules(picture).flatMap((rule) => declarationsOf(rule.body).map((pair) => [rule.selectors.join(", "), ...pair] as [string, string, string])),
      ...declarationsOf(ruleFor(surfaces, ".hero-meta")).map((pair) => [".hero-meta", ...pair] as [string, string, string]),
      ...declarationsOf(ruleFor(surfaces, ".coverage-card p")).map((pair) => [".coverage-card p", ...pair] as [string, string, string])]
      .filter(([, property]) => property === "font-size");
    expect(sized.length).toBeGreaterThan(0);
    for (const [selector, , value] of sized) expect(scale, `${selector} { font-size: ${value} }`).toContain(value);
  });

  // A negative margin on the account amount pulls it over the copy beside it,
  // and the pull can only be tuned to how many rows that copy has. A layout
  // that depends on a row count breaks the next time a row moves, so nothing
  // pulls.
  it("places the account amount without pulling it over the copy beside it", () => {
    const rules = styleRules(surfaces).filter((rule) => rule.selectors.some((selector) => selector.includes(".account-amount")));
    expect(rules.length).toBeGreaterThan(0);
    for (const rule of rules) for (const [property, value] of declarationsOf(rule.body)) {
      if (!property.startsWith("margin")) continue;
      expect(value.includes("-"), `${rule.selectors.join(", ")} { ${property}: ${value} }`).toBe(false);
    }
  });
});
