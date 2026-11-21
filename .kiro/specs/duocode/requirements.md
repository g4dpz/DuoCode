# DuoCode Requirements (Backend MVP 1), revision 3

Source: `DuoCode-Requirements` v2.0 (baseline, dated 21 November 2026) and the owner decisions in the decision register.
Scope: MVP 1, a backend-only game playable through the REST API. The web application, PWA, white-label and multi-tenant work are out of scope.

Status: **draft for owner approval. No implementation is authorised.** Implementation stays unauthorised until all six Phase 1 gates in `tasks.md` are explicitly signed off.

Revision history: revision 2 added the owner decisions OD-1 to OD-10. Revision 3 applies the owner review of revision 2. The change summary is in `revision-3-review-package.md`.

## Specification set

This file owns the requirements and the decision register. Other artefacts own their own definitions and must not redefine them.

| Artefact | Owns |
|---|---|
| `requirements.md` (this file) | Requirements, acceptance criteria, decision register |
| `traceability.md` | Requirement to artefact, API operation, constraint, test and approval-status mapping |
| `design.md` | Architecture overview, layers, credential model, authorisation point, lock ordering, rate-limiting design, configuration keys and defaults |
| `../../../openapi/openapi.yaml` | The wire contract: paths, schemas, status codes, error codes |
| `database-schema.md` | Tables, constraints, migrations, retention clock rules, cleanup SQL |
| `state-machine.md` | Game, player-challenge and credential lifecycles, transition tables, expiry rule |
| `security-assessment.md` | Threats, encryption, key management, rotation implications, logging and metrics rules, residual risks |
| `test-strategy.md` | Test layers, required cases, test group IDs, CI jobs |
| `simulator-design.md` | Simulator behaviour and replay |
| `deployment.md` | Compose stack, secrets, rate-limit values, backups, restore, key recovery, scheduling |
| `revision-3-review-package.md` | Change summary, review checklist, remaining decisions |
| `tasks.md` | Phased tasks and approval gates |

## Glossary

- **Game**: One two-player match with a unique identifier.
- **Player**: A participant in one game, identified by a nickname and held to a game access token. A player has no account.
- **Secret code**: A sequence of 4 symbols chosen from 6. Repeats are allowed.
- **Guess**: A 4-symbol sequence submitted against the opponent's secret code.
- **Feedback**: A pair `(exact, misplaced)` of counts for one guess.
- **Solved**: A player's guess equals the opponent's secret code.
- **Exhausted**: A player has used all 10 guesses without solving.
- **Finished (player)**: A player is solved or exhausted.
- **Game access token**: Bearer credential that authorises one player's actions in one game.
- **Invitation token**: Single-use bearer credential that lets a second player join one game.
- **Rematch capability**: Bearer credential that authorises creating one rematch of one completed game. It grants no access to any game.
- **Credential**: Any of the three tokens above.
- **Reference time**: The database clock value read once at the authorisation point of a request. Every expiry and validity decision in that request uses it.
- **Retention end** (`expires_at`): The instant at or after which a game and everything attached to it is expired.
- **Expired**: `reference time >= expires_at`. The same test applies in authentication, operations and cleanup.
- **Authorisation point**: The single function, called inside each request's database transaction, that decides whether a presented credential is currently valid for the requested operation (design section 5).
- **Rotation replay window**: The short period after a token rotation in which the old token, together with the same idempotency key, can retrieve the new token again (R8.13).
- **Engine**: The pure game-rules module with no HTTP, database, crypto or framework dependency.

## Fixed configuration (MVP 1)

| Parameter | Value |
|---|---|
| Players | 2 |
| Code positions | 4 |
| Symbols | 6 (integers `1`..`6` on the wire; artwork is a client concern) |
| Repeated symbols | Allowed |
| Maximum guesses per player | 10 |
| Feedback | Exact and misplaced counts |

The values live in one configuration object so later work can vary them. MVP 1 does not expose them through the API.

## Decision register

Status values: **Approved** (owner approved, recorded in revision 3 review), **Approved in principle** (approved subject to a pending detail), **Pending** (needs owner decision).

### Owner decisions from revision 2

OD-1 to OD-10 stand as in revision 2: baseline repository layout (OD-1), own code never returned after submission (OD-2), opponent progress limited to counts and flags (OD-3), mandatory `Idempotency-Key` (OD-4), retention defaults (OD-5), application-level encryption (OD-6), separate credentials and no recovery (OD-7), separate specification artefacts (OD-8), date 21 November 2026 correct (OD-9), implementation unauthorised (OD-10). All are Approved.

### Decisions approved in the revision 3 review

| ID | Decision | Status | Applied in |
|---|---|---|---|
| ND-1 | Both secret codes are revealed only by the results endpoint once the game is `COMPLETED`. | Approved | R3.7, R7.4 |
| ND-2 | Rematch flow: the first requester creates the new game and shares the invitation out of band. One rematch per game. | Approved | R9 |
| ND-3 | Separate rematch capability. | Approved | R8.5, R9 |
| ND-4 | Access-token rotation, amended: rotation must be idempotent so a lost response does not lock the player out. Security implications documented. | Approved with amendment | R8.6, R8.13, `security-assessment.md` section 2.2 |
| ND-5 | Only state-changing requests extend the in-progress retention period. | Approved | R11.2 |
| ND-6 | Plain SHA-256 of independently generated 256-bit credentials. | Approved | R8.2 |
| ND-7 | Amended: stored guesses are encrypted with AES-256-GCM using the same key ring as secret codes. Feedback counts, guess numbers and solved or exhausted flags stay in plaintext. Goal: database-only access cannot reconstruct secret codes from guesses and feedback. | Approved with amendment | R4.1, R10, R5.12, `security-assessment.md` section 3 |
| ND-8 | Retention 7, 30 and 180 days. Hourly cleanup. Backups at most 35 days. No player-initiated deletion endpoint in MVP 1. | Approved | R11, R21 |
| ND-9 | Docker-secret-mounted JSON key ring, with documented generation, backup, recovery, rotation and compromise procedures. Old keys stay available as long as any backup containing ciphertext under them may be restored. | Approved with amendment | R10, R21 |
| C-1 | Credentials in `Authorization: Bearer`. Invitation token in the join request body. | Approved | R8 |
| C-2 | No invitation preview endpoint in MVP 1. | Approved | Out of scope |
| C-3 | Duplicate nicknames allowed. | Approved | R1.3 |
| C-4 | Administrative operations limited to metrics and cleanup behind a separate admin token. | Approved | R21 |
| C-5 | No token refresh flow. | Approved | R8 |
| C-6 | Rate limiting in two layers. Approved in principle. Numerical values are recommended in `deployment.md` section 4 for owner approval. | Approved in principle | R20 |
| C-7 | A valid credential of an expired but not yet deleted game returns `410 GAME_EXPIRED`. After deletion the response is `401 INVALID_CREDENTIALS`. Credential records are not retained to preserve the expired response. | Approved with clarification | R8.8, R11.3 |

### Engineering clarifications from the revision 3 review

| ID | Clarification | Applied in |
|---|---|---|
| CL-1 | Every authenticated operation validates current credential status at one authorisation point. Writes recheck under the game-row lock. Reads use one consistent snapshot. | R8.7, R8.11, R8.12 |
| CL-2 | Expiry is `reference time >= expires_at` everywhere. | R11.3 |
| CL-3 | Encryption documentation: key identifiers, nonce uniqueness, AAD, transactional re-encryption, backup recovery, key retirement. | R10, `security-assessment.md` section 3 |
| CL-4 | Rate limiting is shared across instances, using PostgreSQL, plus coarse IP limits at the proxy. Redis is not required. | R20 |
| CL-5 | Nickname validation: trim, reject empty, at most 24 code points, reject control characters, preserve the accepted value, allow duplicates. | R1.3 |
| CL-6 | Idempotency fingerprints use RFC 8785 JSON Canonicalization Scheme. | R5.12 |
| CL-7 | Database constraints enforce player limits, guess limits, rematch uniqueness and idempotency wherever practical. | R5.10, R9.4, `database-schema.md` section 3 |
| CL-8 | Lock ordering and deadlock avoidance documented. Join, guess, rotation, rematch and cleanup races are tested. | `design.md` section 8, R17 |

### Decisions awaiting owner approval

These arose while applying revision 3. Each has a proposal that the drafts assume. None is final until approved. The review package repeats this list with the owner action needed.

| ID | Decision needed | Proposal |
|---|---|---|
| RD-1 | Stock Caddy has no rate-limit module. | Build Caddy with the `caddy-ratelimit` plugin (xcaddy) for the coarse IP limits. Fallback: Nginx with `limit_req`, which the baseline allows. |
| RD-2 | Numerical rate limits, failure mode, and the failed-credential policy. | Values in `deployment.md` section 4. If the limiter cannot reach the database the request fails closed with `503`. The earlier "5-minute block" after failed credential checks is replaced by a token-bucket throttle. |
| RD-3 | Rotation replay window length, and effect of rotation on the player's rematch capability. | Window 10 minutes (configurable). Rotation also revokes the player's unused rematch capability, in the same transaction. |
| RD-4 | Where the admin interfaces are served. | A separate admin listener on the internal network only. The public proxy does not route `/admin/*`. |
| RD-5 | Nickname control-character scope. | Reject Unicode general category `Cc` as instructed, and also reject malformed Unicode (lone surrogates). Format characters (category `Cf`, for example bidirectional overrides) are allowed unless you decide otherwise. |
| RD-6 | Rematch slot after the rematch game is deleted. | If the rematch game is deleted while the original still exists, the original can have a new rematch. Deleting the original leaves the rematch playable and clears its link. |
| RD-7 | Point-in-time recovery for the database. | Not in MVP 1. A restore returns credential state to the backup time. Players who rotated since then lose their seat, and previously rotated-away tokens become valid again. Documented in `deployment.md` section 6. |
| RD-8 | Guess fingerprints cannot be plain hashes because a hash of one of 1296 possible guesses is trivially reversible, which would defeat ND-7. | Fingerprints for guess requests are HMAC-SHA-256 over the canonical form, keyed from the key ring with HKDF. They are re-keyed together with ciphertext during re-encryption. |
| RD-9 | Client IP source and storage for rate limiting. | Take the client IP from the proxy header only for requests arriving from configured proxy addresses. Store only an HMAC of the IP, keyed by a separate secret, never the address. |
| RD-10 | Nonce safety margin. | Random 96-bit nonces. Alert when any key has encrypted 2^28 values and rotate that key. The NIST limit for random nonces is 2^32. |

## Requirements

Acceptance criteria use EARS wording. Baseline references (FR-nnn, SIM-nnn, SCALE-nnn, section numbers) are in brackets. Requirements R1 to R19 keep their revision 2 numbers. R20 and R21 are new.

### R1: Game creation

1. WHEN a client creates a game with a valid nickname, THE system SHALL create a game in state `WAITING_FOR_PLAYER`, create the creator as seat 1, and return the game id, a game access token, an invitation token and the retention end. (FR-001 to FR-005)
2. THE system SHALL generate game ids and tokens from a cryptographically secure random source (credential format in `design.md`). (FR-002, 5.3)
3. THE system SHALL validate every nickname (create, join and rematch) as follows, and reject a failing value with `INVALID_NICKNAME` without creating or changing anything (CL-5, C-3):
   a. Trim leading and trailing Unicode white space (code points with the `White_Space` property).
   b. Reject the result if it is empty.
   c. Reject the result if it is longer than 24 Unicode code points (not UTF-16 units and not bytes).
   d. Reject the result if it contains any code point in Unicode general category `Cc` (U+0000 to U+001F and U+007F to U+009F), and reject malformed Unicode such as unpaired surrogates (RD-5).
   e. Store and return the trimmed value exactly as accepted, with no case folding, normalisation or changes to interior characters.
   f. Permit duplicates, including two players in one game with the same nickname.
4. THE system SHALL return each token in plaintext only in the response that creates it, and SHALL store only token hashes (exception: R8.13).

### R2: Joining

1. WHEN a client presents a valid, unused invitation token for the game and a valid nickname, THE system SHALL add the client as seat 2, consume the invitation, and return a new game access token. (FR-004, FR-015)
2. IF the game already has two players or the invitation is consumed, THEN THE system SHALL reject the join with `GAME_FULL`. (9.4)
3. IF the invitation token is invalid, unknown, or belongs to a different game, or the game does not exist (including after deletion), THEN THE system SHALL reject it with `INVALID_INVITATION` and the same response shape and status in each case. (7.4)
4. IF the invitation is valid and the game is expired but not yet deleted, THEN THE system SHALL reject the join with `410 GAME_EXPIRED` (C-7).
5. WHEN two clients join the same game at once, THE system SHALL admit exactly one. A database constraint SHALL backstop the limit of two players. (FR-024)

### R3: Secret code submission and privacy

1. WHEN a player submits a code of 4 symbols, each in 1..6, THE system SHALL store it encrypted (R10) for that player. (FR-006)
2. IF a code has the wrong length or a symbol outside 1..6, THEN THE system SHALL reject it without changing state. (9.2)
3. IF the player has already submitted a code, THEN THE system SHALL reject the request with `CODE_ALREADY_SET`. A code is immutable once set.
4. THE system SHALL accept a code from seat 1 before seat 2 has joined.
5. WHEN both players have joined and both have submitted codes, THE system SHALL change the game to `ACTIVE` in the same transaction as the second event. (FR-007)
6. THE response to a code submission SHALL NOT contain the submitted code. (OD-2)
7. THE system SHALL NOT return any secret code, own or opponent's, from any endpoint before the game is `COMPLETED`. Only the results endpoint returns codes. (OD-2, ND-1, 3.8)

### R4: Guessing and feedback

1. WHEN a player submits a valid guess to an `ACTIVE` game, THE system SHALL compare it with the opponent's secret code, store the guess encrypted (R10) with its plaintext feedback counts, increment that player's guess count and return the guess number and feedback. (FR-008, FR-009, ND-7)
2. THE feedback calculation SHALL count exact matches first, then count misplaced matches from the remaining symbols, and SHALL NOT count any symbol more often than it occurs in either code. (3.4)
3. THE feedback SHALL contain only the exact count and misplaced count, not per-position information. (3.3)
4. IF a guess is invalid (wrong length, symbol out of range, malformed body, missing or malformed idempotency key), THEN THE system SHALL reject it without changing the guess count or any other state. (FR-021)
5. IF the player has used 10 guesses, THEN THE system SHALL reject further guesses with `ATTEMPTS_EXHAUSTED`. (FR-020)
6. IF the player has already solved, THEN THE system SHALL reject further guesses with `ALREADY_SOLVED`.
7. IF the game is not `ACTIVE`, THEN THE system SHALL reject guesses with `GAME_NOT_ACTIVE`, `GAME_COMPLETED` or `GAME_EXPIRED` as appropriate. (FR-022)
8. WHEN a guess equals the opponent's code, THE system SHALL mark the player solved and record guesses used.
9. WHEN a player uses the tenth guess without solving, THE system SHALL mark the player exhausted.
10. THE system SHALL let a player guess only the opponent's code. No request form SHALL target the player's own code. (9.4)
11. THE system SHALL let each player guess independently, in any order and at any time. (3.6)

### R5: Idempotency and concurrency

1. THE guess endpoint SHALL require an `Idempotency-Key` header whose value is a UUID in canonical text form (8-4-4-4-12 hexadecimal digits, case-insensitive, any version). THE system SHALL reject a missing or malformed key with `INVALID_IDEMPOTENCY_KEY`. (OD-4)
2. THE scope of uniqueness SHALL be the triple (acting player, operation, key). A key is therefore unique per player and per game, because a player belongs to one game, and per operation. The same key value used by the other player, in another game or for another operation is unrelated and SHALL NOT conflict or leak information.
3. THE system SHALL recognise a duplicate by looking up (acting player, operation, key) inside the operation's transaction, after taking the game lock.
4. WHEN a duplicate key arrives with the same request fingerprint, THE system SHALL return the stored original status and body unchanged, with the header `Idempotent-Replay: true`, and SHALL NOT record a guess, change a count or change any other state.
5. WHEN a duplicate key arrives with a different fingerprint, THE system SHALL reject it with `409 IDEMPOTENCY_CONFLICT` and change nothing.
6. THE system SHALL store a key and its response only when the guess succeeded, in the same transaction as the guess. A rejected request (validation, state, attempts) stores nothing, so its key stays free for a corrected request.
7. THE system SHALL keep each key and response until the game is deleted (R11). With at most 10 guesses per player the storage is bounded, and keeping keys for the whole game means a late retry can never consume a second attempt.
8. THE replayed response SHALL be the original response, including the `gameState` and `guessesRemaining` values it carried when first produced, even when the game has since changed.
9. A replay SHALL be checked before game-state and attempt checks, so a retry of the completing guess still returns the original response after the game is `COMPLETED`. A replay still requires a valid credential for the game and a game that is not expired.
10. WHEN concurrent or duplicate requests arrive, THE system SHALL guarantee that no more than one attempt is consumed per distinct key, that guess numbers are contiguous from 1, that no guess follows a solving guess, and that the count never exceeds 10. Database constraints SHALL enforce these rules (CL-7): the unique key and range on guess numbers, a foreign key to the previous guess for contiguity and for "no guess after solved", and the primary key on idempotency records. (FR-023, FR-024)
11. WHEN a request fails part-way, THE system SHALL leave no partial update. All state changes for one request SHALL commit in one database transaction. (5.2)
12. THE request fingerprint SHALL be computed from the envelope `{"operation": <name>, "gameId": <lowercase uuid>, "body": <parsed request body>}` serialised with RFC 8785 JSON Canonicalization Scheme (JCS), so that equivalent bodies (key order, whitespace, escapes) give the same fingerprint. THE system SHALL reject request bodies with duplicate member names before fingerprinting. For guess requests the fingerprint SHALL be an HMAC-SHA-256 keyed from the key ring (RD-8), because an unkeyed hash of one of 1296 possible guesses could be reversed by a database reader. (CL-6)

### R6: Status and progress

1. WHEN an authorised player requests game status, THE system SHALL return the game state, both nicknames, whether each player has joined and has set a code, whether a rematch exists, the retention end, and the opponent's progress summary (R6.3). (FR-010)
2. WHEN an authorised player requests progress, THE system SHALL return that player's own guesses with feedback, guesses used, guesses remaining, and solved and exhausted flags. (FR-010)
3. THE opponent progress summary SHALL contain only the opponent's total guesses used, whether they solved, and whether they exhausted their attempts. THE system SHALL NOT return the opponent's individual guesses or feedback until the game is `COMPLETED`. (OD-3)
4. THE system SHALL NOT expose database identifiers, token hashes or other internal fields. (7.1)
5. THE system SHALL NOT require long-lived connections. Clients poll. (5.1, 12.3)

### R7: Completion and results

1. WHEN both players are finished, THE system SHALL change the game to `COMPLETED`, compute the outcome, set the retention end to completion time plus the completed-game period, and store the result, all in the same transaction as the final guess. (FR-011, 3.6)
2. THE outcome SHALL follow this table (3.7):

| Player 1 | Player 2 | Result |
|---|---|---|
| Solved in n | Solved in m, n < m | Player 1 wins |
| Solved in n | Solved in m, n > m | Player 2 wins |
| Solved in n | Solved in n | Draw |
| Solved | Exhausted | Player 1 wins |
| Exhausted | Solved | Player 2 wins |
| Exhausted | Exhausted | Draw |

3. THE system SHALL NOT end the game when only one player is finished. (3.6)
4. WHEN the game is `COMPLETED`, THE results response SHALL contain both secret codes, both players' guesses and feedback, guesses used, solved status, the outcome and the completion time. (3.8, ND-1)
5. IF results are requested while the game is not `COMPLETED`, THEN THE system SHALL reject the request with `GAME_NOT_COMPLETED` and SHALL NOT decrypt or reveal any code or guess.
6. THE system SHALL retain enough data to reconstruct the game and its result until the retention end. (FR-013)

### R8: Credentials

1. THE system SHALL use three distinct credential types: game access token, invitation token and rematch capability. Each SHALL be accepted only by the operations that expect its type. The type is determined by the stored record and not by the token's visible prefix. (7.3)
2. THE system SHALL generate every credential from its own draw of at least 256 bits of cryptographically secure randomness, with no derivation between credentials, and SHALL store only its plain SHA-256 hash (ND-6). The sole exception is the temporary encrypted copy of a rotated token (R8.13). (5.3)
3. A game access token SHALL authorise exactly one player in exactly one game. It SHALL NOT authorise any other game, including a rematch of the same game. The acting player SHALL always be derived from the token.
4. An invitation token SHALL be single use and SHALL be consumed in the same transaction that creates the second player.
5. A rematch capability SHALL authorise creating at most one rematch of one completed game and SHALL grant no read or play access to any game.
6. WHEN a token is rotated, THE system SHALL create the new credential, revoke the old one, and revoke the player's unused rematch capability (RD-3), in a single transaction. After commit, the old token SHALL NOT authorise any operation except the replay in R8.13. (ND-4)
7. THE system SHALL verify the credential again inside the transaction of every state-changing operation, after taking the game lock, so that a revocation committed earlier cannot be bypassed. (CL-1)
8. THE system SHALL reject revoked, consumed, unknown, deleted and wrong-type credentials with an identical `401 INVALID_CREDENTIALS` response. A credential that would otherwise be accepted but belongs to a game that is expired and not yet deleted SHALL receive `410 GAME_EXPIRED`. Once the game and its credentials are deleted the response is `401`. THE system SHALL NOT keep credential records solely to preserve the `410` response. (C-7)
9. THE system SHALL NOT provide any mechanism to recover a lost credential. Without an account or independently verified identity, possession of the token is the only proof of identity. This limitation SHALL be documented in the API documentation and security assessment. (OD-7)
10. Credentials SHALL be invalid once the game is expired (`reference time >= expires_at`), whether or not cleanup has run.
11. EVERY authenticated operation SHALL decide credential validity at one authorisation point inside its database transaction, using one reference time. The HTTP layer SHALL only extract the token and apply IP rate limits. For state-changing operations the authorisation point runs after the game-row lock. (CL-1)
12. EVERY read operation SHALL run in a single read-only snapshot transaction in which the authorisation point and all data reads see the same committed state. A read whose snapshot began before a rotation commits MAY succeed with the old token. A read that begins after the commit SHALL NOT. (CL-1)
13. THE rotation operation SHALL be idempotent so a lost response does not lock the player out (ND-4). It SHALL require an `Idempotency-Key`. For the rotation replay window after the first successful rotation (default 10 minutes, RD-3), the revoked old token presented with the same key and the same fingerprint SHALL return the same new token with `Idempotent-Replay: true`, as long as the new token has not itself been revoked. The server SHALL hold the new token for this purpose only as AES-256-GCM ciphertext under the key ring, and SHALL clear it after the window. A different key with the old token, or any request after the window, SHALL receive `401`. A reused key with a different old token SHALL receive `409 IDEMPOTENCY_CONFLICT`.
14. THE results of a completed game SHALL remain readable by the player through the player's current access token after any number of rotations. A token revoked by rotation SHALL NOT read results. Rotation changes who may read, not what is stored.

### R9: Rematch

1. WHEN a participant of a `COMPLETED` game requests a rematch capability with their access token, THE system SHALL create a new capability, revoke any previous unused capability of that player for that game, and return the capability once. (ND-3)
2. WHEN a client presents a valid rematch capability and a valid nickname, THE system SHALL, in one transaction, consume the capability, create a new game linked to the original, create the requester as seat 1 with a new game access token, and create a new invitation token. (OD-7, ND-2)
3. THE new game SHALL have entirely new credentials. Tokens of the original game SHALL NOT authorise any operation on the new game, and the new game's tokens SHALL NOT authorise the original game.
4. THE system SHALL permit at most one existing rematch per original game, enforced by a database uniqueness constraint on the link. A second attempt SHALL receive `409 REMATCH_ALREADY_CREATED`.
5. IF the original game is not `COMPLETED`, THEN THE system SHALL refuse to mint a capability with `GAME_NOT_COMPLETED`.
6. THE original game's status SHALL report only whether a rematch exists, never the new game's identifier or credentials.
7. THE system SHALL NOT re-issue tokens of the new game. The opponent obtains the invitation from the player who created the rematch, outside the API.
8. THE link from a rematch to its original SHALL be a foreign key that is cleared (set to null) when the original is deleted. The rematch continues as an ordinary game. Deleting a rematch game SHALL NOT affect the original except that the original may then have a new rematch (RD-6). Capabilities belong to the original game and are deleted with it.

### R10: Encryption and key management

1. THE system SHALL encrypt every stored secret code and every stored guess with AES-256-GCM using a unique random 96-bit nonce per encryption. Guess numbers, feedback counts and solved or exhausted flags MAY be stored in plaintext. (OD-6, ND-7)
2. THE system SHALL bind each ciphertext to its row through GCM additional authenticated data (AAD) that contains a purpose label, the key identifier, the game id, the player id, and for guesses the guess number, so a ciphertext copied elsewhere fails authentication. (CL-3)
3. THE system SHALL hold encryption keys outside PostgreSQL and outside database backups. Keys SHALL NOT appear in database records, migrations, logs, environment dumps or source control. (ND-9)
4. THE system SHALL support a key ring with an integer identifier per key, a status (`ACTIVE` for one key, `DECRYPT_ONLY` for older keys) and creation date. Identifiers SHALL never be reused. Each ciphertext row SHALL record the key identifier that encrypted it.
5. THE system SHALL provide a re-encryption task that moves every ciphertext and keyed fingerprint to the active key. It SHALL process one whole game per transaction under the game lock, so a game is never partly migrated. It SHALL be safe to run repeatedly and while the service is live.
6. THE system SHALL refuse to start without a valid active key, and SHALL verify the key ring with a self-test at start-up.
7. THE system SHALL decrypt only in these paths: guess submission (opponent's code, and the stored guess for replay comparison through the fingerprint), progress (the caller's own guesses), results (after `COMPLETED`: both codes and all guesses) and rotation replay (the stored token). A decrypted value SHALL exist only inside the callback that uses it, SHALL NOT be assigned to long-lived state, logged, serialised or placed in an error, and its buffer SHALL be cleared after use as far as the runtime permits.
8. THE game engine SHALL receive decrypted codes and guesses only as function arguments and SHALL contain no cryptography. Decryption lives in the persistence layer. (R14)
9. THE documentation SHALL describe key generation, storage, backup, recovery, rotation, retirement and compromise response, including that losing every copy of a key makes the affected data unrecoverable. (`security-assessment.md`, `deployment.md`)
10. THE system SHALL document nonce uniqueness: nonces are random, there SHALL be a metric of encryptions per key, and a key SHALL be rotated before it reaches 2^28 encryptions (RD-10).
11. A key SHALL be retired (removed from the ring) only when no database row references it and every backup that may contain data encrypted under it has expired or been destroyed. The earliest retirement date is the completion date of re-encryption plus the maximum backup retention (35 days). Until then the key stays in the ring as `DECRYPT_ONLY` and in the key backup. (ND-9)
12. THE system SHALL provide a key verification task that lists the key identifiers referenced by the database, confirms each is present in the ring, and test-decrypts every ciphertext, for use after restore and before key retirement.

### R11: Expiry, retention and cleanup

1. THE system SHALL read these periods from configuration, with defaults (OD-5, ND-8): unjoined games 7 days, games in progress 30 days, completed games 180 days.
2. THE system SHALL store a retention end (`expires_at`) on every game and maintain it as follows. On creation it is creation time plus the unjoined period and is not extended while the game is unjoined. On join and on every later state-changing request (ND-5) it is that time plus the in-progress period. On completion it is completion time plus the completed period and is not extended again. Reads, polling and idempotent replays do not extend it.
3. A game SHALL be expired when `reference time >= expires_at`. THE system SHALL apply this one rule in the authorisation point, in every operation and in cleanup (CL-2). WHEN a game is expired, THE system SHALL reject every operation on it with `410 GAME_EXPIRED` (credential holder) or the uniform response of R8.8, and SHALL NOT modify it. This applies at once, independent of cleanup. (9.4)
4. THE system SHALL treat every credential of an expired game as invalid. (R8.10)
5. THE cleanup task SHALL permanently delete every game with `reference time >= expires_at` together with its players (nicknames), encrypted secret codes, encrypted guesses, idempotency keys, rotation records, results and credentials. After deletion no record of the credentials remains (R8.8).
6. THE cleanup task SHALL be safe to repeat and to run concurrently with itself and with live traffic: it works in bounded batches, re-checks expiry on the locked row, skips rows locked by other transactions, and produces the same end state however often it runs.
7. A rematch SHALL keep working as a normal game when its original is deleted. (R9.8)
8. THE system SHALL log only counts and durations from cleanup, never nicknames, codes, guesses or tokens.
9. THE documentation SHALL state that deleted data persists in backups for at most the backup retention of 35 days, and that a restore SHALL be followed by cleanup before the service accepts traffic. (ND-8, 5.4)
10. THE system SHALL NOT provide a player-initiated deletion endpoint in MVP 1. (ND-8)
11. THE cleanup task SHALL also remove rate-limit rows idle for more than an hour and clear rotation token ciphertext past its replay window.

### R12: API conventions and errors

1. THE system SHALL serve all player endpoints under `/api/v1/` with JSON bodies. (7.1)
2. THE system SHALL return every error as `{ "error": { "code", "message", "requestId" } }` with a stable machine-readable `code` and a status that matches the error class. (7.4)
3. THE error codes and statuses SHALL be those defined in `openapi/openapi.yaml`, which covers every case listed in baseline 7.4.
4. THE system SHALL validate every body, path parameter and header on the server. Unknown body properties SHALL be rejected.
5. THE error `message` SHALL NOT echo request values, in particular submitted codes, guesses, nicknames or tokens.
6. THE OpenAPI 3.1 document SHALL be approved before implementation starts and SHALL be the contract for contract tests. (7.5, OD-8)
7. THE system SHALL expose `GET /healthz` reporting process, database and key ring readiness.

### R13: Security, privacy, logging and metrics

1. THE system SHALL apply rate limits as specified in R20. (5.3)
2. THE system SHALL NOT write secret codes, guesses, request or response bodies of code and guess endpoints, nicknames, tokens, token hashes, idempotency keys of rotation, `Authorization` headers, admin tokens, encryption keys, fingerprints or decrypted values to logs, metrics, traces, diagnostic output, crash reports or error responses. (OD-2)
3. THE system SHALL be served over HTTPS in deployment, terminated at the reverse proxy.
4. THE system SHALL collect only nicknames and operational data needed to run a game. Nicknames SHALL NOT be shown outside their game. (5.4)
5. THE system SHALL keep administrative credentials separate from player credentials, and players SHALL have no administrative access. (5.3)
6. THE system SHALL NOT require accounts, passwords or personal information. (FR-018)
7. THE project SHALL document retention and deletion with UK GDPR in mind. (5.4)
8. THE metrics SHALL be privacy-safe: aggregate counts, gauges and histograms only. Labels SHALL come from bounded sets (route template, status class, error code, key identifier, operation). They SHALL NOT include game ids, player ids, nicknames, IP addresses, tokens or any value derived from them.
9. THE diagnostic logs SHALL be structured and limited to an allow-list of fields: time, level, request id, route template, status, duration, error code, operation name, counts, and game id (an identifier, not a credential) where needed. Client IP addresses SHALL NOT be written by the application.

### R14: Engine independence and verifiability

1. THE engine SHALL import no Oak, HTTP, database, crypto or I/O module, and an automated check SHALL enforce it. (6.3)
2. THE engine SHALL be deterministic: the same inputs always give the same outputs.
3. THE test suite SHALL include a reference feedback implementation that shares no code with production and SHALL compare both on all 1296 × 1296 secret and guess pairs and on seeded random cases. (3.4, 9.2)

### R15: Simulator

The simulator lives in `tools/simulator` and uses only the public REST API. Its behaviour is defined in `simulator-design.md`.

1. THE simulator SHALL support configurable game count, concurrency, strategy and seed, and SHALL create two independent players per game. (SIM-001 to SIM-005)
2. THE simulator SHALL check feedback against the reference implementation, check state transitions, detect unexpected responses, and verify idempotent guess retries and idempotent rotation retries including a simulated lost rotation response. (SIM-006 to SIM-008)
3. THE simulator SHALL record failures with seed and game number and SHALL replay one game from them. (SIM-009, 9.5)
4. THE simulator SHALL write JSON and a human-readable summary with the metrics listed in baseline 9.5, and SHALL run as `deno task simulate`. (SIM-010 to SIM-012)

### R16: Documentation and client tooling

1. THE repository SHALL include a Postman collection with creation, joining, code submission, guessing, status, results, rotation, rematch, error scenarios and a full two-player lifecycle, using variables and no real credentials. (8.3)
2. THE documentation SHALL include curl examples that play a whole game with separate credentials per player. (8.4)
3. THE documentation SHALL state the lost-token limitation (R8.9) and how to retry a rotation safely (R8.13).

### R17: Testing and CI

1. THE project SHALL include the test layers in `test-strategy.md`, and SHALL cover every negative case in baseline 9.4. (9.1, 9.4)
2. THE test suite SHALL include concurrency scenarios for simultaneous join, guess, token rotation, rematch creation and cleanup, in the combinations listed in `test-strategy.md`. (CL-8)
3. A pull request SHALL trigger format check, lint, type check, unit tests, API integration tests, security checks and build verification. Simulation and larger load tests MAY run as separate jobs. (9.7)
4. THE project SHALL measure API latency and report the 95th percentile against the 500 ms target. (5.1)

### R18: Deployment and operability

1. THE application SHALL be stateless and run as several instances without session affinity. All shared state, including rate-limit counters, SHALL be in PostgreSQL. (6.4)
2. THE project SHALL provide a Docker Compose deployment as described in `deployment.md`. (12.1)
3. THE project SHALL keep versioned database migrations and apply them in a controlled step. (5.6)
4. THE project SHALL keep development and production configuration separate and keep secrets and encryption keys out of source control. (5.6, 14.3)
5. THE system SHALL expose metrics for games created, active and completed, API request count and latency, subject to R13.8. (12.4)

### R19: Licensing, repository layout and specification set

1. THE repository layout SHALL follow baseline section 14.2 as amended by OD-1 (`design.md`). THE README SHALL show the same layout. (OD-1)
2. THE repository SHALL carry the full AGPL-3.0-only text in `LICENSE`, an `SPDX-License-Identifier: AGPL-3.0-only` header on source files, a `NOTICE` file and a `CONTRIBUTING.md` with contribution terms before any outside contribution is accepted. (13.1, 13.4)
3. THE project SHALL NOT assume that AGPL contributions grant commercial relicensing rights. (13.4)
4. THE project SHALL use original names, artwork and symbols. (3.1, 13.5)
5. THE specification artefacts SHALL reference one another, SHALL define each item once in the artefact that owns it, and SHALL be mapped in `traceability.md`.

### R20: Rate limiting

1. THE system SHALL limit request rates in two layers: coarse per-IP limits at the reverse proxy, and finer per-IP and per-credential limits in the application (C-6, CL-4).
2. THE application layer SHALL keep its counters in PostgreSQL so that all instances share them. In-memory counters alone SHALL NOT be relied on. Redis SHALL NOT be required.
3. EACH limit SHALL be a token bucket (capacity and refill rate) updated by a single atomic statement, so concurrent instances cannot oversubscribe a bucket.
4. THE subject of an IP-based bucket SHALL be an HMAC of the client IP keyed by a secret, and the subject of a credential-based bucket SHALL be a hash of the presented token. The application SHALL NOT store IP addresses or plaintext tokens (RD-9).
5. THE application SHALL trust a forwarded client IP only from configured proxy addresses (RD-9).
6. THE system SHALL reject a request over its limit with `429 RATE_LIMITED` and a `Retry-After` header, before doing any other work for IP buckets and at the authorisation point for credential buckets.
7. IF the rate-limit store is unavailable, THEN THE system SHALL fail closed with `503` (RD-2).
8. THE values SHALL be configurable. Recommended starting values are in `deployment.md` section 4 and need owner approval. (C-6)
9. THE rate-limit statement SHALL run in its own short transaction for IP buckets and SHALL follow the lock order in `design.md` section 8 for credential buckets.

### R21: Administration, scheduling, backup and restore

1. THE system SHALL provide two administrative interfaces only: metrics and cleanup. They SHALL be served on a separate admin listener reachable only on the internal network and SHALL NOT be routed by the public proxy (C-4, RD-4). They SHALL require the admin token.
2. THE scheduled cleanup SHALL be run hourly by a dedicated `cleanup` service that runs the cleanup task from the same codebase. Application instances SHALL NOT schedule cleanup themselves and cleanup SHALL NOT depend on an HTTP call. THE admin cleanup endpoint SHALL exist for manual and dry runs and SHALL call the same code. (ND-8)
3. THE system SHALL keep database backups for at most 35 days. (ND-8)
4. THE project SHALL document and drill a database restore procedure and a key recovery procedure (`deployment.md` sections 5 and 6) before production use, including: restore, supplying the key ring, `keys:verify`, clearing rate-limit state, running cleanup before accepting traffic, and the effect of restore on credential state (RD-7).
5. THE project SHALL document key generation, backup, rotation, retirement and compromise procedures (`security-assessment.md` section 3.3, `deployment.md` section 5). (ND-9)

## Out of scope for MVP 1

Web application, PWA, accounts, chat, matchmaking, leaderboards, tournaments, payments, advertising, AI opponents, native apps, multi-tenant infrastructure, white-label administration, custom domains, Kubernetes, microservices, multi-region deployment, mandatory Redis, WebSockets, token recovery, invitation preview, player-initiated deletion, point-in-time database recovery, cloud key management. (Sections 10, 11, 12.5, 16)

Future white-label support is an architectural constraint only.

## Review findings

### Resolved by owner decisions

- Repository layout conflict (OD-1). Own-code visibility (OD-2, ND-1). Secret-code and guess protection (OD-6, ND-7, ND-9). Token lifecycle, rotation and rematch handling (OD-7, ND-2 to ND-4). Retention and backups (ND-8). Expired-credential responses (C-7).

### Edge cases the design must cover

- A player solves on the tenth guess (solved, not exhausted).
- Both players finish at the same moment: one transaction computes the result exactly once.
- Retry of the completing guess after the game is `COMPLETED` (R5.9).
- A game expires while a request is in flight: the reference time at the authorisation point decides (R11.3).
- A rotated token used by a request that began before the rotation committed (R8.7, R8.12).
- A rotation whose response is lost (R8.13).
- Two rematch requests at once (R9.4).
- Cleanup deleting a game that has just been refreshed (R11.6).
- A restore resurrecting deleted games or revoked tokens (R21.4, RD-7).
- Replaying an idempotent request after the key ring has been rotated (R10.5).

### Risks (see `security-assessment.md`)

- Code space is only 1296 codes, so guess limits and rate limits carry the security weight.
- Bearer tokens in URLs or logs leak. Credentials are carried only in headers or bodies.
- A hash of a guess is reversible, so request fingerprints are keyed (R5.12).
- Key loss destroys in-progress codes and guesses (R10.9).
- Lost tokens cannot be recovered (R8.9). The rotation replay window narrows but does not remove this for rotation only.
