import { describe, expect, it } from "vitest";
import tokens from "./tokens.css?raw";
import shell from "./shell.css?raw";
import surfaceBase from "./surface-base.css?raw";
import documents from "./documents.css?raw";
import surfacePrimitives from "./surface-primitives.css?raw";
import review from "./review.css?raw";
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

// What a person can actually read, measured rather than judged. The colours
// come from the token file, the grounds under them from the stylesheets that
// paint them, and the ratio is the one the accessibility floor is written in.
// A sentence the capture stylesheet dresses that falls under the floor fails
// here.
//
// Every pattern below is built with `new RegExp` rather than written as a
// regular-expression literal. The architecture checker tokenises this file,
// and its scanner stops advancing on a literal — see the refusal it raises.
const AA_TEXT = 4.5;
const AA_LARGE = 3;
const AA_NON_TEXT = 3;

// The properties that paint something a person reads, and the properties that
// paint something a person sees. Both are written as the CSS grammar for a
// paint, longhand and shorthand alike, because a colour written as part of a
// shorthand is the same colour on the screen. Anything else carrying a colour
// is refused rather than passed: a gate that silently ignores what it cannot
// classify reports a clean bill it could not have withheld.
const TEXT_PAINTS = ["color"];
const GRAPHICAL_PAINTS = [
  "background", "background-color", "background-image",
  "border", "border-color", "border-top", "border-right", "border-bottom", "border-left",
  "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
  "border-block", "border-block-start", "border-block-end", "border-inline", "border-inline-start", "border-inline-end",
  "outline", "outline-color", "box-shadow", "text-shadow", "text-decoration", "text-decoration-color",
  "column-rule", "column-rule-color", "caret-color", "accent-color", "fill", "stroke",
];

type Paint = { rgb: [number, number, number]; alpha: number };

// The body of one rule, so a token map is built from the mode that rule
// defines and never from every mode the file holds at once.
function blockOf(source: string, selector: string): string {
  const at = source.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule for ${selector}`);
  return source.slice(source.indexOf("{", at) + 1, source.indexOf("}", at));
}

function declarations(source: string): Map<string, string> {
  const declared = new Map<string, string>();
  for (const [, name, value] of source.matchAll(new RegExp("(--[\\w-]+)\\s*:\\s*([^;}]+)", "g"))) declared.set(name, value.trim());
  return declared;
}

// The palette the application renders. A second palette is defined behind a
// qualified `:root` and nothing turns it on, so what a person can read today
// is the plain one, and the two are held apart rather than flattened into each
// other. The qualified rule is found by its shape, so this file never writes
// the attribute that would select it.
function qualifiedRootBlock(source: string): string {
  const at = source.indexOf(":root[");
  if (at < 0) throw new Error("no qualified :root rule to hold apart from the rendered palette");
  return source.slice(source.indexOf("{", at) + 1, source.indexOf("}", at));
}
const light = declarations(blockOf(tokens, ":root"));
const dark = declarations(qualifiedRootBlock(tokens));

function resolve(value: string): string {
  const named = value.match(new RegExp("^var\\((--[\\w-]+)\\)$"));
  if (!named) return value;
  const held = light.get(named[1]);
  if (held === undefined) throw new Error(`no token named ${named[1]} in the light palette`);
  return held;
}

function paint(value: string): Paint {
  const resolved = resolve(value.trim());
  const hex = resolved.match(new RegExp("^#([0-9a-f]{6})$", "i"));
  if (hex) return { rgb: [parseInt(hex[1].slice(0, 2), 16), parseInt(hex[1].slice(2, 4), 16), parseInt(hex[1].slice(4, 6), 16)], alpha: 1 };
  const rgba = resolved.match(new RegExp("^rgba?\\(\\s*([\\d.]+)[,\\s]+([\\d.]+)[,\\s]+([\\d.]+)(?:[,/\\s]+([\\d.]+))?\\s*\\)$", "i"));
  if (!rgba) throw new Error(`not a flat colour: ${resolved}`);
  return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], alpha: rgba[4] === undefined ? 1 : Number(rgba[4]) };
}

// Every layer painted in turn onto the one behind it, so a translucent ground
// is measured as what a person sees rather than as what it declares.
function stack(base: string, ...layers: string[]): [number, number, number] {
  let seen = paint(base).rgb;
  for (const layer of layers) {
    const over = paint(layer);
    seen = [0, 1, 2].map((channel) => Math.round(over.rgb[channel] * over.alpha + seen[channel] * (1 - over.alpha))) as [number, number, number];
  }
  return seen;
}

function relativeLuminance([red, green, blue]: [number, number, number]): number {
  const channel = (value: number) => { const part = value / 255; return part <= 0.04045 ? part / 12.92 : Math.pow((part + 0.055) / 1.055, 2.4); };
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
}

function contrast(front: string, ground: [number, number, number]): number {
  const [lighter, darker] = [relativeLuminance(paint(front).rgb), relativeLuminance(ground)].sort((first, second) => second - first);
  return (lighter + 0.05) / (darker + 0.05);
}

// Every rule a stylesheet holds, with its header split into the selectors it
// groups. A rule nested inside an at-rule is still a rule; the at-rule that
// holds it is not one, so a page-width variation is read as the rules it
// carries rather than as one block.
type Rule = { selectors: string[]; body: string };

function rules(source: string): Rule[] {
  // A comment sits between two rules and would otherwise be read as part of
  // the header that follows it.
  const text = source.replace(new RegExp("/\\*[\\s\\S]*?\\*/", "g"), " ");
  const found: Rule[] = [];
  const open: { header: string; from: number }[] = [];
  let mark = 0;
  for (let at = 0; at < text.length; at += 1) {
    if (text[at] === "{") {
      open.push({ header: text.slice(mark, at).trim(), from: at + 1 });
      mark = at + 1;
      continue;
    }
    if (text[at] !== "}") continue;
    const rule = open.pop();
    if (rule && !rule.header.startsWith("@")) found.push({ selectors: rule.header.split(",").map((one) => one.trim().replace(new RegExp("\\s+", "g"), " ")), body: text.slice(rule.from, at) });
    mark = at + 1;
  }
  return found;
}

// The declaration a selector actually carries, read from the stylesheet that
// carries it rather than restated here. A selector written alongside others
// under one header is found among them rather than missed, and where more than
// one rule declares the same property the last one is the one that paints —
// which is the only one a person can see.
function declared(source: string, selector: string, property: string): string {
  const values: string[] = [];
  for (const rule of rules(source)) {
    if (!rule.selectors.includes(selector)) continue;
    for (const declaration of rule.body.split(";")) {
      const [name, ...rest] = declaration.split(":");
      if (name.trim() === property) values.push(rest.join(":").trim());
    }
  }
  if (!values.length) throw new Error(`${selector} declares no ${property}`);
  return values[values.length - 1];
}

// Every stop of every page gradient the light palette paints, read out of the
// stylesheet that paints them. Nothing here is typed: a page repainted darker
// moves these, and what stands on it is measured again.
// Which token names hold a colour, decided by whether the value each one
// declares parses as one. Nothing here is a list of names anybody chose.
const colourTokens = [...light.entries()].filter(([, value]) => { try { paint(value); return true; } catch { return false; } }).map(([name]) => name);

// Every colour a declaration carries, wherever in its value it sits.
function coloursIn(value: string): string[] {
  const found: string[] = [];
  for (const match of value.matchAll(new RegExp("var\\((--[\\w-]+)\\)", "g"))) if (colourTokens.includes(match[1])) found.push(`var(${match[1]})`);
  for (const match of value.matchAll(new RegExp("#[0-9a-f]{3,8}(?![\\w-])", "gi"))) found.push(match[0]);
  for (const match of value.matchAll(new RegExp("rgba?\\([^)]*\\)", "gi"))) found.push(match[0]);
  return found;
}

const lightSource = tokens.replace(qualifiedRootBlock(tokens), "");
const grounds = [...new Set([...lightSource.matchAll(new RegExp("linear-gradient\\(180deg,\\s*(#[0-9a-f]{6})\\s*0%,\\s*(#[0-9a-f]{6})\\s*100%\\)", "g"))].flatMap((match) => [match[1], match[2]]))];

describe("what a person can read on the screens this cycle authored", () => {
  it("measures the palette the application renders, not the one it merely defines", () => {
    expect(light.get("--ink")).toBe("#21332c");
    expect(dark.get("--ink")).not.toBe(light.get("--ink"));
    expect(dark.get("--paper")).not.toBe(light.get("--paper"));
    expect(paint("var(--ink)").rgb).toEqual([0x21, 0x33, 0x2c]);
    expect(paint("var(--paper)").alpha).toBeLessThan(1);
  });

  it("reads the page's own grounds out of the stylesheet that paints them", () => {
    expect(grounds.length).toBeGreaterThanOrEqual(2);
    for (const page of grounds) expect(relativeLuminance(paint(page).rgb), `page ground ${page}`).toBeGreaterThan(0.5);
  });

  it("puts the passphrase consequence above the floor at the size it renders", () => {
    const ink = declared(capture, ".vault-open-form .vault-passphrase-consequence", "color");
    const paper = declared(capture, ".vault-open-form .vault-passphrase-consequence", "background");
    expect(resolve(declared(capture, ".vault-open-form .vault-passphrase-consequence", "font-size"))).toBe("14px");
    for (const page of grounds) {
      const ground = stack(page, declared(shell, ".sidebar", "background"), declared(shell, ".vault-source-card", "background"), paper);
      expect(contrast(ink, ground), `passphrase on ${page}`).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  it("puts a refusal's words, its dismiss control and its border above their floors", () => {
    const ink = declared(capture, ".notice.notice-refused", "color");
    const paper = declared(capture, ".notice.notice-refused", "background");
    const border = declared(capture, ".notice.notice-refused", "border-color");
    const close = declared(capture, ".notice.notice-refused .notice-close", "color");
    for (const page of grounds) {
      const ground = stack(page, paper);
      expect(contrast(ink, ground), `refusal words on ${page}`).toBeGreaterThanOrEqual(AA_TEXT);
      expect(contrast(close, ground), `refusal dismiss on ${page}`).toBeGreaterThanOrEqual(AA_TEXT);
      expect(contrast(border, ground), `refusal border on ${page}`).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
  });

  // The review screen already dresses a refusal: the border carries the signal
  // and the words stay in ordinary ink. One signal, not three.
  it("dresses a refusal the way the screen that already ships one dresses it", () => {
    const precedent = declared(surfaces, ".review-outcome", "border");
    const border = declared(capture, ".notice.notice-refused", "border-color");
    const words = declared(capture, ".notice.notice-refused", "color");
    const close = declared(capture, ".notice.notice-refused .notice-close", "color");
    expect(precedent).toContain(border);
    expect(words).not.toBe(border);
    expect(close).toBe(words);
    expect(paint(words).rgb).toEqual(paint("var(--ink)").rgb);
  });

  // The picture's own sentence about how far it reaches, on the card that
  // heads it. A citation painted quieter than the figure it qualifies is a
  // citation the product is apologising for, so subordination comes from size
  // and position and never from contrast.
  it("puts the picture's coverage sentence above the floor at the size it renders", () => {
    const ink = declared(surfaces, ".coverage-card p", "color");
    const card = declared(surfaces, ".coverage-card", "background");
    const size = Number(resolve(declared(surfaces, ".coverage-card p", "font-size")).replace("px", ""));
    const floor = size >= 24 ? AA_LARGE : AA_TEXT;
    for (const page of grounds) {
      expect(contrast(ink, stack(page, card)), `picture coverage on ${page}`).toBeGreaterThanOrEqual(floor);
    }
  });

  // The line beside a picture figure that says how well the number is stood
  // behind. It is the whole of X2's second clause on this screen, so it is not
  // decoration and is not painted as any.
  it("puts the picture figure's grade line above the floor at the size it renders", () => {
    const ink = declared(surfaces, ".hero-meta", "color");
    const paper = declared(surfaces, ".hero-card", "background");
    const size = Number(resolve(declared(surfaces, ".hero-meta", "font-size")).replace("px", ""));
    const floor = size >= 24 ? AA_LARGE : AA_TEXT;
    for (const page of grounds) {
      expect(contrast(ink, stack(page, paper)), `picture grade line on ${page}`).toBeGreaterThanOrEqual(floor);
    }
  });

  // The citation each currency's figure carries. It renders on the paper the
  // hero card is painted in, at the smallest step the type scale has.
  it("puts the picture figure's citation above the floor at the size it renders", () => {
    const ink = declared(picture, ".hero-card .picture-figure .picture-citation", "color");
    const paper = declared(surfaces, ".hero-card", "background");
    const size = Number(resolve(declared(picture, ".hero-card .picture-figure .picture-citation", "font-size")).replace("px", ""));
    const floor = size >= 24 ? AA_LARGE : AA_TEXT;
    for (const page of grounds) {
      expect(contrast(ink, stack(page, paper)), `picture citation on ${page}`).toBeGreaterThanOrEqual(floor);
    }
  });

  // An account the picture could not place under any currency, named on the
  // panel because it is named nowhere else. It renders on the coverage card's
  // own ground, beside the sentence about how far the picture reaches.
  it("puts an account named nowhere else above the floor at the size it renders", () => {
    const card = declared(surfaces, ".coverage-card", "background");
    const ink = declared(picture, ".coverage-card .picture-unplaced li", "color");
    for (const selector of [".coverage-card .picture-unplaced strong", ".coverage-card .picture-unplaced span"]) {
      const size = Number(resolve(declared(picture, selector, "font-size")).replace("px", ""));
      const floor = size >= 24 ? AA_LARGE : AA_TEXT;
      for (const page of grounds) {
        expect(contrast(ink, stack(page, card)), `${selector} on ${page}`).toBeGreaterThanOrEqual(floor);
      }
    }
  });

  // A grade's badge and the mark beside it. The pill said every word on the
  // ladder in one colour, so a figure whose records disagree arrived in the
  // colour of a figure that is fine; the pill is neutral now and the mark is
  // what tells them apart, so the mark is a graphical object a person has to
  // see in order to follow the content.
  it("puts a grade's word and its mark above their floors", () => {
    const paper = declared(surfaces, ".hero-card", "background");
    const pill = declared(surfaces, ".evidence-badge", "background");
    const word = declared(surfaces, ".evidence-badge", "color");
    const size = Number(resolve(declared(surfaces, ".evidence-badge", "font-size")).replace("px", ""));
    const floor = size >= 24 ? AA_LARGE : AA_TEXT;
    // The conflicted grade's mark, the one this diff paints. The other
    // grades' marks are measured and filed rather than repainted: they sit
    // below this floor on a pill no change here touches.
    const mark = declared(surfaces, ".mini-dot.conflicted", "background");
    for (const page of grounds) {
      const ground = stack(page, paper, pill);
      expect(contrast(word, ground), `a grade's word on ${page}`).toBeGreaterThanOrEqual(floor);
      expect(contrast(mark, ground), `the conflicted mark on ${page}`).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
  });

  // The row that leads into a figure's evidence. Its edge is what says it is a
  // control at all, so the edge is measured too.
  it("puts the route into a figure's evidence above its floors", () => {
    const paper = declared(surfaces, ".hero-card", "background");
    const chip = declared(surfaces, ".proof-link", "background");
    const ink = declared(surfaces, ".proof-link", "color");
    const edge = declared(surfaces, ".proof-link", "border-color");
    const size = Number(resolve(declared(surfaces, ".proof-link", "font-size")).replace("px", ""));
    const floor = size >= 24 ? AA_LARGE : AA_TEXT;
    for (const page of grounds) {
      const ground = stack(page, paper, chip);
      expect(contrast(ink, ground), `the route's words on ${page}`).toBeGreaterThanOrEqual(floor);
      expect(contrast(edge, ground), `the route's edge on ${page}`).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
  });

  // The total itself, at the size and on the paper the picture gives it.
  it("puts the total above the floor at the size it renders", () => {
    const ink = declared(surfaces, ".hero-amount", "color");
    const paper = declared(surfaces, ".hero-card", "background");
    for (const page of grounds) {
      expect(contrast(ink, stack(page, paper)), `the total on ${page}`).toBeGreaterThanOrEqual(AA_TEXT);
    }
  });

  // Anything the picture paints that a person has to see in order to follow the
  // content is measured at the ground it renders on, never judged, and a
  // colour on a property this gate cannot place is refused rather than waved
  // through: a gate that silently ignores a paint it cannot classify reports a
  // clean bill it could not have withheld.
  //
  // The picture separates one currency from the next with space rather than a
  // rule, because space carries the same "these are two" and has no ratio to
  // clear, and a rule cannot be load-bearing when it is justified and
  // decorative when it is measured.
  it("measures every graphical object the picture paints, and refuses a colour it cannot place", () => {
    const walked = rules(picture);
    expect(walked.length).toBeGreaterThan(0);
    const paper = declared(surfaces, ".hero-card", "background");
    const graphical: { property: string; colour: string }[] = [];
    const unplaced: string[] = [];
    let carried = 0;
    for (const rule of walked) for (const declaration of rule.body.split(";")) {
      const [name, ...rest] = declaration.split(":");
      const property = name.trim();
      const value = rest.join(":").trim();
      if (!property || !value) continue;
      const colours = coloursIn(value);
      carried += colours.length;
      if (!colours.length || TEXT_PAINTS.includes(property)) continue;
      if (GRAPHICAL_PAINTS.includes(property)) { for (const colour of colours) graphical.push({ property, colour }); continue; }
      unplaced.push(`${property}: ${value}`);
    }
    // The sweep read real declarations and found real colours, so a clean bill
    // below is one it could have withheld.
    expect(carried).toBeGreaterThan(0);
    expect(unplaced, "a colour on a property this gate cannot place").toEqual([]);
    for (const { property, colour } of graphical) for (const page of grounds) {
      expect(contrast(colour, stack(page, paper)), `picture ${property} ${colour} on ${page}`).toBeGreaterThanOrEqual(AA_NON_TEXT);
    }
    expect(graphical, "the picture separates its currencies with space, not with an object").toEqual([]);
    // What says two totals are two is the room between them against the room
    // inside either, both read out of the stylesheet that declares them.
    const between = Number(resolve(declared(picture, ".hero-card .picture-figures", "gap")).replace("px", ""));
    const within = Number(resolve(declared(picture, ".hero-card .picture-figure", "gap")).replace("px", ""));
    expect(between / within, `${between}px between currencies against ${within}px inside one`).toBeGreaterThanOrEqual(4);
  });

  it("puts the capture answer and the panel's reading sentence above the floor", () => {
    const answer = declared(capture, ".documents-surface .document-capture-answer p", "color");
    const title = declared(capture, ".documents-surface .document-capture-answer strong", "color");
    const size = resolve(declared(capture, ".documents-surface .document-capture-answer p", "font-size"));
    const floor = Number(size.replace("px", "")) >= 24 ? AA_LARGE : AA_TEXT;
    for (const page of grounds) {
      const ground = stack(page, declared(surfaces, ".feature-panel", "background"));
      expect(contrast(answer, ground), `capture answer on ${page}`).toBeGreaterThanOrEqual(floor);
      expect(contrast(title, ground), `capture answer title on ${page}`).toBeGreaterThanOrEqual(floor);
    }
  });
});
