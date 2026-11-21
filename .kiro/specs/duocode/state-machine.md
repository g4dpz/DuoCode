# DuoCode State Machines

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
| Mint rematch capability | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | `GAME_NOT_COMPLETED` | ok | `GAME_EXPIRED` |
| Create rematch (capability) | not applicable | not applicable | not applicable | ok, while no rematch exists | `GAME_EXPIRED` |

`CODE_ALREADY_SET` applies to a player who has already set a code. In `ACTIVE` both codes are set, so every submission gets that error.

Validation errors (`INVALID_CODE`, `INVALID_GUESS`, `INVALID_NICKNAME`, `INVALID_IDEMPOTENCY_KEY`, `INVALID_REQUEST`) are returned before any state is read or written (R4.4).

### 1.3 Order of checks

For a state-changing request the service applies checks in this order. The first failure decides the response.

1. Request validation and IP rate limit (before the transaction): body, path, headers, nickname rules.
2. Begin transaction. Lock the game row (`design.md` section 8).
3. Authorisation point (`design.md` section 5): read the reference time, look up the credential, evaluate type, revocation, consumption and expiry in the order of `database-schema.md` section 4. Apply the credential rate limit.
4. For guesses and rotation: idempotency lookup, replay or `IDEMPOTENCY_CONFLICT` (R5.9).
5. Game state (`GAME_NOT_ACTIVE`, `GAME_COMPLETED`, `GAME_FULL`, …).
6. Player rules (`ALREADY_SOLVED`, `ATTEMPTS_EXHAUSTED`, `CODE_ALREADY_SET`).
7. Apply changes and commit.

For operations without a game id in the path (create rematch), the credential is looked up once without a lock to find the original game, the game is locked, and the authorisation point runs again under the lock. Only the second result counts.

### 1.4 Reads

Reads (status, progress, results) do not lock the game row. Each runs in one read-only `REPEATABLE READ` transaction. The authorisation point is the first statement, and all later statements in that transaction see the same committed state, so credential validity, expiry, game state and data are mutually consistent (R8.12).

Consequences, all intended:
- A read that began before a rotation committed may complete with the old token. It behaves as if it ran just before the rotation.
- A read that begins after the commit cannot use the old token.
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
| Mint rematch capability | Existing `LIVE` capability for the same player, if any, `→ REVOKED` (reason `SUPERSEDED`). New capability `LIVE`. Game must be `COMPLETED` |
| Create rematch | Capability `LIVE → CONSUMED`. New game, new seat 1 player, new access token and new invitation, all `LIVE`. The original game's other credentials are untouched. At most one rematch exists per original game |
| Game reaches `expires_at` | All credentials of the game become `EXPIRED` at once |
| Cleanup | Credentials deleted with the game |

Rules:
- A `REVOKED` or `CONSUMED` credential never becomes `LIVE` again.
- A write request that passed any earlier check before a rotation committed fails the authorisation point after it, because the authorisation point runs under the game lock (R8.7). Callers see `401 INVALID_CREDENTIALS`.
- Two simultaneous rotations from the same token serialise on the game lock. The first revokes the token. The second fails verification, unless it carries the same idempotency key, in which case it is a replay (section 3.1). Exactly one new token results.
- Two simultaneous rematch creations from the two players serialise on the original game lock. The second sees the existing rematch and gets `REMATCH_ALREADY_CREATED` (R9.4). The unique constraint on `rematch_of` is the backstop.
- Tokens of the original game never authorise the rematch game, and the reverse (R9.3). Each credential record is bound to exactly one game by a composite foreign key.
- No transition re-issues a lost token. The rotation replay below is not a recovery mechanism, because it needs the old token and the original key (R8.9).

### 3.1 Idempotent rotation (ND-4, R8.13)

Request: `POST /games/{gameId}/access-token/rotate` with `Authorization: Bearer <access token P>` and `Idempotency-Key: K`. The fingerprint is the SHA-256 of the RFC 8785 form of `{"operation":"rotateAccessToken","gameId":…,"body":{"fromCredentialId":<id of P>}}`.

Evaluation under the game lock, after the expiry check:

| Presented token P | Rotation record for (player, K) | Result |
|---|---|---|
| `LIVE` access token | none | Rotate. Create rotation record. `201` with the new token |
| `LIVE` access token | exists (from an older token) | `409 IDEMPOTENCY_CONFLICT`, nothing changes |
| `REVOKED` with reason `ROTATED`, and rotation record `from = P` exists | key equals the record's key, fingerprint matches, reference time `<` `replay_until`, ciphertext present, `to` credential still `LIVE` | Replay. Decrypt and return the same new token, `201`, `Idempotent-Replay: true`. No state change |
| `REVOKED` with reason `ROTATED` | any other case (wrong key, window over, new token itself revoked) | `401 INVALID_CREDENTIALS` |
| Any other unknown, revoked, consumed or wrong-type token | any | `401 INVALID_CREDENTIALS` |

The old token has no power outside this table. After the window the ciphertext is cleared (cleanup, and ignored by the rule above even before clearing). A client that loses the response retries with the same token and the same key, up to the window (10 minutes by default).

Cases covered by this design:
- The response is lost in transit: retry gets the same new token.
- The client crashed before storing the new token and restarts within the window: it needs its stored old token and the key. A client must persist both before sending.
- The response is lost and the window passes: the seat is lost (R8.9).
- Retries with the new token as P and the same K: `409` (different `fromCredentialId`).

## 4. Rematch sequence

```
Player A (original game, COMPLETED)                         Server
  POST /games/{id}/rematch-capability   (Bearer dca_A)  -->  mint dcr_A, revoke any older dcr for A
  <-- dcr_A
  POST /rematches {nickname}            (Bearer dcr_A)  -->  lock original game
                                                             rematch exists? -> 409 REMATCH_ALREADY_CREATED
                                                             consume dcr_A
                                                             create game N (rematch_of = id)
                                                             seat 1 player A', token dca_A' (new)
                                                             invitation dci_N (new)
  <-- gameId N, dca_A', dci_N

Player A shares gameId N and dci_N with Player B outside the API (any channel).
Player B:  POST /games/{N}/join {dci_N, nickname}  -->  seat 2, new dca_B'
```

Player B's old capability, if minted, yields `REMATCH_ALREADY_CREATED` while the rematch exists. The original game's status shows only `rematchCreated: true`.

Deletion behaviour (R9.8):
- If the original game is deleted first, `rematch_of` of the rematch becomes null and the rematch continues. The original's capabilities are deleted with it.
- If the rematch game is deleted first (for example an unjoined rematch after 7 days) while the original is still retained, `rematchCreated` becomes false and a new capability can create another rematch (RD-6).
- Rotation of an access token of the original revokes that player's unused capability (R8.6). The player mints a new one.

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
| Rematch by both players | Original game lock. One `201`, one `409`. `UNIQUE (rematch_of)` backstop |
| Rematch while cleanup deletes the original | Cleanup skips the locked row. If cleanup wins, the rematch request finds no credential and gets `401` |
| Cleanup and live traffic | `SKIP LOCKED` and expiry re-check on the locked row |
| Re-encryption and live traffic | Same game lock. One whole game per transaction |
