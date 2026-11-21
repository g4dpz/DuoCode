# DuoCode Security Assessment (revision 3)

Owns: threats and mitigations, credential security, rotation implications, encryption and key management, logging and metrics rules, residual risks. Related: `requirements.md` (R3, R5, R8, R10, R13, R20, R21), `design.md` (credential model, authorisation point, vault, lock ordering), `database-schema.md` (storage), `state-machine.md` (credential lifecycle, idempotent rotation), `../../../openapi/openapi.yaml` (error behaviour), `deployment.md` (secrets, proxy, backups, restore).

Status: draft for owner review (Phase 1 gate 1.5).

## 1. Assets and trust boundaries

| Asset | Why it matters |
|---|---|
| Secret codes and guesses | Knowing a code ends the game. Guesses plus feedback can reveal a code. Private until `COMPLETED` |
| Credentials (access, invitation, rematch, admin) | Bearer secrets. Possession equals identity |
| Encryption key ring | Protects every stored code, guess and temporary rotated token |
| Game integrity (attempt counts, outcome) | The result must be fair |
| Nicknames | Possibly personal data |

Boundaries: client to proxy (internet, HTTPS), proxy to application (private network), application to PostgreSQL (private network), application to key ring file (host filesystem, secret mount), admin listener (internal network only), operator to host (administrative access).

Attackers considered: the opponent (authenticated, tries to learn the code or cheat on attempts), an outsider with a leaked game id, an outsider scraping or brute-forcing, a person who obtains a database backup or has database-only access (read), a person who reads logs or metrics, and a compromised dependency. A malicious server operator is out of scope (the server must know codes to compute feedback). An attacker who can write to the database is only partly covered (section 3.7).

## 2. Credentials

Definitions are in `design.md` section 5 and `state-machine.md` section 3. Security properties:

- 256 bits of randomness per token from `crypto.getRandomValues`, each token an independent draw with no derivation between tokens. Brute force is infeasible.
- Only plain SHA-256 hashes are stored (ND-6). A database or backup reader cannot present a token. Because tokens are random and long, a fast hash gives no practical advantage to an attacker.
- Three types, each valid only where expected. The type comes from the stored record. A rematch capability cannot read a game. An access token cannot create a rematch. An invitation cannot play.
- Carried in `Authorization` headers or request bodies only, never in paths or query strings (C-1), so they do not enter proxy access logs, browser history or `Referer` headers.
- One authorisation point decides validity under the game lock for writes and in one snapshot for reads (R8.11, R8.12). The HTTP layer does no credential decisions.
- Rotation and revocation happen in one transaction under the game lock. A revoked token cannot authorise a later write.
- A rematch creates entirely new credentials. Old tokens never reach the new game.
- Invalid, unknown, revoked, consumed, wrong-type and deleted credentials all return the same `401 INVALID_CREDENTIALS`. A credential that would be accepted but belongs to an expired, not yet deleted game returns `410` (C-7), which discloses only that the holder once had valid access. Once the game is deleted, no record remains, and the response is `401`. Retaining credential records only to keep the `410` was rejected because it would keep data past the retention end.
- Admin token: separate header, separate listener (internal network only), SHA-256 hash in configuration, constant-time comparison.

### 2.1 Lost tokens (documented limitation, R8.9)

DuoCode has no accounts, no email and no independently verified identity. A bearer token is the only proof of who a player is. Therefore:

- A lost token cannot be recovered or re-issued, by the player or by the operator.
- A player with a lost token loses the seat. The opponent's side of the game is unaffected, and the game expires at its retention end.
- Any scheme that "restores" access without a second verified factor would let an attacker take over a seat.
- A token holder who suspects a leak can rotate while they still hold the token. After a leak the attacker holds the token too, so the first to rotate wins the seat. This is a limit of bearer tokens without accounts.
- The limitation is stated in the OpenAPI description and in `docs/API.md`.
- Rotation replay (next section) is not a recovery mechanism. It helps only the holder of the old token and the original key during a short window.

### 2.2 Idempotent rotation: security implications (ND-4)

Problem: a rotation commits on the server, the response is lost, and the client holds only a revoked token. Without a remedy the player is locked out by a network failure.

Mechanism (`state-machine.md` section 3.1): rotation requires an `Idempotency-Key`. For `ROTATION_REPLAY_SECONDS` (default 600 s, RD-3) the server will, on receipt of the revoked old token plus the same key and fingerprint, return the same new token again. The new token is held during the window as AES-256-GCM ciphertext.

Implications:

| # | Implication | Assessment |
|---|---|---|
| 1 | The revoked token keeps a narrow power for the window: it can fetch the new token. | The replay needs the old token **and** the 128-bit key. A thief who holds only the old token (the case rotation is meant to cure) cannot replay unless the thief also saw the key. The key travels in the same request as the token, so an attacker able to read the rotation request (a TLS break or a compromised client) already has both. Then rotation protects nothing, with or without replay |
| 2 | The server briefly stores a new token in recoverable form. | Encrypted with the key ring, bound by AAD to game, player and rotation id. A database-only reader cannot use it. A reader with database and key ring access can read it during the window. Cleared by cleanup after the window (at most window plus one cleanup interval). Outside the window the replay rule refuses, even if the ciphertext still exists |
| 3 | The first rotator wins. | If an attacker with a stolen token rotates before the owner, the attacker gets the seat, and the owner's later rotation fails (`401`). Replay does not change this. It is inherent to bearer tokens without accounts |
| 4 | The attacker can still replay for the owner's rotation. | Only with the key. See 1 |
| 5 | Lost response and lost window. | After the window the seat is lost. Clients should persist the old token and the key before sending, retry promptly and retry with backoff |
| 6 | Replay must not become an oracle. | A wrong key, wrong token or elapsed window all give the same `401`. Replay does not modify state or extend retention |
| 7 | Rate limiting. | `tok:rotate` bucket, small capacity (`deployment.md` section 4) |
| 8 | Keys in logs. | `Idempotency-Key` is never logged for rotation (R13.2) |
| 9 | Interaction with rematch capability. | Rotation revokes the player's unused capability (R8.6), because a thief could have minted one before rotation |
| 10 | Window length. | Longer windows help clients with long outages but extend exposure in 2. 10 minutes is proposed (RD-3) |

Alternatives rejected: client-generated tokens (clients may generate weak tokens, violating ND-6), a two-phase confirm-on-first-use rotation (leaves both tokens live for an unbounded time and writes on reads), and no replay (locks players out on network faults).

## 3. Secret-code and guess encryption (OD-6, ND-7, ND-9)

### 3.1 ND-7 assessment: encrypting guesses

Objective: someone with database-only access must not be able to reconstruct secret codes from stored guesses and feedback.

Before (revision 2): `guesses` held plaintext guesses. A solving guess equals the opponent's code, and any guess plus feedback narrows the code. Encrypting only `secret_codes` gave a database reader the code of every solved challenge and strong hints for the others.

After (revision 3): guesses are AES-256-GCM ciphertext. The database reader sees `guess_number`, `exact`, `misplaced`, the generated `solved` flag, timestamps and ciphertext. The 4 bytes of the guess are not recoverable without the key. Feedback counts alone do not identify the code: the same sequence of counts is compatible with many codes, and the reader does not know the guesses that produced them.

What the reader still learns: how many guesses each player used, the feedback counts, whether and when a player solved (this is also visible to the opponent through the API, OD-3), and timing. The `solved` flag is a function of `exact = 4`. None of these reveal the code.

Hidden traps found and fixed during the assessment:
- Request fingerprints for idempotency were plain SHA-256 hashes of the request body. One of 1296 possible guesses can be recovered from its hash in microseconds. They are now HMAC-SHA-256 keyed from the key ring (RD-8). Rotation fingerprints contain only random identifiers and stay plain SHA-256.
- `idempotency_keys.response_body` holds feedback and counts only, never the guess.
- The progress response to the owner contains their own guesses, so guess decryption is needed in the progress path. The status response does not.

Implementation implications:

| Area | Implication |
|---|---|
| Schema | `guesses.guess_ciphertext` (32 bytes) and `key_id` replace the plaintext array. Symbol and length checks move to the application. Guess numbers, feedback counts and the generated `solved` flag stay in plaintext so database constraints still enforce guess limits, contiguity and "no guess after solved" (`database-schema.md` section 3) |
| Decrypt paths | Guess submission (opponent's code), progress (caller's own guesses, at most 10), results (both codes and up to 20 guesses), rotation replay. Status, join, code submission, mint, rematch and cleanup never decrypt |
| Performance | AES-GCM over 4 bytes is microseconds. The cost is a few `crypto.subtle` calls. Derived keys are imported once per process (non-extractable `CryptoKey`). Expected impact on p95 latency is negligible and is measured in the load test (R17.4) |
| Idempotency | Guess replay compares fingerprints (keyed). It does not need to decrypt the stored guess |
| Re-encryption | The task re-encrypts guesses and re-computes guess fingerprints along with secret codes. More rows per game (at most 22 ciphertexts and 20 fingerprints), still one transaction per game |
| Nonce budget | About 22 encryptions per game (2 codes, up to 20 guesses) plus rotation tokens and re-encryption passes. See 3.3 |
| Integrity | Feedback counts and guess number are in the AAD, so a database writer cannot change them without detection when the row is decrypted (section 3.7) |
| Tests | Plaintext-at-rest scans cover `secret_codes` and `guesses`. Tamper tests cover both. Simulator behaviour unchanged (it uses the API) |
| Operations | Key loss now also destroys guesses. Results of completed games lose codes and guesses. Outcomes and counts survive (they are plaintext) |
| Debugging | Operators cannot read guesses from the database. This is intended |

### 3.2 Scheme

- Algorithm: AES-256-GCM (Web Crypto `AES-GCM`, 128-bit tag).
- Keys: each ring entry holds 32 bytes of key material. Two working keys are derived per entry with HKDF-SHA-256: `duocode/enc/v1` for AES-GCM and `duocode/mac/v1` for HMAC fingerprints. Material is never used directly for both.
- Plaintexts: a code or guess is four bytes (symbols 1 to 6). A rotated token is its 47-byte string.
- Stored form: `nonce(12) || ciphertext || tag(16)`, so 32 bytes for codes and guesses and 75 bytes for tokens. Lengths are fixed and leak nothing about the plaintext.
- Decryption failure (bad tag, unknown key id) returns `500 INTERNAL_ERROR` with no detail, logs the event without any value, and increments an alert metric. The system never falls back to another key or to plaintext.

### 3.3 Key identifiers and nonce uniqueness (CL-3)

- **Key identifiers.** Small positive integers, assigned in increasing order, never reused. Every ciphertext row stores the `key_id` that encrypted it. Fingerprint rows store `fingerprint_key_id`. The identifier is part of the AAD, so changing it makes decryption fail.
- **Nonces.** 96 bits from `crypto.getRandomValues`, fresh for every encryption, including every re-encryption. Uniqueness is probabilistic. Under NIST SP 800-38D the limit for random 96-bit nonces under one key is 2^32 encryptions. With about 22 encryptions per game, one million games use about 2 × 10^7 encryptions, well below the limit. The vault counts encryptions per key id (metric `duocode_encryptions_total{key_id}`) and an alert fires at 2^28 so the key is rotated long before the bound (R10.10, RD-10). Reuse of a nonce under one key would break confidentiality and authenticity for the affected rows, which is why the alert threshold is conservative.
- **Never deterministic.** Two encryptions of the same plaintext always differ.

### 3.4 Authenticated additional data (AAD)

AAD is the concatenation of: an ASCII purpose label, a zero byte, the `key_id` as 2 bytes big-endian, the 16 raw bytes of `game_id`, the 16 raw bytes of `player_id`, then purpose-specific fields.

| Purpose | Label | Extra AAD fields |
|---|---|---|
| Secret code | `duocode/code/v1` | none |
| Guess | `duocode/guess/v1` | `guess_number` (1 byte), `exact` (1 byte), `misplaced` (1 byte) |
| Rotated token | `duocode/rotation/v1` | `rotation_id` (16 bytes) |

A ciphertext moved to another row, game, player or guess number fails authentication. Altering feedback counts in the database is detected when the guess is decrypted.

### 3.5 Handling of decrypted values (R10.7, R10.8)

- Decryption happens in the persistence layer's vault. The engine contains no cryptography and receives plaintext codes and guesses as arguments.
- `vault.use(row, fn)` passes the plaintext to `fn`, clears the buffer afterwards, and returns only what `fn` returns. Guess code returns feedback only.
- The wrapper type redacts under `JSON.stringify`, `toString` and `Deno.inspect`, so accidental logging prints `[REDACTED]`.
- Exceptions raised inside `fn` are replaced by a generic error with no message content from `fn`, then rethrown.
- JavaScript cannot guarantee memory erasure. Clearing buffers reduces the window. Copies may remain until garbage collected. This is a known runtime limit.
- Results requests check `COMPLETED` in the same snapshot before any decrypt call (R7.5).

### 3.6 Key management (ND-9)

**Key ring.** A JSON file mounted as a Docker secret, readable only by the application user:

```json
{ "version": 1, "active": 2,
  "keys": {
    "1": { "key": "<base64 32 bytes>", "status": "DECRYPT_ONLY", "createdAt": "2026-11-21T00:00:00Z" },
    "2": { "key": "<base64 32 bytes>", "status": "ACTIVE",       "createdAt": "2027-06-01T00:00:00Z" } } }
```

- Exactly one key is `ACTIVE`. Older keys needed for existing ciphertext or restorable backups are `DECRYPT_ONLY`.
- The file lives outside the PostgreSQL container and the database volume. Database backups never include it.
- The path comes from `CODE_KEYRING_FILE`. Key material is never placed in environment variables, migrations, images, logs or the repository. `.gitignore` excludes `secrets/`.
- At start-up the application loads the ring, validates each key is 32 bytes and statuses are consistent, encrypts and decrypts a self-test value with the active key, and refuses to start on any failure. `/healthz` reports not ready without a loaded ring.
- Application instances and the `cleanup` and re-encryption tasks all mount the same ring. The `db` and `backup` services never mount it.

**Generation.** `deno task keys:generate` prints a new random 32-byte key in base64 and the next free key id. The operator adds it to the ring file. The command writes nothing into the repository.

**Backup of the ring.**
- Back up the ring file (all keys, including `DECRYPT_ONLY` ones) separately from database backups, in storage that does not share credentials with database backups. Each founding collaborator holds an encrypted copy (for example an age or GPG-encrypted file or a password-manager attachment).
- Update the key backup whenever the ring changes, before the new key is made active in production.
- A ring backup is kept at least as long as any database backup that may contain ciphertext under any key in it (R10.11).
- Two people can recover the ring. Nobody keeps the only copy.

**Recovery (database restore).** See also `deployment.md` section 6.
1. Restore the database backup into a clean database.
2. Obtain the ring backup that covers the backup date. It must contain every `key_id` referenced by the restored data.
3. Run `deno task keys:verify` against the restored database and the ring. It lists the distinct `key_id` and `fingerprint_key_id` values, confirms each is in the ring, and test-decrypts every ciphertext row (R10.12).
4. Only then start the application, run cleanup, and accept traffic.
5. If a needed key is missing, the rows under it are unrecoverable. Affected games cannot be played or shown. Their outcomes and counts survive. Games that finished remain deletable by cleanup.

**Rotation (planned, routine, for example annually or on staff change; mandatory at 2^28 encryptions).**
1. Generate a new key. Add it to the ring as a new id. Back up the ring (new copy).
2. Deploy the ring with the new key `ACTIVE` and the previous key `DECRYPT_ONLY`. New writes use the new key. Existing rows still decrypt because each row names its key.
3. Run `deno task reencrypt` (R10.5), see 3.8. Record the completion date D.
4. Verify no row references the old key with `keys:verify`.
5. Retire the old key (3.9) no earlier than D + 35 days.

**Compromise response.** If a key may have leaked:
1. Treat all data encrypted under it as exposed to whoever holds a copy of the database or backup made while the key existed.
2. Generate a new key and rotate immediately (steps 1 to 4 above).
3. Decide with the owners whether to expire in-progress games early (shorten retention and run cleanup) to remove exposed codes sooner. This is a business decision, not made here.
4. The compromised key stays `DECRYPT_ONLY` while any backup under it exists, because deleting it would make those backups unrestorable. Mark it compromised in the operations log and keep it out of the active path. Backups under it should be destroyed if the owners judge the exposure unacceptable, and then the key can be destroyed sooner than 35 days. This trade-off is for the owners.
5. If a token (access, admin, rate-limit HMAC) may have leaked, rotate that secret separately. Tokens leaked from a database dump are hashes and cannot be presented.
6. Review logs and metrics for the exposure period using the allow-listed fields only.

### 3.7 Integrity against a database writer

A database writer cannot read codes or guesses. Such an attacker can still delete or reorder rows, alter plaintext columns (`players.solved`, `players.guesses_used`, `games.state`, `game_results`), or replay older ciphertexts for the same row. AAD binding prevents copying ciphertext between rows and detects altered feedback counts and guess numbers when a guess is decrypted. It does not protect plaintext state columns. Defence is access control on the database, not cryptography, and the database user of the application is the only account with write rights. This is recorded as a residual risk.

### 3.8 Transactional re-encryption (R10.5)

`deno task reencrypt`:
1. Select games with `FOR UPDATE SKIP LOCKED` that have at least one row whose `key_id` or `fingerprint_key_id` differs from the active id, in batches.
2. For each game, in one transaction under the game lock: decrypt each of its ciphertexts with the row's key, encrypt with the active key and a fresh nonce (AAD recomputed with the new `key_id`), re-compute guess fingerprints from the stored envelope inputs, update the rows. The guess fingerprint input is rebuilt from the decrypted guess, the operation name and the game id.
3. Commit. A crash leaves the game fully old or fully new. A game is never half-migrated.
4. Live traffic is safe: writes to that game wait on the same lock or are skipped by the task, and reads in a snapshot see the old state and the old key, which is still in the ring.
5. Safe to repeat. A second run finds nothing to do. It logs counts only.
6. Clears expired token ciphertext as part of the run when it meets it. Active rotation ciphertext is re-encrypted like any other.

### 3.9 Key retirement (R10.11)

A key is removed from the ring only when all of these hold:
1. `keys:verify` shows no row in `secret_codes`, `guesses`, `idempotency_keys` or `token_rotations` references it.
2. At least `BACKUP_RETENTION_DAYS` (35) have passed since re-encryption finished, so every backup that contains data under the key has expired and been deleted.
3. No retained key backup is needed for restoring any database backup that still exists.
4. The ring backup is updated, and the retired key is destroyed from the ring copies after the same retention.

Until then the key stays `DECRYPT_ONLY`. A compromised key may be retired earlier only by an explicit owner decision (3.6, compromise step 4).

## 4. Logging, metrics and diagnostic rules (OD-2, R13.2, R13.8, R13.9)

Never written to logs, metrics labels, traces, crash reports, health output or error responses:

- Secret codes (own or opponent's), guesses, decrypted values, ciphertext, nonces, fingerprints, key ring contents, rate-limit HMAC key.
- Request and response bodies of code, guess, rotation and rematch endpoints.
- Credentials in any form: `Authorization` header, `X-Admin-Token`, token strings, token hashes, invitation tokens in bodies, rotation and guess idempotency keys.
- Nicknames, error messages that echo them, and client IP addresses (the application never writes them).
- Database parameters. Query logging is disabled, and database errors are mapped to generic errors before leaving the persistence layer.

Allowed in logs: time, level, request id, route template (not the raw path), status, duration, error code, operation name, game id (an identifier, not a credential) where useful for support, counts.

Metrics are aggregate counters, gauges and histograms. Allowed labels come from bounded sets: route template, status class, error code, operation, rate-limit scope, key id. Forbidden labels and values: game id, player id, nickname, IP address, token or anything derived from them. This keeps the metrics endpoint safe to share with a monitoring system.

Mechanisms:
- Request and response bodies are never logged. Headers are logged from an allow-list only.
- A central error mapper builds responses from error codes and fixed messages. It never interpolates request values (R12.5).
- Deno process permissions are minimal (`--allow-net`, `--allow-read` for the key ring and application directory, `--allow-env` for named variables). Crash dumps are disabled in the container.
- Canary tests (`test-strategy.md`, TS-SEC) submit distinctive code, guess, nickname and token values and assert their absence from captured logs, metrics output and error bodies.
- The proxy access log format excludes headers and query strings and rotates after a fixed period (`deployment.md`).

## 5. Threats and mitigations

| # | Threat | Mitigation | Residual |
|---|---|---|---|
| T1 | Opponent reads the secret code during play | No endpoint returns any code before `COMPLETED`. Results check state in the same snapshot before decrypting. Tests assert absence in every response. Own code is never echoed (OD-2) | Low |
| T2 | Impersonation of a player | 256-bit tokens, hashed storage, acting player derived from token, game id must match the credential's game | Token theft by other means (device compromise) |
| T3 | Token guessing | 256-bit entropy. `ip:authfail` throttle and proxy limits. Uniform `401` | Negligible |
| T4 | Token leaks through URLs or logs | Tokens only in headers and bodies. Log rules in section 4 | Client-side leaks |
| T5 | Using an old or revoked token after rotation | `authorise` under the game lock for writes. One snapshot for reads. Replay only for the same key inside the window | A read that began before the commit may finish (bounded by request duration). Section 2.2 |
| T6 | Cross-game or cross-type token use | Credential bound to one game by composite foreign key and to one type. Rematch game has fresh credentials | None identified |
| T7 | Brute-forcing the 1296-code space | Hard cap of 10 guesses enforced by service and constraints. Guessing needs a valid token. Rate limits | A player can still win by luck. Intended |
| T8 | Exceeding attempts by racing or retrying | Game lock, idempotency keys, guess-number and previous-guess constraints | None identified |
| T9 | Replay or tampering of an idempotent request | Keyed fingerprint compare over RFC 8785 form, `409` on mismatch, key scoped per player and operation | None identified |
| T10 | Duplicate completion or double result | Game lock. `game_results` primary key. State check | None identified |
| T11 | Enumeration of game ids or invitations | Unknown game and invalid invitation return identical `404`. Credential failures identical `401` | Timing differences are limited by constant-shape queries, not proven equal |
| T12 | Database-only read or backup read | Tokens hashed. Codes and guesses AES-256-GCM encrypted with a key outside both. Fingerprints keyed | Plaintext feedback counts, nicknames and solved flags (section 3.1). Host compromise exposes key and data |
| T13 | Key theft or loss | Key file outside DB and backups, restricted permissions, separate backup held by two people, rotation, retirement and recovery procedures (section 3.6) | Host compromise exposes the key and the data together. Loss of all copies is unrecoverable |
| T14 | Ciphertext swapping or feedback tampering | AAD binds game, player, key id, and for guesses the number and feedback. Tamper tests | A database writer can still alter plaintext state columns (section 3.7) |
| T15 | Secret code or guess in logs, errors, crash output | Section 4. Redacting type. Canary tests. No body logging | Runtime memory residue |
| T16 | SQL injection | Parameterised queries only. Typed validation of all input | Low |
| T17 | Oversized or malformed input | Body limit, strict JSON schema, unknown and duplicate properties rejected, nickname rules (R1.3) | Low |
| T18 | Denial of service | Proxy limits, shared PostgreSQL token buckets, request timeouts, lock timeouts, pool limits, bounded cleanup batches | Volumetric attacks need provider-level protection. Rate-limit table is a write hot spot under flood (mitigated by Caddy) |
| T19 | Administrative abuse | Separate admin token, separate internal listener not routed by the proxy, constant-time compare | Admin token compromise allows cleanup and metrics only. No game data access |
| T20 | Cleanup deleting live data | Expiry `>=` re-check on locked row, `SKIP LOCKED`, dry run, batch size | Misconfigured TTLs. Configuration validated at start-up |
| T21 | Data kept longer than stated | `expires_at` retention clock, hourly cleanup service, backups at most 35 days (ND-8) | Deleted data persists in backups until they expire. A restore resurrects deleted data until cleanup runs (`deployment.md` section 6) |
| T22 | Dependency compromise | Pinned and locked dependencies, minimal Deno permissions, CI dependency review | Supply-chain risk remains |
| T23 | Seat takeover through a "recovery" flow | No recovery flow exists (section 2.1) | Lost token means lost seat |
| T24 | Rematch hijack by a third party | Capability needs an access token to mint. Rotation revokes it. One rematch per game. Only the presenting player gets seat 1 credentials. Invitation delivered by the creator out of band | Anyone given the invitation can take seat 2, as with any invitation |
| T25 | Weak randomness | Only `crypto.getRandomValues` and `crypto.randomUUID`. `Math.random` banned by lint rule outside the simulator | None identified |
| T26 | Rotation replay abuse | Needs old token and key, short window, encrypted storage, same `401` outside the rule (section 2.2) | First rotator wins, window exposure |
| T27 | Nonce reuse | Random 96-bit nonces, counter and alert at 2^28 per key, rotation (section 3.3) | Negligible at expected volume |
| T28 | IP-based rate limit evasion or abuse of forwarded headers | Forwarded IP trusted only from `TRUSTED_PROXY_CIDRS`. Credential buckets keyed by token hash | Shared NAT users share limits. Attackers with many IPs |
| T29 | Rate-limit data as personal data | Stores HMAC of IP with a secret, not the address. Rows deleted after an hour idle | HMAC key compromise allows IP confirmation for known addresses |
| T30 | Restore reverts credential state | Documented procedure, RD-7. Rate-limit table cleared, cleanup run, tokens rotated after backup are reset | Players who rotated after the backup lose their seat. Revoked tokens revive |
| T31 | Stale or missing key at restore | `keys:verify` before traffic. Ring backup covers backup retention (3.6, 3.9) | Missing key means unrecoverable data |
| T32 | Race between expiry and operations | Single reference time, `>=` rule, lock | None identified |

## 6. Privacy (R13.4, R13.7)

- No accounts, email addresses or real identity. Nicknames are free text and might contain personal data. The privacy notice says so.
- Nicknames are visible only to the two players of that game.
- The application writes no client IP address. The rate limiter stores an HMAC of the IP. The proxy writes no IP in its access log by default (`deployment.md`), and if the owners enable it for abuse investigation, a retention period must be set.
- Retention and deletion follow R11 and `database-schema.md`. A game is deleted at its retention end, with nicknames, codes, guesses and credentials. Backups hold deleted data for at most 35 days.
- There is no player-initiated deletion endpoint in MVP 1 (ND-8). A holder of a bearer token proves control of a seat, not an identity.
- Metrics and logs are privacy-safe (section 4).
- UK GDPR review items for the owners: lawful basis statement, privacy notice text, data processor arrangements for the VPS provider, backup retention wording. They are tasks, not decided here.

## 7. Review checklist for owners (gate 1.5)

1. Confirm the lost-token limitation wording (section 2.1).
2. Review the rotation implications table (section 2.2) and RD-3 (window, capability revocation).
3. Review the ND-7 assessment (section 3.1), in particular the plaintext feedback counts and the keyed fingerprints (RD-8).
4. Review key management, backup, recovery, rotation, retirement and compromise procedures (sections 3.6 to 3.9) and `deployment.md` sections 5 and 6.
5. Review the log and metrics rules (section 4).
6. Review the threat table, especially T5, T12, T13, T21, T26, T30.
7. Confirm RD-7 (restore reverts credential state) and RD-9 (IP handling).

## 8. Residual risks summary

- Plaintext feedback counts, nicknames and state flags remain readable by a database reader.
- Runtime cannot guarantee erasure of decrypted values.
- A host compromise exposes both key and database.
- A database writer can alter plaintext state columns.
- Lost tokens are lost seats. First rotator wins.
- Rotation replay window exposes the new token, encrypted, for up to 10 minutes plus one cleanup interval.
- Deleted data lives in backups for up to 35 days. A restore revives deleted data and rolled-back tokens until cleanup and procedures run.
