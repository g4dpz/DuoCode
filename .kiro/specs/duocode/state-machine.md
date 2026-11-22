# DuoCode State Machines (revision 3.1)

Owns: game states, player-challenge states, credential lifecycle, expiry rule, transition tables. Related: `requirements.md` (R2 to R9, R11), `database-schema.md` (columns and lookup), `design.md` (authorisation point, transaction order, lock ordering), `../../../openapi/openapi.yaml` (error codes and statuses).

## 1. Game states

| State | Meaning | Stored |
|---|---|---|
| `WAITING_FOR_PLAYER` | Created, seat 2 not joined | yes |
| `WAITING_FOR_CODES` | Both joined, at least one code missing | yes |
| `ACTIVE` | Both joined, both codes set | yes |
| `COMPLETED` | Both players finished, result stored | yes |
| `EXPIRED` | Reference time is at or after `expires_at` | no, derived |

Invariant: `ACTIVE` if and only if two players exist and two codes exist and the game is not completed.

```
create -> WAITING_FOR_PLAYER --join--> WAITING_FOR_CODES --both codes set--> ACTIVE --both players finished--> COMPLETED

reference time >= expires_at in any state -> EXPIRED (terminal, derived, then deleted by cleanup)
```

Seat 1 may set its code in `WAITING_FOR_PLAYER`. After seat 2 joins, the game is `WAITING_FOR_CODES` until both codes exist. The second code submission moves it to `ACTIVE`.

### 1.1 Expiry rule (CL-2)

A game is expired when `reference time >= expires_at`. This is the only expiry test. It is applied identically in:
- the authorisation point (database-schema.md section 4),
- every operation (checked again under the game lock for writes),
- cleanup (`expires_at <= clock_timestamp()`).

The reference time is the database clock read once at the authorisation point and used for every decision in the request. Expiry is never evaluated with the application's clock. An expired game rejects every operation and is never modified by a request. Cleanup deletes it. Completed games also reach `EXPIRED` at their retention end.

Responses (C-7): a credential that would otherwise be accepted for an expired game that has not been deleted returns `410 GAME_EXPIRED`. After deletion the credential no longer exists and the response is `401 INVALID_CREDENTIALS`. Joining with a valid invitation of an expired game returns `410`. Joining with an invitation of a deleted game returns `404 INVALID_INVITATION`.

### 1.2 Action by state

| Action | `WAITING_FOR_PLAYER` | `WAITING_FOR_CODES` | `ACTIVE` | `COMPLETED` | `EXPIRED` |
|---|---|---|---|---|---|
| Join | ok, to `WAITING_FOR_CODES` | `GAME_FULL` | `GAME_FULL` | `GAME_FULL` | `GAME_EXPIRED` |
| Submit code | ok (once per player) | ok (once per player), may move to `ACTIVE` | `CODE_ALREADY_SET` | `GAME_COMPLETED` | `GAME_EXPIRED` |
| Submit guess | `GAME_NOT_ACTIVE` | `GAME_NOT_ACTIVE` | ok, may move to `COMPLETED` | `GAME_COMPLETED` | `GAME_EXPIRED` |
| Status, progress | ok | ok | ok | ok | `GAME_EXPIRED` |
| Results | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | ok | `GAME_EXPIRED` |
| Rotate access token | ok | ok | ok | ok | `GAME_EXPIRED` |
| Mint rematch capability | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | ok, unless a rematch marker exists (`REMATCH_ALREADY_CREATED`) | `GAME_EXPIRED` |
| Create rematch (capability) | not applicable | not applicable | not applicable | ok once. Every unused capability is revoked on success, so later attempts get `401` | `GAME_EXPIRED` |

`CODE_ALREADY_SET` applies to a player who has already set a code. In `ACTIVE` both codes are set, so every submission gets that error.

Validation errors (`INVALID_CODE`, `INVALID_GUESS`, `INVALID_NICKNAME`, `INVALID_IDEMPOTENCY_KEY`, `INVALID_REQUEST`) are returned before any state is read or written (R4.4).

### 1.3 Order of checks (writes)

For a state-changing request the service applies checks in this order. The first failure decides the response.

1. Request validation (body, path, headers, nickname rules, idempotency key format). A malformed request is rejected here, before anything is read or written.
2. Preliminary credential lookup by token hash. It is **not authoritative** and grants nothing. It finds the player (for the rate-limit subject) and rejects a token that does not exist at all with `INVALID_CREDENTIALS`. It also feeds `ip:authfail` when it fails.
3. Rate-limit updates (IP and player buckets), each its own short autocommit transaction. A denial returns `429` and the request goes no further. No lock is held.
4. **Encryption claim, then the pre-encryption check** (only for an operation that may encrypt; CR-23, `design.md` 9.1). Claim the units the operation may need from the instance's allowance, reserving whole blocks first if the allowance is short. Then, as the last step before the transaction, run the pre-encryption check (`database-schema.md` 6.2: the key is not sealed and its registered fingerprint matches the loaded material). If the claim cannot be obtained or the check fails, return the claim and continue with an empty claim. The request is not rejected here, because it may need no encryption (step 10 decides).
5. Begin transaction. Lock the game row (`design.md` section 8).
6. Authoritative credential validation (the authorisation point, `design.md` section 5.1): read the reference time, look up the credential, evaluate type, revocation, consumption and expiry in the order of `database-schema.md` section 4. A credential found valid in step 2 but revoked since fails here.
7. For guesses and rotation: idempotency lookup, replay or `IDEMPOTENCY_CONFLICT` (R5.9).
8. Game state (`GAME_NOT_ACTIVE`, `GAME_COMPLETED`, `GAME_FULL`, …).
9. Player rules (`ALREADY_SOLVED`, `ATTEMPTS_EXHAUSTED`, `CODE_ALREADY_SET`, `REMATCH_ALREADY_CREATED`).
10. **Encryption availability** (only for an operation that needs a fresh encryption): if the operation holds no claimed unit (the pre-encryption check failed, the key is sealed or at the hard stop, or a reservation was refused, all in step 4), end with `503 SERVICE_UNAVAILABLE` and `Retry-After`. Nothing has been written. Steps 7 to 9 are unaffected, so an idempotent replay, a conflict and every rule rejection still get their normal answer even when no unit is available (`design.md` section 9.1).
11. Apply changes, writing any ciphertext with the claimed units (each unit is consumed before the cipher is called).
12. **Commit-time check** (only for a transaction that wrote ciphertext; CR-23, `database-schema.md` 6.2): immediately before `COMMIT`, run `SELECT sealed FROM key_usage WHERE key_id = $1 FOR SHARE`. If the key has been sealed, roll back and end with `503 SERVICE_UNAVAILABLE`. The consumed units stay counted. Otherwise commit. After the request, return any claimed units it did not consume.

For operations without a game id in the path (create rematch), step 2 finds the original game, step 5 locks it, and step 6 re-validates under the lock. Only the step 6 result counts.

A retry of the transaction (`design.md` 8.2) is a fresh attempt: it leaves the transaction and repeats from step 4 with a new claim and a new pre-encryption check.

Operations without a credential (create game, join) skip steps 2 and 6 and use the IP buckets only. Create game and join encrypt nothing, so they also skip steps 4, 10 and 12. Join authorises the invitation inside the transaction after the game lock, by the same rules.

### 1.4 Reads (CR-2)

Reads (status, progress, results) do not lock the game row. In this order:

1. Request validation.
2. Preliminary credential lookup. Non-authoritative. Grants nothing. Rejects tokens that do not exist.
3. Rate-limit updates, each in its own short autocommit transaction.
4. Begin a read-only `REPEATABLE READ` transaction.
5. Authoritative credential validation as its **first statement** (the authorisation point). A credential revoked or expired by then fails here with `INVALID_CREDENTIALS` or `GAME_EXPIRED`, regardless of steps 2 and 3.
6. Read all requested data in the same transaction, from the same snapshot.
7. For results: verify `state = COMPLETED` from that snapshot first. Only then read the code and guess ciphertext, decrypt and serialise (R7.5, R10.7). Otherwise return `GAME_NOT_COMPLETED` without reading any ciphertext.

Consistency with the revocation model:
- The preliminary lookup and the rate-limit update never decide validity. Only step 5 does, and it uses the same snapshot as the data.
- A rate-limit update made on behalf of a token that is revoked a moment later is harmless: the request then fails at step 5.
- A read that reaches step 4 before a rotation commits is ordered before the rotation and may complete with the old token. A read that reaches step 4 after the commit cannot.
- A read that began before completion returns the pre-completion view. Results are `GAME_NOT_COMPLETED` for it, even if the game completes a moment later.
- A read never extends `expires_at` (ND-5).

## 2. Player challenge states

Per player, for their attempt at the opponent's code. Derived from `players` columns.

| State | Condition |
|---|---|
| `NOT_STARTED` | `guesses_used = 0` |
| `IN_PROGRESS` | `0 < guesses_used < 10` and not solved |
| `SOLVED` | `solved = true` |
| `EXHAUSTED` | `guesses_used = 10` and `solved = false` |

`SOLVED` and `EXHAUSTED` are terminal and mean the player is finished. A guess on the tenth attempt that matches yields `SOLVED` (not exhausted). The game completes when both players are finished (R7.1).

| Event | From | To |
|---|---|---|
| Guess, no match, `guesses_used` becomes `< 10` | `NOT_STARTED`, `IN_PROGRESS` | `IN_PROGRESS` |
| Guess, match | `NOT_STARTED`, `IN_PROGRESS` | `SOLVED` |
| Guess, no match, `guesses_used` becomes `10` | `IN_PROGRESS` | `EXHAUSTED` |
| Guess | `SOLVED` | rejected, `ALREADY_SOLVED` |
| Guess | `EXHAUSTED` | rejected, `ATTEMPTS_EXHAUSTED` |

Outcome when both finished: table in R7.2, implemented by `determineOutcome`.

## 3. Credential lifecycle

Credentials are described in `design.md`, section 5, and stored per `database-schema.md`.

States (derived from columns):

| State | Condition | Authorises |
|---|---|---|
| `LIVE` | `revoked_at IS NULL AND consumed_at IS NULL` and game not expired | its purpose |
| `REVOKED` | `revoked_at IS NOT NULL` (reason `ROTATED`, `SUPERSEDED` or `ROTATION_SIDE_EFFECT`) | nothing, except rotation replay for `ROTATED` access tokens (section 3.1) |
| `CONSUMED` | `consumed_at IS NOT NULL` | nothing |
| `EXPIRED` | game expired and not deleted | nothing. A credential that would be `LIVE` gets `410 GAME_EXPIRED` |
| deleted | game deleted | nothing. `401 INVALID_CREDENTIALS`. No record remains |

Transitions, each in one transaction under the game lock:

| Event | Effect |
|---|---|
| Create game | New access token `LIVE` for seat 1. New invitation token `LIVE` |
| Join | Invitation `LIVE → CONSUMED`. New access token `LIVE` for seat 2 |
| Rotate access token | New access token `LIVE`. Old access token `LIVE → REVOKED` (reason `ROTATED`). The player's unused rematch capability, if any, `→ REVOKED` (reason `ROTATION_SIDE_EFFECT`). Rotation record created with the new token as encrypted ciphertext and `replay_until = reference time + replay window` |
| Rotation replay | No credential changes. Returns the stored new token (section 3.1) |
| Mint rematch capability | Game must be `COMPLETED` and have no rematch marker. Existing `LIVE` capability for the same player, if any, `→ REVOKED` (reason `SUPERSEDED`). New capability `LIVE` |
| Create rematch | Capability `LIVE → CONSUMED`. All other unused capabilities of the original game `LIVE → REVOKED` (reason `SUPERSEDED`, CH-3). New game, new seat 1 player, new access token and new invitation, all `LIVE`. Rematch marker for the original is inserted in the same transaction (its primary key is the backstop). The original game's access tokens are untouched. At most one rematch is ever created per original game |
| Game reaches `expires_at` | All credentials of the game become `EXPIRED` at once |
| Cleanup | Credentials deleted with the game |

Rules:
- A `REVOKED` or `CONSUMED` credential never becomes `LIVE` again.
- A write request that passed any earlier check before a rotation committed fails the authorisation point after it, because the authorisation point runs under the game lock (R8.7). Callers see `401 INVALID_CREDENTIALS`.
- Two simultaneous rotations from the same token serialise on the game lock. The first revokes the token. The second fails verification, unless it carries the same idempotency key, in which case it is a replay (section 3.1). Exactly one new token results.
- Two simultaneous rematch creations from the two players serialise on the original game lock. The first to take the lock creates the rematch and revokes every unused capability. The second then fails the authorisation point with `401 INVALID_CREDENTIALS` (R9.9, CH-3). If anything else reached the marker insert, its primary key would reject it with `REMATCH_ALREADY_CREATED` (R9.4).
- Tokens of the original game never authorise the rematch game, and the reverse (R9.3). Each credential record is bound to exactly one game by a composite foreign key.
- No transition re-issues a lost token. The rotation replay below is not a recovery mechanism, because it needs the old token and the original key (R8.9). It also never restores the old token (section 3.1).

### 3.1 Idempotent rotation (ND-4, R8.13, CR-3)

Request: `POST /games/{gameId}/access-token/rotate` with `Authorization: Bearer <access token P>` and `Idempotency-Key: K`.

**Key.** `K` must be a version 4 UUID (version nibble `4`, variant `10xx`) generated from a cryptographically secure random source. The server validates the format only. It cannot check where the randomness came from, so the client requirement is stated in the API documentation. The reason for the stricter rule: for rotation `K` is also the replay secret, so it needs the 122 random bits of a v4 UUID. For guess submission `K` is only a deduplication label, so the general rule (any UUID version) applies there (R5.1). A malformed key or another version returns `INVALID_IDEMPOTENCY_KEY` before any state is read.

**Fingerprint.** SHA-256 of the RFC 8785 form of `{"operation":"rotateAccessToken","gameId":…,"body":{"fromCredentialId":<id of P>}}`. It holds only random identifiers.

Evaluation under the game lock, after the expiry check:

| Presented token P | Rotation record for (player, K) | Result |
|---|---|---|
| `LIVE` access token | none | Rotate. Create rotation record. `201` with the new token |
| `LIVE` access token | exists (made from an older token) | `409 IDEMPOTENCY_CONFLICT`, nothing changes |
| `REVOKED` with reason `ROTATED`, and rotation record with `from = P` exists | key equals the record's key, fingerprint matches, reference time `<` `replay_until`, ciphertext present, `to` credential still `LIVE` | Replay. Decrypt and return the original response, the same new token, `201`, `Idempotent-Replay: true`. **No state change** |
| `REVOKED` with reason `ROTATED` | any other case (wrong key, window over, new token itself revoked) | `401 INVALID_CREDENTIALS` |
| Any other unknown, revoked, consumed or wrong-type token | any | `401 INVALID_CREDENTIALS` |

**Conditions for returning the replacement token (RD-11, approved).** All five must hold: (a) the original token is presented, (b) the original UUIDv4 key is presented, (c) the request fingerprint matches, (d) the replay window is still valid at the reference time, (e) the replacement token has not been revoked. The replacement token is decrypted only after all five hold and never appears in logs, diagnostics, metrics, traces or error responses.

**What a replay does and does not do.**
- It returns the original response, the same new token, byte for byte.
- It does not restore, reactivate or un-revoke the old token. The `credentials` row of P keeps `revoked_at` and reason `ROTATED`. No column of any row changes, `expires_at` is unchanged, and no rotation record is created or extended.
- The old token has no power outside this table. Presented to any other operation (including a rotation with another key), it receives `401`.
- Window: `replay_until = reference time of the rotation + ROTATION_REPLAY_SECONDS` (600 by default, RD-3). After it, the replay row is ignored even if the ciphertext still exists. Cleanup clears the ciphertext.

**Consequences of losing the replacement token.**
- Inside the window: retry with the old token and the same key. The same new token comes back.
- After the window: the replacement token is lost for good. The old token is revoked and cannot be used. The server has deleted its stored copy. There is no recovery path for anyone, including the operator. The player loses the seat. The opponent and the game are unaffected, and the game expires at its retention end.
- Clients must persist the old token and the key before sending, persist the new token as soon as it arrives, and retry promptly with backoff.

Cases covered:
- The response is lost in transit: retry gets the same new token.
- The client crashed before storing the new token and restarts within the window: it needs its stored old token and the key.
- The response is lost and the window passes: the seat is lost.
- A retry using the new token as P with the same K: `409`.

## 4. Rematch sequence

```
Player A (original game, COMPLETED)                         Server
  POST /games/{id}/rematch-capability   (Bearer dca_A)  -->  no rematch marker?  mint dcr_A, revoke any older dcr for A
  <-- dcr_A                                                   marker exists?       409 REMATCH_ALREADY_CREATED
  POST /rematches {nickname}            (Bearer dcr_A)  -->  lock original game, authorise dcr_A
                                                             consume dcr_A, revoke every other unused capability of the original
                                                             create game N
                                                             insert rematch marker (original = id, rematch = N)
                                                             seat 1 player A', token dca_A' (new)
                                                             invitation dci_N (new)
  <-- gameId N, dca_A', dci_N

Player A shares gameId N and dci_N with Player B outside the API (any channel).
Player B:  POST /games/{N}/join {dci_N, nickname}  -->  seat 2, new dca_B'
```

Player B's capability, if minted before, was revoked in the rematch transaction, so using it yields `401`. Any attempt to mint a new one yields `409 REMATCH_ALREADY_CREATED`. The original game's status shows `rematchCreated: true`, which is how B finds out. It never shows the new game's id or credentials.

Deletion behaviour (R9.8, RD-6):
- **One rematch ever.** The marker is a row keyed by the original game. It stays after the rematch game is deleted (for example an unjoined rematch after 7 days). `rematchCreated` stays true and no further rematch can be created for that original. This is deliberate.
- **Rematch deleted first.** The marker's `rematch_game_id` is set to null. The marker stays.
- **Original deleted first.** The marker, the original's credentials and capabilities are deleted with it. The rematch game has no foreign key to the original and continues as an ordinary game. Its `rematchOf` is derived from the marker and so disappears.
- Rotation of an access token of the original revokes that player's unused capability (R8.6). The player mints a new one if no marker exists.

## 5. Results after rotation (R8.14)

The results are bound to the player and the game, not to a token. After a rotation the player reads results with the current access token. The revoked token cannot read results, and a rotation changes nothing in the data. Rotating after the game has completed is allowed, and does not extend `expires_at`.

## 6. Concurrency summary

Lock order and deadlock avoidance are in `design.md` section 8. Test scenarios are in `test-strategy.md` (TS-CONC).

| Race | Resolution |
|---|---|
| Two joins | Game lock. First consumes the invitation. Second gets `GAME_FULL`. `UNIQUE (game_id, seat)` backstop |
| Both players guess at once | Game lock serialises. Each player's counts are independent. Completion is computed by whichever commits second, exactly once |
| Duplicate guess requests | Game lock, then idempotency lookup. One guess recorded. Primary key and `UNIQUE (guess_id)` backstop |
| Final guess and expiry | Expiry decided at the reference time under the lock. Whichever acquires the lock first wins consistently |
| Rotation and a guess | Game lock. A guess after the rotation commit with the old token fails verification |
| Two rotations | Game lock. One rotates, the other is a replay (same key) or `401` or `409` |
| Rotation retry racing the original | Original holds the lock first. The retry then replays |
| Rematch by both players | Original game lock. One `201`. The loser's capability is revoked by the winner's transaction, so the loser gets `401`. Primary key of `rematch_markers` is the backstop (`409`) |
| Rematch while cleanup deletes the original | Cleanup skips the locked row. If cleanup wins, the rematch request finds no credential and gets `401`. The marker goes with the original |
| Cleanup deleting a rematch game while the original is active | Marker `rematch_game_id` cleared. The marker row stays |
| Cleanup and live traffic | `SKIP LOCKED` and expiry re-check on the locked row |
| Re-encryption and live traffic | Same game lock. One whole game per transaction |
