// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture rules applied to the repository (task 2.6, R14.1, R8.11; test-strategy.md TS-CRED and section 17).
// Run with: deno task lint:rules (needs --allow-read and --allow-run=deno).
import { assert, assertEquals } from "@std/assert";
import {
  codeOnly,
  credentialReads,
  directImporters,
  engineBannedUses,
  type InfoGraph,
  insideGraph,
  mathRandomUses,
  outsideGraph,
} from "./rules.ts";

const BACKEND = new URL("../../", import.meta.url);
const SRC = new URL("src/", BACKEND);
const REPO = new URL("../", BACKEND);
const ENGINE = new URL("engine/", SRC).href;
const PERSISTENCE = new URL("persistence/", SRC).href;
const LOOKUP = new URL("persistence/credential_lookup.ts", SRC).href;
const AUTHORISE = new URL("services/authorise.ts", SRC).href;
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
  for await (const e of Deno.readDir(dir)) {
    if (e.isDirectory && !SKIP_DIRS.has(e.name)) {
      await walk(new URL(`${e.name}/`, dir), out);
    } else if (e.isFile && SOURCE_EXT.test(e.name)) {
      out.push(new URL(e.name, dir));
    }
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

const rel = (u: URL | string) =>
  (typeof u === "string" ? u : u.href).replace(REPO.href, "");

// ---- the rules on fixtures ----

Deno.test("codeOnly ignores comments and string contents but keeps line numbers", () => {
  const t = `a // Deno.x\n/* ${MR}\n */ b "${MR}" 'crypto' \`fetch(\`\nc`;
  const c = codeOnly(t);
  assertEquals(c.split("\n").length, t.split("\n").length);
  assert(
    !c.includes("Deno") && !c.includes("random") && !c.includes("crypto") &&
      !c.includes("fetch"),
  );
  assert(c.includes("a") && c.includes("b") && c.includes("c"));
});

Deno.test("engine rule flags runtime, crypto, randomness, network, console and dynamic imports", () => {
  for (
    const bad of [
      "Deno.readTextFile('x')",
      "crypto.getRandomValues(a)",
      "globalThis.crypto.subtle",
      "crypto.randomUUID()",
      `${MR}()`,
      "Math . random()",
      "fetch('x')",
      "new WebSocket(u)",
      "console.log(x)",
      "await import('x')",
    ]
  ) {
    assertEquals(
      engineBannedUses("e.ts", `const x = 1;\n${bad};\n`).length,
      1,
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
    `f.ts:3: uses Math.random (allowed only in tools/simulator/)`,
  ]);
});

Deno.test("credential read rule flags SQL that reads the credentials table, inside strings too", () => {
  assertEquals(
    credentialReads(
      "p.ts",
      "x\nconst q = sql`SELECT id FROM credentials WHERE token_hash = $1`;",
    ),
    [
      "p.ts:2: reads the credentials table",
    ],
  );
  assertEquals(
    credentialReads(
      "p.ts",
      "const q = `SELECT 1 FROM games g JOIN  credentials c ON c.game_id = g.id`;",
    ).length,
    1,
  );
  assertEquals(
    credentialReads(
      "p.ts",
      "const q = `UPDATE credentials SET revoked_at = now() WHERE id = $1`;",
    ),
    [],
  );
  assertEquals(
    credentialReads(
      "p.ts",
      "const q = `INSERT INTO credentials (id) VALUES ($1)`;",
    ),
    [],
  );
  assertEquals(credentialReads("p.ts", "const credentialsFrom = 1;"), []);
});

Deno.test("graph helpers find modules outside a prefix, inside a prefix, and direct importers", () => {
  const g: InfoGraph = {
    modules: [
      {
        specifier: `${ENGINE}a.ts`,
        dependencies: [{
          specifier: "./b.ts",
          code: { specifier: `${ENGINE}b.ts` },
        }],
      },
      { specifier: `${ENGINE}b.ts` },
      { specifier: "https://jsr.io/@oak/oak/17.2.2/mod.ts" },
      { specifier: `${ENGINE}missing.ts`, error: "Module not found" },
      {
        specifier: AUTHORISE,
        dependencies: [{
          specifier: "../persistence/credential_lookup.ts",
          code: { specifier: LOOKUP },
        }],
      },
      {
        specifier: `${SRC.href}services/game.ts`,
        dependencies: [{ specifier: "x", code: { specifier: LOOKUP } }],
      },
    ],
  };
  assertEquals(outsideGraph(g, ENGINE).length, 3 + 1);
  assertEquals(insideGraph(g, ENGINE).length, 3);
  assertEquals(directImporters(g, LOOKUP, [AUTHORISE]), [
    `${SRC.href}services/game.ts`,
  ]);
});

// ---- the rules on the repository ----

Deno.test("engine: imports resolve only to engine files, and engine code is pure (R14.1)", async () => {
  const problems: string[] = [];
  for (const f of await walk(new URL("engine/", SRC))) {
    problems.push(
      ...outsideGraph(await graphOf(f), ENGINE).map((p) =>
        `${rel(f)} imports ${rel(p)}`
      ),
    );
    problems.push(...engineBannedUses(rel(f), await Deno.readTextFile(f)));
  }
  assertEquals(problems, []);
});

Deno.test("http: no module under src/http reaches src/persistence (no credential lookup in HTTP, R8.11)", async () => {
  const problems: string[] = [];
  for (const f of await walk(new URL("http/", SRC))) {
    problems.push(
      ...insideGraph(await graphOf(f), PERSISTENCE).map((p) =>
        `${rel(f)} reaches ${rel(p)}`
      ),
    );
  }
  assertEquals(problems, []);
});

Deno.test("credentials: only services/authorise.ts imports persistence/credential_lookup.ts (R8.11, design.md 5.1)", async () => {
  const problems: string[] = [];
  for (const f of await walk(SRC)) {
    problems.push(
      ...directImporters(await graphOf(f), LOOKUP, [AUTHORISE]).map(rel),
    );
  }
  assertEquals([...new Set(problems)], []);
});

Deno.test("credentials: SQL reading the credentials table lives only in persistence/credential_lookup.ts", async () => {
  const problems: string[] = [];
  for (const f of await walk(SRC)) {
    if (f.href !== LOOKUP) {
      problems.push(...credentialReads(rel(f), await Deno.readTextFile(f)));
    }
  }
  assertEquals(problems, []);
});

Deno.test("Math.random is used nowhere outside tools/simulator/ (T25)", async () => {
  const problems: string[] = [];
  for (const f of await walk(REPO)) {
    if (rel(f).startsWith("tools/simulator/")) continue;
    problems.push(...mathRandomUses(rel(f), await Deno.readTextFile(f)));
  }
  assertEquals(problems, []);
});
