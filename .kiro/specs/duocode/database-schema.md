# DuoCode Database Schema and Migrations (revision 3.1)

Owns: tables, constraints, indexes, migration strategy, retention clock rules, cleanup SQL, rate-limit statement. Related: `requirements.md` (R5, R8 to R11, R20), `design.md` (credential model, authorisation point, lock ordering), `state-machine.md` (states and transitions), `security-assessment.md` (encryption), `deployment.md` (backup and restore).

PostgreSQL is the authoritative store. Tables below are the logical model. Final DDL is written in `backend/migrations/0001_init.sql` during implementation and must match this file. The DDL below was applied and constraint-tested against a scratch PostgreSQL database during specification review (versions and results in `revision-3.1-review-package.md`). Behavioural tests are required in implementation (`test-strategy.md`, group TS-DB).

## 1. Entities

```
games 1 ──< players 1 ── 0..1 secret_codes        (encrypted)
  |             |
  |             ├──< guesses 1 ── 1 idempotency_keys   (encrypted guess, keyed fingerprint)
  |             ├──< credentials (ACCESS, REMATCH)
  |             └──< token_rotations                    (encrypted replay copy of new token)
  ├──< credentials (INVITATION; REMATCH of this original game)
  ├── 0..1 game_results
  └── 0..1 rematch_markers (original_game_id) ── 0..1 games (the rematch, link cleared when it is deleted)

rate_limits (independent, shared by all instances)
key_usage   (independent, one authoritative row per key: reserved encryption units)
```

## 2. DDL

```sql
CREATE TYPE game_state AS ENUM
  ('WAITING_FOR_PLAYER','WAITING_FOR_CODES','ACTIVE','COMPLETED');
-- EXPIRED is not stored. It is derived: reference_time >= expires_at (state-machine.md).

CREATE TYPE credential_type AS ENUM ('ACCESS','INVITATION','REMATCH');

CREATE TABLE games (
  id            uuid PRIMARY KEY,                       -- crypto.randomUUID(); identifier, not a credential
  state         game_state NOT NULL,
  config        jsonb NOT NULL,                         -- {positions, symbols, maxGuesses} at creation
  created_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz,
  expires_at    timestamptz NOT NULL,                   -- retention clock, rules in section 5
  CHECK ((state = 'COMPLETED') = (completed_at IS NOT NULL))
);
CREATE INDEX games_expires_idx ON games (expires_at);

CREATE TABLE players (
  id            uuid PRIMARY KEY,
  game_id       uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  seat          smallint NOT NULL CHECK (seat IN (1,2)),
  nickname      text NOT NULL
                CHECK (char_length(nickname) BETWEEN 1 AND 24)             -- code points (UTF-8 database)
                CHECK (nickname !~ E'[\\u0001-\\u001F\\u007F-\\u009F\\u202A-\\u202E\\u2066-\\u2069]'),  -- no Cc, no bidi embedding/override/isolate (NUL cannot occur in text)
  guesses_used  smallint NOT NULL DEFAULT 0 CHECK (guesses_used BETWEEN 0 AND 10),
  solved        boolean NOT NULL DEFAULT false,
  finished_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (game_id, seat),                                -- at most two players per game
  UNIQUE (id, game_id),                                  -- target for composite foreign keys
  CHECK (finished_at IS NULL OR solved OR guesses_used = 10)
);

CREATE TABLE credentials (
  id             uuid PRIMARY KEY,
  type           credential_type NOT NULL,
  game_id        uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  player_id      uuid,
  token_hash     bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),   -- SHA-256 of full token
  created_at     timestamptz NOT NULL DEFAULT now(),
  revoked_at     timestamptz,
  revoked_reason text CHECK (revoked_reason IN ('ROTATED','SUPERSEDED','ROTATION_SIDE_EFFECT')),
  consumed_at    timestamptz,
  FOREIGN KEY (player_id, game_id) REFERENCES players (id, game_id) ON DELETE CASCADE,  -- credential bound to its game
  CHECK ((type = 'INVITATION') = (player_id IS NULL)),
  CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);
-- At most one live credential of each kind:
CREATE UNIQUE INDEX credentials_one_access_per_player
  ON credentials (player_id) WHERE type = 'ACCESS' AND revoked_at IS NULL;
CREATE UNIQUE INDEX credentials_one_rematch_per_player
  ON credentials (player_id) WHERE type = 'REMATCH' AND revoked_at IS NULL AND consumed_at IS NULL;
CREATE UNIQUE INDEX credentials_one_invitation_per_game
  ON credentials (game_id) WHERE type = 'INVITATION';
CREATE INDEX credentials_game_idx ON credentials (game_id);

CREATE TABLE secret_codes (
  player_id   uuid PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,  -- the player who SET the code
  key_id      smallint NOT NULL,                       -- key ring identifier that encrypted this row
  ciphertext  bytea NOT NULL CHECK (octet_length(ciphertext) = 32),       -- nonce(12) || ct(4) || tag(16)
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE guesses (
  id                bigserial PRIMARY KEY,
  player_id         uuid NOT NULL REFERENCES players(id) ON DELETE CASCADE,  -- the player who MADE the guess
  guess_number      smallint NOT NULL CHECK (guess_number BETWEEN 1 AND 10),
  key_id            smallint NOT NULL,
  guess_ciphertext  bytea NOT NULL CHECK (octet_length(guess_ciphertext) = 32),  -- nonce(12) || ct(4) || tag(16)
  exact             smallint NOT NULL CHECK (exact BETWEEN 0 AND 4),             -- plaintext by decision ND-7
  misplaced         smallint NOT NULL CHECK (misplaced BETWEEN 0 AND 4),
  solved            boolean GENERATED ALWAYS AS (exact = 4) STORED,
  prev_guess_number smallint GENERATED ALWAYS AS (CASE WHEN guess_number > 1 THEN guess_number - 1 END) STORED,
  prev_solved       boolean GENERATED ALWAYS AS (CASE WHEN guess_number > 1 THEN false END) STORED,
  created_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (exact + misplaced <= 4),
  UNIQUE (player_id, guess_number),
  UNIQUE (player_id, guess_number, solved),
  -- Contiguity and "no guess after a solving guess": guess n requires guess n-1 to exist and not be solved.
  FOREIGN KEY (player_id, prev_guess_number, prev_solved)
    REFERENCES guesses (player_id, guess_number, solved) ON DELETE CASCADE
);

CREATE TABLE idempotency_keys (                         -- guess submissions only (scope: player, operation, key)
  player_id          uuid NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  key                uuid NOT NULL,
  guess_id           bigint NOT NULL UNIQUE REFERENCES guesses(id) ON DELETE CASCADE,  -- one key per guess, one guess per key
  fingerprint        bytea NOT NULL CHECK (octet_length(fingerprint) = 32),  -- HMAC-SHA-256 over RFC 8785 envelope
  fingerprint_key_id smallint NOT NULL,                -- key ring entry used for the HMAC
  response_status    smallint NOT NULL,
  response_body      jsonb NOT NULL,                   -- original guess response, no code and no guess
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (player_id, key)
);

CREATE TABLE token_rotations (                          -- rotation idempotency (scope: player, operation, key)
  id                uuid PRIMARY KEY,
  game_id           uuid NOT NULL,
  player_id         uuid NOT NULL,
  idempotency_key   uuid NOT NULL,
  from_credential_id uuid NOT NULL UNIQUE REFERENCES credentials(id) ON DELETE CASCADE,
  to_credential_id   uuid NOT NULL UNIQUE REFERENCES credentials(id) ON DELETE CASCADE,
  fingerprint       bytea NOT NULL CHECK (octet_length(fingerprint) = 32),  -- SHA-256 over RFC 8785 envelope of ids only
  token_key_id      smallint,
  token_ciphertext  bytea CHECK (octet_length(token_ciphertext) = 75),      -- nonce(12) || token(47) || tag(16)
  created_at        timestamptz NOT NULL DEFAULT now(),
  replay_until      timestamptz NOT NULL,
  UNIQUE (player_id, idempotency_key),
  FOREIGN KEY (player_id, game_id) REFERENCES players (id, game_id) ON DELETE CASCADE,
  CHECK ((token_ciphertext IS NULL) = (token_key_id IS NULL))
);

CREATE TABLE rematch_markers (                          -- at most one rematch EVER per original game (RD-6)
  original_game_id uuid PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,       -- lives and dies with the original
  rematch_game_id  uuid UNIQUE REFERENCES games(id) ON DELETE SET NULL,           -- cleared when the rematch is deleted. The row stays
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (rematch_game_id IS NULL OR rematch_game_id <> original_game_id)
);

CREATE TABLE game_results (
  game_id       uuid PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
  outcome       text NOT NULL CHECK (outcome IN ('PLAYER_1_WINS','PLAYER_2_WINS','DRAW')),
  p1_solved     boolean NOT NULL,
  p1_guesses    smallint NOT NULL CHECK (p1_guesses BETWEEN 0 AND 10),
  p2_solved     boolean NOT NULL,
  p2_guesses    smallint NOT NULL CHECK (p2_guesses BETWEEN 0 AND 10),
  completed_at  timestamptz NOT NULL
);

CREATE TABLE rate_limits (                              -- shared token buckets, see section 6
  scope         text NOT NULL,
  subject       bytea NOT NULL CHECK (octet_length(subject) = 32),   -- HMAC of client IP, or hash of token. Never raw.
  tokens        double precision NOT NULL,
  refilled_at   timestamptz NOT NULL,
  PRIMARY KEY (scope, subject)
);
CREATE INDEX rate_limits_refilled_idx ON rate_limits (refilled_at);

CREATE TABLE key_usage (                                  -- ONE authoritative row per key: encryption units RESERVED (RD-10, RD-13, CR-9)
  key_id    smallint PRIMARY KEY,
  fingerprint bytea NOT NULL UNIQUE CHECK (octet_length(fingerprint) = 32),  -- SHA-256 of a label and the key material. Kept for ever, so retired material cannot be registered again
  reserved  bigint NOT NULL DEFAULT 0
            CHECK (reserved >= 0 AND reserved <= 1073741824),  -- absolute backstop: 2^30. No statement can exceed it
  sealed    boolean NOT NULL DEFAULT false,                     -- true once the key is no longer allowed to encrypt (rotation, restore)
  CHECK (NOT sealed OR reserved = 1073741824)                   -- a sealed key is always at the limit
);

CREATE TABLE instance_ring_reports (                    -- which ring each running instance has loaded (CR-16)
  instance_id      uuid PRIMARY KEY,                    -- random per process start
  ring_generation  integer NOT NULL CHECK (ring_generation >= 1),
  loaded_key_ids   smallint[] NOT NULL,                 -- every key id the instance can decrypt (ACTIVE, STAGED, DECRYPT_ONLY)
  reported_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE schema_migrations (
  version     integer PRIMARY KEY,
  name        text NOT NULL,
  applied_at  timestamptz NOT NULL DEFAULT now()
);
```

Notes:
- Ciphertext columns are opaque to the database. Symbol range and length of codes and guesses are validated by the application before encryption and cannot be checked by constraints. This is the cost of ND-7.
- `players.guesses_used` equals the count of that player's `guesses` rows. The service updates both in one transaction. A consistency test checks it.
- The nickname constraints implement R1.3(c) and (d) as a backstop. Trimming and the other rules are application-level because PostgreSQL has no Unicode `White_Space` test.
- The rematch marker is a separate row keyed by the original game. Its primary key is what makes "one rematch ever" a database rule (R9.4). Deleting the rematch game clears `rematch_game_id` and leaves the row, so the original can never have a second rematch. Deleting the original deletes the marker, and the rematch game, which has no foreign key to the original, continues as an ordinary game (R9.8). `rematchOf` in the API is derived by looking up the marker whose `rematch_game_id` equals the game.
- `key_usage` counts **reserved units**, not completed encryptions, in **one row per key**. The row is the single authoritative counter and the single serialisation point for every reservation under that key, from every instance. The earlier 32-shard design was **replaced** (section 6.2 explains why). An instance reserves a block of units in its own short autocommit transaction, committed before it performs any encryption from that block, so a reservation can never be rolled back with an application transaction. The `CHECK` constant 2^30 is an absolute database-level ceiling that holds even if an application instance is misconfigured. The row is touched only by the reservation statement, the key-registration insert and the sealing update (lock level L0 in `design.md` section 8.2).
- Credentials of the original game (including the rematch capabilities) reference the original game and its players and are deleted with it. A rematch game has its own `players` and `credentials` rows. Nothing links its credentials to the original game (R9.3).
- No credential record is kept after its game is deleted (R8.8).
- Nonces and ciphertexts: every encryption uses a fresh random 96-bit nonce. See `security-assessment.md` section 3.

## 3. Integrity enforced by the database (CL-7)

| Rule | Mechanism | Remains in service logic |
|---|---|---|
| At most 2 players per game, seats 1 and 2 | `UNIQUE (game_id, seat)` and `seat IN (1,2)` | Seat choice at join |
| One secret code per player | `secret_codes` primary key | |
| At most 10 guesses per player | `guess_number BETWEEN 1 AND 10`, `UNIQUE (player_id, guess_number)` | Early rejection with `ATTEMPTS_EXHAUSTED` |
| Guess numbers contiguous from 1 | Foreign key to the previous guess (`prev_guess_number`) | |
| No guess after a solving guess | Same foreign key requires `prev_solved = false` | Early rejection with `ALREADY_SOLVED` |
| `guesses_used` within range | `CHECK BETWEEN 0 AND 10` | Equality with the count of guess rows |
| One key per guess, one guess per key | `idempotency_keys` primary key `(player_id, key)` and `UNIQUE (guess_id)` | Fingerprint comparison |
| One rotation per key and per old token | `UNIQUE (player_id, idempotency_key)`, `UNIQUE (from_credential_id)` | Replay window and fingerprint |
| At most one rematch ever per game, independent of the rematch game's lifetime | Primary key of `rematch_markers` (`original_game_id`), `UNIQUE (rematch_game_id)` | `REMATCH_ALREADY_CREATED` mapping, creation in the rematch transaction |
| One live access token per player | Partial unique index | Atomic rotation |
| One live rematch capability per player | Partial unique index | Revocation on mint and rotation |
| One invitation per game | Partial unique index | Single-use consumption |
| Credential belongs to a player of its own game | Composite foreign key `(player_id, game_id)` | |
| Result at most once per game | `game_results` primary key | Result only for `COMPLETED` games |
| Completed state has a completion time | `CHECK` on `games` | |
| Nickname length, control characters, bidi embedding, override and isolate controls | `CHECK` constraints | Trim, empty, malformed Unicode |
| Rate-limit bucket unique per subject | Primary key `(scope, subject)` | |
| One authoritative counter row per key, never negative, never above 2^30 | Primary key and `CHECK` of `key_usage` | The conditional reservation statement (section 6.2), monotonic increase, threshold policy |

Not expressible as simple constraints and covered by service logic plus tests: a game is `ACTIVE` only with two players and two codes, a game is `COMPLETED` only when both players are finished, and `game_results` exists only for completed games.

## 4. Credential lookup

The authorisation point (`design.md`, section 5) runs this lookup. `$1` is the SHA-256 of the presented token.

```sql
SELECT c.id, c.type, c.game_id, c.player_id, c.revoked_at, c.revoked_reason, c.consumed_at,
       g.expires_at, clock_timestamp() AS reference_time
FROM credentials c
JOIN games g ON g.id = c.game_id
WHERE c.token_hash = $1;
```

The service evaluates:
1. No row: `INVALID_CREDENTIALS`. This includes tokens of deleted games.
2. Type differs from the operation's expected type: `INVALID_CREDENTIALS`.
3. `revoked_at` or `consumed_at` set: `INVALID_CREDENTIALS`, except the rotation replay in `state-machine.md` section 3.
4. `reference_time >= expires_at`: `GAME_EXPIRED` (C-7).
5. Otherwise valid.

The credential's `game_id` must equal the game in the path. Order: revocation and type are checked before expiry, so a revoked token of an expired game is `401` and a live one is `410`. `reference_time` is read once and used for every decision in the request (CL-2).

## 5. Retention clock rules (`games.expires_at`)

Durations come from configuration (`design.md`, section 11). The reference time is the database clock read at the authorisation point. A game is expired when `reference_time >= expires_at`.

| Event | New `expires_at` |
|---|---|
| Create game (`WAITING_FOR_PLAYER`) | reference time + `TTL_UNJOINED_DAYS` |
| Secret code submitted while `WAITING_FOR_PLAYER` | unchanged |
| Join | reference time + `TTL_IN_PROGRESS_DAYS` |
| Code, guess, access-token rotation while `WAITING_FOR_CODES` or `ACTIVE` | reference time + `TTL_IN_PROGRESS_DAYS` |
| Completion | reference time + `TTL_COMPLETED_DAYS`, `completed_at` = reference time |
| Any read, rematch capability minting, rematch creation, rotation after completion | unchanged |
| Idempotent replay (guess or rotation) | unchanged |

Reads and polling do not extend the clock (ND-5). A completed game's clock never moves again.

## 6. Rate limiting and key usage statements (R20, RD-13)

### 6.1 Rate limiting statement (R20)

A token bucket per `(scope, subject)`. `$cap` is capacity, `$refill` is tokens per second, `$now` is `clock_timestamp()`. One statement, atomic across instances.

```sql
INSERT INTO rate_limits (scope, subject, tokens, refilled_at)
VALUES ($1, $2, $cap - 1, clock_timestamp())
ON CONFLICT (scope, subject) DO UPDATE
SET tokens = LEAST($cap, rate_limits.tokens
                   + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limits.refilled_at)) * $refill) - 1,
    refilled_at = clock_timestamp()
WHERE LEAST($cap, rate_limits.tokens
            + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limits.refilled_at)) * $refill) >= 1
RETURNING tokens;
```

- A returned row means the request is allowed. No row means denied. The bucket is not changed on denial, so a client that keeps retrying is not penalised beyond the refill.
- `Retry-After` is `ceil((1 - tokens) / $refill)` computed by a follow-up read of the bucket, or the application default when the read is skipped.
- Every bucket update, IP or player, runs as its own short autocommit statement before the request transaction begins (CR-2, R20.9). No rate-limit row lock is ever held together with a game lock (`design.md` section 8.2).
- Subjects: `HMAC-SHA-256(RATE_LIMIT_HMAC_KEY, ip)` for IP scopes and `SHA-256("rl" || player_id)` for player scopes (CH-4). The player id comes from the preliminary credential lookup, so no row is created for a token that does not exist. No raw IP or token is stored (RD-9).
- Rows idle for more than an hour are deleted by cleanup (section 7). A bucket full again behaves like a new one.
- Scope names and values are in `deployment.md`, section 4.

### 6.2 Key usage reservation: strict global hard stop (RD-10, RD-13, CR-9)

**Terms.** These three words are used with exactly these meanings in every document.

| Term | Meaning |
|---|---|
| Reserved unit | One permitted encryption, counted in `key_usage.reserved` for a key. The counter `R` is the number of reserved units |
| Encryption invocation | One actual call that encrypts a value with the key. Each invocation consumes exactly one reserved unit that the calling instance holds |
| Allowance | The reserved units one instance holds in memory and has not yet consumed |
| Sealed key | A key whose `sealed` flag is true and whose counter is at 2^30. No reservation is granted under it, and no encrypting request that begins after the seal commits may use it, even if the instance still holds an allowance |

`R` counts every unit ever reserved: units consumed by invocations (whether or not the surrounding transaction committed), units still sitting in instance allowances, and units lost when an instance crashed or restarted. So `R >= invocations`. The counter may overestimate use. It can never underestimate it.

**Design: one authoritative row, one atomic conditional statement.** The 32-shard design of the revision 3.1 draft is **replaced**. With shards, each reservation updated its own shard row, so two instances working on different shards could each see room below the limit and both reserve, and the check of the total across shards was not atomic. A single row per key removes that: every reservation under a key updates the same row, PostgreSQL's row lock serialises them, and the limit check is part of the same statement. The cost is one contended row per key, hit once per `KEY_USAGE_BLOCK` encryptions per instance. At the expected volume that is negligible, and correctness is chosen over contention (owner instruction).

**Key registration** (once per key, idempotent, by `keys:generate`). The row is never deleted, not even when the key is retired from the ring, so `UNIQUE (fingerprint)` makes the database refuse the same key material under a second identifier, which would otherwise give the same AES key a fresh counter (CR-12). The ring keeps the same fingerprints in its history, which also covers a restore that went back past the registration. Order inside `keys:generate` (CR-14, CR-15). It runs only in the `keymgmt` job (`deployment.md` section 2.1) while holding the ring single-writer lock (`SELECT pg_advisory_lock(4242001)`, released at the end), so concurrent generators are serialised and the ring is written with a version check on `generation`: (1) generate the material and compute its fingerprint, and check the fingerprint against the ring history and the database; (2) choose an identifier above the ring's `highestKeyId` and above `max(key_id)` in `key_usage`; (3) **write the identifier and fingerprint into the ring's `fingerprintHistory` with status `PENDING`, raise `highestKeyId`, and back up the ring** (section 5 of `deployment.md`) before touching the database; (4) register the row; (5) **reserve** at least one unit through the reservation statement below; (6) only then encrypt the self-test value; (7) add the ring entry as `STAGED` and mark the history entry `REGISTERED`. Registration comes after the history record so that an interruption at any point leaves a durable, separately backed-up record of the identifier and material, and comes before reservation because the reservation statement refuses an unregistered key. **Recovery from an interrupted run:** a `PENDING` history entry is never reused or deleted. The next run marks it `ABANDONED` (identifier and fingerprint stay in the history for ever), and a restore seals it like any other history entry. A new key therefore has a counter of at least 1 when it is activated, never 0.

Registration results (CR-13): a returned row means the identifier is registered with **this** material (new, or a harmless repeat after an interrupted run). No row means the identifier is already registered with **different** material, and `keys:generate` stops before reserving or encrypting. A unique violation on `fingerprint` means the material is already registered under another identifier, and `keys:generate` also stops. When choosing a new identifier, `keys:generate` uses one above both the ring's `highestKeyId` and `max(key_id)` in `key_usage`, so an identifier registered by an interrupted run is never handed out again.

```sql
INSERT INTO key_usage (key_id, fingerprint) VALUES ($1, $2)       -- $2 = SHA-256('duocode/key-fingerprint/v1' || key material)
ON CONFLICT (key_id) DO UPDATE SET fingerprint = key_usage.fingerprint
WHERE key_usage.fingerprint = EXCLUDED.fingerprint                -- idempotent ONLY for the same material
RETURNING key_id;
```

**Reservation statement** (one statement, its own autocommit transaction, on a connection separate from the request transaction):

```sql
UPDATE key_usage
SET reserved = reserved + $2                          -- $2 = n x KEY_USAGE_BLOCK, n >= 1 whole blocks
WHERE key_id = $1
  AND fingerprint = $4                                -- $4 = fingerprint of the material the instance will encrypt with (CR-14)
  AND NOT sealed
  AND $2 > 0                                          -- a zero or negative request matches no row, so the counter can never go down
  AND reserved + $2 <= $3                             -- $3 = configured hard stop, at most 2^30, a multiple of $2
RETURNING reserved;                                   -- the new total R
```

- One returned row means the `$2` units were granted, and the row holds the new total. No returned row means the request was refused and nothing changed.
- The units are added to the instance's allowance only after the statement has returned. If the outcome is unknown (connection lost), the instance treats it as refused and does not use them. The counter may have gone up. That is an over-count, which is safe.
- A refusal is whole: there are no partial grants. `$2` is always a whole number of blocks and `$3` is a multiple of the block (validated at start-up, `design.md` section 13), so `R` can reach exactly `$3` and any further request is refused.
- **Positive blocks only.** The `$2 > 0` guard in the statement and the start-up validation (`KEY_USAGE_BLOCK` at least 1) mean that no statement can lower `reserved`. A request for zero or a negative number matches no row.
- **Enough units for the whole operation.** An operation that needs `m` units while the instance holds `a` receives `n = ceil((m - a) / block)` whole blocks in one statement, so a small block size can never leave an operation short while capacity remains.
- If the key row does not exist, the statement matches no row and is treated as a refusal. Registration creates it.

**Pre-encryption check** (one cheap read, its own autocommit statement, before the request transaction begins, together with the allowance check, for every request that may encrypt):

```sql
SELECT NOT sealed AND fingerprint = $2 AS usable FROM key_usage WHERE key_id = $1;   -- $2 = fingerprint of the loaded material (CR-14)
```

The check also binds the loaded material to the registry: if the ring entry for the identifier carries different material from the one registered (for example a retired key copied into an active entry), the result is `false` and nothing is encrypted, and the reservation statement refuses it too (CR-14). A request may encrypt under the key only if this returns `true` **and** it holds enough claimed units (`design.md` section 9.1). The claim is taken **before** this check, so that the check is the last thing that happens before the transaction begins. If the check fails, the claim is returned (CR-13). No row (unregistered key) or `false` means the key is unusable. The request is not rejected at once, because it may not need an encryption at all (an idempotent replay or conflict, or a rule rejection). It continues through authorisation, replay lookup and rule checks, and ends with `503` only at the point where a fresh encryption is needed, before anything has been written. This is also what makes a stale in-memory allowance unusable once a key is sealed (section 6.3).

**Commit-time check** (CR-13). Inside every transaction that writes ciphertext, after all ciphertext rows are written and immediately before `COMMIT`, the transaction runs:

```sql
SELECT sealed FROM key_usage WHERE key_id = $1 FOR SHARE;
```

If it returns `true`, the transaction rolls back and the request ends with `503`. `FOR SHARE` conflicts with the `UPDATE` that seals a key, so the two are ordered by PostgreSQL: a transaction that holds the share lock commits first and the seal waits for it, and a transaction that reaches this statement after the seal has committed reads `sealed = true` and rolls back. Therefore **no ciphertext under a key can be committed after that key's seal has committed**. Units consumed by a rolled-back transaction stay counted. The check is taken last in the transaction, after the game lock, and nothing that holds the key row lock ever waits for a game lock, so it adds no deadlock (`design.md` section 8.2).

**Why the hard stop is strict.** In PostgreSQL `READ COMMITTED`, an `UPDATE` takes a row lock. A second `UPDATE` of the same row waits for the first to commit, then re-evaluates its `WHERE` clause against the newly committed row before it changes anything. The comparison `reserved + $2 <= $3` is therefore always made against the latest total. Two instances cannot both be granted the last block. On top of that, the `CHECK (reserved <= 1073741824)` constraint makes any write above 2^30 fail even if an instance were misconfigured with a larger `$3`.

**Guarantees** (each is tested against PostgreSQL, `test-strategy.md` TS-ENC and TS-CONC):

| # | Guarantee | How |
|---|---|---|
| G1 | `R` never exceeds 2^30 for any key | The statement's `WHERE` guard, and the `CHECK` constraint as a backstop |
| G2 | Every encryption invocation consumes one previously reserved unit, including in transactions that fail or roll back | The vault decrements the allowance at the invocation. The reservation committed earlier and independently |
| G3 | All outstanding allowances are inside `R` | A unit enters an allowance only after it was added to `R` |
| G4 | No instance obtains units that take `R` beyond the hard stop | The guard is evaluated atomically against the latest `R` under the row lock |
| G5 | Concurrent reservations cannot pass the limit independently | One row per key. Sharding is removed |
| G6 | An instance never encrypts with an exhausted allowance | The vault's consume step fails when the allowance is zero. The only way to refill it is a granted reservation |
| G7 | A restore cannot let encryption resume under a key whose counter may have rolled back | The restore procedure seals the old key (below) and activates a new one before traffic |
| G8 | `R` can overestimate, never underestimate | Units are reserved before use. Crashes, restarts and unknown outcomes only add unused units |

Consequence of G1 to G4: the number of encryption invocations under a key can never exceed 2^30, even though instances hold allowances and run concurrently, because every invocation needs a unit and at most 2^30 units exist.

**Health reporting.** "Health state" in this section means the admin-only metric `duocode_health_state{component="key_usage",key_id}` (`ok`, `warning`, `degraded`, `critical`, `sealed`) and the alerts built on it (`deployment.md` section 7). Only the key that is `ACTIVE` in the instance's ring can be `warning`, `degraded` or `critical`. A key that is not active and is sealed reports `sealed`, which is the expected end state of a rotation and raises no alert, so a normal rotation never leaves a critical alarm behind (CR-12). The one alarm for a sealed key is when the ring still lists it as `ACTIVE`, which is a misconfiguration and is `critical`. The public `/healthz` deliberately does not expose key usage, so key information is never public. It returns `503` only when the process cannot work at all (database or key ring unavailable).

**Threshold behaviour** (thresholds apply to `R`, the reserved units, after each granted reservation):

| Threshold | `R` reaches | Behaviour |
|---|---|---|
| Warning | 2^27 (134,217,728) | The warning metric `duocode_key_usage_state{key_id}` becomes `WARNING`, one operational warning is logged per key per process start, and the admin health state for the key is `warning`. Reservations continue normally. The public `/healthz` is not affected |
| Rotation required | 2^28 (268,435,456) | State `ROTATION_OVERDUE`: a critical alert is raised, the admin health state for the key is `degraded`, and the key must be rotated. The public `/healthz` stays `ok` so the service is not taken out of rotation. **Reservations under this key continue to be granted until the hard stop** (RD-14, approved). This keeps the game available while the owners rotate, and the cryptographic margin remains large (collision probability about 2^-41 at 2^28, 2^-37 at 2^30). A rotation makes the old key `DECRYPT_ONLY` and seals it, which refuses all further reservations under it |
| Hard stop | 2^30 (1,073,741,824) | `R + block` would exceed the limit, so the statement returns no row. No further units exist. After each instance consumes the units it already holds, no further encryption occurs under the key. Operations that need to encrypt fail closed with `503`. Decryption of existing data is unaffected. A critical alert is raised, the admin health state is `critical`, and a new key must be activated. The public `/healthz` stays `ok` so reads and decryption keep working |

`R` can equal 2^30 exactly: the limit is inclusive of the last unit, so at most 2^30 encryptions ever happen under a key. A block that would take `R` above 2^30 is refused whole. If the owners want a stop strictly before 2^30, set `KEY_USAGE_HARD_STOP` lower. The statement and the proof do not change.

**Sealing a key** (`deno task keys:seal <key_id>`): `INSERT INTO key_usage (key_id, fingerprint, reserved, sealed) VALUES ($1, $2, 1073741824, true) ON CONFLICT (key_id) DO UPDATE SET reserved = 1073741824, sealed = true;`, where `$2` is the key's fingerprint from the ring history. The statement inserts a sealed row when none exists, so a key whose row is missing (for example a key registered after the backup that a restore went back past) is sealed too, and a later registration (`ON CONFLICT DO NOTHING`) cannot reset it. After this commits, every reservation under the key is refused, and every encrypting request that begins afterwards fails the pre-encryption check, whatever the ring says and whatever allowance an instance still holds. Sealing is used (a) at every planned rotation, for the previous key only, after every instance runs the new ring, and (b) at every restore, immediately, for **every identifier in the ring's `fingerprintHistory` as it stood before the new key was added** (every key ever registered, including retired ones, never the new key, `deployment.md` section 6.1). The seal `UPDATE` waits for any transaction that holds the key row in share mode for its commit-time check, so when `keys:seal` returns, no transaction can still commit ciphertext under the key. Units that were reserved but never used stay counted: sealing raises the counter to the limit and never lowers it, so `R` still covers every encryption that was performed. Sealing is idempotent. The `CHECK` forces a sealed row to sit at 2^30.

**Restore (G7).** A restore from backup rolls `key_usage` back in time, so `R` may be lower than the encryptions really performed after the backup. The restore procedure therefore (1) activates a new key in the ring as the only `ACTIVE` key, (2) seals every older key, which burns its restored counter up to the limit so that even a mistaken ring cannot make it reserve again, and (3) restarts all instances, which discards every in-memory allowance. Old keys stay in the ring for decryption only (`security-assessment.md` section 3.6).

**Other rules.**
- Rolled-back or failed application transactions: the reservation committed earlier on its own, so nothing is undone. Units consumed in a failed transaction stay consumed.
- Crash or restart: the unused part of an instance's allowance is lost, and stays counted. The counter over-counts by at most `KEY_USAGE_BLOCK` per instance start per key.
- Contention: one statement per `KEY_USAGE_BLOCK` (1024) encryptions per instance. Negligible.
- `keys:verify` checks the invariant `ciphertext rows under the key <= R` per key and fails if it is violated.
- The reservation statement runs on a separate connection from the request transaction, before it begins. It holds the key row lock for one statement and never while waiting for any other lock. It may wait for transactions that hold the row in share mode for their commit-time check, which is short and cannot form a cycle, because those transactions never wait for anything the reserving connection holds (`design.md` section 8.2).

### 6.2a Ring acknowledgement for staged activation (CR-16)

Every instance upserts its row in `instance_ring_reports` at start-up and on every refresh (`KEY_USAGE_REFRESH_SECONDS`):

```sql
INSERT INTO instance_ring_reports (instance_id, ring_generation, loaded_key_ids, reported_at)
VALUES ($1, $2, $3, now())
ON CONFLICT (instance_id) DO UPDATE SET ring_generation = EXCLUDED.ring_generation,
  loaded_key_ids = EXCLUDED.loaded_key_ids, reported_at = now();
```

`keys:activate <key_id> --expect <N>` refuses to activate unless this returns `true`, where `N` is the number of instances the operator runs (the Compose scale of every service that can encrypt or decrypt), `$2` is the staged key and `$3` is the freshness window (twice the refresh interval):

```sql
SELECT count(*) = $1 AND bool_and($2 = ANY (loaded_key_ids)) AS all_staged
FROM instance_ring_reports
WHERE reported_at > now() - $3::interval;
```

An instance that is running but not reporting is not counted, so the count falls short of `N` and activation is refused. An instance that is stopped loads the newest ring when it starts. Rows not refreshed for a day are deleted by cleanup. The application role may insert and update this table and nothing else new. The `keymgmt` role may only read it.

### 6.3 Key lifecycle: rotation completed at or after a threshold, and stale allowances (RD-14, CR-10, CR-12)

This section is the single description of what happens to a key's allowances when the key stops being the active key. `security-assessment.md` section 3.6a and `deployment.md` sections 6.1 and 6.4 refer to it.

**Rotation completed after the 2^28 threshold** (or at any other time, the rule is the same). Three phases, so that no instance ever meets ciphertext it cannot decrypt:

1. **Stage the new key (CR-12).** `keys:generate` registers the new key (fingerprint, `key_usage` row), reserves at least one unit, encrypts the self-test value and writes the ring entry with status `STAGED`. A staged key is loaded and can decrypt, but is never used to encrypt. Every instance is restarted, one after another, with a ring that contains the staged key. When all of them have it, every reader can decrypt anything the new key will write.
2. **The new key becomes the active encryption key.** The ring changes the new key to `ACTIVE` and the previous key to `DECRYPT_ONLY` (with `deactivatedAt`). Every instance is restarted again, one after another. During this rolling restart some instances encrypt with the previous key and some with the new one. That is safe, because both are still present and unsealed, and every instance can decrypt both. The ring is read only when a process starts and the active key cannot change while a process runs, so no allowance is ever carried across a ring change.
3. **The previous key is sealed** once every instance runs the ring with the new key `ACTIVE`. Sealing applies to the previous key only.

After step 3:
4. **Outstanding in-memory allowances for the previous key are no longer usable.** Two independent mechanisms: (a) an instance restarted with the new ring has no allowance at all, because allowances live in memory only; (b) an instance that somehow still runs the old ring fails the pre-encryption check as soon as the seal commits, so no request that begins after the seal can encrypt under the previous key.
5. **No ciphertext under the previous key is stored after the seal (CR-13).** The commit-time check (section 6.2) orders every transaction that writes ciphertext against the seal. A transaction that commits before the seal is ordinary use, counted. A transaction that reaches the check after the seal rolls back. So the bound is strict: after `keys:seal` returns, no new ciphertext under the previous key exists in the database. Encryption invocations in rolled-back transactions produce nothing that is stored or returned, and their units are counted, so the counter and the hard stop are unaffected. The rotation procedure can start re-encryption as soon as `keys:seal` returns. No timed drain is needed.
6. **Unused reservations stay counted** against the previous key. Sealing sets the counter to 2^30 and never lowers it, and the units that were reserved but not used remain inside the total. The counter therefore overestimates the previous key's use, and never underestimates it.
7. **No instance may resume encryption under the previous key merely because it holds an allowance.** An allowance is permission to use units that were already counted. It is not permission to use the key. The key must also be the instance's active key (ring) and unsealed (database) when each request begins.
8. A key that has been `DECRYPT_ONLY` never becomes `ACTIVE` again.

**Why this order.** Sealing before every instance has the new ring would make instances that still hold the old ring fail with `503` until restarted. Restarting everything first, then sealing, keeps the service available. If an instance was missed, sealing turns the mistake into an immediate and visible failure rather than a silent continued use of the old key. Staging first prevents the opposite failure: an updated instance writing ciphertext that an instance on the old ring cannot decrypt.

**Restore** differs in two ways. Traffic is stopped for the whole procedure and every instance restarts together, so staging is not needed. The counter may be wrong (too low), so every key of the newest ring as it stood **before** the new key was added is sealed immediately, which also repairs the counter by raising it to the limit. The new key is generated after that set is captured and is not sealed. The set is taken from the ring's permanent `fingerprintHistory`, which lists every identifier ever registered, not only the current ring entries, so a key that was retired early and is absent from both the ring and the restored database is sealed again and its fingerprint row is restored (CR-13).

## 7. Cleanup

Cleanup implements R11.5, R11.6 and R11.11. It is one statement per batch and is safe to repeat and to run concurrently.

```sql
-- Batch of expired games. reference time is clock_timestamp(), expiry rule is >=.
WITH batch AS (
  SELECT id
  FROM games
  WHERE expires_at <= clock_timestamp()
  ORDER BY expires_at
  LIMIT $1                       -- CLEANUP_BATCH_SIZE
  FOR UPDATE SKIP LOCKED
)
DELETE FROM games g
USING batch
WHERE g.id = batch.id
  AND g.expires_at <= clock_timestamp()   -- re-check on the locked row
RETURNING g.id;

-- Maintenance statements, run once per cleanup run:
UPDATE token_rotations
SET token_ciphertext = NULL, token_key_id = NULL
WHERE token_ciphertext IS NOT NULL AND replay_until <= clock_timestamp();

DELETE FROM rate_limits
WHERE ctid IN (SELECT ctid FROM rate_limits
               WHERE refilled_at < clock_timestamp() - interval '1 hour'
               FOR UPDATE SKIP LOCKED);

DELETE FROM instance_ring_reports                   -- reports of instances gone for a day (CR-16)
WHERE reported_at < clock_timestamp() - interval '1 day';
```

Properties:
- **Token invalidation.** Credentials are invalid from `expires_at` by the expiry rule (section 4), independent of cleanup. Deleting the game cascades to credentials. Afterwards presented tokens find no record and receive `401` (C-7). No credential records are retained.
- **Deletion of secret codes, guesses and personal data.** The cascade removes `players` (nicknames), `secret_codes`, `guesses`, `idempotency_keys`, `token_rotations`, `credentials` and `game_results`.
- **Rematch marker.** Deleting an original game cascades to its marker row. Deleting a rematch game updates its marker row (`rematch_game_id` set to null) and leaves the marker, so a deleted rematch never frees the original for another one (R9.4, R9.8). The update needs a lock on the marker row. If another cleanup run holds it, the statement waits up to `lock_timeout` and the batch is retried later. Live requests never wait on it because they do not touch the marker of another game, and no lock cycle is possible (`design.md`, section 8.2).
- **Repeatable.** Each run selects only rows still expired. A second run finds nothing new. A crash leaves either a deleted batch or an untouched batch, because each batch is one transaction.
- **Concurrent with live traffic.** Live requests hold `FOR UPDATE` on the game row. `SKIP LOCKED` leaves in-flight games to a later run. A game refreshed between selection and deletion fails the re-check. Each live request decides expiry under its own lock, so a request cannot succeed on a game that cleanup could delete.
- **Concurrent with itself.** Two runs lock disjoint rows because of `SKIP LOCKED`.
- **Bounded work.** Loop batches until a batch deletes fewer rows than the batch size, then report the total.
- **Dry run.** `--dry-run` runs `SELECT count(*)` with the same predicate and deletes nothing.
- **Logging.** Only counts and durations (R11.8).

Backups retain deleted data until they age out (35 days maximum, R11.9). After a restore, cleanup runs before traffic is accepted (`deployment.md`, section 6).

## 8. Data classification

| Data | Class | Storage | Notes |
|---|---|---|---|
| Nickname | Personal data (possibly) | plaintext `players.nickname` | Deleted with the game. Not shown outside the game |
| Secret code | Sensitive game secret | AES-256-GCM ciphertext | Key outside DB and backups |
| Guess | Sensitive game data | AES-256-GCM ciphertext (ND-7) | Same key ring. Feedback counts, guess numbers and solved flags are plaintext |
| Tokens | Credentials | SHA-256 hash only | Temporary ciphertext of a rotated token during the replay window (R8.13) |
| Request fingerprints | Derived from guesses | HMAC keyed from the key ring | Plain hashes would be reversible (RD-8) |
| Idempotency key and response | Operational | plaintext | Response holds no code and no guess |
| Client IP addresses | Not stored by the application | `rate_limits` rows hold an HMAC only (pseudonymised personal data), deleted one hour after last use, excluded from backups (CH-2) | Proxy logs hold none (`deployment.md`). See `security-assessment.md` section 6.2 |
| Encryption counts | Operational | `key_usage`: one row per key id with the reserved unit total | No personal data |

## 9. Migration strategy

- Plain numbered SQL files in `backend/migrations/`: `0001_init.sql`, `0002_….sql`. Versions are contiguous integers.
- A small runner (`deno task migrate`) applies pending files in order, each in a transaction, records them in `schema_migrations`, and holds `pg_advisory_lock` so concurrent starts cannot race.
- Applied files are immutable. CI rejects edits to existing migration files.
- Forward-only. Reversal is a new migration or a restore from backup. Take a backup before applying migrations in production.
- Migrations run as a one-shot step before the application starts (`deployment.md`). The application refuses to start if the database version is older than the version it expects.
- Compatible changes (add column with default, add table, add index concurrently) are preferred so old and new application instances can overlap during a rolling restart.
- No encryption keys or key material appear in migrations (R10.3).
- CI applies all migrations to an empty database and runs the schema tests (`test-strategy.md`, TS-DB).
