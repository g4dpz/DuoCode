// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
/**
 * Architecture rules (task 2.6, R14.1, R8.11; Phase 2 review fixes). Pure
 * functions, so each rule is unit-tested; `rules_test.ts` applies them to the
 * repository and to the committed violating fixtures in `fixtures/`.
 *
 * Conventions these rules fix for later tasks:
 * - The engine (`src/engine/`) imports only other engine files and uses no
 *   runtime, crypto, randomness, clock, network, console, `globalThis`,
 *   `eval` or dynamic import.
 * - The HTTP layer (`src/http/`) imports nothing from `src/persistence/`
 *   directly (it may call services, which use persistence), so it performs no
 *   credential lookup of its own.
 * - Reads of the `credentials` table live in
 *   `src/persistence/credential_lookup.ts`, and only `src/services/authorise.ts`
 *   imports that module (design.md 5.1). Writes (issue, rotate, revoke) may
 *   live elsewhere in `src/persistence/`.
 * - The reference implementation (`tests/reference/`) reaches no engine file
 *   (R14: they share no code).
 */

/** One module of `deno info --json` output. */
export interface InfoModule {
  specifier: string;
  error?: string;
  dependencies?: {
    specifier: string;
    code?: { specifier?: string; error?: string };
  }[];
}
export interface InfoGraph {
  modules: InfoModule[];
  redirects?: Record<string, string>;
}

/**
 * Keeps only code: removes `//` and `/* *\/` comments and blanks the text of
 * string and template literals. Code inside template `${...}` is kept. Quotes
 * and line breaks stay, so line numbers hold.
 */
export function codeOnly(text: string): string {
  let out = "";
  let i = 0;
  // Each entry is the quote being read, or "{" for code inside `${...}` (with its brace depth).
  const stack: { quote: string; depth: number }[] = [];
  const top = () => stack[stack.length - 1];
  while (i < text.length) {
    const c = text[i];
    const n = text[i + 1];
    const t = top();
    if (t !== undefined && t.quote !== "{") {
      if (c === "\\") {
        out += n === "\n" ? "\n" : "  ";
        i += 2;
      } else if (t.quote === "`" && c === "$" && n === "{") {
        out += "${";
        stack.push({ quote: "{", depth: 0 });
        i += 2;
      } else if (c === t.quote) {
        out += c;
        stack.pop();
        i++;
      } else {
        out += c === "\n" ? "\n" : " ";
        i++;
      }
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      stack.push({ quote: c, depth: 0 });
      out += c;
      i++;
    } else if (c === "/" && n === "/") {
      while (i < text.length && text[i] !== "\n") i++;
    } else if (c === "/" && n === "*") {
      i += 2;
      while (i < text.length && !(text[i] === "*" && text[i + 1] === "/")) {
        if (text[i] === "\n") out += "\n";
        i++;
      }
      i += 2;
    } else {
      if (t !== undefined && c === "{") t.depth++;
      if (t !== undefined && c === "}") {
        if (t.depth === 0) stack.pop();
        else t.depth--;
      }
      out += c;
      i++;
    }
  }
  return out;
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

function findAll(
  path: string,
  code: string,
  rules: [RegExp, string][],
): string[] {
  const out: string[] = [];
  for (const [re, what] of rules) {
    const g = new RegExp(
      re.source,
      re.flags.includes("g") ? re.flags : re.flags + "g",
    );
    for (const m of code.matchAll(g)) {
      out.push(`${path}:${lineOf(code, m.index ?? 0)}: ${what}`);
    }
  }
  return out;
}

const MATH_RANDOM = new RegExp(["\\bMath", "random\\b"].join("\\s*\\.\\s*"));

/** Uses that make engine code impure (R14.1). Matches names, not only property access. */
export function engineBannedUses(path: string, text: string): string[] {
  return findAll(path, codeOnly(text), [
    [/\bDeno\b/, "uses the Deno runtime"],
    [/\bcrypto\b/, "uses crypto (including getRandomValues and randomUUID)"],
    [MATH_RANDOM, "uses Math.random"],
    [
      /\bDate\s*\.\s*now\b|\bnew\s+Date\b|\bperformance\b/,
      "reads the clock (pass time in as a parameter)",
    ],
    [
      /\bfetch\b|\b(?:XMLHttpRequest|WebSocket|EventSource)\b/,
      "uses network I/O",
    ],
    [/\bconsole\b/, "uses console output"],
    [/\bglobalThis\b/, "uses globalThis"],
    [/\beval\b|\bFunction\s*\(/, "evaluates code at runtime"],
    [/\bimport\s*\(/, "uses a dynamic import"],
  ]);
}

/** Math.random anywhere outside the simulator (T25). */
export function mathRandomUses(path: string, text: string): string[] {
  return findAll(path, codeOnly(text), [[
    MATH_RANDOM,
    "uses Math.random (allowed only in tools/simulator/)",
  ]]);
}

/**
 * SQL that reads the credentials table: `FROM` or `JOIN` followed by
 * `credentials`, optionally quoted or schema-qualified, across line breaks.
 * SQL lives in strings, so this scans the raw text. Allowed only in
 * src/persistence/credential_lookup.ts.
 */
export function credentialReads(path: string, text: string): string[] {
  const re =
    /\b(?:FROM|JOIN)\s+(?:"?[A-Za-z_][A-Za-z0-9_]*"?\s*\.\s*)?"?credentials"?(?![A-Za-z0-9_])/gi;
  return [...text.matchAll(re)].map((m) =>
    `${path}:${lineOf(text, m.index ?? 0)}: reads the credentials table`
  );
}

/** Every module in the graph that resolves outside `allowedPrefix`, or failed to resolve. */
export function outsideGraph(
  graph: InfoGraph,
  allowedPrefix: string,
): string[] {
  const out: string[] = [];
  for (const m of graph.modules) {
    if (m.error !== undefined) out.push(`${m.specifier}: does not resolve`);
    else if (!m.specifier.startsWith(allowedPrefix)) {
      out.push(`${m.specifier}: outside ${allowedPrefix}`);
    }
  }
  return out;
}

/** Modules in the graph that resolve under `forbiddenPrefix`. */
export function insideGraph(
  graph: InfoGraph,
  forbiddenPrefix: string,
): string[] {
  return graph.modules.filter((m) => m.specifier.startsWith(forbiddenPrefix))
    .map((m) => m.specifier);
}

function resolved(graph: InfoGraph, s: string): string {
  return graph.redirects?.[s] ?? s;
}

/** Direct imports from a module under `fromPrefix` into a module under `intoPrefix`, as "a -> b". */
export function directImportsInto(
  graph: InfoGraph,
  fromPrefix: string,
  intoPrefix: string,
): string[] {
  const out: string[] = [];
  for (const m of graph.modules) {
    if (!m.specifier.startsWith(fromPrefix)) continue;
    for (const d of m.dependencies ?? []) {
      const s = d.code?.specifier;
      if (s !== undefined && resolved(graph, s).startsWith(intoPrefix)) {
        out.push(`${m.specifier} -> ${resolved(graph, s)}`);
      }
    }
  }
  return out;
}

/** Modules in the graph that import `target` directly, other than those in `allowed`. */
export function directImporters(
  graph: InfoGraph,
  target: string,
  allowed: readonly string[],
): string[] {
  return graph.modules
    .filter((m) =>
      (m.dependencies ?? []).some((d) =>
        d.code?.specifier !== undefined &&
        resolved(graph, d.code.specifier) === target
      )
    )
    .map((m) => m.specifier)
    .filter((s) => !allowed.includes(s));
}
