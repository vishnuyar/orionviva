import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createScanner, LanguageVariant, SyntaxKind, tokenIsIdentifierOrKeyword } from "typescript/unstable/ast";

const retiredSkipTitles = [
  "[WP-08 deferred] moves keyboard focus into the Viva dialog when it opens",
  "[WP-08 deferred] lets a keyboard user dismiss the Viva dialog with Escape",
];
const expectedSkips = [];
// The backend's own generated output, read from where the backend writes it.
// Both halves of the parity test read these same bytes; the adapter tests are
// the one place on this side permitted to import it.
const backendParityFixture = "../../../../product/viva/surface/fixtures/overview-parity-v1.json";
// The same artifact, one directory nearer: the shell's own test opens the
// sample vault, and what the sidecar answers for it is these bytes. A shell
// test that authored its own payloads would agree with itself while
// disagreeing with the product.
const shellParityFixture = "../../../product/viva/surface/fixtures/overview-parity-v1.json";
// The persona pack the product ships. A test that asserts what a person is
// told reads the sentence from here; one that types the sentence out passes
// against words nobody shipped. No production module reads it: the sentences
// reach a screen through the bridge, in the reply that carried them.
const personaPackMoments = /^\.\.\/.*\/product\/viva\/persona\/pack-v\d+\/moments\.json$/;
// Every sentence the shipped persona pack holds. A module or a test carrying
// one as a literal is asserting or composing words that already exist
// somewhere they can be changed; the pack is read, never copied.
function packSentences(moments) {
  const sentences = Object.entries(moments).filter(([key]) => key !== "_comment").map(([, value]) => value).filter((value) => typeof value === "string" && value.trim());
  if (!sentences.length) throw new Error("persona pack holds no sentences: the shipped-sentence check would walk an empty set and report a clean bill it could not withhold");
  return sentences;
}

function shippedSentences(productRoot) {
  const versions = JSON.parse(readFileSync(join(productRoot, "viva", "versions.json"), "utf8"));
  const pack = versions.in_force.persona_pack.active;
  const moments = JSON.parse(readFileSync(join(productRoot, "viva", "persona", pack, "moments.json"), "utf8"));
  return { pack, sentences: packSentences(moments) };
}

// A sentence written as bare text between two tags. The scanner above has no
// parser over it, so it reports such a sentence as ordinary words rather than
// as one piece of text, and a rule reading only literals reports a clean bill
// it could not have withheld. The run between a tag's closing `>` and the next
// `<` is read back out of the source it was scanned from, so what is compared
// is what a person would read.
function jsxTextRuns(text, tokens) {
  const runs = [];
  let openedAt = -1;
  for (const token of tokens) {
    if (token.kind === SyntaxKind.GreaterThanToken) { openedAt = token.end; continue; }
    if ((token.kind !== SyntaxKind.LessThanToken && token.kind !== SyntaxKind.LessThanSlashToken) || openedAt < 0) continue;
    const run = text.slice(openedAt, token.start).trim();
    if (run) runs.push({ value: run, start: openedAt });
    openedAt = -1;
  }
  return runs;
}

function shippedSentenceViolations(name, text, sentences) {
  const shipped = new Set(sentences);
  const violations = [];
  const tokens = scanTypeScript(name, text);
  for (const token of tokens) {
    if (token.kind !== SyntaxKind.StringLiteral && token.kind !== SyntaxKind.NoSubstitutionTemplateLiteral) continue;
    if (shipped.has(token.value)) violations.push(`shipped sentence typed out: ${name}:${token.start}`);
  }
  for (const run of jsxTextRuns(text, tokens)) {
    if (shipped.has(run.value)) violations.push(`shipped sentence typed out: ${name}:${run.start}`);
  }
  return [...new Set(violations)];
}

const legacyPaths = ["app/model.ts", "app/bridge-client.ts", "app/data.ts", "app/synthetic.ts"];
const legacyIdentifiers = ["DemoState", "demoState", "snapshotFromBridge", "createLiveLoadingSnapshot", "readStatus", "partialReadFailure"];

function importSpecifiers(text) {
  return [...text.matchAll(/(?:import|export)\s+(?:type\s+)?(?:[^"']*?\s+from\s+)?["']([^"']+)["']/g)].map((match) => match[1]);
}
function isTest(name) { return /\.(test|spec|testSupport)\.(ts|tsx)$/.test(name); }
function isTestSupport(name) { return name === "test/surfaceScenarios.ts"; }
function importsSegment(specifier, segment) { return specifier.split("/").includes(segment); }
function isTestLibrary(specifier) { return specifier === "vitest" || specifier === "react" || specifier.startsWith("@testing-library/"); }
const surfaceMatrixImports = new Set(["./surfaceScenarios", "../features/accounts/Accounts", "../features/overview/Overview", "../surface/types"]);
function ownerTestImportAllowed(name, specifier) {
  if (isTestLibrary(specifier)) return true;
  if (personaPackMoments.test(specifier)) return true;
  // The shim's own test may reach the same two host packages the shim may, and
  // no others, so the published event type checks the shape the test builds.
  if (name === hostShimTest) return specifier.startsWith("./") || hostShimPackages.has(specifier);
  if (name === "test/SurfaceMatrix.test.tsx") return surfaceMatrixImports.has(specifier);
  if (name.startsWith("bridge/")) return specifier.startsWith("./");
  if (name.startsWith("components/")) return specifier.startsWith("./") || specifier === "../surface/types" || specifier === "../surface/evidence";
  if (name.startsWith("surface/adapters/")) return specifier.startsWith("./") || specifier === "../types" || specifier === "../evidence" || specifier === backendParityFixture;
  if (name.startsWith("features/")) return specifier.startsWith("./") || specifier.includes("/components/") || specifier.endsWith("/surface/types") || specifier.endsWith("/surface/evidence") || specifier.endsWith("/app/navigation") || specifier.endsWith("/app/selection");
  if (name.startsWith("surface/fixtures/")) return specifier.startsWith("./") || specifier === "../types" || specifier === "../evidence";
  if (name.startsWith("app/")) return specifier.startsWith("./") || specifier === "../bridge/contracts" || specifier === "../surface/types" || specifier === "../surface/sources" || specifier === shellParityFixture;
  if (name.startsWith("surface/")) return specifier.startsWith("./") || specifier === "../bridge/contracts";
  return specifier.startsWith("./");
}

const globalVitestApis = new Set(["it", "test", "describe", "suite", "xit", "xtest", "xdescribe", "xsuite", "fit", "fdescribe"]);
const disabledVitestApis = new Set(["xit", "xtest", "xdescribe", "xsuite"]);
const focusedVitestApis = new Set(["fit", "fdescribe"]);

// What this checker cannot read, said in full wherever it bites. The scanner
// this fence drives has no parser above it and cannot advance through a
// regular-expression literal, so a module under src writes its patterns with
// `new RegExp`.
const TOKENIZER_REFUSAL = "tokenizer stopped advancing: this checker cannot read a regular-expression literal. Write the pattern as new RegExp(\"…\") instead.";

function scanTypeScript(name, text) {
  const scanner = createScanner(true, name.endsWith(".tsx") ? LanguageVariant.JSX : LanguageVariant.Standard, text);
  const tokens = [];
  let inTemplate = false;
  let templateBraceDepth = 0;
  let read = -1;
  // The scanner reads without a parser above it, so a construct it cannot
  // decide — a regular-expression literal among them — can leave it standing
  // on the same character. Standing still is refused loudly rather than looped
  // over, because a check that never returns is a check that never reports.
  // The refusal names the file, the construct and what to write instead.
  for (let kind = scanner.scan(); kind !== SyntaxKind.EndOfFile; kind = scanner.scan()) {
    if (scanner.getTokenEnd() <= read) throw new Error(`${TOKENIZER_REFUSAL}\n  ${name}:${scanner.getTokenStart()} at ${JSON.stringify(text.slice(scanner.getTokenStart(), scanner.getTokenStart() + 32))}`);
    read = scanner.getTokenEnd();
    if (inTemplate && kind === SyntaxKind.CloseBraceToken && templateBraceDepth === 0) {
      kind = scanner.reScanTemplateToken(false);
      inTemplate = kind !== SyntaxKind.LastTemplateToken;
    } else if (kind === SyntaxKind.TemplateHead) {
      inTemplate = true;
    } else if (inTemplate && kind === SyntaxKind.OpenBraceToken) {
      templateBraceDepth += 1;
    } else if (inTemplate && kind === SyntaxKind.CloseBraceToken) {
      templateBraceDepth -= 1;
    }
    tokens.push({ kind, text: scanner.getTokenText(), value: scanner.getTokenValue(), start: scanner.getTokenStart(), end: scanner.getTokenEnd() });
  }
  return tokens;
}

// The packages the host shim may reach for, named one by one. The shim is the
// only module allowed to speak to the operating system at all, so what it may
// speak to is a list rather than a pattern.
const hostShim = "tauri-host.ts";
const hostShimTest = "tauri-host.test.ts";
// `@tauri-apps/api/event` joins the two the shim already reached because a
// progress frame arrives on an event rather than in a reply: the reply comes
// when the work is over, and a channel that only speaks after the fact reports
// nothing a person could act on.
const hostShimPackages = new Set(["@tauri-apps/plugin-dialog", "@tauri-apps/api/webview", "@tauri-apps/api/event"]);

function capturePrimitiveViolations(name, text) {
  if (name !== "app/App.tsx" && name !== hostShim && !name.startsWith("features/documents/")) return [];
  const violations = [];
  const tokens = scanTypeScript(name, text);
  const forbiddenExecutables = new Set(["FileReader", "DataTransfer", "FormData", "XMLHttpRequest", "showOpenFilePicker", "showSaveFilePicker", "fetch"]);
  const staticFileValue = (tokens, start) => {
    let cursor = start;
    let braces = false;
    let parentheses = 0;
    if (tokens[cursor]?.kind === SyntaxKind.OpenBraceToken) { braces = true; cursor += 1; }
    while (tokens[cursor]?.kind === SyntaxKind.OpenParenToken) { parentheses += 1; cursor += 1; }
    const valueToken = tokens[cursor];
    if (valueToken?.kind !== SyntaxKind.StringLiteral && valueToken?.kind !== SyntaxKind.NoSubstitutionTemplateLiteral) return null;
    cursor += 1;
    while (parentheses > 0 && tokens[cursor]?.kind === SyntaxKind.CloseParenToken) { parentheses -= 1; cursor += 1; }
    if (parentheses > 0 || (braces && tokens[cursor]?.kind !== SyntaxKind.CloseBraceToken)) return null;
    return valueToken.value;
  };
  if (name.startsWith("features/documents/")) { forbiddenExecutables.add("setTimeout"); forbiddenExecutables.add("setInterval"); }
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token.text === "import") {
      let cursor = index + 1;
      while (cursor < tokens.length && tokens[cursor].text !== ";" && tokens[cursor].text !== "import") {
        if (tokens[cursor].kind === SyntaxKind.StringLiteral) {
          const specifier = tokens[cursor].value;
          if (name === hostShim) {
            if (!specifier.startsWith(".") && !hostShimPackages.has(specifier)) violations.push(`capture host package forbidden: ${name} -> ${specifier}`);
          } else if (specifier.includes("@tauri-apps") || specifier.includes("plugin-dialog")) {
            violations.push(`capture dialog import forbidden: ${name}`);
          }
        }
        cursor += 1;
      }
    }
    const executableCall = tokens[index + 1]?.kind === SyntaxKind.OpenParenToken || (tokens[index + 1]?.kind === SyntaxKind.QuestionDotToken && tokens[index + 2]?.kind === SyntaxKind.OpenParenToken);
    if (token.kind === SyntaxKind.Identifier && forbiddenExecutables.has(token.text) && executableCall) violations.push(`capture primitive forbidden: ${name}:${token.start} (${token.text})`);
    if (token.kind === SyntaxKind.Identifier && (token.text === "onDrop" || token.text.startsWith("onDrag")) && tokens[index + 1]?.text === "=") violations.push(`capture drag handler forbidden: ${name}:${token.start} (${token.text})`);
    if (token.kind === SyntaxKind.Identifier && token.text === "navigator" && (tokens[index + 1]?.kind === SyntaxKind.DotToken || tokens[index + 1]?.kind === SyntaxKind.QuestionDotToken) && tokens[index + 2]?.text === "clipboard") violations.push(`capture clipboard primitive forbidden: ${name}:${token.start}`);
    if (token.text !== "<" || tokens[index + 1]?.text !== "input") continue;
    let cursor = index + 2;
    while (cursor < tokens.length && tokens[cursor].text !== ">") {
      if (tokens[cursor].text === "type" && tokens[cursor + 1]?.text === "=" && staticFileValue(tokens, cursor + 2)?.toLowerCase() === "file") violations.push(`file input forbidden: ${name}:${token.start}`);
      cursor += 1;
    }
  }
  return [...new Set(violations)];
}

// The `disabled` attribute, wherever it would be written: an attribute
// position inside a JSX opening tag. A string selector, a property read and
// `aria-disabled` all pass by untouched, because none of them is one.
function disabledAttributeViolations(name, text) {
  const tokens = scanTypeScript(name, text);
  const violations = [];
  const opensElement = (index) => {
    if (tokens[index].kind !== SyntaxKind.LessThanToken) return false;
    const next = tokens[index + 1];
    if (!next || !tokenIsIdentifierOrKeyword(next.kind)) return false;
    const before = tokens[index - 1];
    return !before || !(before.kind === SyntaxKind.Identifier || before.kind === SyntaxKind.NumericLiteral || before.kind === SyntaxKind.StringLiteral || before.kind === SyntaxKind.CloseParenToken || before.kind === SyntaxKind.CloseBracketToken);
  };
  for (let index = 0; index < tokens.length; index += 1) {
    if (!opensElement(index)) continue;
    let depth = 0;
    for (let cursor = index + 2; cursor < tokens.length; cursor += 1) {
      const token = tokens[cursor];
      if (token.kind === SyntaxKind.OpenBraceToken) { depth += 1; continue; }
      if (token.kind === SyntaxKind.CloseBraceToken) { depth -= 1; continue; }
      if (depth > 0) continue;
      if (token.kind === SyntaxKind.GreaterThanToken || token.kind === SyntaxKind.LessThanToken) break;
      if (token.text !== "disabled") continue;
      const before = tokens[cursor - 1];
      if (before && (before.kind === SyntaxKind.MinusToken || before.kind === SyntaxKind.DotToken || before.kind === SyntaxKind.QuestionDotToken)) continue;
      violations.push(`disabled attribute forbidden: ${name}:${token.start}`);
    }
  }
  return [...new Set(violations)];
}

// The window's own drag-drop capture, which is what keeps a dropped file out
// of the webview: while it is on, the native layer takes the drop and no
// browser drop event fires at all. Switching it off would hand the gesture
// back to the page, so the setting is stated rather than inherited, and it is
// read here from the configuration the packaged application is built with.
function dragDropCaptureViolations(source) {
  let configuration;
  try {
    configuration = JSON.parse(source);
  } catch {
    return ["window drag-drop capture unreadable: the Tauri configuration is not JSON"];
  }
  const windows = configuration?.app?.windows;
  if (!Array.isArray(windows) || windows.length === 0) return ["window drag-drop capture unstated: the Tauri configuration declares no window"];
  const violations = [];
  windows.forEach((entry, index) => {
    const named = entry && typeof entry === "object" && !Array.isArray(entry) ? entry : null;
    const label = typeof named?.label === "string" && named.label.trim() ? named.label : `window ${index}`;
    if (!named) { violations.push(`window drag-drop capture unstated: ${label}`); return; }
    if (!Object.prototype.hasOwnProperty.call(named, "dragDropEnabled")) { violations.push(`window drag-drop capture unstated: ${label}`); return; }
    if (named.dragDropEnabled !== true) violations.push(`window drag-drop capture disabled: ${label}`);
  });
  return violations;
}

function vitestBindings(tokens) {
  const aliases = new Map();
  const namespaces = new Set();
  for (let index = 0; index < tokens.length; index += 1) {
    if (tokens[index].text !== "import") continue;
    let end = index + 1;
    while (end < tokens.length && tokens[end].text !== ";" && tokens[end].text !== "import") end += 1;
    const segment = tokens.slice(index + 1, end);
    const from = segment.findIndex((token) => token.text === "from");
    if (from < 0 || segment[from + 1]?.kind !== SyntaxKind.StringLiteral || segment[from + 1].value !== "vitest") continue;
    const bindings = segment.slice(0, from);
    if (bindings[0]?.text === "*" && bindings[1]?.text === "as" && bindings[2]?.kind === SyntaxKind.Identifier) namespaces.add(bindings[2].text);
    const openBrace = bindings.findIndex((token) => token.text === "{");
    const closeBrace = bindings.findIndex((token) => token.text === "}");
    if (openBrace >= 0 && closeBrace > openBrace) {
      let cursor = openBrace + 1;
      while (cursor < closeBrace) {
        if (bindings[cursor].kind !== SyntaxKind.Identifier) { cursor += 1; continue; }
        const imported = bindings[cursor].text;
        const hasAlias = bindings[cursor + 1]?.text === "as" && bindings[cursor + 2]?.kind === SyntaxKind.Identifier;
        const local = hasAlias ? bindings[cursor + 2].text : imported;
        if (globalVitestApis.has(imported)) aliases.set(local, imported);
        cursor += hasAlias ? 3 : 1;
      }
    }
  }
  return { aliases, namespaces };
}

function matchingCloseParen(tokens, open) {
  let depth = 0;
  for (let index = open; index < tokens.length; index += 1) {
    if (tokens[index].kind === SyntaxKind.OpenParenToken) depth += 1;
    if (tokens[index].kind === SyntaxKind.CloseParenToken) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}

function matchingCloseBracket(tokens, open) {
  let depth = 0;
  for (let index = open; index < tokens.length; index += 1) {
    if (tokens[index].kind === SyntaxKind.OpenBracketToken) depth += 1;
    if (tokens[index].kind === SyntaxKind.CloseBracketToken) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}

function rootParenthesisCount(tokens, root) {
  let count = 0;
  while (tokens[root - count - 1]?.kind === SyntaxKind.OpenParenToken) count += 1;
  if (count === 0) return 0;
  const before = tokens[root - count - 1];
  return before && (before.kind === SyntaxKind.Identifier || before.kind === SyntaxKind.CloseParenToken || before.kind === SyntaxKind.CloseBracketToken || before.kind === SyntaxKind.StringLiteral) ? 0 : count;
}

function staticFirstArgument(tokens, call) {
  if (call.template) return null;
  const first = tokens[call.open + 1];
  if (!first || first.kind !== SyntaxKind.StringLiteral) return null;
  const next = tokens[call.open + 2];
  return next && (next.kind === SyntaxKind.CommaToken || next.kind === SyntaxKind.CloseParenToken) ? first.value : null;
}

function auditVitestCalls(name, text) {
  const tokens = scanTypeScript(name, text);
  const { aliases, namespaces } = vitestBindings(tokens);
  const disabled = [];
  const violations = [];
  for (let root = 0; root < tokens.length; root += 1) {
    if (tokens[root].kind !== SyntaxKind.Identifier || tokens[root - 1]?.kind === SyntaxKind.DotToken) continue;
    const base = tokens[root].text;
    let api = aliases.get(base) ?? (globalVitestApis.has(base) ? base : null);
    let namespace = false;
    let wrapped = tokens[root - 1]?.kind === SyntaxKind.GreaterThanToken;
    let wrappersRemaining = rootParenthesisCount(tokens, root);
    if (wrapped && wrappersRemaining === 0 && tokens[root + 1]?.kind === SyntaxKind.CloseParenToken) wrappersRemaining = 1;
    if (wrappersRemaining > 0) wrapped = true;
    let cursor = root + 1;
    while (wrappersRemaining > 0 && tokens[cursor]?.kind === SyntaxKind.CloseParenToken) {
      wrappersRemaining -= 1;
      cursor += 1;
    }
    if (!api && namespaces.has(base)) {
      if ((tokens[cursor]?.kind === SyntaxKind.DotToken || tokens[cursor]?.kind === SyntaxKind.QuestionDotToken) && tokens[cursor + 1] && tokenIsIdentifierOrKeyword(tokens[cursor + 1].kind) && globalVitestApis.has(tokens[cursor + 1].text)) {
        api = tokens[cursor + 1].text;
        namespace = true;
        wrapped ||= tokens[cursor].kind === SyntaxKind.QuestionDotToken;
        cursor += 2;
      } else if (tokens[cursor]?.kind === SyntaxKind.QuestionDotToken && tokens[cursor + 1]?.kind === SyntaxKind.OpenBracketToken && tokens[cursor + 2]?.kind === SyntaxKind.StringLiteral && tokens[cursor + 3]?.kind === SyntaxKind.CloseBracketToken && globalVitestApis.has(tokens[cursor + 2].value)) {
        api = tokens[cursor + 2].value;
        namespace = true;
        wrapped = true;
        cursor += 4;
      } else if (tokens[cursor]?.kind === SyntaxKind.OpenBracketToken && tokens[cursor + 1]?.kind === SyntaxKind.StringLiteral && tokens[cursor + 2]?.kind === SyntaxKind.CloseBracketToken && globalVitestApis.has(tokens[cursor + 1].value)) {
        api = tokens[cursor + 1].value;
        namespace = true;
        wrapped = true;
        cursor += 3;
      } else if (tokens[cursor]?.kind === SyntaxKind.OpenBracketToken || (tokens[cursor]?.kind === SyntaxKind.QuestionDotToken && tokens[cursor + 1]?.kind === SyntaxKind.OpenBracketToken)) {
        violations.push(`dynamic Vitest element access: ${name}:${tokens[root].start}`);
        continue;
      }
    }
    if (!api) continue;
    const parts = [];
    const calls = [];
    let computed = false;
    let dynamicElement = false;
    while (cursor < tokens.length) {
      if (wrappersRemaining > 0 && tokens[cursor].kind === SyntaxKind.CloseParenToken) {
        wrappersRemaining -= 1;
        cursor += 1;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.ExclamationToken) {
        wrapped = true;
        cursor += 1;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.QuestionDotToken && (tokens[cursor + 1]?.kind === SyntaxKind.OpenParenToken || tokens[cursor + 1]?.kind === SyntaxKind.OpenBracketToken)) {
        wrapped = true;
        cursor += 1;
        continue;
      }
      if (tokens[cursor].text === "as" && wrappersRemaining > 0) {
        wrapped = true;
        while (cursor < tokens.length && tokens[cursor].kind !== SyntaxKind.CloseParenToken) cursor += 1;
        continue;
      }
      if ((tokens[cursor].kind === SyntaxKind.DotToken || tokens[cursor].kind === SyntaxKind.QuestionDotToken) && tokens[cursor + 1] && tokenIsIdentifierOrKeyword(tokens[cursor + 1].kind)) {
        parts.push(tokens[cursor + 1].text);
        if (tokens[cursor].kind === SyntaxKind.QuestionDotToken) computed = true;
        cursor += 2;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.OpenBracketToken && tokens[cursor + 1]?.kind === SyntaxKind.StringLiteral && tokens[cursor + 2]?.kind === SyntaxKind.CloseBracketToken) {
        parts.push(tokens[cursor + 1].value);
        computed = true;
        cursor += 3;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.OpenBracketToken) {
        const close = matchingCloseBracket(tokens, cursor);
        if (close < 0) break;
        computed = true;
        dynamicElement = true;
        cursor = close + 1;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.OpenParenToken) {
        const close = matchingCloseParen(tokens, cursor);
        if (close < 0) break;
        calls.push({ open: cursor, close });
        cursor = close + 1;
        continue;
      }
      if (tokens[cursor].kind === SyntaxKind.NoSubstitutionTemplateLiteral || tokens[cursor].kind === SyntaxKind.TemplateHead) {
        calls.push({ open: cursor, close: cursor, template: true });
        if (tokens[cursor].kind === SyntaxKind.TemplateHead) while (cursor < tokens.length && tokens[cursor].kind !== SyntaxKind.LastTemplateToken) cursor += 1;
        cursor += 1;
        continue;
      }
      break;
    }
    if (calls.length === 0) continue;
    if (dynamicElement) violations.push(`dynamic Vitest element access: ${name}:${tokens[root].start}`);
    const isDisabled = disabledVitestApis.has(api) || parts.includes("skip") || parts.includes("skipIf");
    const isFocused = focusedVitestApis.has(api) || parts.includes("only");
    const isTodo = parts.includes("todo");
    const title = staticFirstArgument(tokens, calls.at(-1));
    if (isDisabled) {
      const canonical = !namespace && !computed && !wrapped && base === "it" && api === "it" && parts.length === 1 && parts[0] === "skip" && calls.length === 1 && title !== null;
      disabled.push({ name, title, canonical, position: tokens[root].start });
      if (!canonical) violations.push(`unauthorized disabled test: ${name}:${tokens[root].start} (${title ?? "dynamic title"})`);
    }
    if (isFocused) violations.push(`focused test remains: ${name}:${tokens[root].start}`);
    if (isTodo) violations.push(`todo test remains: ${name}:${tokens[root].start}`);
  }
  return { disabled, violations };
}

export function collectViolations(inputFiles, sentences = []) {
  const files = inputFiles instanceof Map ? inputFiles : new Map(Object.entries(inputFiles));
  const violations = [];
  const code = [...files.entries()].filter(([name]) => /\.(ts|tsx)$/.test(name));
  const production = code.filter(([name]) => !isTest(name) && !isTestSupport(name));

  for (const legacy of legacyPaths) if (files.has(legacy)) violations.push(`legacy module remains: ${legacy}`);

  const disabledTests = [];
  for (const [name, text] of code) {
    const specs = importSpecifiers(text);
    if (name.startsWith("test/") && !isTest(name) && !isTestSupport(name)) for (const specifier of specs) if (!isTestLibrary(specifier) && !specifier.startsWith("./")) violations.push(`test production import forbidden: ${name} -> ${specifier}`);
    if (!isTest(name) && !isTestSupport(name)) violations.push(...capturePrimitiveViolations(name, text));
    violations.push(...disabledAttributeViolations(name, text));
    violations.push(...shippedSentenceViolations(name, text, sentences));
    if (text.includes("WP-01 temporary compatibility export")) violations.push(`compatibility marker remains: ${name}`);
    for (const identifier of legacyIdentifiers) if (new RegExp(`\\b${identifier}\\b`).test(text)) violations.push(`legacy alias or builder remains: ${identifier} in ${name}`);
    if (isTest(name)) {
      const audit = auditVitestCalls(name, text);
      disabledTests.push(...audit.disabled);
      violations.push(...audit.violations);
    }

    if (isTest(name)) for (const specifier of specs) if (!ownerTestImportAllowed(name, specifier)) violations.push(`owner test import forbidden: ${name} -> ${specifier}`);
    if (isTestSupport(name)) for (const specifier of specs) if (specifier !== "../surface/types") violations.push(`test support import forbidden: ${name} -> ${specifier}`);
    if (!isTestSupport(name) && specs.some((specifier) => importsSegment(specifier, "test"))) violations.push(`test support imported outside owner matrix: ${name}`);
    if ((name.startsWith("app/") || name.startsWith("components/") || name.startsWith("features/") || name.startsWith("surface/adapters/")) && name !== "surface/adapters/primitives.ts" && /\b(?:Number\s*\(|parseFloat\s*\(|parseInt\s*\(|Intl\.NumberFormat|\.reduce\s*\()/.test(text)) violations.push(`frontend arithmetic forbidden: ${name}`);

    if (!isTest(name) && !isTestSupport(name)) {
    if (/\bexactValue\b/.test(text) && name !== "surface/types.ts" && !name.startsWith("surface/adapters/") && !name.startsWith("surface/fixtures/")) violations.push(`exactValue crossed the render boundary: ${name}`);
    if (specs.some((specifier) => personaPackMoments.test(specifier))) violations.push(`persona pack read outside a test: ${name}`);
    if (name === "app/App.tsx" && specs.some((specifier) => importsSegment(specifier, "bridge") || importsSegment(specifier, "adapters") || importsSegment(specifier, "contracts") || importsSegment(specifier, "fixtures"))) violations.push(`App crosses a boundary: ${name}`);
    if (name.startsWith("features/")) {
      for (const specifier of specs) {
        const allowedFeatureHelper = (name === "features/documents/Documents.tsx" && specifier === "./documentPresentation") || (name === "features/activity/Activity.tsx" && specifier === "./activityPresentation") || (name === "features/conversation/Questions.tsx" && specifier === "./questionPresentation") || (name === "features/conversation/ConversationDrawer.tsx" && (specifier === "./Questions" || specifier === "./questionPresentation"));
        const allowed = specifier === "react" || specifier === "lucide-react" || importsSegment(specifier, "components") || specifier.endsWith("/surface/types") || specifier.endsWith("/surface/evidence") || specifier.endsWith("/app/navigation") || specifier.endsWith("/app/selection") || allowedFeatureHelper;
        if (!allowed) violations.push(`feature import forbidden: ${name} -> ${specifier}`);
        if (importsSegment(specifier, "bridge") || importsSegment(specifier, "adapters") || importsSegment(specifier, "fixtures")) violations.push(`feature crosses data boundary: ${name} -> ${specifier}`);
        if (importsSegment(specifier, "features") || (specifier.startsWith("../") && !specifier.startsWith("../../"))) violations.push(`feature imports another feature: ${name} -> ${specifier}`);
      }
    }
    if (name.startsWith("components/")) for (const specifier of specs) {
      const allowedEvidenceBoundary = name === "components/EvidenceDrawer.tsx" && specifier === "./FeatureBoundary";
      if (!(specifier === "react" || specifier.endsWith("/surface/types") || specifier.endsWith("/surface/evidence") || allowedEvidenceBoundary)) violations.push(`component import forbidden: ${name} -> ${specifier}`);
    }
    if (name.startsWith("surface/adapters/")) for (const specifier of specs) if (!(specifier.startsWith("./") || specifier === "../types" || specifier === "../evidence")) violations.push(`adapter import forbidden: ${name} -> ${specifier}`);
    if (name.startsWith("bridge/")) for (const specifier of specs) if (!specifier.startsWith("./")) violations.push(`bridge import forbidden: ${name} -> ${specifier}`);
    if (name.startsWith("surface/fixtures/")) for (const specifier of specs) if (!(specifier.startsWith("./") || specifier === "../types")) violations.push(`fixture import forbidden: ${name} -> ${specifier}`);
    if (name !== "surface/sources.ts" && specs.some((specifier) => importsSegment(specifier, "fixtures"))) violations.push(`live fixture import forbidden: ${name}`);
    if (name !== "surface/load-private-snapshot.ts" && specs.some((specifier) => importsSegment(specifier, "adapters"))) violations.push(`adapter imported outside private loader: ${name}`);
    if (name !== "surface/sources.ts" && specs.some((specifier) => specifier.endsWith("/load-private-snapshot") || specifier === "./load-private-snapshot")) violations.push(`private loader imported outside sources: ${name}`);
    if (/\bwindow\b/.test(text) && !(name.startsWith("bridge/") || name === "tauri-host.ts")) violations.push(`window leaked outside host transport: ${name}`);
    if ((name.startsWith("app/") || name.startsWith("components/") || name.startsWith("features/")) && (/\bunknown\b/.test(text) || /Record\s*<\s*string\s*,\s*unknown\s*>/.test(text))) violations.push(`raw shape leaked into UI: ${name}`);
    }
  }

  for (const title of expectedSkips) {
    const matches = disabledTests.filter((entry) => entry.canonical && entry.name === "app/App.test.tsx" && entry.title === title);
    if (matches.length !== 1) violations.push(`skip audit failed: ${title} expected once in app/App.test.tsx, found ${matches.length}`);
  }
  for (const entry of disabledTests) {
    if (entry.canonical && (entry.name !== "app/App.test.tsx" || !expectedSkips.includes(entry.title))) violations.push(`unauthorized canonical skip: ${entry.name}:${entry.position} (${entry.title})`);
  }
  return violations.sort();
}

function selfCheckFiles() {
  return new Map([
    ["app/App.tsx", "import React from 'react'; export const App = () => null;"],
    ["app/App.test.tsx", expectedSkips.map((title) => `it.skip('${title}', () => {});`).join("\n")],
    ["surface/types.ts", "export type Surface = string;"],
    ["surface/evidence.ts", "import type { Surface } from './types'; export const evidence = null as Surface | null;"],
    ["surface/adapters/primitives.ts", "import type { Surface } from '../types'; export const primitive = null as Surface | null;"],
    ["surface/load-private-snapshot.ts", "import type { BridgeClient } from '../bridge/contracts'; import { primitive } from './adapters/primitives'; export { primitive };"],
    ["surface/fixtures/demo-snapshot.ts", "import type { Surface } from '../types'; export const demo = null as Surface | null;"],
    ["surface/sources.ts", "import { demo } from './fixtures/demo-snapshot'; import './load-private-snapshot'; export { demo };"],
    ["bridge/contracts.ts", "export type BridgeClient = {};"],
    ["bridge/client.ts", "import type { BridgeClient } from './contracts'; export const client = {} as BridgeClient;"],
    ["bridge/client.test.ts", "import { it } from 'vitest'; import { client } from './client'; it('frames', () => client);"],
    ["components/Thing.tsx", "import React from 'react'; import type { Surface } from '../surface/types'; export const Thing = (_p: { value: Surface }) => null;"],
    ["components/Thing.test.tsx", "import { it } from 'vitest'; import { Thing } from './Thing'; import type { Surface } from '../surface/types'; it('owns component', () => Thing as Surface | unknown);"],
    ["features/overview/Overview.tsx", "import { Thing } from '../../components/Thing'; import type { Surface } from '../../surface/types'; export const Overview = (_p: { value: Surface }) => Thing;"],
    ["features/overview/Overview.test.tsx", "import { it } from 'vitest'; import { Overview } from './Overview'; import type { Surface } from '../../surface/types'; it('owns feature', () => Overview as Surface | unknown);"],
    ["surface/adapters/primitives.test.ts", "import { it } from 'vitest'; import { primitive } from './primitives'; import type { Surface } from '../types'; it('owns adapter', () => primitive as Surface | null);"],
    ["surface/fixtures/demo-snapshot.test.ts", "import { it } from 'vitest'; import { demo } from './demo-snapshot'; import type { Surface } from '../types'; it('owns fixture', () => demo as Surface | null);"],
  ]);
}

function assertViolation(label, mutate, expected) {
  selfCheckCases.push(label);
  const files = selfCheckFiles();
  mutate(files);
  const violations = collectViolations(files);
  if (!violations.some((violation) => violation.includes(expected))) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

const selfCheckSentences = ["Saved privately. Reading will wait until you choose a reader."];

const selfCheckCases = [];

function assertSentenceViolation(label, mutate) {
  selfCheckCases.push(label);
  const files = selfCheckFiles();
  mutate(files);
  const violations = collectViolations(files, selfCheckSentences);
  if (!violations.some((violation) => violation.includes("shipped sentence typed out"))) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function assertSentenceValid(label, mutate) {
  selfCheckCases.push(label);
  const files = selfCheckFiles();
  mutate(files);
  const violations = collectViolations(files, selfCheckSentences);
  if (violations.length) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function assertConfigurationViolation(label, source, expected) {
  selfCheckCases.push(label);
  const violations = dragDropCaptureViolations(source);
  if (!violations.some((violation) => violation.includes(expected))) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function assertConfigurationValid(label, source) {
  selfCheckCases.push(label);
  const violations = dragDropCaptureViolations(source);
  if (violations.length) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function assertValid(label, mutate) {
  selfCheckCases.push(label);
  const files = selfCheckFiles();
  mutate(files);
  const violations = collectViolations(files);
  if (violations.length) throw new Error(`architecture self-check failed (${label}): ${JSON.stringify(violations)}`);
}

function assertThrows(label, run) {
  selfCheckCases.push(label);
  let threw = false;
  try { run(); } catch { threw = true; }
  if (!threw) throw new Error(`architecture self-check failed (${label}): it returned where it should have refused`);
}

function runSelfChecks() {
  selfCheckCases.length = 0;
  selfCheckCases.push("the unmutated graph is clean");
  const valid = collectViolations(selfCheckFiles());
  if (valid.length) throw new Error(`architecture self-check failed (valid graph): ${JSON.stringify(valid)}`);
  assertValid("unmodified parameterized tests and chains", (files) => files.set("surface/types.test.ts", "import { it as spec } from 'vitest'; import * as v from 'vitest'; spec.each([])('allowed each', () => {}); v.it.for([])('allowed for', () => {}); it.concurrent.sequential('allowed chain', () => {});"));
  assertViolation("fourth skip", (files) => files.set("surface/types.test.ts", "it.skip('fourth skip', () => {});"), "unauthorized canonical skip");
  assertViolation("skip each exact-title escape", (files) => files.set("surface/types.test.ts", `it.skip.each([])('${retiredSkipTitles[0]}', () => {});`), "unauthorized disabled test");
  assertViolation("each call then skip", (files) => files.set("surface/types.test.ts", "it.each([]).skip('parameterized skip', () => {});"), "unauthorized disabled test");
  assertViolation("tagged skip each", (files) => files.set("surface/types.test.ts", "it.skip.each`a | b`('tagged skip', () => {});"), "unauthorized disabled test");
  assertViolation("tagged each then skip", (files) => files.set("surface/types.test.ts", "it.each`a ${rows} b`.skip('tagged skip', () => {});"), "unauthorized disabled test");
  assertViolation("for call then skip", (files) => files.set("surface/types.test.ts", "test.for([]).skip('parameterized for skip', () => {});"), "unauthorized disabled test");
  assertViolation("import alias skip", (files) => files.set("surface/types.test.ts", "import { it as spec } from 'vitest'; spec.skip('aliased skip', () => {});"), "unauthorized disabled test");
  assertViolation("namespace skip", (files) => files.set("surface/types.test.ts", "import * as v from 'vitest'; v.test.concurrent.skip('namespace skip', () => {});"), "unauthorized disabled test");
  assertViolation("namespace static test element", (files) => files.set("surface/types.test.ts", "import * as vt from 'vitest'; vt['test'].skip('namespace element skip', () => {});"), "unauthorized disabled test");
  assertViolation("namespace static it and skip elements", (files) => files.set("surface/types.test.ts", "import * as vt from 'vitest'; vt['it']['skip']('namespace elements skip', () => {});"), "unauthorized disabled test");
  assertViolation("parenthesized it skip", (files) => files.set("surface/types.test.ts", "(it).skip('parenthesized skip', () => {});"), "unauthorized disabled test");
  assertViolation("nested parenthesized it skip", (files) => files.set("surface/types.test.ts", "((it)).skip('nested parenthesized skip', () => {});"), "unauthorized disabled test");
  assertViolation("parenthesized namespace skip", (files) => files.set("surface/types.test.ts", "import * as vt from 'vitest'; (vt.test).skip('parenthesized namespace skip', () => {});"), "unauthorized disabled test");
  assertViolation("static skip element", (files) => files.set("surface/types.test.ts", "it['skip']('static element skip', () => {});"), "unauthorized disabled test");
  assertViolation("namespace static skip element", (files) => files.set("surface/types.test.ts", "import * as vt from 'vitest'; vt.test['skip']('namespace static skip', () => {});"), "unauthorized disabled test");
  assertViolation("mixed parenthesized namespace each static skip", (files) => files.set("surface/types.test.ts", "import * as vt from 'vitest'; const rows = []; (vt['test'].each(rows))['skip']('mixed skip', () => {});"), "unauthorized disabled test");
  assertViolation("optional only", (files) => files.set("surface/types.test.ts", "it?.only('optional focus', () => {});"), "focused test remains");
  assertViolation("parenthesized todo", (files) => files.set("surface/types.test.ts", "((test)).todo('parenthesized todo');"), "todo test remains");
  assertViolation("non-null skip", (files) => files.set("surface/types.test.ts", "it!.skip('non-null skip', () => {});"), "unauthorized disabled test");
  assertViolation("as-asserted skip", (files) => files.set("surface/types.test.ts", "(it as unknown).skip('asserted skip', () => {});"), "unauthorized disabled test");
  assertViolation("type-asserted skip", (files) => files.set("surface/types.test.ts", "(<unknown>it).skip('type asserted skip', () => {});"), "unauthorized disabled test");
  assertViolation("dynamic Vitest element", (files) => files.set("surface/types.test.ts", "const modifier = 'skip'; it[modifier]('dynamic element', () => {});"), "dynamic Vitest element access");
  assertViolation("conditional skip", (files) => files.set("surface/types.test.ts", "it.skipIf(false)('conditional skip', () => {});"), "unauthorized disabled test");
  assertViolation("disabled globals", (files) => files.set("surface/types.test.ts", "xit('xit'); xtest('xtest'); xdescribe('xdescribe'); xsuite('xsuite');"), "unauthorized disabled test");
  for (const title of retiredSkipTitles) {
    assertViolation(`retired canonical skip ${title}`, (files) => files.set("app/App.test.tsx", `it.skip('${title}', () => {});`), "unauthorized canonical skip");
    assertViolation(`retired focused test ${title}`, (files) => files.set("app/App.test.tsx", `it.only('${title}', () => {});`), "focused test remains");
    assertViolation(`retired todo test ${title}`, (files) => files.set("app/App.test.tsx", `it.todo('${title}');`), "todo test remains");
  }
  assertViolation("duplicate canonical skip", (files) => files.set("app/App.test.tsx", `it.skip('${retiredSkipTitles[0]}', () => {});\nit.skip('${retiredSkipTitles[0]}', () => {});`), "unauthorized canonical skip");
  assertViolation("canonical title in wrong file", (files) => files.set("surface/types.test.ts", `it.skip('${retiredSkipTitles[0]}', () => {});`), "unauthorized canonical skip");
  assertViolation("wrong canonical title", (files) => files.set("app/App.test.tsx", `${files.get("app/App.test.tsx")}\nit.skip('wrong title', () => {});`), "unauthorized canonical skip");
  assertViolation("dynamic skip title", (files) => files.set("surface/types.test.ts", "const title = 'dynamic'; it.skip(title, () => {});"), "dynamic title");
  assertViolation("parameterized skip", (files) => files.set("surface/types.test.ts", "it.skip.for([])('parameterized', () => {});"), "unauthorized disabled test");
  assertViolation("direct and chained only", (files) => files.set("surface/types.test.ts", "it.only('focused', () => {}); describe.concurrent.sequential.only('focused suite', () => {});"), "focused test remains");
  assertViolation("direct and parameterized todo", (files) => files.set("surface/types.test.ts", "test.todo('later'); suite.each([]).todo('later each');"), "todo test remains");
  assertViolation("bridge production to surface", (files) => files.set("bridge/client.ts", "import '../surface/types';"), "bridge import forbidden");
  assertViolation("bridge test to upper layers", (files) => files.set("bridge/client.test.ts", "import '../surface/types'; import '../app/session'; import '../surface/fixtures/demo-snapshot';"), "owner test import forbidden");
  assertViolation("component test to sources", (files) => files.set("components/Thing.test.tsx", "import '../surface/sources';"), "owner test import forbidden");
  assertValid("Evidence drawer owns its exact FeatureBoundary sibling", (files) => files.set("components/EvidenceDrawer.tsx", "import { Thing } from './FeatureBoundary'; export { Thing };"));
  assertViolation("other component cannot import FeatureBoundary", (files) => files.set("components/Thing.tsx", "import './FeatureBoundary';"), "component import forbidden");
  assertViolation("Evidence drawer cannot import other component helpers", (files) => files.set("components/EvidenceDrawer.tsx", "import './Thing';"), "component import forbidden");
  assertViolation("adapter test to app", (files) => files.set("surface/adapters/primitives.test.ts", "import '../../app/session';"), "owner test import forbidden");
  assertViolation("feature test to bridge and fixture", (files) => files.set("features/overview/Overview.test.tsx", "import '../../bridge/client'; import '../../surface/fixtures/demo-snapshot';"), "owner test import forbidden");
  assertViolation("fixture test to app", (files) => files.set("surface/fixtures/demo-snapshot.test.ts", "import '../../app/session';"), "owner test import forbidden");
  assertValid("exact surface scenario support and owner matrix", (files) => { files.set("test/surfaceScenarios.ts", "import type { Surface } from '../surface/types'; export const scenario = null as Surface | null;"); files.set("test/SurfaceMatrix.test.tsx", "import { it } from 'vitest'; import { scenario } from './surfaceScenarios'; import { Overview } from '../features/overview/Overview'; import { Accounts } from '../features/accounts/Accounts'; import type { Surface } from '../surface/types'; it('owns the matrix', () => [scenario, Overview, Accounts] as Surface[]);"); });
  assertViolation("owner matrix import outside exact allowlist", (files) => files.set("test/SurfaceMatrix.test.tsx", "import { it } from 'vitest'; import '../features/review/Review'; it('crosses the matrix', () => {});"), "owner test import forbidden");
  assertViolation("other test support remains production", (files) => files.set("test/otherSupport.ts", "import '../app/session';"), "test production import forbidden");
  assertViolation("production imports test support", (files) => files.set("features/overview/Overview.tsx", "import '../../test/surfaceScenarios';"), "test support imported outside owner matrix");
  assertViolation("non-owner test imports scenario support", (files) => files.set("features/overview/Overview.test.tsx", "import '../../test/surfaceScenarios';"), "owner test import forbidden");
  assertViolation("scenario support crosses upper layers", (files) => files.set("test/surfaceScenarios.ts", "import '../app/session'; import '../features/overview/Overview'; import '../surface/fixtures/demo-snapshot'; import '../surface/adapters/overview'; import '../surface/sources'; import '../bridge/client';"), "test support import forbidden");
  assertViolation("feature to bridge", (files) => files.set("features/overview/Overview.tsx", "import '../../bridge/client';"), "feature crosses data boundary");
  assertViolation("feature to adapter", (files) => files.set("features/overview/Overview.tsx", "import '../../surface/adapters/overview';"), "feature crosses data boundary");
  assertViolation("feature to fixture", (files) => files.set("features/overview/Overview.tsx", "import '../../surface/fixtures/demo-snapshot';"), "feature crosses data boundary");
  assertViolation("feature to feature", (files) => files.set("features/overview/Overview.tsx", "import '../review/Review';"), "feature imports another feature");
  assertViolation("raw shape in UI", (files) => files.set("app/raw.ts", "export const raw = (value: unknown): Record<string, unknown> => value as Record<string, unknown>;"), "raw shape leaked into UI");
  assertViolation("live loader to fixture", (files) => files.set("surface/load-private-snapshot.ts", "import './fixtures/demo-snapshot';"), "live fixture import forbidden");
  assertViolation("frontend arithmetic", (files) => files.set("features/overview/Overview.tsx", "export const total = Number('1');"), "frontend arithmetic forbidden");
  assertViolation("compatibility marker", (files) => files.set("app/compat.ts", "// WP-01 temporary compatibility export"), "compatibility marker remains");
  assertViolation("legacy module", (files) => files.set("app/model.ts", "export const old = true;"), "legacy module remains");
  assertViolation("legacy identifier", (files) => files.set("app/alias.ts", "export const demoState = {};"), "legacy alias or builder remains");
  assertViolation("exact value render boundary", (files) => files.set("surface/evidence.ts", "export const leak = (value: { exactValue: string }) => value.exactValue;"), "exactValue crossed the render boundary");
  assertValid("exact value stays in adapters and fixtures", (files) => { files.set("surface/adapters/overview.ts", "export const raw = { exactValue: '1' };"); files.set("surface/fixtures/demo-snapshot.ts", "export const demo = { exactValue: '1' };"); });
  assertValid("capture prose beside a control that waits in words", (files) => files.set("features/documents/Documents.tsx", "const prose = \"The @tauri-apps/plugin-dialog package, FileReader, fetch, onDrop, and type=file stay unavailable.\"; export const Documents = () => <><p>FileReader fetch onDrop type=file @tauri-apps/plugin-dialog</p><button aria-disabled={true}>{prose}</button></>;"));
  assertViolation("file input", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <input type='file' />;"), "file input forbidden");
  assertViolation("braced file input", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <input type={'file'} />;"), "file input forbidden");
  assertViolation("braced case-insensitive file input", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <input type={\"FiLe\"} />;"), "file input forbidden");
  assertViolation("template file input", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <input type={`file`} />;"), "file input forbidden");
  assertViolation("parenthesized file input", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <input type={((\"file\"))} />;"), "file input forbidden");
  assertValid("non-file input kinds remain valid", (files) => files.set("features/documents/Documents.tsx", "const kind = 'file'; export const Documents = () => <><input type={kind} /><input type='text' /><input type={'password'} /><p>type={'file'}</p></>;"));
  assertViolation("drop handler", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <div onDrop={() => {}} />;"), "capture drag handler forbidden");
  assertViolation("drag handler", (files) => files.set("app/App.tsx", "export const App = () => <div onDragOver={() => {}} />;"), "capture drag handler forbidden");
  for (const primitive of ["FileReader", "DataTransfer", "FormData", "XMLHttpRequest", "showOpenFilePicker", "showSaveFilePicker", "fetch"]) assertViolation(`capture primitive ${primitive}`, (files) => files.set("features/documents/Documents.tsx", `export const Documents = () => { ${primitive}(); return null; };`), "capture primitive forbidden");
  assertViolation("clipboard primitive", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => { navigator.clipboard.writeText('x'); return null; };"), "capture clipboard primitive forbidden");
  assertViolation("document timeout", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => { setTimeout(() => {}, 1); return null; };"), "capture primitive forbidden");
  assertViolation("document interval", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => { setInterval(() => {}, 1); return null; };"), "capture primitive forbidden");
  assertViolation("Tauri dialog import", (files) => files.set("features/documents/Documents.tsx", "import { open } from '@tauri-apps/plugin-dialog'; export const Documents = open;"), "capture dialog import forbidden");
  assertValid("exact conversation question presentation pair", (files) => { files.set("features/conversation/questionPresentation.ts", "import type { Surface } from '../../surface/types'; export const questions = null as Surface | null;"); files.set("features/conversation/Questions.tsx", "import { questions } from './questionPresentation'; export { questions };"); });
  assertViolation("Questions other helper", (files) => files.set("features/conversation/Questions.tsx", "import './anythingElse';"), "feature import forbidden");
  assertViolation("other feature imports question presentation", (files) => files.set("features/overview/Overview.tsx", "import '../conversation/questionPresentation';"), "feature import forbidden");
  assertViolation("cross-feature question presentation import", (files) => files.set("features/accounts/Accounts.tsx", "import '../../features/conversation/questionPresentation';"), "feature import forbidden");
  assertValid("exact documents presentation pair", (files) => { files.set("features/documents/documentPresentation.ts", "import type { Surface } from '../../surface/types'; export const document = null as Surface | null;"); files.set("features/documents/Documents.tsx", "import { document } from './documentPresentation'; export { document };"); });
  assertViolation("Documents other helper", (files) => files.set("features/documents/Documents.tsx", "import './anythingElse';"), "feature import forbidden");
  assertViolation("question presentation stays below upper layers", (files) => files.set("features/conversation/questionPresentation.ts", "import '../../bridge/client'; import '../../surface/adapters/review'; import '../../surface/fixtures/demo-snapshot'; import '../../app/session'; import '../overview/Overview';"), "feature crosses data boundary");
  assertValid("exact activity presentation pair", (files) => { files.set("features/activity/activityPresentation.ts", "import type { Surface } from '../../surface/types'; export const activity = null as Surface | null;"); files.set("features/activity/Activity.tsx", "import { activity } from './activityPresentation'; export { activity };"); });
  assertViolation("Activity other helper", (files) => files.set("features/activity/Activity.tsx", "import './anythingElse';"), "feature import forbidden");
  assertViolation("other feature imports activity presentation", (files) => files.set("features/overview/Overview.tsx", "import '../activity/activityPresentation';"), "feature import forbidden");
  assertViolation("activity presentation crosses upper layers", (files) => files.set("features/activity/activityPresentation.ts", "import '../../bridge/client'; import '../../surface/adapters/review'; import '../../surface/fixtures/demo-snapshot'; import '../../app/session'; import '../overview/Overview';"), "feature crosses data boundary");
  assertViolation("activity presentation raw shape", (files) => files.set("features/activity/activityPresentation.ts", "export const raw: unknown = {};"), "raw shape leaked into UI");
  assertViolation("activity presentation arithmetic", (files) => files.set("features/activity/activityPresentation.ts", "export const amount = Number('1');"), "frontend arithmetic forbidden");
  assertValid("exact conversation composition", (files) => { files.set("features/conversation/questionPresentation.ts", "import type { Surface } from '../../surface/types'; export const questions = null as Surface | null;"); files.set("features/conversation/Questions.tsx", "import { questions } from './questionPresentation'; export { questions };"); files.set("features/conversation/ConversationDrawer.tsx", "import { Questions } from './Questions'; import { questions } from './questionPresentation'; export { Questions, questions };"); });
  assertViolation("Conversation other helper", (files) => files.set("features/conversation/ConversationDrawer.tsx", "import './anythingElse';"), "feature import forbidden");
  assertViolation("other feature imports conversation questions", (files) => files.set("features/overview/Overview.tsx", "import '../conversation/Questions';"), "feature import forbidden");
  assertViolation("question presentation crosses upper layers", (files) => files.set("features/conversation/questionPresentation.ts", "import '../../bridge/client'; import '../../surface/adapters/review'; import '../../surface/fixtures/demo-snapshot'; import '../../app/session'; import '../overview/Overview';"), "feature crosses data boundary");
  assertViolation("question presentation raw shape", (files) => files.set("features/conversation/questionPresentation.ts", "export const raw: unknown = {};"), "raw shape leaked into UI");
  assertViolation("question presentation arithmetic", (files) => files.set("features/conversation/questionPresentation.ts", "export const amount = Number('1');"), "frontend arithmetic forbidden");
  assertValid("shell test reads the backend parity artifact", (files) => files.set("app/App.test.tsx", `import { it } from 'vitest'; import artifact from '${shellParityFixture}'; it('reads one artifact', () => artifact);`));
  assertViolation("shell test reads some other backend file", (files) => files.set("app/App.test.tsx", "import held from '../../../product/viva/surface/fixtures/surface-v1.json'; export default held;"), "owner test import forbidden");
  assertValid("adapter test reads the backend parity artifact", (files) => files.set("surface/adapters/primitives.test.ts", `import { it } from 'vitest'; import artifact from '${backendParityFixture}'; import { primitive } from './primitives'; it('reads one artifact', () => [artifact, primitive]);`));
  assertViolation("adapter test reads another path beside the artifact", (files) => files.set("surface/adapters/primitives.test.ts", "import { it } from 'vitest'; import other from '../../../../product/viva/surface/fixtures/surface-v1.json'; it('reads another', () => other);"), "owner test import forbidden");
  assertViolation("non-adapter test reads the parity artifact", (files) => files.set("components/Thing.test.tsx", `import { it } from 'vitest'; import artifact from '../../${backendParityFixture}'; it('reads the artifact', () => artifact);`), "owner test import forbidden");
  assertViolation("adapter production reads the parity artifact", (files) => files.set("surface/adapters/primitives.ts", `import artifact from '${backendParityFixture}'; export const primitive = artifact;`), "adapter import forbidden");
  assertThrows("a source the tokenizer cannot advance through is refused rather than looped over", () => scanTypeScript("probe.ts", "const found = value.match(/^#([0-9a-f]{6})$/i);"));
  assertThrows("a pack holding no sentences is refused rather than walked", () => packSentences({ _comment: "a pack with its lines taken out" }));
  assertThrows("a pack holding only blank sentences is refused", () => packSentences({ documents_saved_no_reader: "   " }));
  assertSentenceViolation("a test types out a sentence the pack ships", (files) => files.set("features/overview/Overview.test.tsx", `import { it } from 'vitest'; it('says it', () => '${selfCheckSentences[0]}');`));
  assertSentenceViolation("a component types out a sentence the pack ships", (files) => files.set("features/overview/Overview.tsx", `export const Overview = () => "${selfCheckSentences[0]}";`));
  assertSentenceViolation("a sentence the pack ships written as a template literal", (files) => files.set("features/overview/Overview.tsx", "export const Overview = () => `" + selfCheckSentences[0] + "`;"));
  assertSentenceViolation("a sentence the pack ships written as bare text between tags", (files) => files.set("features/overview/Overview.tsx", `export const Overview = () => <p>${selfCheckSentences[0]}</p>;`));
  assertSentenceValid("prose between tags that is not one of the pack's sentences", (files) => files.set("features/overview/Overview.tsx", "export const Overview = () => <p>Saved privately, and nothing more is claimed.</p>;"));
  assertSentenceValid("a sentence read from the pack rather than written out", (files) => files.set("features/overview/Overview.test.tsx", "import { it } from 'vitest'; import moments from '../../../../product/viva/persona/pack-v18/moments.json'; it('reads it', () => moments.documents_saved_no_reader);"));
  assertSentenceValid("prose that is not one of the pack's sentences", (files) => files.set("features/overview/Overview.tsx", "export const Overview = () => 'Saved privately, and nothing more is claimed.';"));
  assertValid("a test reads the sentences a person is told from the pack that ships them", (files) => { files.set("features/overview/Overview.test.tsx", "import { it } from 'vitest'; import moments from '../../../../product/viva/persona/pack-v18/moments.json'; import { Overview } from './Overview'; it('reads the pack', () => [moments, Overview]);"); files.set("app/App.test.tsx", `${files.get("app/App.test.tsx")}\nimport moments from '../../../product/viva/persona/pack-v19/moments.json';`); });
  assertViolation("a production module reads the pack", (files) => files.set("features/overview/Overview.tsx", "import moments from '../../../../product/viva/persona/pack-v18/moments.json'; export const Overview = () => moments;"), "persona pack read outside a test");
  assertViolation("a test reads something else from the product package", (files) => files.set("features/overview/Overview.test.tsx", "import { it } from 'vitest'; import other from '../../../../product/viva/persona/pack-v18/phrasings.json'; it('reads more', () => other);"), "owner test import forbidden");
  assertViolation("a test reads the pack by an absolute-looking path", (files) => files.set("features/overview/Overview.test.tsx", "import { it } from 'vitest'; import moments from 'product/viva/persona/pack-v18/moments.json'; it('reads the pack', () => moments);"), "owner test import forbidden");
  assertViolation("forbidden import spread over four lines", (files) => files.set("surface/adapters/primitives.test.ts", "import { it } from 'vitest';\nimport\n  {\n    session\n  }\n  from\n    '../../app/session';\nit('crosses', () => session);"), "owner test import forbidden");
  assertValid("the shim's test reaches the same two packages the shim may", (files) => files.set(hostShimTest, "import { it } from 'vitest'; import type { DragDropEvent } from '@tauri-apps/api/webview'; import { open } from '@tauri-apps/plugin-dialog'; import './tauri-host'; it('types the payload', () => [null as DragDropEvent | null, open]);"));
  assertViolation("the shim's test reaches a package the shim may not", (files) => files.set(hostShimTest, "import { it } from 'vitest'; import { readFile } from '@tauri-apps/plugin-fs'; it('reads', () => readFile);"), "owner test import forbidden");
  assertViolation("another test reaches a host package", (files) => files.set("features/overview/Overview.test.tsx", "import { it } from 'vitest'; import type { DragDropEvent } from '@tauri-apps/api/webview'; it('types', () => null as DragDropEvent | null);"), "owner test import forbidden");
  assertValid("host shim reaches only its two named packages", (files) => files.set(hostShim, "import { open } from '@tauri-apps/plugin-dialog'; import { getCurrentWebview } from '@tauri-apps/api/webview'; import type { BridgeClient } from './bridge/contracts'; export const host = [open, getCurrentWebview] as unknown as BridgeClient;"));
  for (const primitive of ["FileReader", "DataTransfer", "FormData", "XMLHttpRequest", "showOpenFilePicker", "showSaveFilePicker", "fetch"]) assertViolation(`host shim capture primitive ${primitive}`, (files) => files.set(hostShim, `export const read = () => { ${primitive}(); };`), "capture primitive forbidden");
  assertViolation("host shim clipboard primitive", (files) => files.set(hostShim, "export const copy = () => { navigator.clipboard.writeText('x'); };"), "capture clipboard primitive forbidden");
  assertViolation("host shim drag handler", (files) => files.set(hostShim, "export const element = { onDrop: null }; element.onDrop = () => {};"), "capture drag handler forbidden");
  assertViolation("host shim reaches an unnamed host package", (files) => files.set(hostShim, "import { readFile } from '@tauri-apps/plugin-fs'; export const read = readFile;"), "capture host package forbidden");
  assertViolation("host shim reaches a package root rather than the named entry", (files) => files.set(hostShim, "import { getCurrentWebview } from '@tauri-apps/api'; export const webview = getCurrentWebview;"), "capture host package forbidden");
  assertViolation("host shim reaches an ordinary dependency", (files) => files.set(hostShim, "import { useState } from 'react'; export const state = useState;"), "capture host package forbidden");
  assertViolation("disabled attribute with no value", (files) => files.set("features/documents/Documents.tsx", "export const Documents = () => <button disabled>Choose a file</button>;"), "disabled attribute forbidden");
  assertViolation("disabled attribute bound to a state", (files) => files.set("app/App.tsx", "export const App = () => <button disabled={true}>Open</button>;"), "disabled attribute forbidden");
  assertViolation("disabled attribute on a self-closing element", (files) => files.set("components/Thing.tsx", "export const Thing = () => <input disabled />;"), "disabled attribute forbidden");
  assertViolation("disabled attribute on a composed component", (files) => files.set("features/overview/Overview.tsx", "export const Overview = () => <Thing disabled={false} />;"), "disabled attribute forbidden");
  assertViolation("disabled attribute inside a test render", (files) => files.set("surface/types.test.ts", "import { it } from 'vitest'; it('renders', () => <button disabled>x</button>);"), "disabled attribute forbidden");
  assertValid("aria-disabled, disabled selectors and disabled properties", (files) => files.set("components/Thing.tsx", "export const Thing = (props: { busy: boolean; node: HTMLButtonElement }) => { const focusable = 'button:not([disabled]), input:not([disabled])'; props.node.setAttribute('disabled', ''); const flag = props.node.disabled; return <button aria-disabled={props.busy} data-focusable={focusable} data-flag={flag}>Choose a file</button>; };"));
  assertConfigurationValid("window drag-drop capture stated on", JSON.stringify({ app: { windows: [{ title: "OrionViva", dragDropEnabled: true }] } }));
  assertConfigurationViolation("window drag-drop capture switched off", JSON.stringify({ app: { windows: [{ title: "OrionViva", dragDropEnabled: false }] } }), "window drag-drop capture disabled");
  assertConfigurationViolation("window drag-drop capture left to the default", JSON.stringify({ app: { windows: [{ title: "OrionViva" }] } }), "window drag-drop capture unstated");
  assertConfigurationViolation("window drag-drop capture written in the alias spelling", JSON.stringify({ app: { windows: [{ "drag-drop-enabled": true }] } }), "window drag-drop capture unstated");
  assertConfigurationViolation("one window states it and a second does not", JSON.stringify({ app: { windows: [{ label: "main", dragDropEnabled: true }, { label: "second", dragDropEnabled: false }] } }), "window drag-drop capture disabled: second");
  assertConfigurationViolation("no window at all", JSON.stringify({ app: { windows: [] } }), "window drag-drop capture unstated");
  assertConfigurationViolation("a configuration that is not JSON", "{ this is not configuration", "window drag-drop capture unreadable");
  return selfCheckCases.length;
}

function filesAt(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => entry.isDirectory() ? filesAt(join(directory, entry.name)) : [join(directory, entry.name)]);
}

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "src");
const liveFiles = new Map(filesAt(src).filter((file) => /\.(ts|tsx)$/.test(file)).map((file) => [relative(src, file).replaceAll("\\", "/"), readFileSync(file, "utf8")]));
const selfChecks = runSelfChecks();
const shipped = shippedSentences(resolve(root, "..", "product"));
const violations = [...collectViolations(liveFiles, shipped.sentences), ...dragDropCaptureViolations(readFileSync(join(root, "src-tauri", "tauri.conf.json"), "utf8"))];
if (violations.length) {
  for (const violation of violations) console.error(violation);
  process.exit(1);
}
const productionCount = [...liveFiles.keys()].filter((name) => !isTest(name) && !isTestSupport(name)).length;
console.log(`UI architecture self-checks passed (${selfChecks} cases).`);
console.log(`UI architecture boundaries passed (${productionCount} production modules, ${expectedSkips.length} authorized skips).`);
console.log(`UI architecture sentences passed (${shipped.sentences.length} shipped by ${shipped.pack}, none written out under src).`);
console.log(`UI architecture read ${liveFiles.size} modules with a scanner that refuses a regular-expression literal; write new RegExp("…") until it handles one.`);
