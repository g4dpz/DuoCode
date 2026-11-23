// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
/**
 * Typed configuration with start-up validation (task 2.4, R11.1, R18.4).
 *
 * Every key and default comes from `design.md` section 13; the rate-limit
 * defaults come from `deployment.md` section 4.2 (check C46 keeps them in step).
 * Any problem stops start-up. Error messages name the key but never echo its
 * value, and secret values print as `[REDACTED]`.
 */

/** Deployment mode (RD-25). Production applies the "required in production" rules. */
export type Mode = "production" | "development";

/** Log levels accepted by `LOG_LEVEL` (RD-25). */
export const LOG_LEVELS = ["debug", "info", "warn", "error"] as const;
export type LogLevel = typeof LOG_LEVELS[number];

/** One application rate-limit bucket: burst capacity and refill rate. */
export interface RateLimit {
  readonly capacity: number;
  readonly refillPerMinute: number;
}

/** A value that must never be printed. */
export class Secret {
  readonly #value: string;
  constructor(value: string) {
    this.#value = value;
  }
  /** The real value. Use only where the value is needed, never for output. */
  reveal(): string {
    return this.#value;
  }
  toString(): string {
    return "[REDACTED]";
  }
  toJSON(): string {
    return "[REDACTED]";
  }
  [Symbol.for("Deno.customInspect")](): string {
    return "[REDACTED]";
  }
}

export interface Config {
  readonly mode: Mode;
  readonly databaseUrl: Secret;
  readonly codeKeyringFile: string;
  readonly rateLimitHmacKeyFile: string;
  /**
   * Required in production. `undefined` only in development, where it means
   * "trust no forwarded header". Never contains a default route (`/0`).
   */
  readonly trustedProxyCidrs: readonly string[] | undefined;
  /** Required in production; `undefined` only in development. */
  readonly adminTokenSha256: Secret | undefined;
  /** Required in production; `undefined` only in development. */
  readonly adminListen:
    | { readonly host: string; readonly port: number }
    | undefined;
  readonly ttlUnjoinedDays: number;
  readonly ttlInProgressDays: number;
  readonly ttlCompletedDays: number;
  readonly rotationReplaySeconds: number;
  readonly cleanupBatchSize: number;
  readonly cleanupIntervalMinutes: number;
  readonly backupRetentionDays: number;
  readonly keyUsageWarn: number;
  readonly keyUsageRotateBy: number;
  readonly keyUsageHardStop: number;
  readonly keyUsageBlock: number;
  readonly keymgmtLockWaitSeconds: number;
  readonly keyverifyMaxSeconds: number;
  readonly keyUsageRefreshSeconds: number;
  readonly rateLimits: Readonly<Record<string, RateLimit>>;
  readonly dbLockTimeoutMs: number;
  readonly dbStatementTimeoutMs: number;
  readonly logLevel: LogLevel;
  readonly httpMaxBodyBytes: number;
}

/** Every configuration key the application reads (design.md section 13). */
export const CONFIG_KEYS = [
  "DUOCODE_ENV",
  "DATABASE_URL",
  "CODE_KEYRING_FILE",
  "RATE_LIMIT_HMAC_KEY_FILE",
  "TRUSTED_PROXY_CIDRS",
  "ADMIN_TOKEN_SHA256",
  "ADMIN_LISTEN_ADDR",
  "TTL_UNJOINED_DAYS",
  "TTL_IN_PROGRESS_DAYS",
  "TTL_COMPLETED_DAYS",
  "ROTATION_REPLAY_SECONDS",
  "CLEANUP_BATCH_SIZE",
  "CLEANUP_INTERVAL_MINUTES",
  "BACKUP_RETENTION_DAYS",
  "KEY_USAGE_WARN",
  "KEY_USAGE_ROTATE_BY",
  "KEY_USAGE_HARD_STOP",
  "KEY_USAGE_BLOCK",
  "KEYMGMT_LOCK_WAIT_SECONDS",
  "KEYVERIFY_MAX_SECONDS",
  "KEY_USAGE_REFRESH_SECONDS",
  "RATE_LIMITS",
  "DB_LOCK_TIMEOUT_MS",
  "DB_STATEMENT_TIMEOUT_MS",
  "LOG_LEVEL",
  "HTTP_MAX_BODY_BYTES",
] as const;
export type ConfigKey = typeof CONFIG_KEYS[number];

/** Defaults from design.md section 13. Keys without a default are absent. */
export const DEFAULTS: Readonly<Partial<Record<ConfigKey, string>>> = {
  DUOCODE_ENV: "production",
  CODE_KEYRING_FILE: "/run/secrets/duocode_code_keyring",
  RATE_LIMIT_HMAC_KEY_FILE: "/run/secrets/duocode_ratelimit_key",
  TTL_UNJOINED_DAYS: "7",
  TTL_IN_PROGRESS_DAYS: "30",
  TTL_COMPLETED_DAYS: "180",
  ROTATION_REPLAY_SECONDS: "600",
  CLEANUP_BATCH_SIZE: "200",
  CLEANUP_INTERVAL_MINUTES: "60",
  BACKUP_RETENTION_DAYS: "35",
  KEY_USAGE_WARN: "134217728",
  KEY_USAGE_ROTATE_BY: "268435456",
  KEY_USAGE_HARD_STOP: "1073741824",
  KEY_USAGE_BLOCK: "1024",
  KEYMGMT_LOCK_WAIT_SECONDS: "300",
  KEYVERIFY_MAX_SECONDS: "1800",
  KEY_USAGE_REFRESH_SECONDS: "30",
  DB_LOCK_TIMEOUT_MS: "5000",
  DB_STATEMENT_TIMEOUT_MS: "10000",
  LOG_LEVEL: "info",
  HTTP_MAX_BODY_BYTES: "1024",
};

/** Application rate-limit defaults from deployment.md section 4.2 (Layer 2). */
export const RATE_LIMIT_DEFAULTS: Readonly<Record<string, RateLimit>> = {
  "ip:create": { capacity: 10, refillPerMinute: 1 },
  "ip:join": { capacity: 10, refillPerMinute: 2 },
  "ip:rematch": { capacity: 5, refillPerMinute: 1 },
  "ip:authfail": { capacity: 20, refillPerMinute: 10 },
  "ip:admin": { capacity: 10, refillPerMinute: 30 },
  "pl:guess": { capacity: 10, refillPerMinute: 30 },
  "pl:rotate": { capacity: 3, refillPerMinute: 0.1 },
  "pl:mint": { capacity: 3, refillPerMinute: 0.1 },
  "pl:read": { capacity: 30, refillPerMinute: 60 },
  "pl:write": { capacity: 20, refillPerMinute: 30 },
};

const TWO_POW_30 = 2 ** 30;
const TWO_POW_20 = 2 ** 20;
const ADMIN_PORT = 8081;

/** Start-up validation failed. `problems` name keys only, never values. */
export class ConfigError extends Error {
  readonly problems: readonly string[];
  constructor(problems: readonly string[]) {
    super(`Invalid configuration:\n- ${problems.join("\n- ")}`);
    this.name = "ConfigError";
    this.problems = problems;
  }
}

/** Environment values, keyed by configuration key. Missing keys are `undefined`. */
export type EnvSource = Readonly<Partial<Record<string, string | undefined>>>;

/**
 * Parses and validates configuration from `env` without touching the
 * process environment or the file system. Throws `ConfigError` listing every
 * problem found.
 */
export function parseConfig(env: EnvSource): Config {
  const { config, problems } = collect(env);
  if (problems.length > 0) throw new ConfigError(problems);
  return config;
}

/** Validates `env`; the configuration is meaningful only when no problem was found. */
function collect(env: EnvSource): { config: Config; problems: string[] } {
  const problems: string[] = [];
  const raw = (key: ConfigKey): string | undefined => {
    const v = env[key];
    return v === undefined || v.trim() === "" ? DEFAULTS[key] : v.trim();
  };
  const positiveInt = (key: ConfigKey): number => {
    const v = raw(key);
    if (
      v === undefined || !/^[1-9][0-9]*$/.test(v) ||
      !Number.isSafeInteger(Number(v))
    ) {
      problems.push(`${key}: must be a positive integer`);
      return NaN;
    }
    return Number(v);
  };

  const modeRaw = raw("DUOCODE_ENV");
  let mode: Mode = "production";
  if (modeRaw === "production" || modeRaw === "development") mode = modeRaw;
  else problems.push("DUOCODE_ENV: must be production or development");
  const production = mode === "production";

  const dbRaw = raw("DATABASE_URL");
  let databaseUrl = new Secret("");
  if (dbRaw === undefined) problems.push("DATABASE_URL: required");
  else if (!isPostgresUrl(dbRaw)) {
    problems.push("DATABASE_URL: must be a postgres:// or postgresql:// URL");
  } else databaseUrl = new Secret(dbRaw);

  const codeKeyringFile = raw("CODE_KEYRING_FILE") ?? "";
  const rateLimitHmacKeyFile = raw("RATE_LIMIT_HMAC_KEY_FILE") ?? "";

  let trustedProxyCidrs: string[] | undefined;
  const cidrsRaw = raw("TRUSTED_PROXY_CIDRS");
  if (cidrsRaw === undefined) {
    if (production) {
      problems.push("TRUSTED_PROXY_CIDRS: required in production");
    }
  } else {
    const list = cidrsRaw.split(",").map((s) => s.trim());
    if (list.some((c) => !isCidr(c))) {
      problems.push(
        "TRUSTED_PROXY_CIDRS: must be a comma-separated list of IPv4 or IPv6 CIDRs, none of them /0",
      );
    } else trustedProxyCidrs = list;
  }

  let adminTokenSha256: Secret | undefined;
  const hashRaw = raw("ADMIN_TOKEN_SHA256");
  if (hashRaw === undefined) {
    if (production) problems.push("ADMIN_TOKEN_SHA256: required in production");
  } else if (!/^[0-9a-fA-F]{64}$/.test(hashRaw)) {
    problems.push(
      "ADMIN_TOKEN_SHA256: must be 64 hexadecimal characters (a SHA-256)",
    );
  } else adminTokenSha256 = new Secret(hashRaw.toLowerCase());

  let adminListen: { host: string; port: number } | undefined;
  const adminRaw = raw("ADMIN_LISTEN_ADDR");
  if (adminRaw === undefined) {
    if (production) problems.push("ADMIN_LISTEN_ADDR: required in production");
  } else {
    // Development checks the host:port form only; the network rules
    // describe the production topology (RD-17, RD-27).
    const parsed = parseHostPort(adminRaw);
    if (parsed === undefined) {
      problems.push("ADMIN_LISTEN_ADDR: must be host:port");
    } else if (production && parsed.port !== ADMIN_PORT) {
      problems.push(`ADMIN_LISTEN_ADDR: port must be ${ADMIN_PORT}`);
    } else if (
      production && (isLoopback(parsed.host) || isUnspecified(parsed.host))
    ) {
      problems.push(
        "ADMIN_LISTEN_ADDR: must be the internal network address, never loopback or all interfaces (RD-17)",
      );
    } else adminListen = parsed;
  }

  const ttlUnjoinedDays = positiveInt("TTL_UNJOINED_DAYS");
  const ttlInProgressDays = positiveInt("TTL_IN_PROGRESS_DAYS");
  const ttlCompletedDays = positiveInt("TTL_COMPLETED_DAYS");
  const rotationReplaySeconds = positiveInt("ROTATION_REPLAY_SECONDS");
  const cleanupBatchSize = positiveInt("CLEANUP_BATCH_SIZE");
  const cleanupIntervalMinutes = positiveInt("CLEANUP_INTERVAL_MINUTES");
  const backupRetentionDays = positiveInt("BACKUP_RETENTION_DAYS");
  const keyUsageWarn = positiveInt("KEY_USAGE_WARN");
  const keyUsageRotateBy = positiveInt("KEY_USAGE_ROTATE_BY");
  const keyUsageHardStop = positiveInt("KEY_USAGE_HARD_STOP");
  const keyUsageBlock = positiveInt("KEY_USAGE_BLOCK");
  const keymgmtLockWaitSeconds = positiveInt("KEYMGMT_LOCK_WAIT_SECONDS");
  const keyverifyMaxSeconds = positiveInt("KEYVERIFY_MAX_SECONDS");
  const keyUsageRefreshSeconds = positiveInt("KEY_USAGE_REFRESH_SECONDS");
  const dbLockTimeoutMs = positiveInt("DB_LOCK_TIMEOUT_MS");
  const dbStatementTimeoutMs = positiveInt("DB_STATEMENT_TIMEOUT_MS");
  const httpMaxBodyBytes = positiveInt("HTTP_MAX_BODY_BYTES");

  // Key usage thresholds (design.md section 13, RD-10, RD-13).
  if (
    ![keyUsageWarn, keyUsageRotateBy, keyUsageHardStop, keyUsageBlock].some(
      Number.isNaN,
    )
  ) {
    if (
      !(keyUsageWarn <= keyUsageRotateBy &&
        keyUsageRotateBy <= keyUsageHardStop)
    ) {
      problems.push(
        "KEY_USAGE_WARN, KEY_USAGE_ROTATE_BY, KEY_USAGE_HARD_STOP: must satisfy WARN <= ROTATE_BY <= HARD_STOP",
      );
    }
    if (keyUsageHardStop > TWO_POW_30) {
      problems.push("KEY_USAGE_HARD_STOP: must be at most 2^30");
    }
    if (keyUsageBlock > TWO_POW_20) {
      problems.push("KEY_USAGE_BLOCK: must be at most 2^20");
    }
    if (keyUsageHardStop % keyUsageBlock !== 0) {
      problems.push(
        "KEY_USAGE_HARD_STOP: must be a multiple of KEY_USAGE_BLOCK",
      );
    }
  }

  const rateLimits = parseRateLimits(raw("RATE_LIMITS"), problems);

  const levelRaw = raw("LOG_LEVEL");
  let logLevel: LogLevel = "info";
  if ((LOG_LEVELS as readonly string[]).includes(levelRaw ?? "")) {
    logLevel = levelRaw as LogLevel;
  } else problems.push(`LOG_LEVEL: must be one of ${LOG_LEVELS.join(", ")}`);

  const config = deepFreeze({
    mode,
    databaseUrl,
    codeKeyringFile,
    rateLimitHmacKeyFile,
    trustedProxyCidrs,
    adminTokenSha256,
    adminListen,
    ttlUnjoinedDays,
    ttlInProgressDays,
    ttlCompletedDays,
    rotationReplaySeconds,
    cleanupBatchSize,
    cleanupIntervalMinutes,
    backupRetentionDays,
    keyUsageWarn,
    keyUsageRotateBy,
    keyUsageHardStop,
    keyUsageBlock,
    keymgmtLockWaitSeconds,
    keyverifyMaxSeconds,
    keyUsageRefreshSeconds,
    rateLimits,
    dbLockTimeoutMs,
    dbStatementTimeoutMs,
    logLevel,
    httpMaxBodyBytes,
  });
  return { config, problems };
}

/** Checks that a path names a readable regular file. */
export type FileCheck = (path: string) => Promise<boolean>;

/** Default file check: a regular file that can be opened for reading. */
export const readableFile: FileCheck = async (path) => {
  try {
    if (!(await Deno.stat(path)).isFile) return false;
    const f = await Deno.open(path, { read: true });
    f.close();
    return true;
  } catch {
    return false;
  }
};

/**
 * Reads the configuration keys from the process environment, validates them,
 * and checks that the key ring and rate-limit key files exist and are
 * readable. Their contents are checked by the key ring and rate limiter.
 */
export async function loadConfig(
  options: {
    env?: (key: string) => string | undefined;
    fileCheck?: FileCheck;
  } = {},
): Promise<Config> {
  const get = options.env ?? ((key: string) => Deno.env.get(key));
  const fileCheck = options.fileCheck ?? readableFile;
  const env: Record<string, string | undefined> = {};
  for (const key of CONFIG_KEYS) env[key] = get(key);
  // One pass: parse problems and file problems are reported together.
  const { config, problems } = collect(env);
  if (!(await fileCheck(config.codeKeyringFile))) {
    problems.push("CODE_KEYRING_FILE: file does not exist or is not readable");
  }
  if (!(await fileCheck(config.rateLimitHmacKeyFile))) {
    problems.push(
      "RATE_LIMIT_HMAC_KEY_FILE: file does not exist or is not readable",
    );
  }
  if (problems.length > 0) throw new ConfigError(problems);
  return config;
}

function parseRateLimits(
  value: string | undefined,
  problems: string[],
): Record<string, RateLimit> {
  const merged: Record<string, RateLimit> = { ...RATE_LIMIT_DEFAULTS };
  if (value === undefined) return merged;
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    problems.push("RATE_LIMITS: must be JSON");
    return merged;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    problems.push("RATE_LIMITS: must be a JSON object keyed by scope");
    return merged;
  }
  for (const [scope, limit] of Object.entries(parsed)) {
    if (!Object.hasOwn(RATE_LIMIT_DEFAULTS, scope)) {
      problems.push(
        "RATE_LIMITS: unknown scope (allowed: " +
          Object.keys(RATE_LIMIT_DEFAULTS).join(", ") + ")",
      );
      continue;
    }
    if (typeof limit !== "object" || limit === null || Array.isArray(limit)) {
      problems.push(
        `RATE_LIMITS ${scope}: must be an object with capacity and refillPerMinute`,
      );
      continue;
    }
    const keys = Object.keys(limit);
    const { capacity, refillPerMinute } = limit as Record<string, unknown>;
    if (keys.some((k) => k !== "capacity" && k !== "refillPerMinute")) {
      problems.push(
        `RATE_LIMITS ${scope}: only capacity and refillPerMinute are allowed`,
      );
    } else if (
      typeof capacity !== "number" || !Number.isSafeInteger(capacity) ||
      capacity <= 0
    ) {
      problems.push(
        `RATE_LIMITS ${scope}: capacity must be a positive integer`,
      );
    } else if (
      typeof refillPerMinute !== "number" ||
      !Number.isFinite(refillPerMinute) || refillPerMinute <= 0
    ) {
      problems.push(
        `RATE_LIMITS ${scope}: refillPerMinute must be a positive number`,
      );
    } else merged[scope] = { capacity, refillPerMinute };
  }
  return merged;
}

function isPostgresUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return (u.protocol === "postgres:" || u.protocol === "postgresql:") &&
      u.hostname !== "";
  } catch {
    return false;
  }
}

function isIPv4(value: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(value);
  return m !== null &&
    m.slice(1).every((o) =>
      Number(o) <= 255 && (o === "0" || !o.startsWith("0"))
    );
}

function isIPv6(value: string): boolean {
  if (!value.includes(":") || !/^[0-9a-fA-F:.]+$/.test(value)) return false;
  try {
    return new URL(`http://[${value}]/`).hostname !== "";
  } catch {
    return false;
  }
}

function isCidr(value: string): boolean {
  const m = /^([^/]+)\/(\d{1,3})$/.exec(value);
  if (m === null) return false;
  const bits = Number(m[2]);
  if (bits === 0) return false; // a default route would trust every address
  if (isIPv4(m[1])) return bits <= 32;
  if (isIPv6(m[1])) return bits <= 128;
  return false;
}

function parseHostPort(
  value: string,
): { host: string; port: number } | undefined {
  const m = /^(?:\[([^\]]+)\]|([^:\[\]]+)):(\d{1,5})$/.exec(value);
  if (m === null) return undefined;
  const host = m[1] ?? m[2];
  const port = Number(m[3]);
  if (port < 1 || port > 65535) return undefined;
  if (m[1] !== undefined && !isIPv6(host)) return undefined;
  if (
    m[2] !== undefined && !isIPv4(host) &&
    !/^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$/
      .test(host)
  ) {
    return undefined;
  }
  return { host: host.toLowerCase(), port };
}

function isLoopback(host: string): boolean {
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (isIPv4(host)) return host.startsWith("127.");
  if (isIPv6(host)) return new URL(`http://[${host}]/`).hostname === "[::1]";
  return false;
}

function isUnspecified(host: string): boolean {
  if (host === "0.0.0.0") return true;
  if (isIPv6(host)) return new URL(`http://[${host}]/`).hostname === "[::]";
  return false;
}

function deepFreeze<T>(value: T): T {
  if (
    typeof value === "object" && value !== null && !(value instanceof Secret) &&
    !Object.isFrozen(value)
  ) {
    for (const v of Object.values(value)) deepFreeze(v);
    Object.freeze(value);
  }
  return value;
}
