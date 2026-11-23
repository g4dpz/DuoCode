// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture rules (task 2.6, R14.1, R8.11; test-strategy.md TS-CRED and section 17).
// Each rule runs on the repository (no findings allowed) and on the committed fixtures in
// fixtures/ (exactly the planted findings). Run with: deno task lint:rules (--allow-read --allow-run=deno).
import { assert, assertEquals } from "@std/assert";
import {
  codeOnly,
  credentialReads,
  directImporters,
  directImportsInto,
  engineBannedUses,
  type InfoGraph,
  insideGraph,
  mathRandomUses,
  outsideGraph,
} from "./rules.ts";

const BACKEND = new URL("../../", import.meta.url);
const REPO = new URL("../", BACKEND);
const FIXTURES = new URL("fixtures/", import.meta.url);
const MR = "Math" + ".random";
const SOURCE_EXT = /\.(?:ts|tsx|js|jsx|mjs|cjs)$/;
const SKIP_DIRS = new Set([
  ".git",
  "node_modules",
  "coverage",
  ".agents",
  ".worktrees",
  "dist",
]);

async function walk(dir: URL, out: URL[] = []): Promise<URL[]> {
  try {
    for await (const e of Deno.readDir(dir)) {
      if (e.isDirectory && !SKIP_DIRS.has(e.name)) {
        await walk(new URL(`${e.name}/`, dir), out);
      } else if (e.isFile && SOURCE_EXT.test(e.name)) {
        out.push(new URL(e.name, dir));
      }
    }
  } catch (e) {
    if (!(e instanceof Deno.errors.NotFound)) throw e;
  }
  return out;
}

async function graphOf(file: URL): Promise<InfoGraph> {
  const r = await new Deno.Command(Deno.execPath(), {
    args: ["info", "--json", file.pathname],
    cwd: BACKEND.pathname,
    stdout: "piped",
    stderr: "piped",
  }).output();
  if (!r.success) {
    throw new Error(
      `deno info failed for ${file.pathname}: ${
        new TextDecoder().decode(r.stderr)
      }`,
    );
  }
  return JSON.parse(new TextDecoder().decode(r.stdout));
}

/** Applies every rule to a tree with `src/` and `tests/` under `base` (the backend, or the fixtures). */
async function scan(base: URL): Promise<Record<string, string[]>> {
  const src = new URL("src/", base);
  const at = (p: string) => new URL(p, src).href;
  const rel = (s: string) => s.replaceAll(base.href, "");
  const engine = at("engine/"),
    http = at("http/"),
    persistence = at("persistence/");
  const lookup = at("persistence/credential_lookup.ts"),
    authorise = at("services/authorise.ts");
  const out: Record<string, string[]> = {
    engine: [],
    http: [],
    importers: [],
    sql: [],
    reference: [],
  };
  for (const f of await walk(new URL("engine/", src))) {
    out.engine.push(
      ...outsideGraph(await graphOf(f), engine).map((p) =>
        `${rel(f.href)} imports ${rel(p)}`
      ),
    );
    out.engine.push(
      ...engineBannedUses(rel(f.href), await Deno.readTextFile(f)),
    );
  }
  for (const f of await walk(new URL("http/", src))) {
    out.http.push(
      ...directImportsInto(await graphOf(f), http, persistence).map(rel),
    );
  }
  for (const f of await walk(src)) {
    out.importers.push(
      ...directImporters(await graphOf(f), lookup, [authorise]).map(rel),
    );
    if (f.href !== lookup) {
      out.sql.push(...credentialReads(rel(f.href), await Deno.readTextFile(f)));
    }
  }
  for (const f of await walk(new URL("tests/reference/", base))) {
    out.reference.push(
      ...insideGraph(await graphOf(f), engine).map((p) =>
        `${rel(f.href)} reaches ${rel(p)}`
      ),
    );
  }
  for (const k of Object.keys(out)) out[k] = [...new Set(out[k])].sort();
  return out;
}

// ---- the rules on strings ----

Deno.test("codeOnly drops comments and string text but keeps template ${} code and line numbers", () => {
  const t =
    `a // Deno.x\n/* ${MR}\n */ b "${MR}" 'crypto' \`fetch( \${Deno.cwd()} x\`\nc`;
  const c = codeOnly(t);
  assertEquals(c.split("\n").length, t.split("\n").length);
  assert(
    !c.includes("random") && !c.includes("crypto") && !c.includes("fetch"),
  );
  assert(c.includes("Deno.cwd()"), "code inside ${} is kept");
  assert(c.includes("a") && c.includes("b") && c.includes("c"));
});

Deno.test("engine rule flags runtime, crypto, randomness, clocks, network, console, globals, eval and dynamic import", () => {
  for (
    const bad of [
      "Deno.readTextFile('x')",
      "const rt = Deno",
      "const { env } = Deno",
      "`${Deno.cwd()}`",
      "crypto.getRandomValues(a)",
      "globalThis.crypto.subtle",
      `${MR}()`,
      "Math . random()",
      "Date.now()",
      "new Date()",
      "performance.now()",
      "fetch('x')",
      "const f = fetch",
      "new WebSocket(u)",
      "console.log(x)",
      "eval('1')",
      "Function('return 1')()",
      "await import('x')",
    ]
  ) {
    assert(
      engineBannedUses("e.ts", `const x = 1;\n${bad};\n`).length >= 1,
      bad,
    );
  }
  assertEquals(
    engineBannedUses(
      "e.ts",
      "export const feedback = (a: number) => a + 1; // Deno.x crypto\n",
    ),
    [],
  );
});

Deno.test("Math.random rule reports the line", () => {
  assertEquals(mathRandomUses("f.ts", `x\ny\nconst r = ${MR}();\n`), [
    "f.ts:3: uses Math.random (allowed only in tools/simulator/)",
  ]);
});

Deno.test("credential read rule handles line breaks, quoting and schema qualification", () => {
  for (
    const bad of [
      "`SELECT id FROM credentials WHERE token_hash = $1`",
      "`SELECT id\n  FROM\n  credentials\n WHERE x`",
      "`SELECT 1 FROM public.credentials`",
      '`SELECT 1 FROM "credentials" c`',
      '`SELECT 1 FROM "public"."credentials"`',
      "`SELECT 1 FROM games g JOIN credentials c ON c.game_id = g.id`",
      "`WITH x AS (SELECT * FROM credentials) SELECT * FROM x`",
    ]
  ) assertEquals(credentialReads("p.ts", `const q = ${bad};`).length, 1, bad);
  for (
    const ok of [
      "`UPDATE credentials SET revoked_at = now() WHERE id = $1`",
      "`INSERT INTO credentials (id) VALUES ($1)`",
      "`SELECT 1 FROM credentials_archive`",
      "const credentialsFrom = 1;",
    ]
  ) assertEquals(credentialReads("p.ts", ok), [], ok);
  assertEquals(
    credentialReads("p.ts", "x\ny\nconst q = `SELECT 1\nFROM credentials`;"),
    ["p.ts:4: reads the credentials table"],
  );
});

Deno.test("graph helpers: outside, inside, direct imports and direct importers", () => {
  const E = "file:///r/src/engine/",
    P = "file:///r/src/persistence/",
    S = "file:///r/src/services/",
    H = "file:///r/src/http/";
  const g: InfoGraph = {
    modules: [
      {
        specifier: `${H}a.ts`,
        dependencies: [{
          specifier: "../services/s.ts",
          code: { specifier: `${S}s.ts` },
        }],
      },
      {
        specifier: `${S}s.ts`,
        dependencies: [{
          specifier: "../persistence/p.ts",
          code: { specifier: `${P}p.ts` },
        }],
      },
      { specifier: `${P}p.ts` },
      { specifier: `${E}missing.ts`, error: "Module not found" },
    ],
  };
  assertEquals(
    directImportsInto(g, H, P),
    [],
    "HTTP reaching persistence through services is allowed",
  );
  assertEquals(insideGraph(g, P), [`${P}p.ts`]);
  assertEquals(outsideGraph(g, E).length, 4);
  assertEquals(directImporters(g, `${P}p.ts`, []), [`${S}s.ts`]);
  assertEquals(directImporters(g, `${P}p.ts`, [`${S}s.ts`]), []);
});

// ---- the rules on the committed fixtures: exactly the planted findings ----

Deno.test("fixtures: every rule finds exactly its planted violation", async () => {
  const f = await scan(FIXTURES);
  const has = (k: string, s: string) =>
    assert(
      f[k].some((x) => x.includes(s)),
      `${k} should report ${s}: ${f[k].join(" | ")}`,
    );
  has("engine", "src/engine/impure.ts imports src/persistence/db.ts");
  has("engine", "src/engine/impure.ts:6: uses the Deno runtime");
  has("engine", "src/engine/impure.ts:7: reads the clock");
  assert(
    !f.engine.some((x) => x.includes("pure.ts") && !x.includes("impure.ts")),
    "pure.ts is clean",
  );
  assertEquals(f.http, ["src/http/bad.ts -> src/persistence/db.ts"]);
  assertEquals(f.importers, ["src/services/game.ts"]);
  assertEquals(f.sql, [
    "src/persistence/other.ts:6: reads the credentials table",
  ]);
  assertEquals(f.reference, [
    "tests/reference/ref.ts reaches src/engine/pure.ts",
  ]);
  const rand = mathRandomUses(
    "src/services/rand.ts",
    await Deno.readTextFile(new URL("src/services/rand.ts", FIXTURES)),
  );
  assertEquals(rand.length, 1);
});

// ---- the rules on the repository: no findings ----

Deno.test("repository: engine, HTTP, credential and reference rules find nothing (R14.1, R8.11, R14)", async () => {
  assertEquals(await scan(BACKEND), {
    engine: [],
    http: [],
    importers: [],
    sql: [],
    reference: [],
  });
});

Deno.test("repository: Math.random is used nowhere outside tools/simulator/ (T25)", async () => {
  const problems: string[] = [];
  for (const f of await walk(REPO)) {
    const rel = f.href.replace(REPO.href, "");
    if (
      rel.startsWith("tools/simulator/") || f.href.startsWith(FIXTURES.href)
    ) continue;
    problems.push(...mathRandomUses(rel, await Deno.readTextFile(f)));
  }
  assertEquals(problems, []);
});
