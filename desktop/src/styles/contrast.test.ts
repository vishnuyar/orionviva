import { describe, expect, it } from "vitest";
import tokens from "./tokens.css?raw";
import shell from "./shell.css?raw";
import surfaces from "./surfaces.css?raw";
import capture from "./capture.css?raw";

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

// The declaration a selector actually carries, read from the stylesheet that
// carries it rather than restated here.
function declared(source: string, selector: string, property: string): string {
  const block = blockOf(source, selector);
  for (const declaration of block.split(";")) {
    const [name, ...rest] = declaration.split(":");
    if (name.trim() === property) return rest.join(":").trim();
  }
  throw new Error(`${selector} declares no ${property}`);
}

// Every stop of every page gradient the light palette paints, read out of the
// stylesheet that paints them. Nothing here is typed: a page repainted darker
// moves these, and what stands on it is measured again.
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
