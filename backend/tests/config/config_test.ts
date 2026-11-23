// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Tests for the configuration module (task 2.4; test-strategy.md TS-RET, TS-RATE, TS-OPS, TS-ENC start-up cases).
import { assert, assertEquals, assertRejects, assertThrows } from "@std/assert";
import {
  CONFIG_KEYS,
  ConfigError,
  DEFAULTS,
  type EnvSource,
  loadConfig,
  parseConfig,
  RATE_LIMIT_DEFAULTS,
} from "../../src/config/config.ts";

const DB = "postgres://duocode:s3cret-pw@db:5432/duocode";
const HASH = "a".repeat(64);
const PROD: EnvSource = {
  DATABASE_URL: DB,
  TRUSTED_PROXY_CIDRS: "10.0.0.0/8,fd00::/8",
  ADMIN_TOKEN_SHA256: HASH,
  ADMIN_LISTEN_ADDR: "10.0.1.5:8081",
};
const DEV: EnvSource = { DUOCODE_ENV: "development", DATABASE_URL: DB };

function problems(env: EnvSource): readonly string[] {
  const e = assertThrows(() => parseConfig(env), ConfigError);
  return e.problems;
}
function hasProblem(env: EnvSource, key: string): void {
  const p = problems(env);
  assert(
    p.some((x) => x.startsWith(key)),
    `expected a ${key} problem, got: ${p.join(" | ")}`,
  );
}

Deno.test("defaults match design.md section 13 when only required keys are set", () => {
  const c = parseConfig(PROD);
  assertEquals(c.mode, "production");
  assertEquals(c.ttlUnjoinedDays, 7);
  assertEquals(c.ttlInProgressDays, 30);
  assertEquals(c.ttlCompletedDays, 180);
  assertEquals(c.rotationReplaySeconds, 600);
  assertEquals(c.cleanupBatchSize, 200);
  assertEquals(c.cleanupIntervalMinutes, 60);
  assertEquals(c.backupRetentionDays, 35);
  assertEquals(c.keyUsageWarn, 2 ** 27);
  assertEquals(c.keyUsageRotateBy, 2 ** 28);
  assertEquals(c.keyUsageHardStop, 2 ** 30);
  assertEquals(c.keyUsageBlock, 1024);
  assertEquals(c.keymgmtLockWaitSeconds, 300);
  assertEquals(c.keyverifyMaxSeconds, 1800);
  assertEquals(c.keyUsageRefreshSeconds, 30);
  assertEquals(c.dbLockTimeoutMs, 5000);
  assertEquals(c.dbStatementTimeoutMs, 10000);
  assertEquals(c.logLevel, "info");
  assertEquals(c.httpMaxBodyBytes, 1024);
  assertEquals(c.codeKeyringFile, "/run/secrets/duocode_code_keyring");
  assertEquals(c.rateLimitHmacKeyFile, "/run/secrets/duocode_ratelimit_key");
  assertEquals(c.rateLimits, RATE_LIMIT_DEFAULTS);
  assertEquals(c.trustedProxyCidrs, ["10.0.0.0/8", "fd00::/8"]);
  assertEquals(c.adminListen, { host: "10.0.1.5", port: 8081 });
});

Deno.test("every key has a default or is required, and no default exists for an unknown key", () => {
  for (const k of Object.keys(DEFAULTS)) {
    assert((CONFIG_KEYS as readonly string[]).includes(k), k);
  }
});

Deno.test("mode defaults to production, so the production-only keys are required", () => {
  hasProblem({ DATABASE_URL: DB }, "TRUSTED_PROXY_CIDRS");
  hasProblem({ DATABASE_URL: DB }, "ADMIN_TOKEN_SHA256");
  hasProblem({ DATABASE_URL: DB }, "ADMIN_LISTEN_ADDR");
});

Deno.test("development mode allows the production-only keys to be absent", () => {
  const c = parseConfig(DEV);
  assertEquals(c.mode, "development");
  assertEquals(c.trustedProxyCidrs, undefined);
  assertEquals(c.adminTokenSha256, undefined);
  assertEquals(c.adminListen, undefined);
});

Deno.test("an unknown mode is rejected", () => {
  hasProblem({ ...PROD, DUOCODE_ENV: "staging" }, "DUOCODE_ENV");
});

Deno.test("DATABASE_URL is required and must be a PostgreSQL URL", () => {
  hasProblem({ ...PROD, DATABASE_URL: undefined }, "DATABASE_URL");
  hasProblem({ ...PROD, DATABASE_URL: "mysql://u:p@h/db" }, "DATABASE_URL");
  hasProblem({ ...PROD, DATABASE_URL: "not a url" }, "DATABASE_URL");
  assertEquals(
    parseConfig({ ...PROD, DATABASE_URL: "postgresql://h/db" }).databaseUrl
      .reveal(),
    "postgresql://h/db",
  );
});

Deno.test("TTLs, replay window, batch size and other numbers must be positive integers", () => {
  for (
    const key of [
      "TTL_UNJOINED_DAYS",
      "TTL_IN_PROGRESS_DAYS",
      "TTL_COMPLETED_DAYS",
      "ROTATION_REPLAY_SECONDS",
      "CLEANUP_BATCH_SIZE",
      "CLEANUP_INTERVAL_MINUTES",
      "BACKUP_RETENTION_DAYS",
      "KEYMGMT_LOCK_WAIT_SECONDS",
      "KEYVERIFY_MAX_SECONDS",
      "KEY_USAGE_REFRESH_SECONDS",
      "DB_LOCK_TIMEOUT_MS",
      "DB_STATEMENT_TIMEOUT_MS",
      "HTTP_MAX_BODY_BYTES",
    ]
  ) {
    for (
      const bad of ["0", "-1", "1.5", "abc", "1e3", "007", "9007199254740993"]
    ) {
      hasProblem({ ...PROD, [key]: bad }, key);
    }
  }
  assertEquals(
    parseConfig({ ...PROD, TTL_COMPLETED_DAYS: " 90 " }).ttlCompletedDays,
    90,
  );
});

Deno.test("an empty value falls back to the default", () => {
  assertEquals(
    parseConfig({ ...PROD, TTL_UNJOINED_DAYS: "" }).ttlUnjoinedDays,
    7,
  );
});

Deno.test("key usage: WARN <= ROTATE_BY <= HARD_STOP <= 2^30, block divides hard stop, block <= 2^20", () => {
  hasProblem({ ...PROD, KEY_USAGE_WARN: String(2 ** 29) }, "KEY_USAGE_WARN");
  hasProblem(
    { ...PROD, KEY_USAGE_ROTATE_BY: String(2 ** 30 + 1024) },
    "KEY_USAGE_WARN",
  );
  hasProblem(
    { ...PROD, KEY_USAGE_HARD_STOP: String(2 ** 30 + 1024) },
    "KEY_USAGE_HARD_STOP",
  );
  hasProblem({ ...PROD, KEY_USAGE_BLOCK: "1000" }, "KEY_USAGE_HARD_STOP");
  hasProblem({ ...PROD, KEY_USAGE_BLOCK: String(2 ** 21) }, "KEY_USAGE_BLOCK");
  hasProblem({ ...PROD, KEY_USAGE_BLOCK: "0" }, "KEY_USAGE_BLOCK");
  // A stricter (lower) hard stop is allowed.
  const c = parseConfig({
    ...PROD,
    KEY_USAGE_WARN: "1024",
    KEY_USAGE_ROTATE_BY: "2048",
    KEY_USAGE_HARD_STOP: "4096",
    KEY_USAGE_BLOCK: "1024",
  });
  assertEquals(c.keyUsageHardStop, 4096);
});

Deno.test("RATE_LIMITS overrides only the scopes it names", () => {
  const c = parseConfig({
    ...PROD,
    RATE_LIMITS: '{"pl:guess":{"capacity":5,"refillPerMinute":12}}',
  });
  assertEquals(c.rateLimits["pl:guess"], { capacity: 5, refillPerMinute: 12 });
  assertEquals(c.rateLimits["pl:rotate"], RATE_LIMIT_DEFAULTS["pl:rotate"]);
  const f = parseConfig({
    ...PROD,
    RATE_LIMITS: '{"pl:rotate":{"capacity":3,"refillPerMinute":0.05}}',
  });
  assertEquals(f.rateLimits["pl:rotate"].refillPerMinute, 0.05);
});

Deno.test("RATE_LIMITS rejects bad JSON, unknown scopes and non-positive values", () => {
  for (
    const bad of [
      "not json",
      "[]",
      '{"pl:nope":{"capacity":1,"refillPerMinute":1}}',
      '{"pl:guess":{"capacity":0,"refillPerMinute":1}}',
      '{"pl:guess":{"capacity":1.5,"refillPerMinute":1}}',
      '{"pl:guess":{"capacity":1,"refillPerMinute":0}}',
      '{"pl:guess":{"capacity":1,"refillPerMinute":-2}}',
      '{"pl:guess":{"capacity":"10","refillPerMinute":1}}',
      '{"pl:guess":{"capacity":1,"refillPerMinute":1,"burst":2}}',
      '{"pl:guess":5}',
    ]
  ) hasProblem({ ...PROD, RATE_LIMITS: bad }, "RATE_LIMITS");
});

Deno.test("TRUSTED_PROXY_CIDRS accepts IPv4 and IPv6 CIDRs only", () => {
  for (
    const bad of [
      "10.0.0.0",
      "10.0.0.0/33",
      "256.0.0.0/8",
      "fd00::/129",
      "example.com/8",
      "10.0.0.0/8,",
      "010.0.0.0/8",
    ]
  ) {
    hasProblem({ ...PROD, TRUSTED_PROXY_CIDRS: bad }, "TRUSTED_PROXY_CIDRS");
  }
  assertEquals(
    parseConfig({ ...PROD, TRUSTED_PROXY_CIDRS: " 172.16.0.0/12 , ::1/128" })
      .trustedProxyCidrs,
    [
      "172.16.0.0/12",
      "::1/128",
    ],
  );
});

Deno.test("ADMIN_TOKEN_SHA256 must be 64 hex characters and is normalised to lower case", () => {
  for (const bad of ["abc", "g".repeat(64), "a".repeat(63), "a".repeat(65)]) {
    hasProblem({ ...PROD, ADMIN_TOKEN_SHA256: bad }, "ADMIN_TOKEN_SHA256");
  }
  assertEquals(
    parseConfig({ ...PROD, ADMIN_TOKEN_SHA256: "A".repeat(64) })
      .adminTokenSha256?.reveal(),
    "a".repeat(64),
  );
});

Deno.test("ADMIN_LISTEN_ADDR: internal address on port 8081, never loopback or all interfaces (RD-17)", () => {
  for (
    const bad of [
      "10.0.1.5",
      "10.0.1.5:8080",
      "127.0.0.1:8081",
      "127.1.2.3:8081",
      "localhost:8081",
      "[::1]:8081",
      "[0:0:0:0:0:0:0:1]:8081",
      "0.0.0.0:8081",
      "[::]:8081",
      "[0::0]:8081",
      ":8081",
      "10.0.1.5:99999",
    ]
  ) hasProblem({ ...PROD, ADMIN_LISTEN_ADDR: bad }, "ADMIN_LISTEN_ADDR");
  assertEquals(
    parseConfig({ ...PROD, ADMIN_LISTEN_ADDR: "app:8081" }).adminListen,
    { host: "app", port: 8081 },
  );
  assertEquals(
    parseConfig({ ...PROD, ADMIN_LISTEN_ADDR: "[fd00::5]:8081" }).adminListen
      ?.port,
    8081,
  );
});

Deno.test("LOG_LEVEL accepts debug, info, warn and error only", () => {
  for (const level of ["debug", "info", "warn", "error"]) {
    assertEquals(parseConfig({ ...PROD, LOG_LEVEL: level }).logLevel, level);
  }
  hasProblem({ ...PROD, LOG_LEVEL: "verbose" }, "LOG_LEVEL");
});

Deno.test("all problems are reported together", () => {
  const p = problems({
    DATABASE_URL: undefined,
    TTL_UNJOINED_DAYS: "0",
    LOG_LEVEL: "x",
  });
  for (
    const key of [
      "DATABASE_URL",
      "TTL_UNJOINED_DAYS",
      "LOG_LEVEL",
      "TRUSTED_PROXY_CIDRS",
    ]
  ) {
    assert(p.some((x) => x.startsWith(key)), key);
  }
});

Deno.test("secrets are never printed: values redacted in output, errors name keys only", () => {
  const c = parseConfig(PROD);
  for (
    const out of [
      String(c.databaseUrl),
      JSON.stringify(c),
      Deno.inspect(c, { depth: 10 }),
    ]
  ) {
    assert(!out.includes("s3cret-pw"), "database password leaked");
    assert(!out.includes(HASH), "admin hash leaked");
  }
  assert(JSON.stringify(c).includes("[REDACTED]"));
  const canary = "CANARY-9f3b";
  const e = assertThrows(
    () =>
      parseConfig({
        ...PROD,
        DATABASE_URL: `mysql://u:${canary}@h/db`,
        ADMIN_TOKEN_SHA256: canary,
        TTL_UNJOINED_DAYS: canary,
        RATE_LIMITS: `{"${canary}":1}`,
        ADMIN_LISTEN_ADDR: canary,
      }),
    ConfigError,
  );
  assert(
    !e.message.includes(canary),
    "a configuration value was echoed in the error",
  );
});

Deno.test("the loaded configuration is immutable", () => {
  const c = parseConfig(PROD);
  assert(Object.isFrozen(c));
  assert(Object.isFrozen(c.rateLimits));
  assert(Object.isFrozen(c.rateLimits["pl:guess"]));
});

Deno.test("loadConfig reads only the configuration keys and requires both secret files", async () => {
  const seen: string[] = [];
  const env = (k: string) => {
    seen.push(k);
    return {
      ...PROD,
      CODE_KEYRING_FILE: "/k",
      RATE_LIMIT_HMAC_KEY_FILE: "/r",
    }[k];
  };
  const ok = await loadConfig({ env, fileCheck: () => Promise.resolve(true) });
  assertEquals(ok.codeKeyringFile, "/k");
  assertEquals([...seen].sort(), [...CONFIG_KEYS].sort());
  const e = await assertRejects(
    () => loadConfig({ env, fileCheck: (p) => Promise.resolve(p === "/k") }),
    ConfigError,
  );
  assert(e.problems.some((x) => x.startsWith("RATE_LIMIT_HMAC_KEY_FILE")));
});

Deno.test("the default file check accepts a readable file and refuses a missing one", async () => {
  const self = new URL(import.meta.url).pathname;
  const env = (
    k: string,
  ) => ({
    ...PROD,
    CODE_KEYRING_FILE: self,
    RATE_LIMIT_HMAC_KEY_FILE: self,
  }[k]);
  assertEquals((await loadConfig({ env })).codeKeyringFile, self);
  const missing = (
    k: string,
  ) => ({ ...PROD, CODE_KEYRING_FILE: "/nonexistent/duocode/keyring" }[k]);
  const e = await assertRejects(
    () => loadConfig({ env: missing }),
    ConfigError,
  );
  assert(e.problems.some((x) => x.startsWith("CODE_KEYRING_FILE")));
});
