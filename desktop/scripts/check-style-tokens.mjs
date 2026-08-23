import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The file that defines the token set. It is the one stylesheet allowed to
// carry a raw value, because a value has to be written down somewhere once.
const tokenFile = "tokens.css";

// The stylesheets that predate the token set. They are ratcheted rather than
// migrated: their counts may fall and may never rise. Every other stylesheet
// under the styles directory is held to zero, whatever it is called.
const ratchetFiles = [
  "shell.css", "surfaces.css", "surface-base.css", "documents.css",
  "surface-primitives.css", "review.css", "surface-details.css",
  "conversation.css", "activity.css", "trust.css", "evidence.css",
  "surface-responsive.css",
];

const colourTokens = ["--ink", "--muted", "--line", "--paper", "--panel", "--sage", "--moss", "--rust", "--gold"];
const typeTokens = ["--text-caption", "--text-fine", "--text-body", "--text-lead", "--text-title", "--text-section", "--text-page", "--text-display"];
const leadingTokens = ["--leading-tight", "--leading-body", "--leading-loose"];
const weightTokens = ["--weight-regular", "--weight-medium", "--weight-strong"];
const spaceTokens = ["--space-hair", "--space-xs", "--space-sm", "--space-md", "--space-lg", "--space-xl", "--space-2xl", "--space-3xl"];
const radiusTokens = ["--radius-sm", "--radius-md", "--radius-lg", "--radius-xl", "--radius-pill", "--radius-circle"];
const durationTokens = ["--duration-quick", "--duration-settle", "--duration-drift"];
const easingTokens = ["--ease-standard", "--ease-enter", "--ease-exit"];
const iconTokens = ["--icon-xs", "--icon-sm", "--icon-md", "--icon-lg", "--icon-xl"];
const requiredTokens = [...colourTokens, ...typeTokens, ...leadingTokens, ...weightTokens, ...spaceTokens, ...radiusTokens, ...durationTokens, ...easingTokens, ...iconTokens];

// The dark palette is selected by this attribute and nothing sets it. Both
// halves of that sentence are checked: the block exists, and no module writes
// the attribute, and no stylesheet asks the operating system.
const darkSelector = ':root[data-theme="dark"]';
const darkAttribute = "data-theme";
const systemColourQuery = "prefers-color-scheme";
const reducedMotionQuery = "prefers-reduced-motion";

// Motion is forbidden where a figure or a grade is read. A number that slides
// into place, or a confidence label that fades between states, invites a
// person to read the movement as part of the claim.
const moneyClassPrefixes = ["hero-amount", "account-amount", "coverage-number", "signal-value", "figure", "detail-figure", "activity-detail-figure", "activity-list-figure", "selected-account-figure"];
const gradeClassPrefixes = ["identity-state", "activity-identity-state", "conversation-identity-state", "trust-identity-state", "precision-state", "review-source-state", "evidence-target-state", "trust-state-label", "state-pill", "status-dot", "evidence-badge", "preview-badge", "activity-row-badge", "document-capture-status"];
// Each prefix has to earn its place: the gate fails when one matches no class
// in any stylesheet, so renaming a guarded class is loud rather than silent.
const guardedClassPrefixes = [...moneyClassPrefixes, ...gradeClassPrefixes];

// Literal characters standing in for an icon, and the shape of an icon size
// written as a bare number. Both are counted, neither is replaced.
const glyphStandIns = ["◎", "↑", "↓", "•", "×"];
const bareIconSize = /size=\{\d+\}/g;

const categoryOfProperty = new Map();
function assignCategory(category, properties) { for (const property of properties) categoryOfProperty.set(property, category); }
assignCategory("type", ["font-size"]);
assignCategory("leading", ["line-height"]);
assignCategory("weight", ["font-weight"]);
assignCategory("space", ["margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "margin-inline", "margin-block", "margin-inline-start", "margin-inline-end", "margin-block-start", "margin-block-end", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "padding-inline", "padding-block", "padding-inline-start", "padding-inline-end", "padding-block-start", "padding-block-end", "gap", "row-gap", "column-gap", "inset", "top", "right", "bottom", "left"]);
assignCategory("radius", ["border-radius", "border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius"]);
assignCategory("colour", ["color", "background", "background-color", "background-image", "border", "border-top", "border-right", "border-bottom", "border-left", "border-color", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color", "outline", "outline-color", "fill", "stroke", "box-shadow", "text-shadow", "caret-color", "accent-color"]);
assignCategory("motion", ["transition", "transition-duration", "transition-delay", "transition-timing-function", "animation", "animation-duration", "animation-delay", "animation-timing-function"]);

// What a raw value looks like, per category. These are shapes — a number with
// a unit, a hex triple, a colour function, a curve from the CSS grammar — not
// a list of words anyone chose.
const literalPatterns = new Map([
  ["type", [/-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|pt)\b/g]],
  ["leading", [/(?<![\w.#-])(?:\d+\.?\d*|\.\d+)(?:px|rem|em)?(?![\w%.-])/g]],
  ["weight", [/(?<![\w.#-])[1-9]00(?![\w.%-])/g, /(?<![\w-])(?:bolder|lighter|bold)(?![\w-])/g]],
  ["space", [/-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|ch|ex)\b/g]],
  ["radius", [/-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|%)/g]],
  ["colour", [/#[0-9a-fA-F]{3,8}\b/g, /(?<![\w-])(?:rgba|rgb|hsla|hsl|color-mix)\(/g]],
  ["motion", [/(?<![\w-])(?:\d+\.?\d*|\.\d+)m?s\b/g, /(?<![\w-])(?:cubic-bezier|steps)\(/g, /(?<![\w-])(?:ease-in-out|ease-in|ease-out|ease|linear|step-start|step-end)(?![\w-])/g]],
]);
const categories = [...literalPatterns.keys()].sort();

// The size of what is not migrated, measured against the tree by
// `node scripts/check-style-tokens.mjs --write-baseline`. It is written by the
// generator and never by hand.
// baseline start
const baseline = {
  "ratchet": {
    "shell.css": {
      "colour": 67,
      "leading": 7,
      "motion": 4,
      "radius": 17,
      "space": 71,
      "type": 31,
      "weight": 18
    },
    "surfaces.css": {
      "colour": 0,
      "leading": 0,
      "motion": 0,
      "radius": 0,
      "space": 0,
      "type": 0,
      "weight": 0
    },
    "surface-base.css": {
      "colour": 32,
      "leading": 8,
      "motion": 0,
      "radius": 7,
      "space": 46,
      "type": 19,
      "weight": 10
    },
    "documents.css": {
      "colour": 14,
      "leading": 5,
      "motion": 0,
      "radius": 3,
      "space": 19,
      "type": 7,
      "weight": 0
    },
    "surface-primitives.css": {
      "colour": 36,
      "leading": 3,
      "motion": 0,
      "radius": 5,
      "space": 32,
      "type": 17,
      "weight": 4
    },
    "review.css": {
      "colour": 35,
      "leading": 8,
      "motion": 0,
      "radius": 8,
      "space": 35,
      "type": 15,
      "weight": 3
    },
    "surface-details.css": {
      "colour": 2,
      "leading": 0,
      "motion": 0,
      "radius": 0,
      "space": 4,
      "type": 3,
      "weight": 1
    },
    "conversation.css": {
      "colour": 39,
      "leading": 8,
      "motion": 0,
      "radius": 7,
      "space": 30,
      "type": 17,
      "weight": 3
    },
    "activity.css": {
      "colour": 30,
      "leading": 6,
      "motion": 0,
      "radius": 6,
      "space": 34,
      "type": 14,
      "weight": 7
    },
    "trust.css": {
      "colour": 21,
      "leading": 4,
      "motion": 0,
      "radius": 4,
      "space": 22,
      "type": 7,
      "weight": 3
    },
    "evidence.css": {
      "colour": 32,
      "leading": 3,
      "motion": 0,
      "radius": 6,
      "space": 23,
      "type": 13,
      "weight": 4
    },
    "surface-responsive.css": {
      "colour": 2,
      "leading": 1,
      "motion": 2,
      "radius": 0,
      "space": 47,
      "type": 5,
      "weight": 0
    }
  },
  "icons": {
    "glyphStandIns": 3,
    "bareIconSizes": 17
  }
};
// baseline end

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, " "));
}

function lineAt(text, index) {
  let line = 1;
  for (let cursor = 0; cursor < index; cursor += 1) if (text[cursor] === "\n") line += 1;
  return line;
}

// A CSS declaration reader. Its subject is `property: value` inside a block,
// with the block headers it sits under, which is what every rule below asks
// about. It is deliberately not a TypeScript parser and not a prose reader.
function scanCss(text) {
  const source = stripComments(text);
  const found = [];
  const seen = [];
  const headers = [];
  let buffer = "";
  let bufferStart = 0;
  let parens = 0;
  let quote = null;
  const flush = () => {
    const trimmed = buffer.trim();
    buffer = "";
    if (!trimmed || !headers.length) return;
    if (headers[headers.length - 1].startsWith("@")) return;
    const split = trimmed.indexOf(":");
    if (split < 0) return;
    found.push({
      selector: headers[headers.length - 1],
      enclosing: [...headers],
      property: trimmed.slice(0, split).trim(),
      value: trimmed.slice(split + 1).trim(),
      line: lineAt(source, bufferStart),
    });
  };
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (!buffer.trim() && character.trim()) bufferStart = index;
    if (quote) {
      buffer += character;
      if (character === quote && source[index - 1] !== "\\") quote = null;
      continue;
    }
    if (character === '"' || character === "'") { quote = character; buffer += character; continue; }
    if (character === "(") parens += 1;
    if (character === ")") parens -= 1;
    if (parens === 0 && character === "{") { const header = buffer.trim().replace(/\s+/g, " "); headers.push(header); seen.push(header); buffer = ""; continue; }
    if (parens === 0 && character === "}") { flush(); headers.pop(); continue; }
    if (parens === 0 && character === ";") { flush(); continue; }
    buffer += character;
  }
  return { declarations: found, selectors: seen.filter((header) => !header.startsWith("@")) };
}

function declarations(text) { return scanCss(text).declarations; }

// Every block header, including one whose block is empty. A rule that declares
// nothing still tells the gate which classes this product has.
function blockSelectors(text) { return scanCss(text).selectors; }

function withoutVariables(value) {
  let text = value;
  let previous = null;
  while (previous !== text) {
    previous = text;
    text = text.replace(/var\(\s*--[\w-]+\s*(,([^()]|\([^()]*\))*)?\)/g, " ");
  }
  return text;
}

function rawLiterals(property, value) {
  const category = categoryOfProperty.get(property);
  if (!category) return [];
  const remainder = withoutVariables(value).replace(/!important/g, " ");
  const literals = [];
  for (const pattern of literalPatterns.get(category)) for (const match of remainder.matchAll(pattern)) literals.push(match[0]);
  // Zero is not a design decision, so the token set does not hold one and a
  // stylesheet writing one has not stepped outside it.
  return literals.filter((literal) => !/^-?(?:0+\.?0*|\.0+)(?:px|rem|em|ch|ex|pt|%|ms|s)?$/.test(literal));
}

function emptyCounts() {
  return Object.fromEntries(categories.map((category) => [category, 0]));
}

function measure(text) {
  const counts = emptyCounts();
  for (const declaration of declarations(text)) {
    if (declaration.property.startsWith("--")) continue;
    const category = categoryOfProperty.get(declaration.property);
    if (!category) continue;
    counts[category] += rawLiterals(declaration.property, declaration.value).length;
  }
  return counts;
}

function classNames(selector) {
  return [...selector.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((match) => match[1]);
}

function matchesPrefix(name, prefix) { return name === prefix || name.startsWith(`${prefix}-`); }

// How far the motion prohibition actually reaches. The list is an enumeration
// of classes this product declares, not a reader of what a name looks like, so
// its reach is a number worth measuring and printing rather than assuming.
function guardedCoverage(styles, prefixes) {
  const present = [...new Set([...styles.values()].flatMap((text) => blockSelectors(text).flatMap(classNames)))];
  return {
    covered: present.filter((name) => prefixes.some((prefix) => matchesPrefix(name, prefix))).sort(),
    empty: prefixes.filter((prefix) => !present.some((name) => matchesPrefix(name, prefix))),
  };
}

// A class name that provably matches no declared prefix, derived rather than
// chosen, so the case that proves the prohibition does not guess stays true
// whatever joins the list.
function undeclaredClassName(prefixes) {
  let name = "money-amount";
  while (prefixes.some((prefix) => matchesPrefix(name, prefix))) name = `not-${name}`;
  return name;
}

function totalRaw(counts) { return Object.values(counts).reduce((total, count) => total + count, 0); }

// The report counts what this run walked. A recorded baseline is a ceiling the
// ratchet enforces, never a number the report recites: a migrated value has to
// show up here the moment it lands, or the line is a claim nobody measured.
function measurementLines({ styles, modules, baseline, prefixes }) {
  const measured = Object.fromEntries(ratchetFiles.map((name) => [name, measure(styles.get(name) ?? "")]));
  const debt = ratchetFiles.map((name) => `${name} ${totalRaw(measured[name])}`).join(", ");
  const icons = countIcons(modules);
  const tokenCount = tokensDeclaredIn(styles.get(tokenFile) ?? "", isBaseBlock).size;
  const slack = [
    ...ratchetFiles.map((name) => ({ name, below: totalRaw(baseline.ratchet[name] ?? {}) - totalRaw(measured[name]) })),
    { name: "glyph stand-ins", below: baseline.icons.glyphStandIns - icons.glyphStandIns },
    { name: "bare icon sizes", below: baseline.icons.bareIconSizes - icons.bareIconSizes },
  ].filter((entry) => entry.below > 0);
  return [
    `Style tokens passed (${styles.size} stylesheets, ${tokenCount} tokens).`,
    `Raw values still outside the token system: ${debt}. Icon stand-ins: ${icons.glyphStandIns} glyphs, ${icons.bareIconSizes} bare sizes.`,
    ...(slack.length ? [`Ratchet slack: ${slack.map((entry) => `${entry.below} below the recorded ceiling on ${entry.name}`).join(", ")}. Regenerate the baseline to tighten it.`] : []),
    ...reachLines(styles, prefixes),
  ];
}

function reachLines(styles, prefixes) {
  const { covered } = guardedCoverage(styles, prefixes);
  return [
    `Motion is refused near money and grades on ${covered.length} classes, named by ${prefixes.length} declared prefixes.`,
    "A class not named by one of those prefixes is not seen, so a new money or grade surface joins the list in this script.",
  ];
}

function guardedClass(name, prefixes) {
  return prefixes.find((prefix) => matchesPrefix(name, prefix)) ?? null;
}

function suppressesMotion(value) {
  const remainder = withoutVariables(value).replace(/!important/g, " ").trim();
  if (/^none$/i.test(remainder)) return true;
  const durations = [...remainder.matchAll(/(?<![\w-])(?:\d+\.?\d*|\.\d+)m?s\b/g)].map((match) => match[0]);
  return durations.length > 0 && durations.every((duration) => Number.parseFloat(duration) === 0);
}

function definedTokens(text) {
  const defined = new Set();
  for (const declaration of declarations(text)) if (declaration.property.startsWith("--")) defined.add(declaration.property);
  return defined;
}

// A token counts as declared by a block only when that block is exactly where
// it sits, so a name present in the dark palette does not stand in for a name
// missing from the base one.
function tokensDeclaredIn(text, accepts) {
  const declared = new Set();
  for (const declaration of declarations(text)) {
    if (!declaration.property.startsWith("--")) continue;
    if (accepts(declaration.enclosing)) declared.add(declaration.property);
  }
  return declared;
}

function isBaseBlock(enclosing) { return enclosing.length === 1 && enclosing[0] === ":root"; }
function isDarkBlock(enclosing) { return enclosing.length === 1 && enclosing[0] === darkSelector; }
function isReducedMotionBlock(enclosing) { return enclosing.length === 2 && enclosing[0].startsWith("@media") && enclosing[0].includes(reducedMotionQuery); }

function countIcons(modules) {
  let glyphs = 0;
  let sizes = 0;
  for (const text of modules.values()) {
    for (const glyph of glyphStandIns) glyphs += text.split(glyph).length - 1;
    sizes += [...text.matchAll(bareIconSize)].length;
  }
  return { glyphStandIns: glyphs, bareIconSizes: sizes };
}

function collectViolations({ styles, modules, baseline, prefixes = guardedClassPrefixes }) {
  const violations = [];
  if (!styles.size) violations.push("no stylesheet found: the token gate has nothing to read");
  if (!modules.size) violations.push("no module found: the icon ratchet has nothing to read");
  if (!styles.has(tokenFile)) violations.push(`stylesheet missing: ${tokenFile}`);
  for (const name of Object.keys(baseline.ratchet)) if (!styles.has(name)) violations.push(`stylesheet missing: ${name}`);

  const tokenText = styles.get(tokenFile) ?? "";
  const defined = definedTokens(tokenText);
  const base = tokensDeclaredIn(tokenText, isBaseBlock);
  for (const token of requiredTokens) if (!base.has(token)) violations.push(`token missing from the token file: ${token}`);

  const dark = tokensDeclaredIn(tokenText, isDarkBlock);
  for (const token of colourTokens) if (!dark.has(token)) violations.push(`dark palette incomplete: ${token}`);
  for (const token of dark) if (!colourTokens.includes(token)) violations.push(`dark palette name unknown: ${token}`);
  const reset = tokensDeclaredIn(tokenText, isReducedMotionBlock);
  for (const token of durationTokens) if (!reset.has(token)) violations.push(`reduced motion does not reset: ${token}`);

  for (const prefix of guardedCoverage(styles, prefixes).empty) violations.push(`guarded class prefix matches nothing: ${prefix}`);

  for (const [name, text] of styles) {
    const stripped = stripComments(text);
    if (stripped.includes(systemColourQuery)) violations.push(`dark palette activated: ${name} asks ${systemColourQuery}`);
    for (const declaration of declarations(text)) {
      if (declaration.property.startsWith("--") && name !== tokenFile) violations.push(`token defined outside the token file: ${name}:${declaration.line} ${declaration.property}`);
      for (const match of declaration.value.matchAll(/var\(\s*(--[\w-]+)/g)) if (!defined.has(match[1])) violations.push(`undefined token used: ${name}:${declaration.line} var(${match[1]})`);
      const guarded = classNames(declaration.selector).map((name) => guardedClass(name, prefixes)).find(Boolean);
      if (guarded && categoryOfProperty.get(declaration.property) === "motion" && !suppressesMotion(declaration.value)) {
        violations.push(`motion forbidden near money or grade: ${name}:${declaration.line} .${guarded} (${declaration.property})`);
      }
    }
  }

  for (const [name, text] of styles) {
    if (name === tokenFile) continue;
    const counts = measure(text);
    const allowed = baseline.ratchet[name] ?? emptyCounts();
    for (const category of categories) {
      if (counts[category] <= (allowed[category] ?? 0)) continue;
      if (name in baseline.ratchet) violations.push(`raw value count rose: ${name} ${category} ${counts[category]} over the recorded ${allowed[category] ?? 0}`);
      else for (const declaration of declarations(text)) {
        if (categoryOfProperty.get(declaration.property) !== category) continue;
        for (const literal of rawLiterals(declaration.property, declaration.value)) {
          violations.push(`raw value outside the token system: ${name}:${declaration.line} ${declaration.property} (${literal})`);
        }
      }
    }
  }

  for (const [name, text] of modules) if (text.includes(darkAttribute)) violations.push(`dark palette activated: ${name} sets ${darkAttribute}`);
  const icons = countIcons(modules);
  if (icons.glyphStandIns > baseline.icons.glyphStandIns) violations.push(`icon stand-in count rose: ${icons.glyphStandIns} glyphs over the recorded ${baseline.icons.glyphStandIns}`);
  if (icons.bareIconSizes > baseline.icons.bareIconSizes) violations.push(`bare icon size count rose: ${icons.bareIconSizes} over the recorded ${baseline.icons.bareIconSizes}`);

  return [...new Set(violations)].sort();
}

function syntheticTokenFile() {
  const light = requiredTokens.map((token) => `  ${token}: ${colourTokens.includes(token) ? "#101010" : "0"};`).join("\n");
  const darkBlock = colourTokens.map((token) => `  ${token}: #f0f0f0;`).join("\n");
  const motionBlock = durationTokens.map((token) => `    ${token}: 0s;`).join("\n");
  return `:root {\n${light}\n}\n${darkSelector} {\n${darkBlock}\n}\n@media (${reducedMotionQuery}: reduce) {\n  :root {\n${motionBlock}\n  }\n}\n`;
}

function selfCheckStyles() {
  const styles = new Map([
    [tokenFile, syntheticTokenFile()],
    ["shell.css", ".nav-item { color: #123456; padding: 11px; font-size: 13px; }"],
    ["surfaces.css", ".hero-card { border-radius: 12px; transition: transform .2s ease; }"],
    ["capture.css", ".capture-panel { padding: var(--space-md); color: var(--ink); font-size: var(--text-body); }"],
    ["guards.css", guardedClassPrefixes.map((prefix) => `.${prefix} { color: var(--ink); }`).join("\n")],
  ]);
  for (const name of ratchetFiles) if (!styles.has(name)) styles.set(name, "");
  return styles;
}

function selfCheckModules() {
  return new Map([["app/App.tsx", `export const App = () => <X size={16}>${glyphStandIns[0]}</X>;`]]);
}

function selfCheckBaseline() {
  const styles = selfCheckStyles();
  return {
    ratchet: Object.fromEntries(ratchetFiles.map((name) => [name, measure(styles.get(name) ?? "")])),
    icons: countIcons(selfCheckModules()),
  };
}

function caseWorld(mutate) {
  const world = { styles: selfCheckStyles(), modules: selfCheckModules(), baseline: selfCheckBaseline(), prefixes: [...guardedClassPrefixes] };
  mutate(world);
  return world;
}

function runCase(mutate) { return collectViolations(caseWorld(mutate)); }

function assertViolation(label, mutate, expected) {
  const violations = runCase(mutate);
  if (!violations.some((violation) => violation.includes(expected))) throw new Error(`style token self-check failed (${label}): expected ${JSON.stringify(expected)}, got ${JSON.stringify(violations)}`);
}

function assertReport(label, mutate, expected) {
  const lines = measurementLines(caseWorld(mutate)).join(" ");
  if (!lines.includes(expected)) throw new Error(`style token self-check failed (${label}): expected ${JSON.stringify(expected)}, got ${JSON.stringify(lines)}`);
}

function assertValid(label, mutate) {
  const violations = runCase(mutate);
  if (violations.length) throw new Error(`style token self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function runSelfChecks() {
  const cases = [];
  // The motion cases name real guarded classes by reading the list rather than
  // repeating it, so renaming a prefix is one edit and not a hunt.
  const [money, moneyAlt, moneyThird] = moneyClassPrefixes;
  const [grade, gradeAlt] = gradeClassPrefixes;
  const check = (kind, label, mutate, expected) => {
    cases.push(label);
    if (kind === "red") assertViolation(label, mutate, expected);
    else if (kind === "report") assertReport(label, mutate, expected);
    else assertValid(label, mutate);
  };

  check("green", "the tree as the baseline records it", () => {});
  check("green", "a new stylesheet written entirely from tokens", ({ styles }) => styles.set("capture.css", ".capture-panel { gap: var(--space-sm); border-radius: var(--radius-md); transition: opacity var(--duration-quick) var(--ease-standard); }"));
  check("green", "a token read with a fallback", ({ styles }) => styles.set("capture.css", ".capture-panel { padding: var(--space-md, var(--space-sm)); }"));

  check("red", "a new stylesheet sets a type size", ({ styles }) => styles.set("capture.css", ".capture-panel { font-size: 15px; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a line height", ({ styles }) => styles.set("capture.css", ".capture-panel { line-height: 1.4; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a font weight by number", ({ styles }) => styles.set("capture.css", ".capture-panel { font-weight: 600; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a font weight by keyword", ({ styles }) => styles.set("capture.css", ".capture-panel { font-weight: bold; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets spacing", ({ styles }) => styles.set("capture.css", ".capture-panel { padding: 14px 6px; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets negative spacing", ({ styles }) => styles.set("capture.css", ".capture-panel { margin-top: -17px; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a radius", ({ styles }) => styles.set("capture.css", ".capture-panel { border-radius: 12px 12px 12px 4px; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a pill radius", ({ styles }) => styles.set("capture.css", ".capture-panel { border-radius: 999px; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a hex colour", ({ styles }) => styles.set("capture.css", ".capture-panel { color: #21332c; }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a colour function", ({ styles }) => styles.set("capture.css", ".capture-panel { background-color: rgba(0, 0, 0, 0.2); }"), "raw value outside the token system");
  check("red", "a new stylesheet hides a colour in a gradient", ({ styles }) => styles.set("capture.css", ".capture-panel { background: linear-gradient(180deg, #f6f1e7 0%, #f2efe8 100%); }"), "raw value outside the token system");
  check("red", "a new stylesheet sets a duration", ({ styles }) => styles.set("capture.css", ".capture-panel { transition: opacity 200ms var(--ease-standard); }"), "raw value outside the token system");
  check("red", "a new stylesheet sets an easing keyword", ({ styles }) => styles.set("capture.css", ".capture-panel { transition: opacity var(--duration-quick) ease-in-out; }"), "raw value outside the token system");
  check("red", "a new stylesheet writes its own curve", ({ styles }) => styles.set("capture.css", ".capture-panel { transition-timing-function: cubic-bezier(0.2, 0, 0, 1); }"), "raw value outside the token system");
  check("red", "a raw value hides inside a media query", ({ styles }) => styles.set("capture.css", "@media (min-width: 700px) { .capture-panel { padding: 18px; } }"), "raw value outside the token system");
  check("red", "a raw value hides behind a comment", ({ styles }) => styles.set("capture.css", ".capture-panel { /* padding: var(--space-md); */ padding: 18px; }"), "raw value outside the token system");
  check("green", "a raw value only mentioned in a comment", ({ styles }) => styles.set("capture.css", ".capture-panel { /* was padding: 18px */ padding: var(--space-md); }"));

  check("red", "a stylesheet defines its own token", ({ styles }) => styles.set("capture.css", ".capture-panel { --capture-gap: 18px; padding: var(--capture-gap); }"), "token defined outside the token file");
  check("red", "a stylesheet reads a token nobody defined", ({ styles }) => styles.set("capture.css", ".capture-panel { padding: var(--space-enormous); }"), "undefined token used");
  check("red", "a required token is deleted", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace("  --space-md: 0;\n", "")), "token missing from the token file: --space-md");
  check("red", "an unused colour token is deleted", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace("  --sage: #101010;\n", "")), "token missing from the token file: --sage");
  check("red", "an icon size token is deleted", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace("  --icon-md: 0;\n", "")), "token missing from the token file: --icon-md");

  check("red", "the dark palette drops a name", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace("  --moss: #f0f0f0;\n", "")), "dark palette incomplete: --moss");
  check("red", "the dark palette invents a name", ({ styles }) => styles.set(tokenFile, `${syntheticTokenFile()}${darkSelector} { --dark-only: #000000; }`), "dark palette name unknown: --dark-only");
  check("red", "a stylesheet asks the operating system for a scheme", ({ styles }) => styles.set("capture.css", `@media (${systemColourQuery}: dark) { .capture-panel { color: var(--ink); } }`), "dark palette activated");
  check("red", "the token file activates the dark palette", ({ styles }) => styles.set(tokenFile, `${syntheticTokenFile()}@media (${systemColourQuery}: dark) { :root { --ink: #f0f0f0; } }`), "dark palette activated");
  check("red", "a module sets the dark attribute", ({ modules }) => modules.set("app/App.tsx", `export const theme = "${darkAttribute}";`), "dark palette activated");
  check("red", "reduced motion stops resetting a duration", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace("    --duration-drift: 0s;\n", "")), "reduced motion does not reset: --duration-drift");

  check("red", "a figure carries a transition", ({ styles }) => styles.set("capture.css", `.${money} { transition: transform var(--duration-quick) var(--ease-standard); }`), "motion forbidden near money or grade");
  check("red", "a figure family member carries a transition", ({ styles }) => styles.set("capture.css", `.${money}-note { transition: opacity var(--duration-quick) var(--ease-standard); }`), "motion forbidden near money or grade");
  check("red", "a grade carries an animation", ({ styles }) => styles.set("capture.css", `.${grade} { animation: var(--duration-drift) var(--ease-enter); }`), "motion forbidden near money or grade");
  check("red", "a grade animates only inside a media query", ({ styles }) => styles.set("capture.css", `@media (min-width: 700px) { .${gradeAlt} { transition: opacity var(--duration-quick) var(--ease-standard); } }`), "motion forbidden near money or grade");
  check("red", "a figure animates as part of a selector list", ({ styles }) => styles.set("capture.css", `.capture-panel, .${moneyAlt} { transition: opacity var(--duration-quick) var(--ease-standard); }`), "motion forbidden near money or grade");
  check("red", "a figure animates through a descendant selector", ({ styles }) => styles.set("capture.css", `.${moneyThird} strong { transition: opacity var(--duration-quick) var(--ease-standard); }`), "motion forbidden near money or grade");
  check("green", "a figure suppresses motion", ({ styles }) => styles.set("capture.css", `.${money} { transition: none; animation: none; }`));
  check("green", "a figure suppresses motion with a zero duration", ({ styles }) => styles.set("capture.css", `.${money} { transition: opacity 0s; }`));
  check("green", "a panel that is not a figure carries a transition", ({ styles }) => styles.set("capture.css", ".capture-panel { transition: opacity var(--duration-quick) var(--ease-standard); }"));
  check("green", "a guarded class named only by an empty rule", ({ styles }) => styles.set("guards.css", `${styles.get("guards.css")}\n.${money}:hover {}`));
  check("red", "a guarded class is renamed out of the stylesheets", ({ styles }) => styles.set("guards.css", styles.get("guards.css").replace(`.${money} {`, ".renamed-class {")), `guarded class prefix matches nothing: ${money}`);
  check("red", "a renamed figure then carries motion, and the prefix is what goes red", ({ styles }) => styles.set("guards.css", `${styles.get("guards.css").replace(`.${money} {`, ".renamed-class {")}\n.renamed-class { transition: opacity var(--duration-quick) var(--ease-standard); }`), `guarded class prefix matches nothing: ${money}`);
  check("red", "a grade prefix is declared and no stylesheet has the class", ({ prefixes }) => prefixes.push("capture-grade"), "guarded class prefix matches nothing: capture-grade");
  check("red", "a guarded class is deleted outright", ({ styles }) => styles.set("guards.css", styles.get("guards.css").replace(`.${gradeAlt} { color: var(--ink); }`, "")), `guarded class prefix matches nothing: ${gradeAlt}`);
  // The prohibition is an enumeration of classes this product declares. A class
  // that reads like money and is not on the list is not seen, and the report
  // says so on every run rather than letting a clean exit imply otherwise.
  check("green", "a money-looking class that nobody declared is not seen", ({ styles, prefixes }) => styles.set("capture.css", `.${undeclaredClassName(prefixes)} { transition: opacity var(--duration-settle) var(--ease-standard); }`));
  check("report", "the report counts the classes the prohibition reaches", ({ styles, prefixes }) => { styles.clear(); prefixes.length = 0; prefixes.push("hero-amount", "state-pill"); styles.set("guards.css", `.hero-amount {} .hero-amount-note {} .state-pill {} .${undeclaredClassName(prefixes)} {}`); }, "on 3 classes, named by 2 declared prefixes");
  check("report", "the report says what it does not see", () => {}, "A class not named by one of those prefixes is not seen");
  check("report", "the report tells a reader where a new surface joins", () => {}, "joins the list in this script");
  // Every number the report prints has to move when the tree moves, or it is a
  // recital of a constant that was true once.
  check("report", "the debt line falls when a raw value is migrated", ({ styles }) => styles.set("shell.css", ".nav-item { color: var(--ink); padding: 11px; font-size: 13px; }"), "shell.css 2");
  check("report", "the slack line names a file below its recorded ceiling", ({ styles }) => styles.set("shell.css", ".nav-item { color: var(--ink); padding: 11px; font-size: 13px; }"), "1 below the recorded ceiling on shell.css");
  check("report", "the debt line reports the tree and not the recorded ceiling", ({ styles, baseline }) => { styles.set("shell.css", ".nav-item { color: var(--ink); padding: var(--space-md); font-size: var(--text-body); }"); baseline.ratchet["shell.css"] = Object.fromEntries(categories.map((category) => [category, 99])); }, "shell.css 0");
  check("report", "the icon line falls when a stand-in is removed", ({ modules }) => modules.set("app/App.tsx", "export const App = () => null;"), "0 glyphs, 0 bare sizes");
  check("report", "the slack line names an icon count below its ceiling", ({ modules }) => modules.set("app/App.tsx", "export const App = () => null;"), "1 below the recorded ceiling on glyph stand-ins");
  check("report", "the token count is measured from the token file", ({ styles }) => styles.set(tokenFile, syntheticTokenFile().replace(":root {", ":root {\n  --extra-token: 0;")), `${requiredTokens.length + 1} tokens`);
  check("green", "a guarded class is renamed and the prefix follows it", ({ styles, prefixes }) => { styles.set("guards.css", styles.get("guards.css").replace(`.${money} {`, ".renamed-class {")); prefixes[prefixes.indexOf(money)] = "renamed-class"; });

  check("red", "the legacy shell adds a raw colour", ({ styles }) => styles.set("shell.css", `${styles.get("shell.css")}\n.nav-label { color: #654321; }`), "raw value count rose: shell.css colour");
  check("red", "the legacy surfaces add a raw type size", ({ styles }) => styles.set("surfaces.css", `${styles.get("surfaces.css")}\n.hero-meta { font-size: 13px; }`), "raw value count rose: surfaces.css type");
  check("green", "the legacy shell migrates one value to a token", ({ styles }) => styles.set("shell.css", ".nav-item { color: var(--ink); padding: 11px; font-size: 13px; }"));
  check("red", "a ratcheted stylesheet disappears", ({ styles }) => styles.delete("surfaces.css"), "stylesheet missing: surfaces.css");
  check("red", "the token file disappears", ({ styles }) => styles.delete(tokenFile), `stylesheet missing: ${tokenFile}`);
  check("red", "the stylesheet set is empty", ({ styles }) => styles.clear(), "no stylesheet found");
  check("red", "the module set is empty", ({ modules }) => modules.clear(), "no module found");

  check("red", "a module adds an icon stand-in glyph", ({ modules }) => modules.set("features/capture/Capture.tsx", `export const mark = "${glyphStandIns[0]}";`), "icon stand-in count rose");
  check("red", "a module adds a bare icon size", ({ modules }) => modules.set("features/capture/Capture.tsx", "export const icon = <X size={18} />;"), "bare icon size count rose");
  check("green", "a module sizes an icon from a token", ({ modules }) => modules.set("features/capture/Capture.tsx", "export const icon = <X className=\"capture-icon\" />;"));

  return cases.length;
}

function filesAt(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => entry.isDirectory() ? filesAt(join(directory, entry.name)) : [join(directory, entry.name)]);
}

function readTree(directory, pattern) {
  return new Map(filesAt(directory).filter((file) => pattern.test(file)).map((file) => [relative(directory, file).replaceAll("\\", "/"), readFileSync(file, "utf8")]));
}

const selfPath = fileURLToPath(import.meta.url);
const root = resolve(dirname(selfPath), "..");
const liveStyles = readTree(join(root, "src", "styles"), /\.css$/);
const liveModules = readTree(join(root, "src"), /\.(ts|tsx)$/);

if (process.argv.includes("--write-baseline")) {
  const measured = {
    ratchet: Object.fromEntries(ratchetFiles.map((name) => [name, measure(liveStyles.get(name) ?? "")])),
    icons: countIcons(liveModules),
  };
  const rewritten = readFileSync(selfPath, "utf8").replace(/(\/\/ baseline start\n)[\s\S]*?(\/\/ baseline end)/, `$1const baseline = ${JSON.stringify(measured, null, 2)};\n$2`);
  writeFileSync(selfPath, rewritten);
  console.log(`Style token baseline written from the current tree: ${JSON.stringify(measured)}`);
  process.exit(0);
}

const selfChecks = runSelfChecks();
const violations = collectViolations({ styles: liveStyles, modules: liveModules, baseline });
if (violations.length) {
  for (const violation of violations) console.error(violation);
  process.exit(1);
}
console.log(`Style token self-checks passed (${selfChecks} cases).`);
for (const line of measurementLines({ styles: liveStyles, modules: liveModules, baseline, prefixes: guardedClassPrefixes })) console.log(line);
