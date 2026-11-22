# DuoCode Security Assessment (revision 3.1, final for gate review, strict hard-stop correction)

Owns: threats and mitigations, credential security, rotation implications, encryption and key management, logging and metrics rules, residual risks. Related: `requirements.md` (R3, R5, R8, R10, R13, R20, R21), `design.md` (credential model, authorisation point, vault, lock ordering), `database-schema.md` (storage), `state-machine.md` (credential lifecycle, idempotent rotation), `../../../openapi/openapi.yaml` (error behaviour), `deployment.md` (secrets, proxy, backups, restore).

Status: draft for owner review (Phase 1 gate 1.5). Nothing here is signed off.

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

Mechanism (`state-machine.md` section 3.1): rotation requires an `Idempotency-Key` that is a **version 4 UUID from a cryptographically secure random source** (122 random bits), because here the key is also the replay secret. For `ROTATION_REPLAY_SECONDS` (600 s, approved RD-3) the server will, on receipt of the revoked old token plus the same key and fingerprint, return the original response, the same new token, again. The new token is held during the window as AES-256-GCM ciphertext. **A replay does not restore, reactivate or un-revoke the old token**: it changes no stored row, and the old token still receives `401` on every other operation.

Implications:

| # | Implication | Assessment |
|---|---|---|
| 1 | The revoked token keeps a narrow power for the window: it can fetch the new token. | The replay needs the old token **and** the 128-bit key. A thief who holds only the old token (the case rotation is meant to cure) cannot replay unless the thief also saw the key. The key travels in the same request as the token, so an attacker able to read the rotation request (a TLS break or a compromised client) already has both. Then rotation protects nothing, with or without replay |
| 2 | The server briefly stores a new token in recoverable form. | Encrypted with the key ring, bound by AAD to game, player and rotation id. A database-only reader cannot use it. A reader with database and key ring access can read it during the window. Cleared by cleanup after the window (at most window plus one cleanup interval). Outside the window the replay rule refuses, even if the ciphertext still exists |
| 3 | The first rotator wins. | If an attacker with a stolen token rotates before the owner, the attacker gets the seat, and the owner's later rotation fails (`401`). Replay does not change this. It is inherent to bearer tokens without accounts |
| 4 | The attacker can still replay for the owner's rotation. | Only with the key. See 1 |
| 5 | Lost response, then lost window. | Inside the window the retry succeeds. **After the window, if the replacement token was never stored by the client, the seat is lost permanently.** The server has deleted its copy, the old token is revoked, and nothing can restore either. The opponent and the game are unaffected and the game expires at its retention end. Clients must persist the old token and the key before sending, persist the new token on arrival, and retry promptly with backoff |
| 6 | Replay must not become an oracle. | A wrong key, wrong token or elapsed window all give the same `401`. Replay does not modify state or extend retention |
| 7 | Rate limiting. | `pl:rotate` bucket keyed by player, small capacity (`deployment.md` section 4.2). Rotating does not reset it |
| 8 | Keys in logs. | `Idempotency-Key` is never logged for rotation (R13.2) |
| 9 | Interaction with rematch capability. | Rotation revokes the player's unused capability (R8.6), because a thief could have minted one before rotation |
| 10 | Window length. | Longer windows help clients with long outages but extend exposure in 2. 10 minutes is approved (RD-3) |
| 11 | Key entropy. | A guessable key would let a holder of the old token replay. The key must be UUIDv4 from a CSPRNG (122 bits). The server rejects other UUID versions and malformed values, but cannot verify the source of randomness. The requirement is stated in the OpenAPI document and `docs/API.md`. Guess keys use the general any-version UUID rule because they are only labels |
| 12 | Replay is not a second authorisation path. | The old token is accepted only by the rotation operation, only with the matching key, and only inside the window. A test asserts the old token fails every other operation after a replay (TS-CRED) |
| 13 | Decrypted credential in a response. | The replay response contains the decrypted replacement token. This is the narrow third exception approved as RD-11, separate from the two game-data exceptions in section 3.5. It applies only when all five conditions hold (old token, original UUIDv4 key, matching fingerprint, valid window, replacement token not revoked). The token is never written to a log, diagnostic, metric, trace or error response, and a canary test checks that (TS-SEC) |

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
- **Nonces.** 96 bits from `crypto.getRandomValues`, fresh for every encryption, including every re-encryption. Uniqueness is probabilistic, so it needs a per-key budget (RD-10, section 3.3a).
- **Never deterministic.** Two encryptions of the same plaintext always differ.

### 3.3a Nonce budget, rotation thresholds and the usage counter (RD-10, RD-13, CR-9)

**Terms.** A *reserved unit* is one permitted encryption, counted in the key's total `R`. An *encryption invocation* is one actual encryption and consumes one reserved unit. An *allowance* is the reserved units an instance holds unconsumed, and is part of `R`. The thresholds below apply to `R`. Because `R >= invocations` always, a limit on `R` is a limit on invocations.

Facts: random 96-bit nonces with AES-GCM. The probability that any two of `n` encryptions under one key share a nonce is about `n² / 2^97`. NIST SP 800-38D allows at most `2^32` invocations per key with random nonces, which bounds that probability at `2^-32`.

| Policy point | Encryptions under one key | Collision probability `n² / 2^97` | Margin against the NIST target of 2^-32, in probability | Margin in count against 2^32 |
|---|---|---|---|---|
| NIST maximum | 2^32 | 2^-33 | 2× | 1× |
| Hard stop (refuse to encrypt) | 2^30 | 2^-37 | 32× | 4× |
| Rotation required by | 2^28 | 2^-41 | 512× | 16× |
| Warning | 2^27 | 2^-43 | 2048× | 32× |

Rationale:
- At about 22 encryptions per game (2 codes, up to 20 guesses), 2^28 is about 12 million games per key. A new key per year or per 2^28 encryptions, whichever comes first, is far beyond the expected volume, so the threshold costs nothing in practice and gives a wide safety margin.
- Re-encryption counts too: every row it rewrites is a new encryption under the new key.
- The three points give time to react: the warning prompts planning, the rotation point makes rotation mandatory, and the hard stop makes the application fail closed before the limit rather than silently exceed it.

**Mechanism (RD-13 and CR-9): durable reservations against one authoritative counter, with a strict hard stop.** The full specification is `database-schema.md` section 6.2. In brief:

1. One row per key holds `R`. A single atomic statement grants a positive whole number of blocks only if `R + units <= hard stop`: `UPDATE key_usage SET reserved = reserved + units WHERE key_id = k AND NOT sealed AND units > 0 AND reserved + units <= hard_stop RETURNING reserved`. No row returned means refused, with no change. A zero or negative request matches no row, so the counter can never go down, and an operation that needs many units gets as many whole blocks as it needs in one statement.
2. The statement runs in its own autocommit transaction on a separate connection, before the request transaction. A reservation is therefore never rolled back with an application transaction.
3. An instance adds the units to its in-memory allowance only after the statement returns. Before an operation's transaction it atomically **claims** the units it may need from the allowance, and returns what it did not use. Each encryption invocation consumes one claimed unit, and the vault refuses to encrypt with none. If no units can be obtained, the operation is not rejected at once: it still answers replays, conflicts and rule rejections normally, and ends with `503` only where a fresh encryption is needed, before anything is written (a rotation replay needs no encryption, so a lost rotation response is never turned into a lockout by an exhausted key).
4. A database `CHECK (reserved <= 2^30)` is an absolute backstop independent of application configuration.

**Why the hard stop is strict, and why the 32 shards were replaced.** With shards, each reservation updated one shard row, and the total across shards was read separately. Two instances working on different shards could both see room below the limit and both reserve, and instances already holding allowances kept encrypting after another instance saw the limit exceeded. The draft therefore only approximated the limit, up to one block per instance. The single row removes the race: PostgreSQL's row lock serialises every reservation under the key, and a waiting update re-evaluates its `WHERE` clause against the latest committed `R` before changing anything, so two instances cannot both be granted the last block. Allowances are inside `R` by construction, because a unit enters an allowance only after it was added to `R`. So the number of invocations is at most the number of units ever reserved, which is at most 2^30. Contention is one statement per 1024 encryptions per instance on one row, which is not significant at DuoCode's expected volume. Correctness was chosen over parallelism.

**Guarantees:**
- *Cannot be rolled back with the application transaction:* the reservation is committed independently, earlier.
- *Accounts for every invocation, including failed or rolled-back transactions:* invocations consume reserved units regardless of the transaction outcome.
- *No underestimate:* an encryption needs a unit, a unit needs a committed reservation, so `R >= invocations`. Crashes, restarts and unknown outcomes only add unused units, so the counter may overestimate. That is acceptable and safe.
- *Strict global limit:* `R <= 2^30` always (statement guard plus `CHECK`), with several instances, concurrent reservations, and instances holding outstanding allowances.
- *No encryption without a unit:* an exhausted allowance stops encryption until a reservation is granted, and at the hard stop none is.

**Threshold behaviour** (exact):

| Threshold | Behaviour |
|---|---|
| 2^27 reserved units | Warning metric, one operational warning per key per process start, admin health state `warning`. Reservations continue. The public `/healthz` is not affected |
| 2^28 reserved units | The key is `ROTATION_OVERDUE`: critical alert, admin health state `degraded` (the public `/healthz` stays `ok`). Rotation is mandatory. **Reservations under the key continue to be granted until the hard stop** (RD-14, approved), so a late rotation is not an outage. Rotating makes the old key `DECRYPT_ONLY` and seals it, after which no reservation under it is granted |
| 2^30 reserved units | Hard stop. A block that would take `R` above 2^30 is refused, so `R` never exceeds 2^30. `R` can equal 2^30 exactly. No further encryption occurs under the key once instances have consumed the units they already hold. Encrypting operations fail closed with `503`. Decryption is unaffected |

**Limit of the mechanism, and the restore rule (RD-13).** The invariant holds for the live database. If the database is restored from an earlier backup, the `key_usage` row goes back in time too, and `R` may be lower than the encryptions really performed under the key after the backup. Ciphertexts from that period may survive elsewhere (the lost database, older backups, copies held by an attacker), so the nonce budget cannot be assumed unspent. The restore procedure therefore always: generates a new key and makes it the only `ACTIVE` key; **seals every older key** (sets its counter to 2^30, so any reservation under it is refused even if the ring were mistaken); and restarts all instances so every in-memory allowance is discarded. This happens before traffic is accepted, unless the restore is proved lossless (pre-restore counters not above restored counters). The previous key becomes `DECRYPT_ONLY`, stays in the ring so existing data decrypts, and never becomes `ACTIVE` again. The ring file lives outside the database and is not rolled back by a restore, so it keeps the new key and the old key's `DECRYPT_ONLY` status (`deployment.md` section 6.1).

A further guard: `keys:verify` checks that the number of ciphertext rows under each key does not exceed its reserved total. A violation is evidence of a rolled-back or corrupted counter and fails verification.

Configuration: `KEY_USAGE_WARN`, `KEY_USAGE_ROTATE_BY`, `KEY_USAGE_HARD_STOP` (at most 2^30, a multiple of the block), `KEY_USAGE_BLOCK` (`design.md` section 13).

### 3.4 Authenticated additional data (AAD)

AAD is the concatenation of: an ASCII purpose label, a zero byte, the `key_id` as 2 bytes big-endian, the 16 raw bytes of `game_id`, the 16 raw bytes of `player_id`, then purpose-specific fields.

| Purpose | Label | Extra AAD fields |
|---|---|---|
| Secret code | `duocode/code/v1` | none |
| Guess | `duocode/guess/v1` | `guess_number` (1 byte), `exact` (1 byte), `misplaced` (1 byte) |
| Rotated token | `duocode/rotation/v1` | `rotation_id` (16 bytes) |

A ciphertext moved to another row, game, player or guess number fails authentication. Altering feedback counts in the database is detected when the guess is decrypted.

### 3.5 Handling of decrypted values (R10.7, R10.8, CR-1)

Permitted API serialisation of decrypted game data, exactly two cases:
1. **Progress:** a player receives their own guesses and feedback through their authenticated progress endpoint.
2. **Results:** both players' codes, guesses and feedback through the authenticated results endpoint, only once the game is `COMPLETED`.

Also decrypted but not serialised as game data: the opponent's code during guess submission (only feedback leaves), and the stored token in a rotation replay (a credential, RD-11).

Prohibited without exception: decrypted values in logs, diagnostics, metrics, traces, error responses, crash output and any persistent plaintext storage (including stored idempotency responses and any database column other than the ciphertext columns).


- Decryption happens in the persistence layer's vault. The engine contains no cryptography and receives plaintext codes and guesses as arguments.
- `vault.use(row, fn)` passes the plaintext to `fn`, clears the buffer afterwards, and returns only what `fn` returns. Guess code returns feedback only.
- The wrapper type redacts under `JSON.stringify`, `toString` and `Deno.inspect`, so accidental logging prints `[REDACTED]`.
- Exceptions raised inside `fn` are replaced by a generic error with no message content from `fn`, then rethrown.
- JavaScript cannot guarantee memory erasure. Clearing buffers reduces the window. Copies may remain until garbage collected. This is a known runtime limit.
- Results requests verify `COMPLETED` in the same snapshot before any ciphertext is read or decrypted. The vault's results method requires a `CompletedGame` value that only that check can create, and a repository spy test asserts zero ciphertext reads for a game that is not completed (R7.5, TS-ENC).

### 3.6 Key management (ND-9)

**Key ring.** A JSON file mounted as a Docker secret, readable only by the application user:

```json
{ "version": 1, "generation": 7, "highestKeyId": 3, "active": 2,
  "fingerprintHistory": { "1": { "fp": "<hex sha-256>", "state": "REGISTERED" }, "2": { "fp": "<hex sha-256>", "state": "REGISTERED" }, "3": { "fp": "<hex sha-256>", "state": "REGISTERED" } },
  "keys": {
    "1": { "key": "<base64 32 bytes>", "selfTest": "<base64 known-answer ciphertext>", "status": "DECRYPT_ONLY", "createdAt": "2026-11-21T00:00:00Z", "deactivatedAt": "2027-06-01T00:00:00Z" },
    "2": { "key": "<base64 32 bytes>", "selfTest": "<base64 known-answer ciphertext>", "status": "ACTIVE", "createdAt": "2027-06-01T00:00:00Z" },
    "3": { "key": "<base64 32 bytes>", "selfTest": "<base64 known-answer ciphertext>", "status": "STAGED", "createdAt": "2028-01-10T00:00:00Z" } } }
```

- Exactly one key is `ACTIVE`. A `STAGED` key is loaded and can decrypt but is never used to encrypt: it exists so that a new key can be on every instance before any instance writes with it (section 3.6, rotation). Older keys needed for existing ciphertext or restorable backups are `DECRYPT_ONLY`. A key that has been `DECRYPT_ONLY` never becomes `ACTIVE` again: when a key stops being active its `deactivatedAt` is set, and the application refuses to start if a key with `deactivatedAt` set is marked `ACTIVE`. `generation` increases with every change to the ring, so the newest copy can be identified.
- The file lives outside the PostgreSQL container and the database volume. Database backups never include it.
- The path comes from `CODE_KEYRING_FILE`. Key material is never placed in environment variables, migrations, images, logs or the repository. `.gitignore` excludes `secrets/`.
- **Key material and identifiers are never reused, even after retirement.** At load, each entry's material must match the fingerprint recorded in `fingerprintHistory` for its identifier, and before encrypting it must match `key_usage.fingerprint` (pre-encryption check and reservation statement), so a retired key cannot be pasted into an active entry to use that entry's counter (CR-14). The loader and `keys:generate` reject a ring in which two identifiers carry the same 32 bytes of key material (compared by fingerprint, never by printing the material), reject a new identifier that is not above `highestKeyId`, and reject new material whose fingerprint appears in `fingerprintHistory`. The history keeps the fingerprint (SHA-256 of a label and the key material, not reversible) of **every key ever registered, including retired ones**, and is never shortened, so removing a retired key from the ring does not make its material acceptable again. The same fingerprint is stored in `key_usage.fingerprint`, which is `UNIQUE` and never deleted, so the database refuses it too. The ring history also covers a restore that went back past the registration. Reusing material under a new identifier would give the same AES key a fresh counter and bypass its lifetime nonce budget, so it is treated as an error (CR-11, CR-12). `keys:verify` repeats the checks. The fingerprint history is backed up with the ring.
- **Start-up self-test does not encrypt.** At start-up the application loads the ring, validates each key is 32 bytes and statuses are consistent, and decrypts each key's `selfTest` known-answer value, which `keys:generate` encrypted once when it created the key (`keys:generate` registers the key, reserves at least one unit through the normal reservation statement, and only then encrypts it, so a new key's counter is at least 1). Because the self-test never encrypts, an instance can start when the active key is sealed or at the hard stop: it serves reads and decrypts existing data, and answers every request that needs a fresh encryption with `503`. It refuses to start on any ring failure. `/healthz` reports not ready without a loaded ring.
- Application instances and the `cleanup` and re-encryption tasks all mount the same ring. The `db` and `backup` services never mount it.

**Generation and ring changes (CR-15).** All ring changes (`keys:generate`, `keys:activate`, `keys:seal`, `keys:abandon`) run only in the dedicated `keymgmt` job (`deployment.md` section 2.1), never in `app` or `cleanup`. They **write key material directly into the protected ring source file** and never print it: output shows only the key identifier, status and the first 8 hex digits of the fingerprint. Logs, job output and error messages never contain key material. Every ring-changing operation is serialised by a single-writer lock (a PostgreSQL advisory lock held for the whole operation, including the ring backup) and writes the ring with a version check: it reads `generation`, writes a new file with `generation + 1`, and replaces the old file only if `generation` is still the one it read, otherwise it aborts and starts again. So two concurrent generators can never publish from stale snapshots and lose each other's history entries.

**Backup of the ring.**
- Back up the ring file (all keys, including `DECRYPT_ONLY` ones) separately from database backups, in storage that does not share credentials with database backups. Each founding collaborator holds an encrypted copy (for example an age or GPG-encrypted file or a password-manager attachment).
- Update the key backup whenever the ring changes, before the new key is made active in production.
- A ring backup is kept at least as long as any database backup that may contain ciphertext under any key in it (R10.11).
- Two people can recover the ring. Nobody keeps the only copy.

**Recovery (database restore).** See also `deployment.md` section 6. Before step 1, stop and drain every process that can encrypt (`app`, `cleanup`, `reencrypt` and any key job), so no allowance or counter changes during the restore and any lossless comparison.
1. Restore the database backup into a clean database.
2. Obtain the **newest** ring (highest `generation`) and its `highestKeyId`, never a ring from the database backup date, because the database may have gone back past keys that were created and used afterwards. It must contain every `key_id` referenced by the restored data.
3. Run `deno task keys:verify` against the restored database and the ring. It lists the distinct `key_id` and `fingerprint_key_id` values, confirms each is in the ring, and test-decrypts every ciphertext row (R10.12).
4. **Activate a new key before traffic (R10.13, RD-13).** First **record the set S of every key identifier in the newest ring's `fingerprintHistory` as it stands, before any new key is added** (every key ever registered, including retired keys). Then generate a new key with an identifier above `highestKeyId` (the tool rejects duplicate or previously used material), add it to the ring as the only `ACTIVE` key (no staging is needed, traffic is stopped and every instance restarts together), mark the previous active key `DECRYPT_ONLY`, increase the ring `generation`, back up the ring, and **seal exactly the identifiers in S** (`deno task keys:seal`, which inserts a sealed row with the fingerprint from the history if the restored database has none, so the database registry of fingerprints is restored too), so the restored, possibly lowered counters cannot grant reservations. **Do not seal the new key.** Restart every instance so that no allowance survives. Skip the new key and the sealing only if the restore is proved lossless: for every key that can still encrypt (the `ACTIVE` key and every `STAGED` key) the restored row exists with the same sealed flag and a counter not lower than before, **and** for every identifier in `fingerprintHistory` the restored row exists with its original fingerprint and sealed flag (CR-14, CR-15). Still restart every instance. Re-run `keys:verify`.
5. Only then start the application, run cleanup, and accept traffic.
6. If a needed key is missing, the rows under it are unrecoverable. Affected games cannot be played or shown. Their outcomes and counts survive. Games that finished remain deletable by cleanup.

**Rotation (planned, routine, for example annually or on staff change; mandatory by 2^28 reserved units). Three phases, the same whether the key is below 2^27 or already past 2^28.**
1. **Stage.** `deno task keys:generate` (new identifier above `highestKeyId`, duplicate or previously used material rejected, key registered, at least one unit reserved, self-test value encrypted). Add the new key to the ring as `STAGED` and raise `generation`. Back up the ring (new copy). **Restart every instance**, one after another, with this ring. When every running instance has acknowledged the staged key in `instance_ring_reports` (`database-schema.md` 6.2a), every reader can decrypt anything the new key will write. `keys:activate` checks this and refuses otherwise (CR-16).
2. **Activate.** Change the ring: new key `ACTIVE`, previous key `DECRYPT_ONLY` with `deactivatedAt`, raise `generation`, back up the ring. **Restart every instance** again, one after another. During this rolling restart some instances encrypt with the previous key and some with the new one. Both are present and unsealed on every instance, so nothing is unreadable. Allowances live in memory only, so a restarted instance holds none. Confirm every instance reports the new generation.
3. **Seal.** `deno task keys:seal <previous id>` seals the previous key only: `sealed = true`, counter 2^30. The seal waits for transactions that are in their commit-time check on that key and commits after them. After this commits no instance can reserve under the key, no request that begins afterwards passes the pre-encryption check, and no transaction can commit ciphertext under it, because the commit-time check of any later transaction sees the seal and rolls back (`database-schema.md` section 6.2, CR-13). Units reserved but never used stay counted against the previous key.
4. Run `deno task reencrypt` (R10.5), see 3.8. Record the completion date D.
5. Verify no row references the previous key with `keys:verify`.
6. Retire the previous key (3.9) no earlier than D + 35 days. Its fingerprint stays in the history for ever.
### 3.6a Key lifecycle (single summary, RD-14, CR-10)

| State of a key | Ring status | `key_usage` | Reservations | Encryption | Decryption |
|---|---|---|---|---|---|
| Registered, active, below 2^27 | `ACTIVE` | `sealed = false`, `R` below 2^27 | Granted | Yes | Yes |
| Warning | `ACTIVE` | `R` at or above 2^27 | Granted, warning raised | Yes | Yes |
| Rotation overdue | `ACTIVE` | `R` at or above 2^28 | Granted until 2^30, critical alert, admin health `degraded` | Yes | Yes |
| Hard stop | `ACTIVE` | `R` = 2^30 | Refused (a block that would exceed 2^30) | Only with units already held, then `503` | Yes |
| Staged (new key, before activation) | `STAGED` | `sealed = false`, `R` at least 1 (self-test unit) | Not requested | No | Yes |
| Superseded (after rotation, at any `R`, including after 2^28) | `DECRYPT_ONLY`, `deactivatedAt` set | `sealed = true`, `R` = 2^30, admin health `sealed` (expected, no alert) | Refused | **No.** No ciphertext under it can be committed after the seal commits, whatever allowance an instance holds (commit-time check) | Yes |
| Retired | removed from the ring, fingerprint kept in `fingerprintHistory` | **row kept permanently** (sealed, fingerprint kept) so the database keeps refusing that material | Refused | No | No (no data may remain under it) |

Rules for the transition to *Superseded*, identical in `database-schema.md` 6.3, `deployment.md` 6.1 and 6.3:
- The new key is staged on every instance first, then becomes the active key, and every instance is restarted so that the ring and the allowances are fresh.
- The previous key becomes decrypt-only, and is sealed only after every instance runs the new ring.
- Outstanding in-memory allowances for the previous key are not usable: restarted instances have none, and a missed instance fails the pre-encryption check as soon as the seal commits. No ciphertext under the previous key can be committed after the seal: every transaction that writes ciphertext checks the key under a share lock immediately before commit, and the seal is ordered after any such transaction already holding it.
- Unused reservations stay counted. Sealing never lowers a counter.
- No instance resumes encryption under the previous key because it holds an allowance.
- A superseded key never becomes active again.

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
4. The ring backup is updated, and the retired key's **material** is destroyed from the ring copies after the same retention. Its identifier and fingerprint stay in `fingerprintHistory`, and its sealed `key_usage` row stays in the database, for ever (CR-14).

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
| T5 | Using an old or revoked token after rotation | Preliminary lookup grants nothing. Authoritative validation under the game lock for writes and as the first statement of a snapshot for reads. Replay only for the same v4 key inside the window, and it never reactivates the old token | A read that began before the commit may finish (bounded by request duration). Section 2.2 |
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
| T24 | Rematch hijack by a third party | Capability needs an access token to mint. Rotation revokes it. One rematch ever per original game (marker row, RD-6), and creating it revokes every other unused capability (CH-3). Only the presenting player gets seat 1 credentials. Invitation delivered by the creator out of band | Anyone given the invitation can take seat 2, as with any invitation |
| T25 | Weak randomness | Only `crypto.getRandomValues` and `crypto.randomUUID`. `Math.random` banned by lint rule outside the simulator | None identified |
| T26 | Rotation replay abuse | Needs old token and key, short window, encrypted storage, same `401` outside the rule (section 2.2) | First rotator wins, window exposure |
| T27 | Nonce reuse | Random 96-bit nonces, one authoritative durable reservation counter per key with a strict global limit of 2^30 (atomic conditional statement plus `CHECK`), warning at 2^27, rotation by 2^28 (reservations continue until the hard stop, RD-14), hard stop at 2^30 (RD-10, RD-13, CR-9, section 3.3a). New key and sealing of older keys after any restore | Negligible at expected volume. A restore without a new key could understate usage, which the procedure prevents |
| T28 | IP-based rate limit evasion or abuse of forwarded headers | Forwarded IP trusted only from `TRUSTED_PROXY_CIDRS`. Player buckets keyed by player id after a preliminary lookup | Shared NAT users share limits. Attackers with many IPs. A holder of an old revoked token can drain the player's bucket until it refills |
| T29 | Rate-limit data as personal data | Stores an HMAC of the IP with a secret, not the address. Rows deleted after an hour idle. Table excluded from backups (section 6.2) | HMAC key compromise together with a database copy allows IP confirmation, and for IPv4 enumeration of all addresses |
| T30 | Restore reverts credential state | Documented procedure. Rate-limit table cleared, cleanup run, tokens rotated after backup are reset | Players who rotated after the backup lose their seat. Revoked tokens revive. No point-in-time recovery (RD-7, accepted risk, reassess before production) |
| T31 | Stale or missing key at restore | `keys:verify` before traffic. Ring backup covers backup retention (3.6, 3.9) | Missing key means unrecoverable data |
| T32 | Race between expiry and operations | Single reference time, `>=` rule, lock | None identified |
| T33 | Decrypted game data leaving through an unintended path | Exactly two serialisation exceptions, results gated on `COMPLETED` before any ciphertext read, redacting wrapper, no persistent plaintext, canary tests | Runtime memory residue |
| T34 | Guessable rotation key | UUIDv4 required, 122 random bits, format enforced, plus old token needed | Client may use a weak generator. The server cannot detect it |
| T35 | Key material reuse under a new identifier, identifier reuse, or re-registration of retired material, giving the same AES key a fresh counter | Ring loader and `keys:generate` reject duplicate material and non-increasing identifiers, `highestKeyId` is monotonic, `fingerprintHistory` keeps every key ever registered, `key_usage.fingerprint` is `UNIQUE` and never deleted, `keys:verify` repeats the checks (CR-11, CR-12) | Operator editing the ring by hand is detected at the next start-up. A restore that lost both the ring history and the database row is covered by the ring backup |

## 6. Privacy (R13.4, R13.7)

- No accounts, email addresses or real identity. Nicknames are free text and might contain personal data. The privacy notice says so.
- Nicknames are visible only to the two players of that game.
- The application writes no client IP address. The rate limiter stores an HMAC of the IP (section 6.2). The proxy writes no IP in its access log by default (`deployment.md`), and if the owners enable it for abuse investigation, a retention period must be set.
- Retention and deletion follow R11 and `database-schema.md`. A game is deleted at its retention end, with nicknames, codes, guesses and credentials. Backups hold deleted data for at most 35 days.
- There is no player-initiated deletion endpoint in MVP 1 (ND-8). A holder of a bearer token proves control of a seat, not an identity.
- Metrics and logs are privacy-safe (section 4).
- UK GDPR review items for the owners: lawful basis statement, privacy notice text, data processor arrangements for the VPS provider, backup retention wording. They are tasks, not decided here.

### 6.2 Client IP handling for rate limiting (RD-9)

**What is stored.** In `rate_limits`, for IP scopes: `subject = HMAC-SHA-256(RATE_LIMIT_HMAC_KEY, client IP)` (32 bytes), the scope name, a token count and the last refill time. The raw address is never written to the database, logs, metrics or traces by the application.

**Privacy implications.**
- An IP address is personal data under UK GDPR. A keyed HMAC is pseudonymised data, not anonymous data: whoever holds the key can test whether a given address is in the table, and the IPv4 space (2^32) is small enough that holder of key plus database could recover every address in it. The key is therefore the protection and is handled as a secret.
- The purpose is abuse prevention (rate limiting), a legitimate interest. The privacy notice must say that IP addresses are processed transiently for this purpose in pseudonymised form. Wording is a task for the owners (section 6).
- The proxy sees the raw IP in transit, as any internet service does. The proxy access log does not record it by default.
- The HMAC subjects cannot be linked to nicknames, games or players: player buckets use the player id and IP buckets use only the IP, in separate rows.

**Retention.** A row is deleted by cleanup once it has been idle for an hour, so a row lives at most about two hours after its last request (one hour idle plus up to one cleanup interval). Rows exist only for addresses that sent requests in that period. `rate_limits` is excluded from database backups (CH-2), so no HMAC is retained beyond live data. After a restore the table is truncated.

**Key management.**
- A separate 32-byte secret (`duocode_ratelimit_key`), distinct from the code key ring, mounted as a Docker secret in `app` only, generated with `deno task keys:generate --type ratelimit`.
- It is not backed up (CH-2): losing it only resets the counters, because all buckets are rebuilt on the next requests.
- Rotation (planned or on suspected compromise): replace the secret and restart the application. All old rows become unmatched and are deleted within about two hours. No migration and no data re-keying are needed. During the changeover buckets restart full, a brief and harmless relaxation.
- Compromise response: rotate as above. Because the table holds only an hour of data and is excluded from backups, the exposure from a leaked key plus a stolen live database is limited to the addresses active in the last hours.
- Without the key, the table gives an attacker nothing useful. With the key and a copy of the table, active addresses can be confirmed.

## 7. Review checklist for owners (gate 1.5)

1. Confirm the lost-token limitation wording (section 2.1).
2. Review the rotation implications table (section 2.2): UUIDv4 key, no reactivation of the old token, loss of the replacement token after the window, RD-11 (decrypted replacement token in the replay response, approved with its five conditions) and RD-12 (rotation revokes the unused rematch capability, approved).
3. Review the ND-7 assessment (section 3.1), the serialisation exceptions (section 3.5), and the nonce thresholds with the durable reservation counter and the restore rule (section 3.3a, RD-10, RD-13, all approved).
4. Review key management, backup, recovery, rotation, retirement and compromise procedures (sections 3.6 to 3.9) and `deployment.md` sections 5 and 6.
5. Review the log and metrics rules (section 4).
6. Review the threat table, especially T5, T12, T13, T21, T26, T30.
7. Confirm the IP handling documentation (section 6.2, RD-9) and the accepted operational risk of no point-in-time recovery (RD-7, reassess before production).

## 8. Residual risks summary

- Plaintext feedback counts, nicknames and state flags remain readable by a database reader.
- Runtime cannot guarantee erasure of decrypted values.
- A host compromise exposes both key and database.
- A database writer can alter plaintext state columns.
- Lost tokens are lost seats. First rotator wins.
- Rotation replay window exposes the new token, encrypted, for up to 10 minutes plus one cleanup interval.
- Deleted data lives in backups for up to 35 days. A restore revives deleted data and rolled-back tokens until cleanup and procedures run. No point-in-time recovery in MVP 1 (RD-7).
- Losing the replacement token of a rotation after the replay window loses the seat.
- Pseudonymised IP HMACs exist for up to about two hours, and a leaked HMAC key plus a database copy allows confirming addresses.
