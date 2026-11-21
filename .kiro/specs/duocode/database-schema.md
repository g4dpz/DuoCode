# DuoCode Database Schema and Migrations

Owns: tables, constraints, indexes, migration strategy, retention clock rules, cleanup SQL, rate-limit statement. Related: `requirements.md` (R5, R8 to R11, R20), `design.md` (credential model, authorisation point, lock ordering), `state-machine.md` (states and transitions), `security-assessment.md` (encryption), `deployment.md` (backup and restore).

PostgreSQL is the authoritative store. Tables below are the logical model. Final DDL is written in `backend/migrations/0001_init.sql` during implementation and must match this file. The DDL below was syntax-checked against PostgreSQL 15 in a scratch database during specification review. Behavioural tests are required in implementation (`test-strategy.md`, group TS-DB).

## 1. Entities

```
games 1 ──< players 1 ── 0..1 secret_codes        (encrypted)
  |             |
  |             ├──< guesses 1 ── 1 idempotency_keys   (encrypted guess, keyed fingerprint)
  |             ├──< credentials (ACCESS, REMATCH)
  |             └──< token_rotations                    (encrypted replay copy of new token)
  ├──< credentials (INVITATION; REMATCH of this original game)
  ├── 0..1 game_results
  └── 0..1 games (rematch_of, cleared when the original is deleted)

rate_limits (independent, shared by all instances)
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
  rematch_of    uuid UNIQUE REFERENCES games(id) ON DELETE SET NULL,   -- at most one existing rematch per game
  config        jsonb NOT NULL,                         -- {positions, symbols, maxGuesses} at creation
  created_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz,
  expires_at    timestamptz NOT NULL,                   -- retention clock, rules in section 5
  CHECK ((state = 'COMPLETED') = (completed_at IS NOT NULL)),
  CHECK (rematch_of IS NULL OR rematch_of <> id)
);
CREATE INDEX games_expires_idx ON games (expires_at);

CREATE TABLE players (
  id            uuid PRIMARY KEY,
  game_id       uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  seat          smallint NOT NULL CHECK (seat IN (1,2)),
  nickname      text NOT NULL
                CHECK (char_length(nickname) BETWEEN 1 AND 24)             -- code points (UTF-8 database)
                CHECK (nickname !~ E'[\\u0001-\\u001F\\u007F-\\u009F]'),    -- no Cc characters (NUL cannot occur in text)
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
- `rematch_of` uses `ON DELETE SET NULL`. When an original game is deleted the rematch continues (R9.8).
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
| At most one existing rematch per game | `UNIQUE (rematch_of)` | `REMATCH_ALREADY_CREATED` mapping |
| One live access token per player | Partial unique index | Atomic rotation |
| One live rematch capability per player | Partial unique index | Revocation on mint and rotation |
| One invitation per game | Partial unique index | Single-use consumption |
| Credential belongs to a player of its own game | Composite foreign key `(player_id, game_id)` | |
| Result at most once per game | `game_results` primary key | Result only for `COMPLETED` games |
| Completed state has a completion time | `CHECK` on `games` | |
| Nickname length and control characters | `CHECK` constraints | Trim, empty, malformed Unicode |
| Rate-limit bucket unique per subject | Primary key `(scope, subject)` | |

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

## 6. Rate limiting statement (R20)

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
- IP buckets run in their own short autocommit statement before anything else. Credential buckets run once inside the request transaction after the game lock (lock order in `design.md`, section 8).
- Subjects: `HMAC-SHA-256(RATE_LIMIT_HMAC_KEY, ip)` for IP scopes and `SHA-256("rl" || token)` for credential scopes. No raw IP or token is stored (RD-9).
- Rows idle for more than an hour are deleted by cleanup (section 7). A bucket full again behaves like a new one.
- Scope names and values are in `deployment.md`, section 4.

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
```

Properties:
- **Token invalidation.** Credentials are invalid from `expires_at` by the expiry rule (section 4), independent of cleanup. Deleting the game cascades to credentials. Afterwards presented tokens find no record and receive `401` (C-7). No credential records are retained.
- **Deletion of secret codes, guesses and personal data.** The cascade removes `players` (nicknames), `secret_codes`, `guesses`, `idempotency_keys`, `token_rotations`, `credentials` and `game_results`.
- **Rematch link.** The `ON DELETE SET NULL` action updates the rematch game's `rematch_of` (R9.8). That update needs a lock on the rematch game row. If a live request holds it, cleanup waits up to `lock_timeout` and the batch is retried later (`design.md`, section 8).
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
| Client IP addresses | Not stored by the application | rate-limit rows hold an HMAC only | Proxy logs hold none (`deployment.md`) |

## 9. Migration strategy

- Plain numbered SQL files in `backend/migrations/`: `0001_init.sql`, `0002_….sql`. Versions are contiguous integers.
- A small runner (`deno task migrate`) applies pending files in order, each in a transaction, records them in `schema_migrations`, and holds `pg_advisory_lock` so concurrent starts cannot race.
- Applied files are immutable. CI rejects edits to existing migration files.
- Forward-only. Reversal is a new migration or a restore from backup. Take a backup before applying migrations in production.
- Migrations run as a one-shot step before the application starts (`deployment.md`). The application refuses to start if the database version is older than the version it expects.
- Compatible changes (add column with default, add table, add index concurrently) are preferred so old and new application instances can overlap during a rolling restart.
- No encryption keys or key material appear in migrations (R10.3).
- CI applies all migrations to an empty database and runs the schema tests (`test-strategy.md`, TS-DB).
