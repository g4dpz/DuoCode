// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
/**
 * Architecture rules (task 2.6, R14.1, R8.11). Pure functions, so each rule is
 * unit-tested on fixtures; `rules_test.ts` applies them to the repository.
 *
 * Conventions these rules fix for later tasks:
 * - The engine (`src/engine/`) imports only other engine files: no Oak, HTTP,
 *   database, crypto, randomness or I/O.
 * - The HTTP layer (`src/http/`) imports nothing from `src/persistence/`, so it
 *   can perform no credential lookup.
 * - Reads of the `credentials` table live in `src/persistence/credential_lookup.ts`,
 *   and only `src/services/authorise.ts` imports that module (design.md 5.1).
 *   Writes (issue, rotate, revoke) may live elsewhere in `src/persistence/`.
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
 * Keeps only code: removes `//` and `/* *\/` comments and blanks the contents of
 * string and template literals (quotes and line breaks stay, so line numbers hold).
 * Expressions inside template `${}` are blanked too; the rules accept that limit.
 */
export function codeOnly(text: string): string {
  let out = "";
  let i = 0;
  let quote: string | null = null;
  while (i < text.length) {
    const c = text[i];
    const n = text[i + 1];
    if (quote !== null) {
      if (c === "\\") {
        out += n === "\n" ? "\n" : "  ";
        i += 2;
        continue;
      }
      if (c === quote) {
        out += c;
        quote = null;
      } else out += c === "\n" ? "\n" : " ";
      i++;
    } else if (c === '"' || c === "'" || c === "`") {
      quote = c;
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
  text: string,
  rules: [RegExp, string][],
): string[] {
  const code = codeOnly(text);
  const out: string[] = [];
  for (const [re, what] of rules) {
    for (
      const m of code.matchAll(
        new RegExp(
          re.source,
          re.flags.includes("g") ? re.flags : re.flags + "g",
        ),
      )
    ) {
      out.push(`${path}:${lineOf(code, m.index ?? 0)}: ${what}`);
    }
  }
  return out;
}

const MATH_RANDOM = new RegExp(["\\bMath", "random\\b"].join("\\s*\\.\\s*"));

/** Uses that make engine code impure (R14.1): runtime, crypto, randomness, network, console, dynamic import. */
export function engineBannedUses(path: string, text: string): string[] {
  return findAll(path, text, [
    [/\bDeno\s*\./, "uses the Deno runtime API"],
    [/\bcrypto\b/, "uses crypto (including getRandomValues and randomUUID)"],
    [MATH_RANDOM, "uses Math.random"],
    [/\bfetch\s*\(/, "uses fetch"],
    [/\b(?:XMLHttpRequest|WebSocket)\b/, "uses network I/O"],
    [/\bconsole\s*\./, "uses console output"],
    [/\bimport\s*\(/, "uses a dynamic import"],
  ]);
}

/** Math.random anywhere outside the simulator (T25). */
export function mathRandomUses(path: string, text: string): string[] {
  return findAll(path, text, [[
    MATH_RANDOM,
    "uses Math.random (allowed only in tools/simulator/)",
  ]]);
}

/**
 * SQL that reads the credentials table (`FROM credentials`, `JOIN credentials`).
 * SQL lives in strings, so this scans the raw text, comments included.
 * Allowed only in src/persistence/credential_lookup.ts.
 */
export function credentialReads(path: string, text: string): string[] {
  const out: string[] = [];
  text.split("\n").forEach((line, i) => {
    if (/\b(?:FROM|JOIN)\s+credentials\b/i.test(line)) {
      out.push(`${path}:${i + 1}: reads the credentials table`);
    }
  });
  return out;
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

/** Modules in the graph that import `target` directly, other than those in `allowed`. */
export function directImporters(
  graph: InfoGraph,
  target: string,
  allowed: readonly string[],
): string[] {
  const resolve = (s: string) => graph.redirects?.[s] ?? s;
  return graph.modules
    .filter((m) =>
      (m.dependencies ?? []).some((d) =>
        d.code?.specifier !== undefined && resolve(d.code.specifier) === target
      )
    )
    .map((m) => m.specifier)
    .filter((s) => !allowed.includes(s));
}
