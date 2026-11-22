# DuoCode Deployment Design (revision 3.1, final for gate review, strict hard-stop correction)

Owns: Compose stack, secrets and key ring handling, rate-limit values, backups, restore and key recovery, scheduling of cleanup. Related: `requirements.md` (R10, R11, R13, R18, R20, R21), `design.md` (configuration keys, lock ordering, rate-limiting design), `security-assessment.md` (key management, logging), `database-schema.md` (migrations, cleanup, rate-limit SQL).

Target: one Linux VPS running Docker Compose. Application instances are stateless, so more can be added later without redesign. Kubernetes, multi-region and mandatory Redis are out of scope.

## 1. Services

```
Internet -> proxy (Caddy, public 80/443) -> app (1..n, public listener :8080) -> db (PostgreSQL)
                                              |  \
                                              |   admin listener :8081 (internal network only, not routed by proxy)
                                         key ring (Docker secret, read-only mount)

one-shot:   migrate   (before app)
scheduled:  cleanup   (hourly, dedicated service)
            backup    (daily)
```

| Service | Image and role | Notes |
|---|---|---|
| `proxy` | Caddy, from the pinned, reproducible custom build with the rate-limit module (RD-1, section 4.3). TLS with automatic certificates, HTTP to HTTPS redirect, body size limit, coarse per-IP limits | Only service with published ports (80, 443). Routes `/api/v1/*` and `/healthz` to `app:8080`. Returns `404` for `/admin/*`. Sets `X-Forwarded-For` |
| `app` | Deno image, non-root user, read-only root filesystem, `deno run` with minimal permissions | Public listener `:8080` and admin listener `:8081`. Depends on `migrate` completing and `db` healthy. Scale with `--scale app=n` |
| `db` | `postgres`, named volume, healthcheck, no published port | Private network only |
| `migrate` | Same image as `app`, runs `deno task migrate` once | Takes the advisory lock. Exits |
| `cleanup` | Same image as `app`, loop running `deno task cleanup` every `CLEANUP_INTERVAL_MINUTES` | The only scheduler of cleanup (R21.2). Mounts the key ring (cleanup does not decrypt, but shares the start-up check). Admin endpoint is for manual runs |
| `backup` | `pg_dump` of the database, compressed and encrypted | Section 5. Never mounts the key ring |

Networks: `edge` (proxy and app public listener) and `internal` (app, db, migrate, cleanup, backup, admin listener). The database is never on `edge`. The `app` service is attached to both networks, so network membership alone does not isolate the admin listener. The admin listener therefore binds only to the `app` address on the `internal` network (`ADMIN_LISTEN_ADDR`, required, never loopback and never all interfaces), so it does not accept connections on the `edge` interface (RD-17). Operators reach the admin listener through an SSH tunnel or `docker compose exec`.

## 2. Application permissions and hardening

- Deno flags: `--allow-net` limited to the two listen addresses and the database host, `--allow-read` limited to the key ring file, the rate-limit key file and the application directory, `--allow-env` limited to the configuration keys. No `--allow-run`, `--allow-write`, `--allow-ffi`.
- Container: non-root, read-only filesystem with a temporary directory for runtime only, dropped Linux capabilities, resource limits, restart policy `unless-stopped`.
- Crash and core dumps disabled. No debug endpoints.
- Dependencies pinned with `deno.lock`. The image build uses the lockfile.
- PostgreSQL role for the application has the minimum rights it needs on the application schema. The `backup` role is read-only.

### 2.1 Key management job (`keymgmt`, CR-15)

Ring changes need write access to the ring and to the key backup store. The application must not have either. A separate one-shot job does this work:

| Item | `keymgmt` job | `app`, `cleanup`, `reencrypt` |
|---|---|---|
| Ring source file (host path, owned by a dedicated key-management user, mode 0600, directory 0700) | Read and write | No access to the source. They receive it read-only as the Docker secret `duocode_code_keyring` at start-up |
| Key backup store credentials | Yes, its own Docker secret | No |
| Database | Its own role `duocode_keymgmt`: `SELECT`, `INSERT` and `UPDATE` on `key_usage`, `SELECT` on `instance_ring_reports`, `SELECT` and `UPDATE` on `ring_state`, `SELECT (key_id)` on `secret_codes` and `guesses` and `SELECT (token_key_id)` on `token_rotations` and `SELECT (fingerprint_key_id)` on `idempotency_keys` (column grants for the reconciliation check, no ciphertext, CR-20), and the ring advisory lock. For the offline accepted-loss run only (RD-21), in addition to those: `SELECT (player_id)` on `secret_codes`, `guesses` and `idempotency_keys`, `SELECT (game_id)` on `token_rotations`, `SELECT (id, game_id)` on `players`, `SELECT (id, state, expires_at)` and `UPDATE (expires_at)` on `games`. No other access to game tables | Application role, plus `SELECT`, `INSERT`, `UPDATE` and `DELETE` on `instance_ring_reports` (the upsert reads through `EXCLUDED`, cleanup prunes), `SELECT` on `ring_state` (admission) and the presence lock (CR-17, CR-19) |
| Network | Database and backup store only | Unchanged |
| Started by | An operator, on demand (`docker compose run --rm keymgmt <command>`) | Compose |

- Commands: `keys:generate`, `keys:activate` (online, or `--offline`), `keys:seal`, `keys:abandon`, `keys:retire`, `keys:reconcile-gate` and `keys:prune-accepted-loss` (`database-schema.md` 6.2a). `keys:verify` is not a `keymgmt` command: it runs in the separate `keyverify` job (below). Every command takes the ring single-writer lock (`pg_advisory_lock` on a fixed key) for its whole run, writes the ring with the version check described in `security-assessment.md` section 3.6, backs up the new ring before releasing the lock, and only then exits.
- `keys:activate` refuses to activate a staged key until every **live reader** acknowledges it. Live readers are the processes that hold a presence lock on their own database connection, so a stopped process is never counted and a live process that has not reported blocks activation. The operator also passes the expected number of live readers (`database-schema.md` section 6.2a). The job needs no access to the admin listener and no admin credential (CR-16, CR-17).
- `keys:activate --offline` is the only way to activate a key when no reader is running: initial setup (no active key exists yet) and the restore procedure. It refuses while any presence lock is held (CR-17).
- **Roster participants (CR-17).** The long-running services `app` and `cleanup`, and a `reencrypt` job while it runs, take a presence lock and report: they use the application role, which can write reports. `keyverify` takes a lock in a separate class and blocks activation while it runs, because it reads ciphertext but does not report. `keymgmt` reads the newest ring itself and is not part of the roster. Do not run `reencrypt` or `keyverify` during phases 1 and 2 of a rotation.
- **Bounded lock waits (CR-18).** `keymgmt` never waits without limit: it takes the ring lock with `pg_try_advisory_lock` in a retry loop for at most `KEYMGMT_LOCK_WAIT_SECONDS` (default 300) and then aborts, printing the process ids that hold the lock. `keyverify` takes the ring lock in **shared** mode with `pg_try_advisory_lock_shared(4242001)` and exits at once with "busy" if a ring change is in progress, so it never starts in the middle of one and can never block one indefinitely. It also runs under a hard deadline, `KEYVERIFY_MAX_SECONDS` (default 1800): every statement carries a `statement_timeout`, and a process timer ends the job, which releases its locks because they are session locks. `keyverify` is admitted like every reader (`database-schema.md` 6.2a), so it cannot run with a ring older than the fleet requires.
- `keys:verify` runs in a **separate `keyverify` job**, not in `keymgmt`: it needs to read ciphertext from game tables, which the ring-writing job must not see. `keyverify` has a read-only database role (`SELECT` on `key_usage`, `secret_codes`, `guesses`, `idempotency_keys`, `token_rotations` and `ring_state`, and `SELECT (id, game_id)` on `players`, which the authenticated data of codes and guesses needs, CR-17; no access to nicknames), reads the ring read-only like the application, has **no writable ring, no backup-store access and no publication rights**, and cannot change anything (CR-16).
- The job never prints key material. Output: identifier, status, fingerprint prefix, ring generation.
- Distribution: after a ring change, the operator restarts the instances (the phases in 6.4). Each instance reads the new ring read-only at start-up. The application's permissions are not changed by this.
- The job image is the application image, run with different Deno permissions (`--allow-read` and `--allow-write` limited to the ring directory, `--allow-net` limited to the database and the backup store).

## 3. Configuration and secrets

Keys and defaults are defined once in `design.md`, section 13. This section covers where values come from.

| Value | Source |
|---|---|
| `DATABASE_URL` | Docker secret or `.env` file outside the repository |
| Code key ring | Docker secret `duocode_code_keyring`, mounted at `/run/secrets/duocode_code_keyring`, restricted to the application user (ND-9). Mounted into `app`, `cleanup` and the `reencrypt` and `keys:verify` jobs only |
| Rate-limit HMAC key | Docker secret `duocode_ratelimit_key`, 32 random bytes. Separate from the code key ring, mounted in `app` only, not backed up (RD-9, CH-2, `security-assessment.md` section 6.2) |
| `ADMIN_TOKEN_SHA256` | `.env` file or secret (hash only, never the token) |
| TTLs, batch size, replay window, rate limits, log level | `.env` file |

Rules:
- Only `.env.example` and a `secrets.example/` directory with placeholders are committed. `.env`, `secrets/` and key files are in `.gitignore`.
- Separate environment files for development and production. Development uses throwaway keys generated by `deno task keys:generate`.
- A start-up check validates all configuration. Missing or invalid values (including non-positive TTLs, replay window or rate-limit values) stop the application with a message that never prints secret values. Production mode also requires `TRUSTED_PROXY_CIDRS`.
- Key generation, ring backup, rotation, retirement and compromise procedures are in `security-assessment.md` section 3.6 to 3.9. Backup and restore are in sections 5 and 6 below.

## 4. Proxy settings and rate limits

### 4.1 Proxy

- HTTPS only. HSTS enabled. TLS 1.2 or later.
- Request body limit 1 KiB on `/api/v1/*`.
- Request and header timeouts to limit slow clients.
- `/admin/*` is not routed. The proxy answers `404`.
- Access log format: time, method, a fixed route template (for example `/api/v1/games/{id}/guesses`) or one fixed label for a path that matches no route, never the raw path or query string, status, duration, request id. No headers, no query strings, no bodies, and no client IP by default. Retention 14 days, then deleted (approved at Gate 2). If the owners enable IP logging for abuse investigation, a retention period must be set and the privacy notice updated.
- Adds a request id header the application also logs, and the forwarded client IP header. The application trusts it only from `TRUSTED_PROXY_CIDRS` (RD-9).
- Rate limiting module: stock Caddy has none. The proxy is built from a pinned, reproducible custom build that includes `github.com/mholt/caddy-ratelimit` (RD-1 approved). Build files, pins, provenance and maintenance are in section 4.3. The alternative, Nginx with `limit_req`, stays documented as the fallback.

### 4.2 Rate limits: recommended starting values (C-6, RD-2)

For owner approval. Values are configuration. They are tuned from measured load (R17.4). Application buckets are token buckets with the capacity (burst) and refill rate shown, kept in PostgreSQL and shared across instances (`design.md` section 11). **These values are approved as starting values (RD-2), on three conditions: every value stays configurable, enforcement is shared by all application instances through PostgreSQL, and a failure of the PostgreSQL rate-limit store fails closed with `503`.** They are tuned later from measured load.

**Layer 1: proxy, per client IP, sliding window**

| Scope | Limit |
|---|---|
| Any request to `/api/v1/*` | 300 per minute |
| `POST /api/v1/games` and `POST /api/v1/rematches` | 30 per minute |
| `POST /api/v1/games/*/join` | 30 per minute |

**Layer 2: application, per client IP (HMAC of IP)**

| Scope | Applies to | Capacity | Refill per minute |
|---|---|---|---|
| `ip:create` | `POST /games` | 10 | 1 |
| `ip:join` | `POST /games/{id}/join` | 10 | 2 |
| `ip:rematch` | `POST /rematches` | 5 | 1 |
| `ip:authfail` | Each failed credential check (consumes one) | 20 | 10 |
| `ip:admin` | Admin listener | 10 | 30 |

**Layer 2: application, per player (hash of the player id, only after the preliminary credential lookup finds a credential; CH-4)**

| Scope | Applies to | Capacity | Refill per minute |
|---|---|---|---|
| `pl:guess` | `POST /games/{id}/guesses` | 10 | 30 |
| `pl:rotate` | `POST /games/{id}/access-token/rotate` (known rotation replays are exempt, RD-18, RD-22) | 3 | 0.1 (6 per hour) |
| `pl:mint` | `POST /games/{id}/rematch-capability` | 3 | 0.1 |
| `pl:read` | Status, progress, results | 30 | 60 |
| `pl:write` | Secret code submission | 20 | 30 |

Reasoning: a person guesses a few times a minute at most, so 30 per minute with a burst of 10 is generous and still caps a script at 10 guesses well before exhaustion matters. Clients polling every 5 seconds use 12 reads per minute. Creating and joining are rare, so low refill rates stop game-creation floods without hurting households behind one address. Failed credential checks refill slowly so that guessing tokens is throttled to about 10 attempts per minute per IP after a burst of 20. Simulator and load tests use a separate environment with raised IP limits (`simulator-design.md`).

Order of events for every authenticated request: validate, check that the `ip:authfail` bucket has a token available (empty: `429` before any lookup), preliminary credential lookup (grants nothing), rate-limit updates as separate autocommit statements, then the request transaction with the authoritative credential check (`design.md` section 5.1). Failures are charged to `ip:authfail` outside the game transaction, after rollback when authoritative validation fails. A token the preliminary lookup does not find skips only the player buckets and the game transaction. A token it knows to be revoked is rejected before any player bucket is charged (RD-20), except for rotation requests (RD-18). A validated replay stays exempt from `pl:rotate` (RD-18): a rotation request with a live token first runs a read-only replay check and, unless that shows a known replay, is charged to `pl:rotate` before its transaction like every other limited operation (RD-22). Two identical requests at the same moment may both be charged, which is accepted (`state-machine.md` section 3.1). A denied request does no further work.

Behaviour on denial: `429 RATE_LIMITED` with `Retry-After`. If the limiter store fails, the request gets `503` (fail closed, RD-2). Repeated failed credential checks are throttled by the `ip:authfail` bucket, which needs no extra state (the revision 3 idea of a timed block after repeated failures was dropped).

### 4.3 Caddy custom build: pinned, reproducible, documented (RD-1, R18.6)

Caddy is retained. Because stock Caddy has no rate-limit module, the project builds its own binary. The build must be reproducible and every input version-pinned.

**Pins** (CH-6 approved: the module is pinned to its exact commit. The other versions were verified against the upstream repositories at specification time and are re-verified and recorded in `BUILD-PINS.md` when the build is implemented):

| Input | Pin |
|---|---|
| Caddy | `v2.11.9` (released 2026-11-05) |
| Rate-limit module | `github.com/mholt/caddy-ratelimit` at commit `5625512f24f6f59d6f64fb3aafe5eecff0b286db` (2026-06-12). Apache-2.0. The repository has a single tag, `v0.1.0`, which predates features this design uses (subnet prefixes, metrics), so the build pins a commit (as a Go pseudo-version) instead of the tag (CH-6) |
| Go toolchain | The exact patch release required by the pinned Caddy `go.mod`, pinned in the Dockerfile by image digest |
| Builder and runtime base images | Pinned by digest, never by tag alone |
| `xcaddy` | `v0.4.7`, used only to regenerate `go.mod` and `go.sum` when upgrading. It is not part of the repeatable build |
| Transitive dependencies | Fixed by the committed `go.sum` (Go checksum database verification stays on) |

**Files** (committed under `deployment/caddy/`, created in Phase 9):
- `go.mod`, `go.sum`: the module that requires the pinned Caddy and module versions.
- `main.go`: imports Caddy's `cmd` package, the standard module set (blank import of `github.com/caddyserver/caddy/v2/modules/standard`, without which the proxy has no HTTP server, TLS or reverse proxy) and the rate-limit module, and nothing else.
- `Dockerfile`: multi-stage build. Builder stage uses the pinned Go image. Runtime stage uses a pinned minimal base. The Compose file references the resulting image by digest.
- `BUILD-PINS.md`: every version and digest above, with the date verified.
- `BUILD-RECORD.md`: one entry per release: binary sha256, image digest, SBOM digest, builder, date, CI run id.

**Reproducible build rules.**
- `CGO_ENABLED=0`, `GOFLAGS=-mod=readonly`, `go build -trimpath -buildvcs=false -ldflags="-s -w -buildid="`.
- `go mod verify` must pass before the build. No network access to anything but the module proxy during dependency download, and none during compilation.
- `SOURCE_DATE_EPOCH` set to the commit time, and the image built with timestamps rewritten, so layers do not carry the build time.
- A CI job builds the binary twice in clean builders and fails if the two sha256 values differ. The agreed value goes into `BUILD-RECORD.md`.
- `go version -m` of the binary is compared with `BUILD-PINS.md` to prove the pinned versions are the ones built in.

**Provenance and supply chain.**
- The build runs only in GitHub Actions from a protected branch. Build provenance is attested (SLSA-style attestation from the workflow) and attached to the image.
- An SBOM (SPDX) is generated for the binary and stored with the build record.
- `govulncheck` runs against the binary in CI. A known exploitable vulnerability fails the build.
- The module's licence (Apache-2.0) and Caddy's (Apache-2.0) are recorded in `NOTICE` before release, with the third-party list.

**Maintenance.**
- Owner: one named founding collaborator (**OI-1, name to be given by the owners**). Reviews Caddy security advisories and the module repository at least monthly.
- Routine upgrade: one pull request that changes the pins, regenerates `go.mod` and `go.sum`, shows the dependency diff and the upstream change log for the module, re-runs the reproducibility job and the rate-limit tests, and adds a `BUILD-RECORD.md` entry. A module bump requires reading the upstream diff, because the project depends on a single maintainer and untagged commits.
- Security upgrade: apply within 7 days for a high or critical advisory affecting the proxy (approved at Gate 2).
- Exit criteria: if the module has an unfixed security issue, or has had no maintenance for 12 months while Caddy moves on incompatibly, switch to the documented Nginx `limit_req` fallback. The fallback configuration is kept in the operations docs and exercised in a TS-OPS test so it is ready.
- The proxy only performs coarse per-IP limiting. All fine-grained limits are in the application (section 4.2), so replacing the module affects only layer 1.

## 5. Backups, retention and key ring backup (ND-8, ND-9)

**Database backups**
- Daily `pg_dump` (custom format) of the database, compressed and encrypted to the backup recipients (both founding collaborators, for example with `age`). The backup encryption key is separate from the code key ring.
- Retention of backups: at most 35 days (`BACKUP_RETENTION_DAYS`). Older backups are deleted automatically. Backups are stored off the VPS in storage with its own credentials, not reachable from the `app` service (**OI-2: provider to be chosen by the owners**).
- Deleted games remain in backups until they age out. The privacy notice states this. After a restore, cleanup runs before traffic (section 6).
- Take a fresh backup before applying migrations in production.
- Backups contain ciphertext under the code keys and plaintext feedback counts, nicknames and credential hashes. They are access-controlled accordingly.
- The `rate_limits` table is excluded from backups (`pg_dump --exclude-table-data=rate_limits`, CH-2), so pseudonymised IP HMACs are never retained for 35 days. The rate-limit HMAC key is not backed up. Losing it only resets the counters.

**Key ring backup**
- Every version of the ring file (all keys, `ACTIVE` and `DECRYPT_ONLY`) is backed up separately from database backups, encrypted for both owners, and stored where database-backup credentials cannot reach it (`security-assessment.md` section 3.6).
- A ring backup is kept at least as long as the newest database backup that may contain data encrypted under any key in it. Because backups live for at most 35 days, a retired key's backup copy may be destroyed 35 days after the last row under that key was re-encrypted (R10.11, `security-assessment.md` section 3.9).
- Old encryption keys stay in the ring as `DECRYPT_ONLY` for as long as any backup containing ciphertext under them may need restoring (ND-9). The retirement checklist is the authority.
- Update the ring backup before a new key is made active in production.

## 6. Restore and key recovery procedures (R21.4)

These procedures are drilled before first production use and after any change to backup or key handling. The drill runs in a non-production environment and plays a game to completion.

### 6.1 Database restore (with new-key activation, RD-13)

1. Put the proxy into maintenance mode (return `503`). **Stop and drain every process that can encrypt**: `app`, `cleanup`, any running `reencrypt` job and any key job. Confirm no application connection remains to the database. If a lossless proof is wanted (step 6), only now read the `key_usage` rows of the live database (counter and `sealed` for **every** key, including `STAGED` keys). Nothing may change them afterwards.
2. Create a clean database and restore the chosen backup into it. Do not restore over a live database.
3. **Run migrations now** if the backup is older than the current schema (`deno task migrate`, under its advisory lock). Every later step uses tables and columns from the current schema (`ring_state`, `instance_ring_reports`, `key_usage.fingerprint` and `sealed`), so they must exist before the gate is reconciled or any key is sealed (CR-21).
4. Fetch the **newest** key ring (highest `generation`) and note its `highestKeyId`, its `fingerprintHistory` and the **set S of every key identifier in `fingerprintHistory`, as it is before any new key is added** (every key ever registered, including keys retired and removed from the ring, CR-13), and mount it as the secret. Never use a ring from the database backup date: the database may have gone back past keys that were created and used afterwards, and a new key identifier must not reuse one. The ring must contain every key id present in the restored data.
5. **Reconcile the admission gate** (CR-19): `docker compose run --rm keymgmt keys:reconcile-gate`. No reader is running (step 1), so it is allowed. It confirms that every key id referenced by restored ciphertext is in the newest ring, and sets `ring_state.required_key_ids` to the keys that ring loads, removing requirements for retired keys or abandoned staged keys that the restored row may still contain. Then run `deno task keys:verify` (R10.12) in the `keyverify` job. It lists key ids and fingerprint key ids referenced by the restored data, confirms each is in the ring, and test-decrypts every ciphertext. Stop here if it fails (section 6.2).
6. **Activate a new encryption key before any traffic (R10.13).** The restore rolled the `key_usage` counters back, so the key that was active may have encrypted more values than the restored counter shows, and ciphertexts from that period may still exist in the lost database, older backups or other copies. Run `deno task keys:generate` (the new identifier is above `highestKeyId`, and the tool rejects duplicate or previously used key material, registers the key, reserves at least one unit and encrypts the self-test value), activate the new key with `keys:activate <new id> --offline` (every reader is stopped, so no presence lock is held, CR-17), which makes it the only `ACTIVE` key, mark the previous active key `DECRYPT_ONLY` (it stays in the ring, so existing data still decrypts, and it never becomes `ACTIVE` again), raise the ring `generation`, back up the new ring in the separate key backup store, and **seal exactly the identifiers in the set S recorded in step 4 with `deno task keys:seal <key id>`, never the new key**. Sealing inserts a sealed row (using the key's fingerprint from the ring history) when the restored database has none for that identifier, so a key that was registered after the backup is sealed too, and a later registration cannot reset it (`database-schema.md` section 6.2). Sealing sets the counter to the hard-stop value 2^30, so every later reservation under those keys is refused even if the ring were wrong. Then, **with every service still stopped** (CR-20), abandon any staged key sealed by this step, run `keys:reconcile-gate` again so the gate matches the ring after the new key is added and any staged key is abandoned (CR-19), and re-run `keys:verify`. No service is started in this step: `app` and `cleanup` start in step 9, as fresh processes with no in-memory allowance and with the reconciled gate. This step may skip the new key, the sealing and the second reconciliation only if the restore is proved lossless: the pre-restore database was stopped and drained in step 1, is still readable, and **for every key that can still encrypt** (the `ACTIVE` key and every `STAGED` key) the restored row exists, is not sealed differently, and its counter is not lower than the pre-restore counter. In addition, **for every identifier in S** the restored row must exist with the same fingerprint and the same sealed flag as before the restore, so that no historical seal is undone and no fingerprint row is lost (CR-14). If any check fails, the restore is not lossless: every key in S, including staged keys, is sealed and a new key is generated (CR-13). **A `STAGED` key that this seals is abandoned**: its ring entry is removed (or marked `DECRYPT_ONLY` if anything was ever encrypted under it, which cannot happen for a staged key), its history entry is marked `ABANDONED` with the fingerprint kept, and a fresh key is generated. The activation tool refuses a sealed candidate, so an abandoned staged key can never be activated by mistake (CR-14). **On the lossless path the services are still started only in step 9, as fresh processes, so no allowance survives the restore.** If in doubt, do not skip it. After traffic resumes, run `deno task reencrypt` in the background to move data to the new key. The old key is retired later by the rule in `security-assessment.md` section 3.9.
7. Truncate `rate_limits` if it holds rows (it is excluded from backups, so a restore normally leaves it empty). The buckets are meaningless after a restore. Provide the current `duocode_ratelimit_key` secret, or generate a new one.
8. Run `deno task cleanup`. Games that were deleted after the backup was taken have returned. Cleanup deletes every game with `expires_at <= now`, so rule-based deletion is re-applied before anyone can reach them. Run it until it reports zero.
9. Start `app` and `cleanup` (fresh processes: no allowance survives, and each passes the admission check against the reconciled gate before it serves). This is the first point in the procedure at which any reader runs. Check `/healthz`. Remove maintenance mode.
10. Run the simulator against the restored stack (a small run).
11. Record date, restore point, whether step 6 was skipped and why, backup used, ring version and checks in the operations log.

Consequences of any restore, to be stated in the operations notes (RD-7):
- Credential state returns to the backup time. A player who rotated after that time holds a token the restored database does not know, and loses their seat. A token rotated away after the backup becomes valid again.
- Games created after the backup are gone. Guesses made after the backup are gone. Players resubmit.
- Games deleted after the backup return until step 8 removes them.
- Point-in-time recovery is not part of MVP 1 (RD-7). It would reduce the loss window and can be added by archiving WAL.

### 6.2 Encryption key recovery

Situation A, key ring file damaged or lost, backup exists:
1. Retrieve the latest ring backup (two people can).
2. Verify checksums, mount as the secret, run `keys:verify` against the live database.
3. Restart `app` and `cleanup`.

Situation B, a needed key is missing from every ring copy:
1. Run `keys:verify`. It names the missing key ids and the counts of affected rows.
2. Rows under that key cannot be decrypted. They cannot be recovered by any means (there is no escrow and no database copy of keys).
3. Affected in-progress games cannot continue and are abandoned. They expire and are deleted by cleanup. Affected completed games lose their codes and guesses in results (results return an internal error for them), while outcomes and counts survive.
4. Other games are unaffected. The application starts only if the active key is present. If the active key is missing, generate a new ring, accept the loss of in-flight data under the old key, and record the incident.
5. Do not delete ciphertext rows by hand. Let retention remove them.
6. **Offline recovery so the service can start again (RD-19).** With `app` and `cleanup` stopped (no reader live), the owners accept in writing that the data under the missing key is lost. The operator then runs `keys:reconcile-gate` in the `keymgmt` job with the missing key ids named as accepted loss. The reconciliation then sets the admission gate to the keys the newest ring loads, instead of stopping because ciphertext references a key id that is not in the ring (`database-schema.md` section 6.2a). The tool first records the affected games durably (every game with a row under a missing ciphertext key or a missing fingerprint key, `database-schema.md` section 6.2a, RD-21). An affected game that is still in progress is expired at once (`expires_at` set to now), so it is not played or shown and cleanup deletes it without decrypting. An affected completed game is not changed: its outcome and counts survive and results return an internal error. The fingerprint history entry, the key registry row and the sealed counter of the missing key are kept, so its identifier is never reused and no counter is lowered. The key part of the record (key id, fingerprint, counts) is kept permanently in the ring history. Each affected game's id and state are removed from the record when that game is deleted, by `keys:prune-accepted-loss` (`keymgmt`, run at least daily, section 7), so no game data outlives the 35-day backup limit (RD-23). `reencrypt` skips games in the record and reports how many (RD-24). `keys:verify` is run with the recorded list (`--accepted-loss`, option form for task 9.2a). It excludes only rows that reference a recorded missing key id and belong to a recorded game, and it fails on any other missing key reference, any unrecorded affected row and any ciphertext that does not decrypt. `app` and `cleanup` start only after the gate is reconciled and that verification has passed for all other data. This situation never allows a start with the gate unreconciled.

Situation C, suspected key compromise: follow `security-assessment.md` section 3.6 (compromise response). Keep the compromised key `DECRYPT_ONLY` until the owners decide how to handle backups under it.

### 6.3 Key retirement

Follow the checklist in `security-assessment.md` section 3.9: `keys:verify` shows no references, at least `BACKUP_RETENTION_DAYS` since re-encryption finished, the ring backup is updated, then remove the key from the active ring with `keys:retire` in the `keymgmt` job (it also removes the key from `ring_state.required_key_ids`) and, after the same retention, from ring backups.

### 6.4 Planned key rotation, including one completed after 2^28 (RD-14, CR-10, CR-12)

The same procedure applies whether the rotation is routine, prompted by the warning at 2^27, or late because the key already passed 2^28 (`ROTATION_OVERDUE`, reservations still granted). The rules are defined once in `database-schema.md` section 6.3 and `security-assessment.md` sections 3.6 and 3.6a. It has **three phases**, so that no instance ever meets ciphertext it cannot decrypt:

**Phase 1, stage.**
1. `deno task keys:generate`, run in the `keymgmt` job (section 2.1). It writes the key material directly into the protected ring source file and prints only the identifier, status and fingerprint prefix, never the material. The identifier is above `highestKeyId`. The tool rejects duplicate or previously used key material, registers the key (row and fingerprint), reserves at least one unit and encrypts the self-test value. Its output is metadata only.
2. Add the key to the ring as `STAGED` (it decrypts, never encrypts), raise the ring `generation`, and back up the ring and its fingerprint history (section 5).
3. **Restart every live reader** (`app` and `cleanup`), one after another. `reencrypt` and `keyverify` must not be running during phases 1 and 2. Each restarted process takes its presence lock and reports its loaded ring before it serves requests. `keys:activate` in phase 2 checks the roster (CR-16, CR-17).

**Phase 2, activate.**
4. Run `keys:activate <new id> --expect <N>`. It refuses unless exactly `N` live readers hold presence locks, every one of them has reported the staged key, and no `keyverify` job is running (`database-schema.md` 6.2a). It then changes the ring: the new key `ACTIVE`, the previous key `DECRYPT_ONLY` with `deactivatedAt` set, `generation` raised. Back up the ring.
5. **Restart every instance** again, one after another. During this rolling restart some instances encrypt with the previous key and some with the new one. Both keys are in every ring and unsealed, so every instance can decrypt both. Allowances live in memory only, so a restarted instance holds none for the previous key. Check that every instance reports the new generation.

**Phase 3, seal.**
6. `deno task keys:seal <previous id>` (`sealed = true`, counter 2^30), for the previous key only. The seal waits for every transaction that is in its commit-time check on that key (share lock) and commits after them. From the moment it commits, no reservation is granted under the key, no request that begins afterwards passes the pre-encryption check, and **no transaction can commit ciphertext under it**: a transaction that reaches its commit-time check after the seal rolls back (CR-13). An instance that was missed fails visibly, raising the refusal alert, and is restarted.
7. Units that were reserved for the previous key and never used remain counted in its total. The counter is never lowered. The admin health state of the previous key becomes `sealed`, which is expected and raises no alert.
8. Run `deno task reencrypt` and `keys:verify`, then retire the previous key by the checklist in 6.3 and `security-assessment.md` section 3.9. Re-encryption can start as soon as `keys:seal` returns, because no ciphertext under the previous key can be committed afterwards. Its fingerprint stays in the ring history for ever.

A key that has been `DECRYPT_ONLY` never becomes `ACTIVE` again. Restore (6.1) uses the same sealing and restart rules, but needs no staging because traffic is stopped and all instances restart together.

## 7. Scheduling of cleanup and re-encryption (R11, R21.2)

- The `cleanup` service runs the cleanup task every `CLEANUP_INTERVAL_MINUTES` (default 60). Each run loops batches of `CLEANUP_BATCH_SIZE` until a batch is short, then clears expired rotation ciphertext and idle rate-limit rows. The run has a time budget and exits cleanly. The next interval continues.
- Scheduling is by this one service, not by application instances (R21.2), so scaling `app` never multiplies cleanup runs. The task is safe even if two runs overlap (`SKIP LOCKED`).
- `POST /admin/cleanup` on the admin listener runs the same code for manual and dry runs.
- Key usage alerts (per key id, from the admin metrics `duocode_key_usage_state` and `duocode_health_state`): state `WARNING` at 2^27 reserved units is an operational warning, `ROTATION_OVERDUE` at 2^28 is a critical alert (rotate the key now, reservations still succeed until 2^30, procedure 6.4), and a reservation refusal or pre-encryption check failure **for the key that is `ACTIVE` in the ring** is a critical alert (the hard stop was reached, or the key is sealed while an instance still has it as `ACTIVE`). A sealed key that is not active (state `sealed`) is the normal end of a rotation and raises no alert, so a rotation never leaves a critical alarm behind. The public `/healthz` is not used for key usage.
- Alerts: cleanup not completed for 3 intervals, cleanup errors for 3 consecutive runs, expired-but-undeleted games above a threshold (metric `duocode_games_expired_pending`), cleanup lock timeouts above a threshold.
- `deno task reencrypt` is run by the operator during key rotation, not on a schedule. It skips games listed in an accepted-loss record and reports the number skipped (RD-24).
- `keys:prune-accepted-loss` (`keymgmt` job) is run at least daily by the operator's scheduler while any accepted-loss record still lists a game (RD-23). It removes the ids of deleted games from the record and does nothing when the record lists none.

## 8. Migrations and releases

- `migrate` runs before `app` starts and holds an advisory lock. The `app` refuses to start if the schema version is lower than expected.
- Release procedure: build image, run CI, take backup, `docker compose pull`, run `migrate`, start new `app` instances, check `/healthz`, stop old instances. Migrations are written to stay compatible with the previous release for one version (rolling restart).
- Rollback: redeploy the previous image. Schema rollback is forward-only through a new migration or a restore.

## 9. Monitoring

- `/admin/metrics` (Prometheus text format) on the admin listener, scraped from the internal network by a local collector or checked manually in MVP 1. It is privacy-safe by rule (R13.8).
- Health: `/healthz` on the public listener is used by Compose healthchecks and an external uptime check.
- Metrics listed in `design.md`, section 14, plus `duocode_decrypt_failures_total`, `duocode_encryptions_total{key_id}` (informational invocation count; the thresholds 2^27, 2^28 and 2^30, approved RD-10, are decided from the reserved total and key usage state in section 7, never from this count), `duocode_games_expired_pending` and rate-limit denials by scope.
- Host metrics (CPU, memory, disk, database size) from the VPS tooling. Hosting cost is tracked manually (baseline 12.4).

## 10. Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local | Development | Compose with `.env.development`, throwaway keys, self-signed or HTTP-only proxy |
| CI | Automated tests | PostgreSQL service container, generated test key ring, short replay window |
| Dev Linux server | Definition-of-done deployment (baseline 17.1) | Same Compose files, separate secrets |
| Production | Public | Separate secrets, keys, backups |

## 11. Deployment acceptance

The backend MVP deployment is accepted when:
1. `docker compose up` on a clean Linux host starts all services and `/healthz` reports ready.
2. The application refuses to start without a valid key ring and without the rate-limit key.
3. A complete game plays through the proxy over HTTPS with curl. `/admin/*` through the proxy returns `404`.
4. The simulator runs against the deployed stack and exits zero.
5. The `cleanup` service removes an artificially expired game on schedule, and the admin endpoint reports the same.
6. A backup and restore drill (section 6.1) succeeds with the key ring supplied separately, including `keys:verify` and cleanup before traffic.
7. A key rotation drill (stage the key on every instance, activate it by a rolling restart with traffic running and no request failing to decrypt, `keys:seal` the old key, `reencrypt`, `keys:verify`) succeeds without failed requests, a reservation attempt under the sealed key is refused, a request that begins after the seal on an instance still holding an allowance for it fails the pre-encryption check, and the restore drill includes new-key activation (step 6 of section 6.1) and shows the restored counters behind the pre-restore ones.
8. Rate limits behave as in section 4.2 with two `app` instances running.
9. The Caddy image is built from the pinned files, two independent builds give the same binary digest, the digest matches `BUILD-RECORD.md`, and `go version -m` matches `BUILD-PINS.md` (section 4.3).

## 12. Accepted operational risks

| Risk | Decision | Reassess |
|---|---|---|
| No point-in-time recovery in MVP 1. A restore returns the database to the last daily backup: up to 24 hours of games, guesses and rotations are lost, deleted games reappear until cleanup runs, rotated-away tokens become valid again and players who rotated since lose their seat (`security-assessment.md` T30) | Accepted by the owner as a documented operational risk (RD-7) | Before production deployment. Options then: continuous WAL archiving to the off-host store, or more frequent dumps. Task 10.6 in `tasks.md` |
| Single-maintainer rate-limit module in the Caddy build | Accepted with pinning, review on every bump and the Nginx fallback (section 4.3) | At each upgrade |
| Pseudonymised IP HMACs held for up to about two hours | Accepted subject to the privacy notice (`security-assessment.md` section 6.2) | When the privacy notice is written |
