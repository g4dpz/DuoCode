# DuoCode Design Overview (Backend MVP 1), revision 3

Implements `requirements.md`. This file is the architectural overview. Detailed definitions live in the artefacts listed in the document map. Decision IDs (OD-n, ND-n, C-n, CL-n, RD-n) are defined in the decision register in `requirements.md`.

## 1. Document map and ownership

| Topic | Single source of truth |
|---|---|
| Requirements, decisions | `requirements.md` |
| Requirement to artefact, test and approval mapping | `traceability.md` |
| Architecture, layers, credential model, authorisation point, lock ordering, rate-limiting design, configuration keys and defaults | this file |
| HTTP paths, schemas, status codes, error codes | `../../../openapi/openapi.yaml` |
| Tables, constraints, indexes, migrations, cleanup and rate-limit SQL | `database-schema.md` |
| States, transitions, expiry rule, credential lifecycle, idempotent rotation | `state-machine.md` |
| Threats, encryption, key management, logging and metrics rules | `security-assessment.md` |
| Test layers, required cases, test group IDs | `test-strategy.md` |
| Simulator | `simulator-design.md` |
| Compose stack, secrets, rate-limit values, backups, restore, scheduling | `deployment.md` |
| Change summary and open decisions | `revision-3-review-package.md` |
| Tasks and approval gates | `tasks.md` |

If two documents disagree, the owning document wins and the other is a defect to fix.

## 2. Architecture

```
 curl / Postman / simulator
            |  HTTPS
          Caddy  (TLS, coarse per-IP limits; does not route /admin)
            |
      Oak HTTP layer      routing, token extraction, validation, IP rate limit, error mapping
            |
      Services            use cases, transaction boundaries, authorisation point
        |        \
     Engine     Persistence (repositories, SecretCodeVault, rate limiter, migrations)
   (pure rules)        |
                  PostgreSQL             key ring file (outside DB and backups)

 Admin listener (internal network only): /admin/metrics, /admin/cleanup
 cleanup service (Compose): runs the cleanup task hourly from the same codebase
```

Dependency rule: `engine` imports nothing from other layers and nothing with I/O or cryptography. `services` import `engine` and interfaces for persistence. `http` imports services. Persistence implements the interfaces. The simulator and the API client import neither services nor persistence.

Application instances hold no session state. All shared state, including rate-limit counters, is in PostgreSQL. Several instances can run behind the proxy without affinity (SCALE-001, SCALE-002).

## 3. Repository layout (OD-1)

```
duocode/
├── .github/workflows/ci.yml  copilot-setup-steps.yml   .github/copilot-instructions.md
├── .kiro/specs/duocode/            requirements.md design.md tasks.md and the artefacts in section 1
├── backend/
│   ├── deno.json
│   ├── migrations/                 versioned SQL, see database-schema.md
│   ├── src/
│   │   ├── engine/                 pure rules
│   │   ├── services/               use cases, authorisation point
│   │   ├── persistence/            repositories, vault, rate limiter, migration runner
│   │   ├── http/                   Oak apps (public and admin), routes, middleware, validation
│   │   ├── config/                 typed configuration
│   │   ├── tasks/                  cleanup, reencrypt, keys:generate, keys:verify
│   │   └── main.ts
│   └── tests/                      unit, engine, reference, integration, security, concurrency
├── tools/
│   ├── simulator/                  game simulator (simulator-design.md)
│   └── api-client/                 typed API client used by tests and the simulator
├── openapi/openapi.yaml
├── postman/                        collection.json, environments/
├── docs/                           architecture.md API.md security.md testing.md licensing.md
├── deployment/                     docker-compose.yml, configuration/
├── frontend/                       created when browser work starts, not before
├── README.md  CONTRIBUTING.md  LICENSE  NOTICE  .gitignore
```

`docs/API.md` carries the curl walk-through, the lost-token limitation and the safe-retry rules for rotation (R16).

## 4. Game engine

Pure functions and types. No clock, randomness, I/O or cryptography.

```ts
type Symbol = 1 | 2 | 3 | 4 | 5 | 6;
type Code = readonly [Symbol, Symbol, Symbol, Symbol];
interface Feedback { exact: number; misplaced: number }
interface GameConfig { positions: 4; symbols: 6; maxGuesses: 10 }

parseCode(input: unknown, cfg): Result<Code, CodeError>
computeFeedback(secret: Code, guess: Code): Feedback
applyGuess(state: PlayerChallenge, feedback: Feedback, cfg): PlayerChallenge
isSolved / isExhausted(state, cfg)
determineOutcome(p1: PlayerOutcome, p2: PlayerOutcome): Outcome
```

Feedback: count exact matches by position. Over the remaining positions, for each symbol add `min(count in secret, count in guess)` to misplaced. A symbol is never counted more often than it occurs in either code.

Reference implementation (tests only, `backend/tests/reference/`): a different algorithm (mark-and-remove over arrays) that imports nothing from `src/engine`. Details in `test-strategy.md`.

Decrypted secret codes and guesses reach the engine only as arguments. `parseCode` never includes the input in an error value. Nickname validation, request canonicalisation and fingerprints are not engine concerns. They live in `http/` and `services/`.

## 5. Credential model and authorisation point (OD-7, CL-1)

Defined here once. Lifecycle is in `state-machine.md`, storage in `database-schema.md`, wire use in `openapi.yaml`.

| Type | Prefix | Issued | Presented as | Authorises | Lifetime |
|---|---|---|---|---|---|
| Game access token | `dca_` | Create game, join, rematch creation, rotation | `Authorization: Bearer` | One player in one game: status, progress, code, guesses, results, rotate, mint rematch capability | Until the game is expired (`reference time >= expires_at`), rotation or deletion |
| Invitation token | `dci_` | Create game, rematch creation | JSON body of join | Join one game as seat 2, once | Until used or the game is expired |
| Rematch capability | `dcr_` | Minted by `POST /games/{id}/rematch-capability` on a completed game | `Authorization: Bearer` | `POST /rematches` for one completed game, once | Until used, replaced by a newer capability for the same player, revoked by a rotation of the same player's access token, or the original game is expired |

- Format: prefix + base64url of 32 bytes from `crypto.getRandomValues` (43 characters, 256 bits). Every credential is its own independent draw. The prefix aids secret scanning and client mistakes and is never trusted. The credential's type is the `type` column of its stored record.
- Storage: plain SHA-256 of the full token string, as `bytea`, with a unique index (ND-6). Plaintext exists only in the response that issues the token. Exception: for the rotation replay window, the new token is also stored as AES-256-GCM ciphertext (section 5.2).
- Game id: UUID from `crypto.randomUUID()`. It is an identifier, not a credential.
- Credential records are deleted with their game and are not kept afterwards (C-7).

### 5.1 Authorisation point

One function, `authorise(tx, token, expectedType, gameId?, options)`, owned by the services layer, decides every credential question. Nothing else reads the credentials table for decisions.

- The HTTP layer only extracts the bearer token (or the invitation from the body), validates the header format, applies IP rate limits, and passes the token to the service. It performs no credential lookup of its own.
- `authorise` reads the reference time once with `clock_timestamp()`, runs the lookup in `database-schema.md` section 4 and returns either an authorised principal (credential id, player id, game id, seat) or one of `INVALID_CREDENTIALS`, `GAME_EXPIRED`. Expiry is `reference time >= expires_at`.
- **Writes:** begin the transaction, lock the game row, call `authorise`. The decision is made with the lock held and so reflects every committed rotation or revocation. For operations that carry no game id (`createRematch`), the service does one unlocked lookup to find the game, locks it, and calls `authorise` again. Only the second result is used.
- **Reads:** one read-only `REPEATABLE READ` transaction. `authorise` is its first statement. Every following read in the transaction sees the same snapshot, so the decision and the data are consistent. No game lock is taken, so reads never block writers (R8.12, `state-machine.md` section 1.4).
- **Rate limits:** credential-based limits are applied by `authorise` after a credential is found (section 11).
- **Rotation replay:** `authorise` is given the option `allowRotationReplay` by the rotation operation only. Every other operation treats a revoked token as `INVALID_CREDENTIALS`.
- The reference time returned by `authorise` is the only clock used by the rest of the request, including setting `expires_at`.

### 5.2 Rotation and idempotency (ND-4)

Rotation requires an `Idempotency-Key` and is specified in `state-machine.md` section 3.1. Summary of the design:

1. Under the game lock: create the new access token, revoke the old one (reason `ROTATED`), revoke the player's unused rematch capability (`ROTATION_SIDE_EFFECT`), and insert a `token_rotations` row. All in one transaction.
2. The row holds the fingerprint of the request and the new token encrypted with AES-256-GCM under the key ring (AAD: purpose, key id, game id, player id, rotation id). It also holds `replay_until = reference time + ROTATION_REPLAY_SECONDS`.
3. A retry with the same old token and the same key, inside the window and while the new token is still live, returns the same new token, flagged as a replay. After the window the ciphertext is cleared by cleanup and the replay rule no longer applies.
4. The security consequences are in `security-assessment.md` section 2.2. They are bounded by: the replay needs both the old token and the key, the window is short, the stored value is encrypted, and replay changes no state.

### 5.3 No recovery

A lost token cannot be re-issued, because there is no verified identity. Rotation needs the current token. Replay needs the old token and the key. The limitation is stated in the OpenAPI description and in `docs/API.md` (R8.9).

## 6. Game flow

States and transitions are in `state-machine.md`. Summary:

1. Player 1 creates a game and receives an access token and an invitation token, and sets a code.
2. Player 2 joins with the invitation, receives an access token and sets a code. The game becomes `ACTIVE` when both codes exist.
3. Each player guesses against the opponent's code until solved or exhausted.
4. When both are finished the game becomes `COMPLETED` and results, including both codes, become readable.
5. A participant can mint a rematch capability. Presenting it creates a new game with new credentials (R9).

## 7. API summary

The contract is `openapi/openapi.yaml`. Operations:

| Operation | Method and path | Credential |
|---|---|---|
| Create game | `POST /games` | none |
| Join game | `POST /games/{gameId}/join` | invitation token in body |
| Submit secret code | `PUT /games/{gameId}/secret-code` | access token |
| Game status | `GET /games/{gameId}` | access token |
| Submit guess | `POST /games/{gameId}/guesses` | access token and `Idempotency-Key` |
| Player progress | `GET /games/{gameId}/progress` | access token |
| Results | `GET /games/{gameId}/results` | access token (current) |
| Rotate access token | `POST /games/{gameId}/access-token/rotate` | access token and `Idempotency-Key` |
| Mint rematch capability | `POST /games/{gameId}/rematch-capability` | access token |
| Create rematch | `POST /rematches` | rematch capability |
| Health | `GET /healthz` | none |
| Metrics | `GET /admin/metrics` | admin token, admin listener only |
| Cleanup | `POST /admin/cleanup` | admin token, admin listener only |

Conventions are in R12. Error bodies never echo request values.

## 8. Transactions, lock ordering and deadlock avoidance (CL-8)

### 8.1 Transaction pattern

Every state-changing use case runs in one transaction at `READ COMMITTED` with a fixed shape:

1. Validate the request and apply the IP rate limit (no transaction).
2. `BEGIN`. Set `lock_timeout` (default 5 s) and `statement_timeout` (default 10 s) for the transaction.
3. `SELECT … FROM games WHERE id = $1 FOR UPDATE` on the game addressed by the request.
4. `authorise` (section 5.1). It also applies the credential rate limit.
5. Idempotency lookup, state checks and rule checks (`state-machine.md` section 1.3).
6. Apply changes, update `expires_at` where the operation counts as activity (R11.2).
7. `COMMIT`.

Validation failures happen before `BEGIN`, so they cannot modify anything.

### 8.2 Lock order

The order is total and the same in every code path:

| Level | Lock | Held by |
|---|---|---|
| L0 | IP rate-limit bucket row | Its own autocommit statement. Released at once. No other lock is held while waiting for it |
| L1 | `games` row of the game addressed | Every write, from step 3 to commit. Also re-encryption and cleanup (with `SKIP LOCKED`) |
| L2 | Credential rate-limit bucket row | One upsert after L1 inside a write. Reads take no L1 and update it in an autocommit statement |
| L3 | Rows of `players`, `credentials`, `secret_codes`, `guesses`, `idempotency_keys`, `token_rotations`, `game_results` | Only while holding the L1 lock of their own game |

Rules:
- **One game lock per transaction.** No transaction locks two existing games. `createRematch` locks the original (L1) and then inserts the new game. Nobody else can lock a row that does not exist yet, and a concurrent insert for the same rematch is excluded by the original's lock.
- **Child rows only under the game lock.** Because every writer holds L1 first, writers on the same game are fully serialised and cannot deadlock on child rows. Their order among L3 rows is therefore unconstrained.
- **Rate-limit rows never precede a game lock.** L0 is released before L1 is requested. L2 is taken after L1. Nothing holds L2 and then asks for L1.
- **Never wait in maintenance.** Cleanup and re-encryption use `FOR UPDATE SKIP LOCKED` on games and never wait for L1. Rate-limit pruning uses `SKIP LOCKED`.
- **Foreign key side effect.** Deleting an original game updates the rematch game row (`ON DELETE SET NULL`). That waits, bounded by `lock_timeout`, if a request holds the rematch game's lock. The request on the rematch game never touches the original, so this cannot form a cycle. A lock timeout makes cleanup skip the batch and retry on the next run.
- **Retries.** Deadlock (`40P01`), serialisation failure (`40001`) and unique-violation backstops are retried once by the transaction helper. Lock timeout is not retried and returns `503` to the client with `Retry-After`.
- **Idle transactions** are bounded by `idle_in_transaction_session_timeout`.

### 8.3 Guess submission

Order of checks inside the transaction:

1. Lock game, `authorise`.
2. Look up `(player_id, key)` in `idempotency_keys`. If found, recompute the fingerprint for this request with the record's `fingerprint_key_id` and compare in constant time. Equal: return the stored response and stop. Different: `IDEMPOTENCY_CONFLICT`. (R5.3 to R5.5, R5.9)
3. Check game is `ACTIVE`, player not solved, `guesses_used < 10`.
4. Decrypt the opponent's code inside the vault callback, compute feedback, encrypt the guess, insert it with `guess_number = guesses_used + 1`, update the player, insert the idempotency record with the response body, update `expires_at`.
5. If both players are finished, compute the outcome, insert the result, set `COMPLETED` and the completed-game `expires_at`.
6. Commit and return `201`.

Database backstops: `UNIQUE (player_id, guess_number)` with range check, the previous-guess foreign key (contiguity and no guess after solved), and the idempotency primary key and `UNIQUE (guess_id)` (`database-schema.md` section 3). If a backstop fires the transaction helper retries once and the normal path then finds the stored record.

### 8.4 Other races

All races named by the owner (simultaneous join, guess, rotation, rematch, cleanup) are resolved by the rules above and tabulated in `state-machine.md` section 6. Each has a named test in `test-strategy.md` (TS-CONC).

## 9. Secret and guess protection (OD-6, ND-7)

A `SecretCodeVault` in the persistence layer owns encryption. Cryptographic detail, key ring, rotation, retirement and recovery are specified in `security-assessment.md` section 3. Architectural rules:

- Services never see ciphertext or keys. They call `vault.sealCode`, `vault.sealGuess`, `vault.sealToken` on write, and `vault.use(row, fn)` on read paths.
- `use` hands the decrypted value to a callback and clears the buffer afterwards. The callback result must not contain the value. The guess path returns only feedback.
- A `Secret` wrapper type redacts itself under `JSON.stringify`, `toString` and `Deno.inspect`. Any accidental logging prints `[REDACTED]`.
- Decrypt failure (authentication failure, unknown key id) returns an internal error with no detail and raises an alert metric. It never falls back.
- Decryption occurs only in the paths named in R10.7: guess submission, progress (caller's own guesses), results after `COMPLETED`, rotation replay.
- Request fingerprints for guesses are keyed HMACs from the vault (`vault.fingerprint`), not plain hashes (RD-8, R5.12).
- The vault reports an encryption counter per key id for the nonce-safety alert (R10.10).

## 10. Request canonicalisation and fingerprints (CL-6)

- Bodies are parsed once. Duplicate member names are rejected as `INVALID_REQUEST`. Unknown members are rejected.
- The envelope `{"operation": name, "gameId": lowercase uuid, "body": parsed body}` is serialised with RFC 8785 JCS. Bodies in this API contain only integers, strings, arrays and objects, so JCS reduces to sorted member names, no insignificant whitespace, ES6 number formatting and minimal string escaping. A small implementation is acceptable if it passes the RFC 8785 test vectors and the property tests in `test-strategy.md` (TS-IDEM). A vetted library may replace it.
- Guess fingerprint: `HMAC-SHA-256(HKDF(key[kid], "duocode/fingerprint/v1"), JCS(envelope))` with `kid` stored in `fingerprint_key_id`.
- Rotation fingerprint: SHA-256 of JCS of `{"operation":"rotateAccessToken","gameId":…,"body":{"fromCredentialId":…}}`. It contains no secret that can be enumerated.
- Equal canonical bodies give equal fingerprints. Any difference in a symbol, in operation or in game changes it.

## 11. Rate limiting (R20, C-6, CL-4)

Two layers. In-memory limits are not used as a control because instances do not share them.

**Layer 1: Caddy, per client IP, coarse.** Protects the application from floods before any work is done. Requires a rate-limit module (RD-1). Values in `deployment.md` section 4.

**Layer 2: application, shared in PostgreSQL.** Token buckets in `rate_limits` (`database-schema.md` section 6), one atomic upsert per check.

| Subject | When | Scopes |
|---|---|---|
| HMAC of client IP | Before the transaction, own autocommit statement | `ip:create`, `ip:join`, `ip:rematch`, `ip:authfail`, `ip:admin` |
| SHA-256 of presented token | Inside `authorise`, after the credential is found | `tok:guess`, `tok:rotate`, `tok:mint`, `tok:read`, `tok:write` |

- A failed credential check consumes from `ip:authfail`. When that bucket is empty the request is rejected with `429` before any credential lookup, which throttles token guessing.
- Credential buckets apply only after a credential is found, so a flood of random tokens cannot create bucket rows. Random tokens are limited by `ip:authfail` and Caddy.
- The client IP comes from the proxy's `X-Forwarded-For` only when the connection comes from `TRUSTED_PROXY_CIDRS`. Otherwise the socket address is used (RD-9).
- If the bucket statement fails, the request is rejected with `503` (RD-2).
- A denial returns `429 RATE_LIMITED` with `Retry-After`.
- Idle rows are deleted by cleanup.
- Redis stays out of MVP 1. If measurements later show contention on rate-limit rows, move the buckets to Redis behind the same interface (SCALE-004).

## 12. Expiry, retention and cleanup (OD-5, ND-8)

Specified in R11. Mechanics:
- `games.expires_at` is the only retention clock. Rules in `database-schema.md` section 5. A game is expired at `reference time >= expires_at` everywhere (`state-machine.md` section 1.1).
- Credentials of an expired game are invalid at once (R8.10). Credential records are deleted with the game and not retained (C-7).
- Cleanup runs in a dedicated `cleanup` service every `CLEANUP_INTERVAL_MINUTES` (default 60) using `deno task cleanup`. Application instances never schedule it. `POST /admin/cleanup` on the admin listener runs the same code for manual and dry runs.
- Each batch deletes games with `FOR UPDATE SKIP LOCKED` and re-checks expiry on the locked row. Cascading foreign keys remove all dependent data. The same run clears expired rotation ciphertext and idle rate-limit rows.
- Backups, restore and cleanup after restore are in `deployment.md` sections 5 and 6.

## 13. Configuration

All keys are read at start-up, validated, and failure is fatal. Defaults are the single definition.

| Key | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none (required) | PostgreSQL connection |
| `CODE_KEYRING_FILE` | `/run/secrets/duocode_code_keyring` | Path to key ring file (ND-9) |
| `RATE_LIMIT_HMAC_KEY_FILE` | `/run/secrets/duocode_ratelimit_key` | Secret for IP subject HMAC (RD-9) |
| `TRUSTED_PROXY_CIDRS` | none (required in production) | Addresses whose `X-Forwarded-For` is trusted |
| `ADMIN_TOKEN_SHA256` | none (required in production) | Hex SHA-256 of the admin token |
| `ADMIN_LISTEN_ADDR` | `127.0.0.1:8081` | Admin listener, never published |
| `TTL_UNJOINED_DAYS` | `7` | Unjoined retention |
| `TTL_IN_PROGRESS_DAYS` | `30` | In-progress retention |
| `TTL_COMPLETED_DAYS` | `180` | Completed retention |
| `ROTATION_REPLAY_SECONDS` | `600` | Rotation replay window (RD-3) |
| `CLEANUP_BATCH_SIZE` | `200` | Games per cleanup batch |
| `CLEANUP_INTERVAL_MINUTES` | `60` | Cleanup service interval |
| `BACKUP_RETENTION_DAYS` | `35` | Used by key retirement checks and docs |
| `RATE_LIMITS` | see `deployment.md` section 4 | Capacity and refill per scope |
| `DB_LOCK_TIMEOUT_MS` | `5000` | Transaction lock timeout |
| `DB_STATEMENT_TIMEOUT_MS` | `10000` | Statement timeout |
| `LOG_LEVEL` | `info` | Logging |
| `HTTP_MAX_BODY_BYTES` | `1024` | Body size limit |

Validation: TTLs, replay window, batch size and rate-limit values must be positive. `BACKUP_RETENTION_DAYS` must be positive. Development and production use separate environment files. Only `.env.example` is committed.

## 14. Observability (R13.8, R13.9)

- Structured JSON logs with allow-listed fields only: time, level, request id, route template, status, duration, error code, operation, counts, game id where needed. No client IP, no nicknames, no bodies, no headers beyond the allow-list. Rules in `security-assessment.md` section 4.
- Metrics (Prometheus text format) on the admin listener: games created, active, completed; requests by route template and status class; latency histogram; database pool usage; cleanup deleted count and duration; rate-limit denials by scope; encryptions per key id; decrypt failures; replays by operation. Labels come from bounded sets and never contain game ids, player ids, nicknames, IP addresses or tokens.
- `GET /healthz` runs `SELECT 1` and verifies the key ring loaded. It is on the public listener and reveals nothing else.

## 15. Future compatibility (constraints only)

- No tenant tables or code in MVP 1. `games.config` is JSON so rule variations can come later without a schema change.
- The engine takes `GameConfig` as a parameter. Services and HTTP layers hold no presentation assumptions. A `frontend/` directory is added when browser work starts.
- SPDX headers on source files, `NOTICE`, and `CONTRIBUTING.md` before outside contributions (R19).

## 16. Remaining decisions

Pending decisions are RD-1 to RD-10 in `requirements.md`. This design assumes the proposals recorded there.
